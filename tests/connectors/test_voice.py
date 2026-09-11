"""Voice intake, against ``moto``. No AWS credentials, no network.

``moto`` runs real S3 and Transcribe semantics in-process, but three of its
behaviours will mislead a test that does not know about them, so each is named
where it is relied on:

* **It advances the job status one step per ``GetTranscriptionJob`` call**
  (``None -> QUEUED -> IN_PROGRESS -> COMPLETED``). So a first poll returning
  ``("running", None)`` is moto's state machine, not evidence about ours.
* **It never writes the transcript object**, so the COMPLETED path has to have the
  object put there by the test.
* **It never produces FAILED**, so that branch is reached by stubbing rather than
  by driving the client.
* **It does not verify SigV4 on S3**, so round-tripping a presigned PUT through it
  proves nothing about the signature. The presigning tests therefore assert on the
  URL itself, which is where the real failure lives.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import boto3
import pytest
from moto import mock_aws

from second.settings import AWS_REGION, S3_BUCKET
from second.voice import transcribe as transcribe_module
from second.voice import upload as upload_module
from second.voice.transcribe import (
    TranscriptionError,
    get_transcription,
    job_name,
    start_transcription,
    transcript_key,
)
from second.voice.upload import VoiceError, audio_key, presigned_put, store_audio

AUDIO = b"\x1aE\xdf\xa3" + b"fake opus payload" * 8
"""An EBML magic number and some bytes. Transcribe is not actually decoding it here,
and a recogniseable header makes a failure easier to read than a blob of zeroes."""


@pytest.fixture
def bucket():
    with mock_aws():
        boto3.client("s3", region_name=AWS_REGION).create_bucket(
            Bucket=S3_BUCKET,
            CreateBucketConfiguration={"LocationConstraint": AWS_REGION},
        )
        yield boto3.client("s3", region_name=AWS_REGION)


# ---------------------------------------------------------------------------
# Job names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "seed,expected",
    [
        ("2026-09-11T14:03:22", "second-2026-09-11T14-03-22"),
        ("has space", "second-has-space"),
        ("a/b/c", "second-a-b-c"),
        ("", "second-recording"),
        ("!!!", "second-recording"),
        ("already.legal_name-1", "second-already.legal_name-1"),
    ],
)
def test_job_names_are_legal(seed, expected):
    """``TranscriptionJobName`` accepts ``^[0-9a-zA-Z._-]+`` only.

    No colons -- so the obvious generator, ``datetime.now().isoformat()``, is
    rejected. botocore enforces only a minimum length of 1, so an illegal name
    passes client-side and fails at the service with a message about the job name
    that reads like a bug somewhere else.
    """
    assert job_name(seed) == expected
    assert not transcribe_module.JOB_NAME_CHARS.search(job_name(seed))
    assert 1 <= len(job_name(seed)) <= 200


def test_a_very_long_seed_is_truncated():
    assert len(job_name("x" * 500)) == 200


def test_the_transcript_key_ends_in_json():
    """An ``OutputKey`` that does not end in ``.json`` is treated as a folder, and
    Transcribe appends ``<jobName>.json`` -- so ``transcripts/abc`` becomes
    ``transcripts/abc/abc.json`` and a reader looking at the first finds nothing."""
    assert transcript_key("second-abc") == "transcripts/second-abc.json"
    assert transcript_key("second-abc").endswith(".json")


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def test_store_audio_puts_the_object_and_returns_an_s3_uri(bucket):
    uri = store_audio(AUDIO, "audio/webm;codecs=opus", audio_key("second-abc"))

    assert uri == f"s3://{S3_BUCKET}/audio/second-abc.webm"
    stored = bucket.get_object(Bucket=S3_BUCKET, Key="audio/second-abc.webm")
    assert stored["Body"].read() == AUDIO
    assert stored["ContentType"] == "audio/webm;codecs=opus", (
        "the browser's content type is stored as-is; Transcribe reads MediaFormat, "
        "not this, so there is nothing to gain by rewriting it"
    )


def test_an_empty_recording_raises_rather_than_transcribing_to_nothing(bucket):
    """A silent recording produces a genuinely COMPLETED job with an empty
    transcript. Catching it at the door is the difference between a clear error and
    an agent planning against nothing."""
    with pytest.raises(VoiceError, match="empty"):
        store_audio(b"", "audio/webm", audio_key("second-abc"))


def test_an_oversized_recording_raises(bucket):
    with pytest.raises(VoiceError, match="over the"):
        store_audio(b"x" * (upload_module.MAX_AUDIO_BYTES + 1), "audio/webm", audio_key("s"))


def test_the_presigned_url_does_not_sign_the_content_type(bucket):
    """The brief's diagnosis was right and its fix was backwards.

    Signing a bare ``audio/webm`` puts ``content-type`` in ``X-Amz-SignedHeaders``
    and the browser must then send that exact string. ``fetch`` sets it from
    ``blob.type``, which MediaRecorder makes ``audio/webm;codecs=opus`` -- so
    signing a bare value *guarantees* the SignatureDoesNotMatch 403 it was meant to
    avoid. Not signing it at all lets the browser send whatever it likes.

    moto does not verify SigV4, so this asserts on the URL rather than on a
    round-trip. The URL is where the real failure is.
    """
    signed = parse_qs(urlsplit(presigned_put(audio_key("second-abc"))["url"]).query)

    assert signed["X-Amz-SignedHeaders"] == ["host"], signed["X-Amz-SignedHeaders"]
    assert "content-type" not in signed["X-Amz-SignedHeaders"][0]


def test_the_presigned_url_addresses_the_regional_endpoint(bucket):
    """A global host answers with a 307 to the regional one. ``curl`` follows it and
    succeeds; a browser re-preflights the redirect target and fails CORS, reporting
    nothing about regions."""
    host = urlsplit(presigned_put(audio_key("second-abc"))["url"]).netloc
    assert AWS_REGION in host, host
    assert host != "s3.amazonaws.com"


def test_a_url_that_would_fail_in_a_browser_is_refused(bucket, monkeypatch):
    """Guards the guard: prove the check fires, rather than trusting that it would.

    Without this, :func:`test_the_presigned_url_does_not_sign_the_content_type`
    passes because the code happens to be right today, and the refusal path has
    never executed.
    """
    real = upload_module._client

    class SigningContentType:
        def __getattr__(self, name):
            return getattr(real(), name)

        def generate_presigned_url(self, *args, **kwargs):
            kwargs.setdefault("Params", {})["ContentType"] = "audio/webm"
            return real().generate_presigned_url(*args, **kwargs)

    monkeypatch.setattr(upload_module, "_client", lambda: SigningContentType())
    with pytest.raises(VoiceError, match="SignatureDoesNotMatch"):
        presigned_put(audio_key("second-abc"))


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------


def test_start_transcription_uploads_and_starts_a_job(bucket):
    job = start_transcription(AUDIO, "audio/webm;codecs=opus", name_seed="demo-one")

    assert job == "second-demo-one"
    bucket.head_object(Bucket=S3_BUCKET, Key="audio/second-demo-one.webm")

    described = boto3.client("transcribe", region_name=AWS_REGION).get_transcription_job(
        TranscriptionJobName=job
    )["TranscriptionJob"]
    assert described["Media"]["MediaFileUri"] == f"s3://{S3_BUCKET}/audio/{job}.webm"
    assert described["MediaFormat"] == "webm"
    assert described["LanguageCode"] == "en-GB"
    assert "MediaSampleRateHertz" not in described, (
        "a sample rate that does not match the audio makes the JOB fail, and the rate "
        "of a MediaRecorder blob is unknowable without decoding it"
    )


def test_only_one_language_parameter_is_sent(bucket):
    """Passing two of LanguageCode / IdentifyLanguage / IdentifyMultipleLanguages
    makes the **job** fail rather than the call, so it returns 200 and the cause
    only appears in FailureReason later."""
    job = start_transcription(AUDIO, "audio/webm", name_seed="lang")
    described = boto3.client("transcribe", region_name=AWS_REGION).get_transcription_job(
        TranscriptionJobName=job
    )["TranscriptionJob"]

    present = {k for k in ("LanguageCode", "IdentifyLanguage", "IdentifyMultipleLanguages") if k in described}
    assert present == {"LanguageCode"}


def test_a_running_job_reports_running(bucket):
    """moto advances one status per ``GetTranscriptionJob`` call, so the first poll
    is QUEUED and the second IN_PROGRESS -- both of which are "running" to us."""
    job = start_transcription(AUDIO, "audio/webm", name_seed="polling")

    assert get_transcription(job) == ("running", None)
    assert get_transcription(job) == ("running", None)


def test_a_completed_job_returns_the_transcript(bucket):
    """moto does not write the transcript object, so the test puts it there --
    which also pins the exact key path the reader derives from the job name."""
    job = start_transcription(AUDIO, "audio/webm", name_seed="finished")
    bucket.put_object(
        Bucket=S3_BUCKET,
        Key=transcript_key(job),
        Body=json.dumps(
            {
                "jobName": job,
                "accountId": "123456789012",
                "results": {
                    "transcripts": [{"transcript": "I want to get comfortable speaking to a room."}],
                    "items": [{"id": 0}],
                    "audio_segments": [{"id": 0}],
                },
                "status": "COMPLETED",
            }
        ).encode("utf-8"),
    )

    get_transcription(job)  # QUEUED
    get_transcription(job)  # IN_PROGRESS
    status, text = get_transcription(job)  # COMPLETED

    assert status == "done"
    assert text == "I want to get comfortable speaking to a room."


def test_an_empty_transcript_raises(bucket):
    """The empty-list failure in its voice form.

    No microphone permission, a muted track or a near-empty blob all produce a
    genuinely COMPLETED job whose transcript is ``""``. Returning ``("done", "")``
    would hand an agent a valid-looking success to plan against.
    """
    job = start_transcription(AUDIO, "audio/webm", name_seed="silent")
    bucket.put_object(
        Bucket=S3_BUCKET,
        Key=transcript_key(job),
        Body=json.dumps({"results": {"transcripts": [{"transcript": "   "}]}}).encode("utf-8"),
    )

    get_transcription(job)
    get_transcription(job)
    with pytest.raises(TranscriptionError, match="empty transcript"):
        get_transcription(job)


def test_a_missing_transcript_object_raises_with_the_key(bucket):
    """moto leaves the bucket empty on COMPLETED, which is also what a wrong
    ``OutputKey`` looks like -- so the error names the key it looked at."""
    job = start_transcription(AUDIO, "audio/webm", name_seed="notwritten")
    get_transcription(job)
    get_transcription(job)

    with pytest.raises(TranscriptionError, match="transcripts/second-notwritten.json"):
        get_transcription(job)


def test_an_unexpected_transcript_shape_raises(bucket):
    job = start_transcription(AUDIO, "audio/webm", name_seed="wrongshape")
    bucket.put_object(
        Bucket=S3_BUCKET, Key=transcript_key(job), Body=json.dumps({"results": {}}).encode("utf-8")
    )
    get_transcription(job)
    get_transcription(job)

    with pytest.raises(TranscriptionError, match="unexpected shape"):
        get_transcription(job)


def test_a_missing_job_raises_and_names_the_real_exception(bucket):
    """A job that does not exist returns **BadRequestException**, not
    NotFoundException -- both are in the service model and both are HTTP 400, so
    code branching on NotFoundException would never fire."""
    with pytest.raises(TranscriptionError, match="BadRequestException"):
        get_transcription("second-never-existed")


def test_a_failed_job_raises_with_the_reason(bucket, monkeypatch):
    """moto has no transition to FAILED, so this stubs the description.

    The branch matters more than most: almost every input mistake -- a cross-region
    bucket, a mismatched MediaFormat, two language parameters -- returns 200 from
    ``StartTranscriptionJob`` and fails asynchronously, so ``FailureReason`` is the
    only place the cause ever appears.
    """

    class Failed:
        def get_transcription_job(self, TranscriptionJobName):
            return {
                "TranscriptionJob": {
                    "TranscriptionJobName": TranscriptionJobName,
                    "TranscriptionJobStatus": "FAILED",
                    "FailureReason": "The media format that you specified doesn't match the detected media format.",
                }
            }

    monkeypatch.setattr(transcribe_module, "_client", lambda: Failed())
    with pytest.raises(TranscriptionError, match="doesn't match the detected media format"):
        get_transcription("second-failed")


def test_an_unrecognised_status_raises_rather_than_guessing(bucket, monkeypatch):
    class Strange:
        def get_transcription_job(self, TranscriptionJobName):
            return {"TranscriptionJob": {"TranscriptionJobStatus": "PAUSED_FOR_REVIEW"}}

    monkeypatch.setattr(transcribe_module, "_client", lambda: Strange())
    with pytest.raises(TranscriptionError, match="unrecognised status"):
        get_transcription("second-strange")


def test_the_seam_matches_what_platform_will_call():
    """The shape PLATFORM was told to expect, asserted rather than assumed."""
    import inspect

    from second import voice

    start = inspect.signature(voice.start_transcription)
    assert list(start.parameters)[:2] == ["audio_bytes", "content_type"]
    assert all(
        start.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        for name in list(start.parameters)[2:]
    ), "anything beyond the seam's two arguments must be keyword-only"

    assert list(inspect.signature(voice.get_transcription).parameters) == ["job_id"]


def test_importing_voice_needs_no_credentials():
    """``graphs/composition.py`` imports connector modules inside a narrow
    ``try/except ImportError``. A credentials error at import time would escape it
    and take the composition root down at startup rather than at first use."""
    import importlib

    for name in ("second.voice", "second.voice.upload", "second.voice.transcribe"):
        importlib.reload(importlib.import_module(name))
