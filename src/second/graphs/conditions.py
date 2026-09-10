"""The routing decisions, as typed predicates on graph state.

This is the architectural centrepiece of Second: **the decision to interrupt the
user is a typed field read by a conditional edge, not a prompt hoping for the
best.** The Diagnostician emits a ``Diagnosis``; the edge reads
``requires_user_decision``, ``confidence`` and ``blocker_type``; the Adapter acts
or the Communicator asks. No natural language is parsed to make that call.

Three constraints on everything in this module, each learned from the SDK source
rather than assumed:

**Conditions must be pure.** Each one is evaluated **at least twice** per
traversal -- once when routing (``graph.py:973``) and again when building the
next node's input (``graph.py:1213``), plus more with multiple incoming edges.
Do not log, count, mutate or call anything with a side effect from here. Assume
no particular call count at all.

**Sibling edges are independent OR-gates, not a switch.** ``add_edge`` conditions
are evaluated per edge, so two sibling edges that are both true will both fire
and *both* target nodes will run. Every branch pair here is therefore derived
from one shared predicate as strict logical complements -- ``x`` and ``not x`` --
so exactly one can hold.

**Never route on ``stop_reason``.** A structured-output run ends with
``stop_reason == "tool_use"``, because the loop short-circuits the moment the
schema tool validates. An edge testing for ``"end_turn"`` would never fire.
Route on the typed result being present, then on its fields.
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel
from strands.multiagent.graph import GraphState

from second.core.models import Diagnosis, ExtractionResult
from second.settings import CONFIDENCE_FLOOR

T = TypeVar("T", bound=BaseModel)


def typed_result(state: GraphState | Any, node_id: str, model_type: type[T]) -> T | None:
    """Read a node's structured output off the graph state.

    Accepts a ``GraphState`` (what an edge condition receives) or a
    ``GraphResult`` (what a completed run returns). Both expose the same
    ``results`` mapping and this only touches that, so one reader serves the
    edges and the service layer alike.

    Returns ``None`` rather than raising when the node did not run, failed, or
    exited without a typed result. That last case is real and silent: a run that
    hits ``limit_turns``, ``limit_total_tokens`` or is cancelled exits with
    ``structured_output`` set to ``None`` and **no exception raised**. Callers
    must treat ``None`` as "we do not know", which for Second always means ask
    rather than act.
    """
    node_result = state.results.get(node_id)
    if node_result is None:
        return None
    structured = getattr(getattr(node_result, "result", None), "structured_output", None)
    return structured if isinstance(structured, model_type) else None


# ---------------------------------------------------------------------------
# Daily graph: does Second act, or does it ask?
# ---------------------------------------------------------------------------


def needs_user_decision(state: GraphState) -> bool:
    """True when Second must ask the user rather than change the plan itself.

    Three ways this becomes true, and the third is the one that matters:

    1. The Diagnostician said so outright.
    2. It is not confident enough -- below ``CONFIDENCE_FLOOR``.
    3. It classified the blocker as ``UNKNOWN``. This is the honest
       "I can't tell -- what's blocking this?", and it is a feature. A system
       that always has an explanation is a system that invents them.

    Missing or untyped output also routes here. **Failure direction: ask.**
    Asking a needless question costs the user five seconds; acting on a
    diagnosis that was never made costs them a calendar they no longer trust.
    """
    diagnosis = typed_result(state, "diagnostician", Diagnosis)
    if diagnosis is None:
        return True
    return (
        diagnosis.requires_user_decision
        or diagnosis.confidence < CONFIDENCE_FLOOR
        or diagnosis.blocker_type == "UNKNOWN"
    )


def can_act_alone(state: GraphState) -> bool:
    """The strict complement of :func:`needs_user_decision`.

    Written as a negation rather than as its own set of tests, deliberately.
    Two independently-authored conditions drift, and because sibling edges are
    OR-gates rather than a switch, drift means both branches fire and the
    Adapter and the Communicator both run.
    """
    return not needs_user_decision(state)


# ---------------------------------------------------------------------------
# Intake graph: did we understand the person well enough to plan?
# ---------------------------------------------------------------------------


def extraction_needs_clarifying(state: GraphState) -> bool:
    """True when the Extractor could not confidently turn speech into goals.

    Loose speech is allowed to be loose. When it genuinely is not clear what
    someone wants, the honest move is to ask before building a plan on a guess --
    the same principle as the Daily graph's ``UNKNOWN``, one stage earlier.
    """
    extraction = typed_result(state, "extractor", ExtractionResult)
    if extraction is None:
        return True
    if extraction.clarifying_questions:
        return True
    if not extraction.goals:
        return True
    return any(goal.extraction_confidence < CONFIDENCE_FLOOR for goal in extraction.goals)


def extraction_is_clear(state: GraphState) -> bool:
    """The strict complement of :func:`extraction_needs_clarifying`."""
    return not extraction_needs_clarifying(state)


# ---------------------------------------------------------------------------
# Context-aware variant
# ---------------------------------------------------------------------------


def forced_path(name: str):
    """Build a condition that follows an override supplied at invocation time.

    Used by the demo to drive a specific branch deterministically on stage,
    without touching the real predicates.

    **The parameter must literally be named ``invocation_state``.** The SDK
    dispatches context-style conditions by inspecting the parameter name
    (``graph.py:98-110``); spell it anything else and it silently degrades to the
    one-argument convention and raises ``TypeError`` at traversal time.
    """

    def condition(state: GraphState, *, invocation_state: dict[str, Any], **kwargs: Any) -> bool:
        override = invocation_state.get("second", {}).get("force_path")
        return override == name

    return condition
