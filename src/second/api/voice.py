"""The voice seam, resolved at call time.

CONNECTORS owns the upload, the transcription and the job lifecycle. SURFACES
owns the microphone, the live transcript and the HTTP shape. This module is the
join, and it is deliberately thin -- two functions and an error mapping.

**The seam, as CONNECTORS publishes it:**

    start_transcription(audio_bytes, content_type, *, name_seed=None) -> str
    get_transcription(job_id) -> ("running", None) | ("done", transcript)

**Two things that do not line up, and both are the HTTP layer's job to fix.**

*It raises where the route promises a status.* ``get_transcription`` never
returns ``"failed"`` -- a failed job raises ``TranscriptionError`` carrying
Transcribe's own ``FailureReason``, which CONNECTORS argues is the only
explanation that exists, and they are right. But the route's contract is
``{"status": "running|done|failed", "transcript": str | null}``, and a browser
polling a dead job needs an answer rather than a 500. So the exception is caught
here and becomes ``failed`` with its message attached. CONNECTORS offered to
return the tuple instead; converting is better, because the reason survives
either way and their version keeps the cause attached for the audit log.

*It caps the upload twice.* ``store_audio`` enforces its own maximum, so the
route reads CONNECTORS' constant rather than declaring a second one. Two caps
that can disagree is worse than one in the wrong place.

Resolved per call rather than at import, so the API starts and serves the rest
of its routes when this package is missing -- and says so on this one route
instead of failing to boot on all nine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)

WEBM = "audio/webm"
"""Bare, with no codecs parameter.

An S3 presigned PUT signs the content type, so ``audio/webm;codecs=opus`` --
which is what ``MediaRecorder.mimeType`` reports -- fails the signature check
and returns an opaque 403 that reads like a CORS error. The browser re-wraps the
blob; this is the server-side half of the same agreement."""

FALLBACK_MAX_BYTES = 25 * 1024 * 1024
"""Only used if CONNECTORS' own constant ever disappears. Theirs wins."""


class MissingVoice(RuntimeError):
    """The voice package is not importable, and this says who owns it."""


@dataclass(frozen=True)
class VoiceSeam:
    """CONNECTORS' voice functions, plus the exceptions they raise."""

    start: Callable[..., str]
    get: Callable[[str], tuple[str, str | None]]
    max_bytes: int
    rejected: type[Exception]
    """Raised when the recording itself is unusable -- empty, or too large."""
    broke: type[Exception]
    """Raised when transcription could not start, or failed, or went missing."""


def resolve_voice() -> VoiceSeam:
    """Find CONNECTORS' voice seam, or explain its absence.

    Raises:
        MissingVoice: The package is absent, or does not export the seam.
    """
    try:
        from second import voice
    except ImportError as error:
        raise MissingVoice(
            "second.voice does not exist yet (owned by CONNECTORS). "
            "The browser's live transcript still works; the accurate one needs this."
        ) from error

    try:
        return VoiceSeam(
            start=voice.start_transcription,
            get=voice.get_transcription,
            max_bytes=int(getattr(voice, "MAX_AUDIO_BYTES", FALLBACK_MAX_BYTES)),
            rejected=voice.VoiceError,
            broke=voice.TranscriptionError,
        )
    except AttributeError as error:
        raise MissingVoice(
            "second.voice is missing part of its seam "
            "(start_transcription, get_transcription, VoiceError, TranscriptionError) "
            "-- owned by CONNECTORS."
        ) from error


def read_job(seam: VoiceSeam, job_id: str) -> dict[str, Any]:
    """One poll, in the shape the route promised.

    **Failure direction: answer, with the reason.** A transcription that died
    has to come back as ``failed`` and not as a 500, because the browser is in a
    polling loop and a 500 tells it nothing about whether to keep going. The
    live transcript the Web Speech API already painted is unaffected either way,
    so a failure here costs the user the accurate version, not the intake.
    """
    try:
        status, transcript = seam.get(job_id)
    except seam.broke as error:
        logger.warning("transcription %s failed", job_id, exc_info=True)
        return {"status": "failed", "transcript": None, "detail": str(error)}

    if status not in ("running", "done"):
        # The seam documents exactly two, so a third means it changed underneath
        # us. Saying that is more useful than passing an unknown string through
        # to a screen that switches on it.
        return {
            "status": "failed",
            "transcript": None,
            "detail": f"second.voice returned an unrecognised status {status!r}.",
        }

    return {"status": status, "transcript": transcript}
