"""Turning a recording into words, with Amazon Transcribe batch.

The seam PLATFORM calls::

    start_transcription(audio_bytes: bytes, content_type: str) -> str   # job id
    get_transcription(job_id: str) -> tuple[str, str | None]            # (status, transcript)

``status`` is ``"running" | "done" | "failed"``.

Batch, not streaming, and not for latency reasons
-------------------------------------------------

botocore 1.43.91 ships no ``transcribestreaming`` service model -- asking for one
raises ``UnknownServiceError`` -- and the ``amazon-transcribe`` package is not
installed. Streaming would therefore mean hand-rolling SigV4 WebSocket frames.
``webm`` is in the batch ``MediaFormat`` enum, so batch it is. $0.006/minute, free
under 60 minutes a month.

**Perceived latency is not this module's problem.** SURFACES paints a live
transcript with the Chrome Web Speech API, free and instant; this result swaps in
when the job lands. They own how fast it feels, this owns whether it is right.

Everything here fails loudly
----------------------------

Transcribe's failure mode is the one this whole domain is written against: almost
every input mistake returns **HTTP 200** from ``StartTranscriptionJob`` and fails
asynchronously, so ``FailureReason`` on the finished job is the only place the cause
appears. And a silent recording -- no microphone permission, a muted track, a
near-empty blob -- produces a genuinely ``COMPLETED`` job whose transcript is the
empty string. That is the empty-list failure in its voice form: a valid-looking
success the agent then plans against. So an empty transcript raises.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from second.settings import AWS_REGION, S3_BUCKET
from second.voice.upload import VoiceError, audio_key, aws_config, store_audio

logger = logging.getLogger(__name__)

LANGUAGE_CODE = "en-GB"
"""Exactly one of ``LanguageCode``, ``IdentifyLanguage`` and
``IdentifyMultipleLanguages`` may be passed -- two makes the **job** fail, not the
call. Hardcoded rather than detected: the owner is the only speaker in this demo,
and language identification adds a way for the job to fail for no benefit.
Stepping over this costs a worse transcript for a non-en-GB speaker, which is a
product decision to revisit after the deadline, not a correctness one."""

MEDIA_FORMAT = "webm"
"""In the batch ``MediaFormat`` enum, verified offline against botocore 1.43.91:
``['mp3','mp4','wav','flac','ogg','amr','webm','m4a']``. botocore does **not**
validate this client-side, so a wrong value only surfaces as ``FailureReason`` on a
job that returned 200."""

TRANSCRIPT_PREFIX = "transcripts"

JOB_NAME_CHARS = re.compile(r"[^0-9a-zA-Z._-]")
"""``TranscriptionJobName`` accepts ``^[0-9a-zA-Z._-]+`` only -- no colons, no
spaces, no slashes. botocore enforces only a minimum length of 1, so a name built
from ``datetime.isoformat()`` (which contains colons) passes client-side and is
rejected by the service."""


class TranscriptionError(RuntimeError):
    """A transcription could not be completed. Raised, never returned."""


def _client() -> Any:
    import boto3  # noqa: PLC0415 - lazy, so importing this module needs no AWS

    return boto3.client("transcribe", region_name=AWS_REGION, config=aws_config())


def _s3() -> Any:
    import boto3  # noqa: PLC0415

    return boto3.client("s3", region_name=AWS_REGION, config=aws_config())


def job_name(seed: str) -> str:
    """A legal ``TranscriptionJobName`` from any string.

    Args:
        seed: Anything identifying this recording. Injected rather than generated
            from the clock so tests are deterministic -- and because the obvious
            generator, an ISO timestamp, contains colons and is rejected.
    """
    cleaned = JOB_NAME_CHARS.sub("-", seed).strip("-") or "recording"
    return f"second-{cleaned}"[:200]


def transcript_key(job: str) -> str:
    """Where the transcript lands.

    The ``.json`` suffix is load-bearing: an ``OutputKey`` that does not end in
    ``.json`` is treated as a **folder** and Transcribe appends
    ``<jobName>.json`` to it, so ``transcripts/abc`` becomes
    ``transcripts/abc/abc.json`` and a reader looking at ``transcripts/abc`` finds
    nothing.
    """
    return f"{TRANSCRIPT_PREFIX}/{job}.json"


def start_transcription(
    audio_bytes: bytes,
    content_type: str,
    *,
    name_seed: str | None = None,
    new_name: Callable[[], str] | None = None,
) -> str:
    """Upload a recording and start transcribing it. Returns the job id.

    Args:
        audio_bytes: The recording, as captured.
        content_type: What the browser said it was. Stored with the object and
            otherwise unused -- Transcribe reads ``MediaFormat``, not the object's
            content type.
        name_seed: Basis for the job name, sanitised. Pass something traceable.
        new_name: Supplies a seed when ``name_seed`` is None. Injected so tests do
            not depend on a clock or a random source.

    Returns:
        The job id, to hand back to :func:`get_transcription`.

    Raises:
        VoiceError: If the recording is empty or too large.
        TranscriptionError: If the job could not be started.
    """
    seed = name_seed or (new_name() if new_name else _default_seed())
    job = job_name(seed)
    uri = store_audio(audio_bytes, content_type, audio_key(job))

    try:
        _client().start_transcription_job(
            TranscriptionJobName=job,
            Media={"MediaFileUri": uri},
            MediaFormat=MEDIA_FORMAT,
            LanguageCode=LANGUAGE_CODE,
            OutputBucketName=S3_BUCKET,
            OutputKey=transcript_key(job),
        )
    except Exception as error:  # noqa: BLE001 - every botocore error becomes one type here
        raise TranscriptionError(f"could not start transcribing {job!r}: {error}") from error

    logger.info("started transcription %s for %s", job, uri)
    return job


def _default_seed() -> str:
    """A seed when the caller supplies none.

    Deliberately not a timestamp: an ISO timestamp contains colons and
    :func:`job_name` would have to mangle it anyway. ``uuid4`` is unique per upload,
    which is what the job name actually needs -- job records are retained for 90
    days and the name must be unique per account per region for that long.
    """
    import uuid  # noqa: PLC0415

    return uuid.uuid4().hex[:16]


def get_transcription(job_id: str) -> tuple[str, str | None]:
    """Where a transcription has got to, and the words if it is finished.

    Args:
        job_id: What :func:`start_transcription` returned.

    Returns:
        ``("running", None)`` while Transcribe works, or ``("done", transcript)``.

    Raises:
        TranscriptionError: If the job failed, does not exist, reports a status this
            code does not recognise, or **finished with an empty transcript**. The
            last case is the one worth knowing about: a silent recording transcribes
            successfully to ``""``, and returning that would hand an agent a
            valid-looking success to plan against.

    Note:
        ``"failed"`` is in the seam's contract and this function never returns it --
        a failed job raises instead, carrying Transcribe's own ``FailureReason``.
        Almost every input mistake returns 200 from ``StartTranscriptionJob`` and
        fails asynchronously, so that string is the only explanation that exists,
        and an exception is how it reaches the audit log with its cause attached.
        If PLATFORM would rather have the tuple, say so and it is two lines.
    """
    try:
        described = _client().get_transcription_job(TranscriptionJobName=job_id)
    except Exception as error:  # noqa: BLE001
        # A missing job is BadRequestException, not NotFoundException -- both are
        # declared in the service model and both are HTTP 400, but branching on
        # NotFoundException would never fire.
        raise TranscriptionError(
            f"could not read transcription job {job_id!r}: {error}. "
            "A job that does not exist reports BadRequestException."
        ) from error

    job = described.get("TranscriptionJob") or {}
    status = job.get("TranscriptionJobStatus", "")

    if status in ("QUEUED", "IN_PROGRESS"):
        return "running", None

    if status == "FAILED":
        raise TranscriptionError(
            f"transcription {job_id!r} failed: "
            f"{job.get('FailureReason') or 'Transcribe gave no reason'}"
        )

    if status != "COMPLETED":
        raise TranscriptionError(
            f"transcription {job_id!r} reported an unrecognised status {status!r}; "
            "refusing to guess what it means"
        )

    text = _read_transcript(job, job_id)
    if not text.strip():
        raise TranscriptionError(
            f"transcription {job_id!r} completed with an empty transcript. The "
            "recording was silent, the microphone was muted, or no audio was "
            "captured -- Transcribe reports this as success."
        )
    return "done", text


def _read_transcript(job: dict[str, Any], job_id: str) -> str:
    """Pull the text out of the transcript object in S3.

    Reads the bucket rather than the service-managed ``TranscriptFileUri``, which is
    a presigned URI valid for only fifteen minutes and would need an HTTP client in
    this path. The key is derived from the job name, so nothing has to be stored
    between starting a job and reading it.
    """
    key = _output_key(job, job_id)
    try:
        body = _s3().get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()
        payload = json.loads(body)
    except Exception as error:  # noqa: BLE001
        raise TranscriptionError(
            f"transcription {job_id!r} completed but its transcript could not be read "
            f"from s3://{S3_BUCKET}/{key}: {error}"
        ) from error

    try:
        # results.transcripts is a list; a basic batch job always returns one
        # element. results also carries items[] and audio_segments[] that this
        # deliberately ignores rather than validating.
        return str(payload["results"]["transcripts"][0]["transcript"])
    except (KeyError, IndexError, TypeError) as error:
        raise TranscriptionError(
            f"transcription {job_id!r} returned a transcript in an unexpected shape: "
            f"top-level keys {sorted(payload) if isinstance(payload, dict) else type(payload)}"
        ) from error


def _output_key(job: dict[str, Any], job_id: str) -> str:
    """The S3 key of the transcript, preferring what Transcribe actually reported."""
    reported = (job.get("Transcript") or {}).get("TranscriptFileUri", "")
    if reported.startswith("s3://"):
        return reported.split("/", 3)[3]
    if reported:
        # A service-managed https URI: .../<bucket>/<key...>
        path = urlsplit(reported).path.lstrip("/")
        if path.startswith(f"{S3_BUCKET}/"):
            return path[len(S3_BUCKET) + 1 :]
    return transcript_key(job_id)


IAM_ACTIONS = (
    "s3:PutObject",
    "s3:GetObject",
    "transcribe:StartTranscriptionJob",
    "transcribe:GetTranscriptionJob",
)
"""The minimum this module needs, for PLATFORM's IAM policy.

One consequence worth knowing before the deploy: **Transcribe reads the bucket as
the calling identity**, not as a service principal, unless
``JobExecutionSettings.DataAccessRoleArn`` is passed. So the AgentCore task role
needs ``s3:GetObject`` on this bucket itself -- a policy that grants only
``transcribe:*`` produces an ``AccessDenied`` that looks like a Transcribe
permission problem and is actually an S3 one. Avoiding
``DataAccessRoleArn`` is deliberate: it additionally requires
``AllowDeferredExecution`` alongside it, and passing the ARN alone fails.
"""
