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
from datetime import date
from typing import Any

from second.core.models import (
    AuditEntry,
    BriefJudgement,
    DailyBrief,
    ExtractionResult,
    FeedbackResult,
    GoalStatus,
    IntakeResult,
    LivingGraph,
    PreparedAction,
    ScheduleDecision,
)
from second.core.clock import Clock
from second.graphs.brief import assemble
from second.graphs.composition import resolve_clock
from second.graphs.conditions import typed_result
from second.graphs.daily import build_daily_graph
from second.graphs.feedback import build_feedback_graph
from second.graphs.intake import build_intake_graph
from second.persistence.store import LivingGraphStore
from second.settings import DEMO_USER_ID

logger = logging.getLogger(__name__)

_store: LivingGraphStore | None = None


def _clock_for(today: date | None) -> Clock:
    """Build the clock for a run.

    ``today`` stays in the public signatures because the HTTP layer and the
    scheduled trigger both want to pin a date. When it is not given, the
    timezone is discovered from the user's calendar rather than asked for.
    """
    resolved = resolve_clock()
    if today is None:
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
    reschedule: bool = False,
) -> LivingGraph:
    """Pause, retire or reactivate a goal.

    Args:
        user_id: Whose goal this is.
        goal_id: The goal to change.
        status: ``"active"``, ``"paused"`` or ``"retired"``.
        reschedule: Reserved for re-running the Scheduler over the freed time.
            Not yet wired -- the Goals screen currently shows the freed slots and
            the next Daily run reallocates them.

    Returns:
        The graph as written.

    Raises:
        ValueError: If the goal is not in the graph.
    """
    def change(graph: LivingGraph) -> None:
        goal = next((candidate for candidate in graph.goals if candidate.id == goal_id), None)
        if goal is None:
            raise ValueError(f"no goal {goal_id!r} for {user_id!r}")
        goal.status = status

    return get_store().mutate(user_id, change)


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

    brief = assemble(
        graph=load_living_graph(user_id),
        clock=clock,
        judgement=judgement,
        prepared=[prepared_action] if prepared_action else [],
    )
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
