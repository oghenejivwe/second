"""Getting the recording into S3, where Amazon Transcribe can read it.

Two paths, and the primary one needs no presigning at all.

**The server path** is what PLATFORM's seam uses. ``start_transcription(audio_bytes,
content_type)`` already holds the bytes, so :func:`store_audio` calls
``put_object`` directly. No signature to get wrong, no CORS, no browser involved.

**The presigned path** is for SURFACES, if the browser would rather PUT straight to
S3 than post the blob through FastAPI. It is optional and it is second, because the
presigned route is where an evening goes.

The content-type trap, and why the brief's advice is inverted here
-----------------------------------------------------------------

The brief says to sign the PUT with a bare ``audio/webm``, because ``MediaRecorder``
sends ``audio/webm;codecs=opus`` and the mismatch produces a
``SignatureDoesNotMatch`` 403 that looks exactly like a CORS problem.

**The diagnosis is right and the fix is not. Do not sign the content type at all.**
Passing ``ContentType`` to ``generate_presigned_url`` puts ``content-type`` into
``X-Amz-SignedHeaders``, and the browser must then send that string byte for byte.
``fetch(url, {method: 'PUT', body: blob})`` sets it from ``blob.type``, which is
``audio/webm;codecs=opus`` -- so signing a bare ``audio/webm`` *guarantees* the
mismatch the brief is trying to avoid, and the only way out would be telling
SURFACES to override the header on every request.

Omitting ``ContentType`` yields ``X-Amz-SignedHeaders=host``: the browser may send
whatever it likes. This costs nothing, because **Transcribe does not read the
object's Content-Type** -- it uses the ``MediaFormat`` parameter. The stored object
keeps ``audio/webm;codecs=opus`` and the job still works.

The region trap
---------------

With botocore's default addressing style, a presigned URL for a bucket outside
``us-east-1`` is signed for the bucket's region but addressed to the *global*
host ``bucket.s3.amazonaws.com``. ``curl`` follows the resulting 307 and succeeds;
a browser re-preflights the redirect target and fails CORS. So the client is built
with virtual addressing and an explicit regional endpoint, and
:func:`presigned_put` asserts the host is regional before handing the URL out.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from second.settings import AWS_REGION, S3_BUCKET

logger = logging.getLogger(__name__)

AUDIO_PREFIX = "audio"
PRESIGN_TTL_SECONDS = 900
"""Fifteen minutes. Long enough for a person to finish speaking and the upload to
land on a slow connection; short enough that a URL copied out of devtools is not a
standing write credential for the bucket."""

MAX_AUDIO_BYTES = 25 * 1024 * 1024
"""About 90 minutes of Opus. A cap exists because the upload path is reachable from
a browser; stepping over it costs the user a refusal on a recording nobody intends
to make, and not capping it costs an unbounded S3 object per request."""


class VoiceError(RuntimeError):
    """An upload could not be completed. Raised, never returned."""


def aws_config() -> Any:
    """Retry policy for every boto3 client in this domain.

    **botocore 1.43.91 defaults to ``legacy`` retry mode, not ``standard``** --
    verified at runtime, ``{'mode': 'legacy'}``. Legacy is five attempts with
    uncapped ``rand() * 2**n`` backoff, so a throttled call can hang for the better
    part of a minute in the middle of a live demo. ``standard`` is three attempts
    with truncated binary exponential backoff and full jitter.

    Note ``max_attempts=2`` -- botocore reads it as *retries* and reports
    ``total_max_attempts: 3``, which is the three this project settled on
    (``settings.RETRY_MAX_ATTEMPTS``). Passing 3 would quietly give four.
    """
    from botocore.config import Config  # noqa: PLC0415 - lazy

    return Config(
        signature_version="s3v4",
        s3={"addressing_style": "virtual"},
        retries={"mode": "standard", "max_attempts": 2},
    )


def _client() -> Any:
    """An S3 client addressed the way presigning needs.

    ``virtual`` addressing plus an explicit regional endpoint keeps the signed host
    and the signed region in agreement. ``s3v4`` is already the default in botocore
    1.43.91, stated here because the presigned URL is wrong in a browser-specific,
    hard-to-read way without it.
    """
    import boto3  # noqa: PLC0415 - lazy, so importing this module needs no AWS

    return boto3.client(
        "s3",
        region_name=AWS_REGION,
        endpoint_url=f"https://s3.{AWS_REGION}.amazonaws.com",
        config=aws_config(),
    )


def audio_key(job_name: str) -> str:
    """Where a recording lives, derived from the job it will be transcribed by.

    One name for both means :func:`~second.voice.transcribe.get_transcription` can
    find the transcript from the job id alone, with nothing to store in between.
    """
    return f"{AUDIO_PREFIX}/{job_name}.webm"


def store_audio(audio_bytes: bytes, content_type: str, key: str) -> str:
    """Put a recording in S3 and return its ``s3://`` URI.

    Args:
        audio_bytes: The recording.
        content_type: Whatever the browser sent, e.g. ``audio/webm;codecs=opus``.
            Stored as-is. Transcribe ignores it in favour of ``MediaFormat``.
        key: The object key, from :func:`audio_key`.

    Returns:
        ``s3://bucket/key`` -- exactly the shape ``Media.MediaFileUri`` requires.

    Raises:
        VoiceError: If the recording is empty or larger than :data:`MAX_AUDIO_BYTES`.
            Empty is its own case: a silent recording produces a **successful**
            transcription job with an empty transcript, so catching it here is the
            difference between a clear error and an agent planning against nothing.
    """
    if not audio_bytes:
        raise VoiceError("the recording is empty; nothing was captured")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise VoiceError(
            f"the recording is {len(audio_bytes) // 1024}KB, over the "
            f"{MAX_AUDIO_BYTES // 1024}KB limit"
        )

    _client().put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=audio_bytes,
        ContentType=content_type or "audio/webm",
    )
    logger.info("stored %d bytes at s3://%s/%s", len(audio_bytes), S3_BUCKET, key)
    return f"s3://{S3_BUCKET}/{key}"


def presigned_put(key: str, expires_in: int = PRESIGN_TTL_SECONDS) -> dict[str, Any]:
    """A URL the browser can PUT a recording to directly. For SURFACES.

    **The browser must send no particular Content-Type.** ``content-type`` is
    deliberately absent from the signed headers, so ``fetch(url, {method: 'PUT',
    body: blob})`` works unchanged with whatever ``blob.type`` MediaRecorder
    produced.

    Returns:
        ``{"url", "key", "expires_in", "method"}``. ``method`` is always ``"PUT"``.

    Raises:
        VoiceError: If the signed URL would send a browser through a cross-region
            redirect, which surfaces as an unexplained CORS failure rather than as
            anything mentioning regions.
    """
    url = _client().generate_presigned_url(
        "put_object",
        Params={"Bucket": S3_BUCKET, "Key": key},
        ExpiresIn=expires_in,
        HttpMethod="PUT",
    )
    _assert_browser_safe(url)
    return {"url": url, "key": key, "expires_in": expires_in, "method": "PUT"}


def _assert_browser_safe(url: str) -> None:
    """Refuse a presigned URL that a browser would fail on.

    Both checks exist because both failure modes present as CORS problems and
    neither mentions its actual cause.
    """
    parts = urlsplit(url)
    signed = parse_qs(parts.query).get("X-Amz-SignedHeaders", [""])[0]

    if "content-type" in signed:
        raise VoiceError(
            f"the presigned URL signs {signed!r}. MediaRecorder sends "
            "'audio/webm;codecs=opus' and a signed content-type must match byte for "
            "byte, so this produces a SignatureDoesNotMatch 403 that reads as CORS. "
            "Do not pass ContentType to generate_presigned_url."
        )

    if not re.search(rf"\.s3[.-]{re.escape(AWS_REGION)}\.amazonaws\.com$", parts.netloc):
        raise VoiceError(
            f"the presigned URL addresses {parts.netloc!r}, which is not the "
            f"{AWS_REGION} endpoint. The global host answers with a 307 to the "
            "regional one; curl follows it and a browser re-preflights the redirect "
            "and fails CORS."
        )


CORS_CONFIGURATION = {
    "CORSRules": [
        {
            "AllowedMethods": ["PUT"],
            "AllowedOrigins": ["http://localhost:5173", "http://localhost:3000"],
            "AllowedHeaders": ["*"],
            "ExposeHeaders": ["ETag"],
            "MaxAgeSeconds": 3000,
        }
    ]
}
"""What the bucket needs for :func:`presigned_put` to work from the React app.

Applied by PLATFORM, not here -- bucket configuration is deployment, and this
module does not own deployment. Recorded here because the CORS rule and the
signing choice have to agree, and they are easier to keep in agreement when
they are written down next to each other.

Add the deployed origin before the demo. ``AllowedHeaders: ["*"]`` is broad; it is
acceptable because the rule permits only ``PUT`` to one bucket and the URL is
already a short-lived capability.
"""
