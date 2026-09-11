"""What the HTTP layer calls. The only door into the graphs.

SURFACES owns the routes; PLATFORM owns what happens behind them. Everything
here returns a type from ``second.core.models``, so the API layer serialises and
does not interpret.

Every function is safe to call before its agents exist: a missing agent module
raises ``MissingAgent`` naming the module and its owner, rather than an
ImportError three frames deep.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Any

from second.core.models import (
    AuditEntry,
    BriefJudgement,
    DailyBrief,
    ExtractionResult,
    FeedbackResult,
    GoalStatus,
    GoalStatusChange,
    IntakeResult,
    LivingGraph,
    ObservationReport,
    PreparedAction,
    ScheduledBlock,
    ScheduleDecision,
)
from second.core.clock import Clock
from second.graphs.brief import assemble, blocks_on
from second.graphs.composition import resolve_clock
from second.graphs.conditions import typed_result
from second.graphs.daily import build_daily_graph
from second.graphs.feedback import build_feedback_graph
from second.graphs.intake import build_intake_graph
from second.persistence.serde import decimals_to_native
from second.persistence.store import LivingGraphStore
from second.settings import DEMO_TODAY_ENV, DEMO_USER_ID

logger = logging.getLogger(__name__)

_store: LivingGraphStore | None = None


def _plural(count: int, noun: str) -> str:
    """"1 slot", "3 slots". A string in the demo should not read "3 slot(s)"."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _span(minutes: int) -> str:
    """Minutes as something a person would say out loud."""
    if minutes < 60:
        return _plural(minutes, "minute")
    hours = minutes / 60
    if hours.is_integer():
        return _plural(int(hours), "hour")
    return f"{hours:.1f} hours"


def _clock_for(today: date | None) -> Clock:
    """Build the clock for a run.

    ``today`` stays in the public signatures because the HTTP layer and the
    scheduled trigger both want to pin a date. When it is not given, the
    timezone is discovered from the user's calendar rather than asked for.
    """
    resolved = resolve_clock()
    if today is None:
        pinned = os.environ.get(DEMO_TODAY_ENV)
        if pinned:
            return Clock.fixed(date.fromisoformat(pinned), zone_name=resolved.name)
        return resolved
    return Clock.fixed(today, zone_name=resolved.name)


def get_store() -> LivingGraphStore:
    """The process-wide Living Graph store, built on first use.

    Lazy so that importing this module needs no AWS credentials -- which matters
    because the API layer imports it at startup and the tests never want it.
    """
    global _store
    if _store is None:
        _store = LivingGraphStore()
    return _store


def set_store(store: LivingGraphStore | None) -> None:
    """Replace the store. For tests and for the AgentCore entrypoint."""
    global _store
    _store = store


# ---------------------------------------------------------------------------


def load_living_graph(user_id: str = DEMO_USER_ID) -> LivingGraph:
    """Read the whole Living Graph, for rendering."""
    return get_store().load(user_id)


def read_audit(user_id: str = DEMO_USER_ID, limit: int = 50) -> list[AuditEntry]:
    """Read the most recent things the system did, newest first."""
    return get_store().read_audit(user_id, limit)


def set_goal_status(
    user_id: str,
    goal_id: str,
    status: GoalStatus,
    *,
    today: date | None = None,
) -> GoalStatusChange:
    """Pause, retire or reactivate a goal, and say what time it released.

    Returns the freed slots as real data rather than leaving the caller to work
    them out. SURFACES is forbidden from computing a plan in the client, and it
    is right to be: a schedule Second did not make is a schedule Second cannot
    stand behind.

    **It reports time freed, not time redistributed.** The Scheduler has not run
    again at this point, so nothing has moved yet. The next daily run reallocates
    it, and ``note`` says so. Claiming a redistribution that has not happened
    would be exactly the kind of confident fiction this product exists to avoid.

    Args:
        user_id: Whose goal this is.
        goal_id: The goal to change.
        status: ``"active"``, ``"paused"`` or ``"retired"``.
        today: Pin the day, for reproducible scenarios.

    Returns:
        The graph as written, the upcoming slots released, and what happens next.

    Raises:
        ValueError: If the goal is not in the graph.
    """
    clock = _clock_for(today)
    before = get_store().load(user_id)
    goal = before.goal_by_id(goal_id)
    if goal is None:
        raise ValueError(f"no goal {goal_id!r} for {user_id!r}")

    freed: list[ScheduledBlock] = []
    if status in ("paused", "retired"):
        # Computed BEFORE the status changes, because afterwards the goal is
        # excluded from scheduling and its slots become invisible.
        seen: set[tuple[str, datetime]] = set()
        for horizon_day in range(0, 28):
            for block in blocks_on(before, clock, clock.today + timedelta(days=horizon_day)):
                if block.goal_id == goal_id and (block.task_id, block.start) not in seen:
                    seen.add((block.task_id, block.start))
                    freed.append(block)

    def change(graph: LivingGraph) -> None:
        target = graph.goal_by_id(goal_id)
        if target is None:
            raise ValueError(f"no goal {goal_id!r} for {user_id!r}")
        target.status = status

    written = get_store().mutate(user_id, change)

    minutes = sum(block.duration_min for block in freed)
    if status == "active":
        note = f"{goal.title!r} is active again. The next daily run will schedule it."
    elif not freed:
        note = f"{goal.title!r} is {status}. It was holding no upcoming slots."
    else:
        note = (
            f"{_plural(len(freed), 'slot')} over the next four weeks, "
            f"{_span(minutes)} in all, {'is' if len(freed) == 1 else 'are'} now free. "
            "The next daily run reallocates the time to the goals still active."
        )

    return GoalStatusChange(
        goal_id=goal_id,
        goal_title=goal.title,
        status=status,
        graph=written,
        freed=freed,
        freed_minutes=minutes,
        note=note,
    )


# ---------------------------------------------------------------------------


async def run_intake(
    user_id: str = DEMO_USER_ID,
    transcript: str = "",
    *,
    today: date | None = None,
    **build_kwargs: Any,
) -> IntakeResult:
    """Turn a spoken brain dump into a plan in the user's calendar.

    Returns early with clarifying questions and no schedule when the Extractor
    was not confident -- the graph is built to stop there rather than plan on a
    guess.
    """
    composed = build_intake_graph(
        store=get_store(), user_id=user_id, clock=_clock_for(today), **build_kwargs
    )
    result = await composed.run(transcript)

    extraction = typed_result(result, "extractor", ExtractionResult)
    schedule = typed_result(result, "scheduler", ScheduleDecision)

    return IntakeResult(
        graph=load_living_graph(user_id),
        clarifying_questions=list(extraction.clarifying_questions) if extraction else [],
        schedule=schedule,
    )


def runtime_status(user_id: str = DEMO_USER_ID) -> dict[str, Any]:
    """What is actually running, so a screen never has to claim it.

    SURFACES declined to hardcode "Sonnet 5, direct API" on the grounds that they
    could not verify it at runtime. That instinct is right and it is the same rule
    the product applies to itself: do not assert what you have not checked.

    Every value here is read from live configuration rather than written down.
    """
    from second.settings import (
        ANTHROPIC_MODEL_ID,
        AWS_REGION,
        BEDROCK_MODEL_ID,
        MAX_MODEL_CALLS_PER_NODE,
        MODEL_PROVIDER,
    )

    provider = MODEL_PROVIDER.lower()
    clock = _clock_for(None)
    return {
        "provider": provider,
        "model": ANTHROPIC_MODEL_ID if provider == "anthropic" else BEDROCK_MODEL_ID,
        "region": AWS_REGION if provider == "bedrock" else None,
        "timezone": clock.name,
        "timezone_source": clock.source,
        "timezone_trustworthy": clock.is_trustworthy,
        "today": clock.today.isoformat(),
        "max_model_calls_per_node": MAX_MODEL_CALLS_PER_NODE,
        "user_id": user_id,
    }


def get_today(user_id: str = DEMO_USER_ID, today: date | None = None) -> DailyBrief:
    """Read today's brief WITHOUT running the graph.

    ``GET /api/today`` used to invoke the whole Daily flow -- five agents, tens of
    seconds, real tokens -- on a route a browser might poll. SURFACES found it.

    So reading is now free and running is deliberate. If a brief was computed
    today it comes back as it was. If not, the day is assembled from the Living
    Graph alone: the schedule and the deadline risks are facts and cost nothing,
    and the judgement-shaped parts are simply absent rather than invented.

    **Failure direction: show the factual day.** A user opening the app before the
    morning run should see their schedule, not a spinner and not an error.
    """
    clock = _clock_for(today)
    cached = get_store().load_brief(user_id, clock.today)
    if cached:
        return DailyBrief.model_validate(decimals_to_native(cached))

    return assemble(
        graph=load_living_graph(user_id),
        clock=clock,
        judgement=None,
        observations=None,
    )


async def run_daily(
    user_id: str = DEMO_USER_ID,
    today: date | None = None,
    **build_kwargs: Any,
) -> DailyBrief:
    """Run one day's cycle and return the day.

    **A brief is always returned.** Existing is not interrupting: the schedule is
    a plan the user asked for, and it is there whenever they look. What stays
    rare is ``notify`` and ``decisions`` -- and when both are empty,
    ``silence_reason`` records why, so quietness is auditable rather than
    indistinguishable from a failure.

    The schedule and the deadline risks are computed from the Living Graph rather
    than asked of a model, so no block in this brief can be imaginary.
    """
    clock = _clock_for(today)
    composed = build_daily_graph(store=get_store(), user_id=user_id, clock=clock, **build_kwargs)
    result = await composed.run("Yesterday's plan against what actually happened.")

    judgement = typed_result(result, "communicator", BriefJudgement)
    if judgement is None:
        logger.warning("communicator produced no typed result; falling back to a factual brief")

    prepared_action = typed_result(result, "preparer", PreparedAction)
    observations = typed_result(result, "observer", ObservationReport)

    brief = assemble(
        graph=load_living_graph(user_id),
        clock=clock,
        judgement=judgement,
        prepared=[prepared_action] if prepared_action else [],
        observations=observations,
    )
    get_store().save_brief(user_id, brief)
    if brief.is_quiet:
        logger.info("quiet day: %s", brief.silence_reason or "nothing needed the user")
    return brief


async def run_feedback(
    user_id: str = DEMO_USER_ID,
    text: str = "",
    *,
    today: date | None = None,
    **build_kwargs: Any,
) -> FeedbackResult:
    """Apply what the user said back to the plan."""
    composed = build_feedback_graph(
        store=get_store(), user_id=user_id, clock=_clock_for(today), **build_kwargs
    )
    result = await composed.run(text)

    interpreted = typed_result(result, "interpreter", FeedbackResult)  # type: ignore[arg-type]
    return interpreted or FeedbackResult()
