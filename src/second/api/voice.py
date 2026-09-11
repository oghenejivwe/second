"""The seam CONNECTORS fills. Until then, it refuses legibly.

``src/second/voice/`` does not exist yet. SURFACES sends the bytes and does not
talk to S3 or Transcribe, so rather than approximate either, this resolves the
real module at call time and -- when it is absent -- raises the same shape of
error PLATFORM uses for a missing agent: one that names the module and its
owner.

That matters more than it looks. A temporary approximation on a critical path is
how a defect reaches a demo wearing a comment that says it is temporary; and a
503 reading *second.voice does not exist yet (owned by CONNECTORS)* tells
everyone -- including a judge -- exactly where the edge of the build is. The
alternative, a route that silently returns a fake transcript, would make the
Record screen look finished and be a lie.

The contract expected of ``second.voice``, agreed in the brief:

    async def transcribe(audio: bytes, *, content_type: str) -> str

Anything else it exposes is CONNECTORS' business.
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)

WEBM = "audio/webm"
"""Bare, with no codecs parameter.

An S3 presigned PUT signs the content type, so ``audio/webm;codecs=opus`` --
which is what ``MediaRecorder.mimeType`` reports -- fails the signature check
and returns an opaque 403 that reads like a CORS error. The browser re-wraps the
blob; this is the server-side half of the same agreement."""


class MissingVoice(RuntimeError):
    """The voice seam has not been built yet, and says who owns it."""


class Transcriber(Protocol):
    async def __call__(self, audio: bytes, *, content_type: str) -> str: ...


def resolve_transcriber() -> Transcriber:
    """Find CONNECTORS' transcriber, or explain its absence.

    Resolved per call rather than at import, so the API starts, serves the
    fixture-backed screens and reports the gap on one route instead of failing
    to boot on all nine.
    """
    try:
        from second.voice import transcribe  # type: ignore[attr-defined]
    except ImportError as error:
        raise MissingVoice(
            "second.voice does not exist yet (owned by CONNECTORS). "
            "The browser's live transcript still works; the accurate one needs this."
        ) from error
    except AttributeError as error:  # pragma: no cover - module exists, symbol does not
        raise MissingVoice(
            "second.voice exists but does not export transcribe(audio, *, content_type) "
            "(owned by CONNECTORS)."
        ) from error

    return transcribe
