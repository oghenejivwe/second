"""The nine routes. Every one is a call into ``graphs.service`` plus serialisation.

**There is no logic in this file and that is the design.** HTTP shape is a UI
concern; agent orchestration is not. The seam between them is where the two
domains stop colliding, so a route that started computing something would be a
defect in the architecture rather than a style problem.

**Every payload is ``model_dump(mode="json")``, sent through an explicit
``JSONResponse``.** Not ``response_model=``, and not a bare pydantic return.
Both of those hand the object to FastAPI's own encoder, which re-walks and
re-validates it -- work already done, and a second chance for a datetime to come
out in a shape the browser did not expect. The contract says pydantic's own JSON
mode is what the browser sees, so that is literally what is sent.

That matters most for datetimes, where the asymmetry is deliberate and load-
bearing: ``ScheduledBlock.start`` carries an offset and ``Task.scheduled_slots``
do not, because the Living Graph stores wall-clock time. Re-encoding risks
normalising one into the other, and an hour that moves between two screens is a
plan the user stops trusting.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Path, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from second.api.voice import WEBM, read_job, resolve_voice
from second.core.models import GoalStatus
from second.graphs import service
from second.settings import DEMO_USER_ID

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

def sent(model: BaseModel) -> JSONResponse:
    """Serialise exactly as the contract promises, and not a second time."""
    return JSONResponse(content=model.model_dump(mode="json"))


# --- what the browser sends -------------------------------------------------


class TranscriptIn(BaseModel):
    transcript: str = Field(min_length=1, max_length=20_000)


class FeedbackIn(BaseModel):
    text: str = Field(min_length=1, max_length=8_000)


class GoalStatusIn(BaseModel):
    status: GoalStatus


# --- the graph --------------------------------------------------------------


@router.get("/graph")
def read_graph() -> JSONResponse:
    """The whole Living Graph, for rendering."""
    graph = service.load_living_graph(DEMO_USER_ID)
    return JSONResponse(content={"graph": graph.model_dump(mode="json")})


@router.get("/audit")
def read_audit(limit: int = Query(default=50, ge=1, le=500)) -> JSONResponse:
    """The most recent things the system did, newest first.

    The demo's primary evidence that Second is doing what it claims, which is
    why the limit is generous: a judge scrolling back through a whole run is the
    intended use.
    """
    entries = service.read_audit(DEMO_USER_ID, limit=limit)
    return JSONResponse(content={"entries": [entry.model_dump(mode="json") for entry in entries]})


# --- the day ----------------------------------------------------------------


@router.get("/today")
async def read_today() -> JSONResponse:
    """Today's brief.

    **A brief is always returned.** Existing is not interrupting: the schedule
    is a plan the user asked for and it is there whenever they look. What stays
    rare is ``notify`` and ``decisions``.

    This runs the Daily graph rather than reading a cached brief, because there
    is nowhere to cache one -- the store holds the Living Graph, not the day.
    Worth knowing before wiring a poll to it: a GET here is not cheap.
    """
    brief = await service.run_daily(DEMO_USER_ID)
    return sent(brief)


@router.post("/daily/run")
async def run_daily() -> JSONResponse:
    """Run the daily cycle now.

    Tens of seconds, awaited in the request. Deliberate: the alternative is a
    job id and a poll, and the screen already has something true to show while
    it waits. A brief that arrives with the response cannot be missed.
    """
    brief = await service.run_daily(DEMO_USER_ID)
    return sent(brief)


# --- intake -----------------------------------------------------------------


@router.post("/intake")
async def run_intake(body: TranscriptIn) -> JSONResponse:
    """Turn a spoken brain dump into a plan in the user's calendar.

    Returns the whole ``IntakeResult`` verbatim -- ``graph``,
    ``clarifying_questions``, ``schedule``. The brief's route table called that
    last-but-one key ``questions``; the same brief says every payload is the
    model's own dump with no bespoke shapes, and the model wins.

    When ``clarifying_questions`` is non-empty, ``schedule`` is ``None`` and the
    graph stopped on purpose: it was not clear enough what the user wanted to
    justify putting anything in their calendar.
    """
    result = await service.run_intake(DEMO_USER_ID, body.transcript)
    return sent(result)


@router.post("/feedback")
async def run_feedback(body: FeedbackIn) -> JSONResponse:
    """Apply what the user said back to the plan.

    Also carries the daily check-in's answers -- by ruling, there is no separate
    check-in route. The Interpreter turns the text into typed
    ``CompletionReport``s, and the user's answer beats every inference.
    """
    result = await service.run_feedback(DEMO_USER_ID, body.text)
    return sent(result)


# --- goals ------------------------------------------------------------------


@router.post("/goals/{goal_id}/status")
def set_goal_status(body: GoalStatusIn, goal_id: str = Path(min_length=1)) -> JSONResponse:
    """Pause, retire or reactivate a goal, and say what time it released.

    Returns ``GoalStatusChange``, not the bare graph: ``freed`` carries the
    upcoming slots the goal was holding, each a full ``ScheduledBlock`` with its
    ladder intact.

    It reports time **freed**, never redistributed. The Scheduler has not run at
    this point, so nothing has moved; ``note`` says when it will. A missing goal
    raises ``ValueError`` in the service and becomes a 404 in ``app.py``.
    """
    change = service.set_goal_status(DEMO_USER_ID, goal_id, body.status)
    return sent(change)


# --- voice ------------------------------------------------------------------


@router.post("/voice")
def start_voice(audio: UploadFile = File()) -> JSONResponse:
    """Take the recorded audio and start transcribing it.

    A **sync** route on purpose. CONNECTORS' ``start_transcription`` is
    blocking -- it puts the object in S3 and calls Transcribe -- and calling it
    from an ``async def`` would stall the event loop for the whole round trip,
    stopping every other request including the poll that follows. FastAPI runs a
    sync route in a worker thread, which is the idiom for exactly this, and it is
    why ``audio.file.read()`` appears here rather than ``await audio.read()``.

    Read fully before starting, also on purpose: ``UploadFile`` is tied to the
    request, and anything holding it afterwards would be reading from a file
    Starlette has already closed.

    The content type is forced to bare ``audio/webm``. The browser sends that
    too -- an S3 presigned PUT signs the content type, and
    ``audio/webm;codecs=opus`` fails the signature with an opaque 403 that reads
    like CORS. Both halves of that agreement are written down where someone
    tempted to "fix" either will see it.
    """
    seam = resolve_voice()
    payload = audio.file.read()

    if not payload:
        return JSONResponse(status_code=400, content={"detail": "The upload was empty."})
    if len(payload) > seam.max_bytes:
        # Checked against CONNECTORS' own constant, so the two cannot drift. They
        # check it again inside store_audio; this one exists to refuse before the
        # bytes are handed on.
        return JSONResponse(
            status_code=413,
            content={
                "detail": (
                    f"That recording is {len(payload) // 1_000_000} MB; the limit is "
                    f"{seam.max_bytes // 1_000_000} MB."
                )
            },
        )

    try:
        job_id = seam.start(payload, WEBM)
    except seam.rejected as error:
        # The recording itself is unusable. The user can do something about that.
        return JSONResponse(status_code=400, content={"detail": str(error)})
    except seam.broke as error:
        # Transcribe would not take the job. Nothing the user can do, and the
        # live transcript is still on screen, so this is not fatal to the intake.
        logger.warning("could not start transcription", exc_info=True)
        return JSONResponse(status_code=502, content={"detail": str(error)})

    return JSONResponse(content={"job_id": job_id})


@router.get("/voice/{job_id}")
def read_voice(job_id: str = Path(min_length=1)) -> JSONResponse:
    """Where that transcription got to.

    Sync for the same reason as the POST: the seam makes a blocking AWS call.

    Always 200 with a status, including for a job that died -- see
    ``api/voice.read_job``. A browser in a polling loop needs to be told to stop,
    and a 500 does not tell it that.
    """
    seam = resolve_voice()
    return JSONResponse(content=read_job(seam, job_id))
