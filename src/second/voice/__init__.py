"""Voice intake: the server side of speaking your goals aloud.

SURFACES owns the microphone and the live transcript. This owns the upload, the
transcription, and whether the words are right.

The seam PLATFORM calls::

    start_transcription(audio_bytes, content_type) -> str        # job id
    get_transcription(job_id) -> tuple[str, str | None]          # (status, transcript)

Importing this module requires no AWS credentials and makes no network call. Every
boto3 client is built inside the function that uses it, because
``graphs/composition.py`` imports connector modules inside a ``try/except
ImportError`` -- and a credentials error raised at import time would escape that
and take the composition root down at startup instead of at first use.
"""

from second.voice.transcribe import (
    TranscriptionError,
    get_transcription,
    job_name,
    start_transcription,
    transcript_key,
)
from second.voice.upload import (
    CORS_CONFIGURATION,
    MAX_AUDIO_BYTES,
    VoiceError,
    audio_key,
    presigned_put,
    store_audio,
)

__all__ = [
    "CORS_CONFIGURATION",
    "MAX_AUDIO_BYTES",
    "TranscriptionError",
    "VoiceError",
    "audio_key",
    "get_transcription",
    "job_name",
    "presigned_put",
    "start_transcription",
    "store_audio",
    "transcript_key",
]
