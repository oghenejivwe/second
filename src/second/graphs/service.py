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
    Communique,
    ExtractionResult,
    FeedbackResult,
    GoalStatus,
    IntakeResult,
    LivingGraph,
    ScheduleDecision,
    TodayCard,
)
from second.graphs.conditions import typed_result
from second.graphs.daily import build_daily_graph
from second.graphs.feedback import build_feedback_graph
from second.graphs.intake import build_intake_graph
from second.persistence.store import LivingGraphStore
from second.settings import DEMO_USER_ID

logger = logging.getLogger(__name__)

_store: LivingGraphStore | None = None


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
    composed = build_intake_graph(store=get_store(), user_id=user_id, today=today, **build_kwargs)
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
) -> TodayCard | None:
    """Run one day's cycle.

    Returns ``None`` when Second decided there was nothing worth saying. That is
    the common case and it is correct -- the reason is recorded in the audit log,
    so silence is auditable rather than indistinguishable from a failure.
    """
    composed = build_daily_graph(store=get_store(), user_id=user_id, today=today, **build_kwargs)
    result = await composed.run("Yesterday's plan against what actually happened.")

    communique = typed_result(result, "communicator", Communique)  # type: ignore[arg-type]
    if communique is None:
        logger.warning("communicator produced no typed result; staying silent")
        return None
    if not communique.should_speak:
        logger.info("silence: %s", communique.silence_reason)
        return None
    return communique.card


async def run_feedback(
    user_id: str = DEMO_USER_ID,
    text: str = "",
    *,
    today: date | None = None,
    **build_kwargs: Any,
) -> FeedbackResult:
    """Apply what the user said back to the plan."""
    composed = build_feedback_graph(store=get_store(), user_id=user_id, today=today, **build_kwargs)
    result = await composed.run(text)

    interpreted = typed_result(result, "interpreter", FeedbackResult)  # type: ignore[arg-type]
    return interpreted or FeedbackResult()
