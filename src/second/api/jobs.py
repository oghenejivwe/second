"""Voice transcription jobs, tracked in-process.

``POST /api/voice`` hands back a job id immediately and the browser polls
``GET /api/voice/{job_id}``, because Amazon Transcribe takes tens of seconds and
an HTTP request that waits that long is a request that times out somewhere
between here and the user.

**Why not ``BackgroundTasks``.** Starlette runs background tasks *after* the
response is sent, which is the right shape, but a task that raises has nowhere
to put the exception: it is logged by the server and the caller is never told.
For a poll-for-status endpoint that failure mode is exactly wrong -- the browser
would poll a job that is already dead, forever. So the exception is captured and
becomes ``status == "failed"`` with the reason attached.

**Failure direction: fail the job loudly and keep the live transcript.** The
Record screen already has words on screen from the Web Speech API by the time
this runs. If the accurate transcript never arrives, the user loses the upgrade,
not the intake -- so a failed job is a line of explanation, not a dead end.

This registry is deliberately process-local and unbounded-in-time only by the
sweep below. There is one user and one demo; a Redis-backed job store would be
infrastructure for a problem this build does not have.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

logger = logging.getLogger(__name__)

JobStatus = Literal["running", "done", "failed"]

MAX_JOBS = 64
"""Keep the most recent jobs only. A demo makes a handful; a leak here would be
a slow one, but a bounded dict costs nothing and removes the question."""

STALE_AFTER = timedelta(hours=1)


@dataclass
class Job:
    """One transcription, from upload to transcript."""

    id: str
    status: JobStatus = "running"
    transcript: str | None = None
    error: str | None = None
    started: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    task: asyncio.Task[str] | None = None


class JobRegistry:
    """Somewhere for an in-flight transcription to live."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def start(self, work: Awaitable[str]) -> Job:
        """Run ``work`` in the background and return the job tracking it.

        ``work`` resolves to the transcript. Anything it raises is recorded on
        the job rather than escaping into the event loop's exception handler,
        where the browser could never see it.
        """
        job = Job(id=uuid.uuid4().hex)
        self._jobs[job.id] = job
        self._sweep()

        async def run() -> str:
            try:
                transcript = await work
            except asyncio.CancelledError:
                job.status = "failed"
                job.error = "The transcription was cancelled before it finished."
                raise
            except Exception as error:  # noqa: BLE001 - the point is to keep it
                job.status = "failed"
                job.error = f"{type(error).__name__}: {error}"
                logger.warning("voice job %s failed", job.id, exc_info=True)
                return ""
            job.status = "done"
            job.transcript = transcript
            return transcript

        job.task = asyncio.create_task(run(), name=f"voice:{job.id}")
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def _sweep(self) -> None:
        """Drop finished jobs once they are old, and cap the total."""
        cutoff = datetime.now(timezone.utc) - STALE_AFTER
        for job_id, job in list(self._jobs.items()):
            if job.status != "running" and job.started < cutoff:
                del self._jobs[job_id]

        while len(self._jobs) > MAX_JOBS:
            oldest = min(self._jobs.values(), key=lambda job: job.started)
            del self._jobs[oldest.id]


registry = JobRegistry()
"""The process-wide registry. Replaced in tests."""
