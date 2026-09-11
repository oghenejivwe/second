"""The tools every agent uses to read and write the Living Graph.

These docstrings are not documentation. The ``@tool`` decorator turns each type
hint and docstring into the tool spec the model reads, so the wording here is
part of the prompt. Vague phrasing produces vague tool calls.

**Tools raise; they never return an error dict.** The decorator already catches
every exception, formats a proper error result, and attaches the original
exception to ``AfterToolCallEvent.exception``. A hand-built error dict passes
straight through and leaves that ``None``, stripping the audit record of its
stack context -- which matters precisely because the audit trail is the evidence.

The store arrives through ``invocation_state["second"]["store"]``, injected once
per run by the graph. Namespacing is required rather than tidy: the SDK writes
reserved keys (``agent``, ``messages``, ``system_prompt``, ``tool_config``,
``request_state``, ``event_loop_cycle_*``) onto the caller's own dict mid-run.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from strands import ToolContext, tool

from second.core.models import Diagnosis, Goal, Link, LivingGraph, Slip
from second.persistence.store import LivingGraphStore
from second.settings import NAMESPACE

LAYERS = ("goals", "person", "links", "all")


class GraphToolError(RuntimeError):
    """A graph tool was asked for something the graph cannot do."""


def run_scope(invocation_state: dict[str, Any]) -> dict[str, Any]:
    """Second's own corner of the run-wide shared dict."""
    return invocation_state.setdefault(NAMESPACE, {})


def _store(tool_context: ToolContext) -> LivingGraphStore:
    scope = run_scope(tool_context.invocation_state)
    store = scope.get("store")
    if store is None:
        raise GraphToolError(
            "no Living Graph store on this run. The graph must inject "
            'invocation_state["second"]["store"] before invoking.'
        )
    return store


def _upsert_by_id(existing: list, incoming: list, model_type: type) -> list:
    """Replace matching ids, append new ones, preserve order."""
    by_id = {item.id: item for item in existing}
    for raw in incoming:
        parsed = model_type.model_validate(raw)
        by_id[parsed.id] = parsed
    ordered = [by_id.pop(item.id) for item in existing if item.id in by_id]
    return ordered + list(by_id.values())


# ---------------------------------------------------------------------------


@tool(context=True)
def read_graph(user_id: str, layer: str, tool_context: ToolContext) -> dict:
    """Read the user's Living Graph -- their goals, what is known about them, or both.

    Args:
        user_id: Whose graph to read. Use the id given in your instructions.
        layer: Which part to read. One of:
            "goals" for goals, their routes and tasks, including slip history;
            "person" for observed preferences, constraints, honoured and
            abandoned time slots, recurring blockers and resources already
            served; "links" for the connections between the two; "all" for
            everything.

    Returns:
        The requested layer as a dictionary.

    Raises:
        GraphToolError: If the layer is not one of the four listed above.
    """
    if layer not in LAYERS:
        raise GraphToolError(f"unknown layer {layer!r}; expected one of {LAYERS}")

    graph = _store(tool_context).load(user_id)

    if layer == "goals":
        return {"goals": [goal.model_dump(mode="json") for goal in graph.goals]}
    if layer == "person":
        return graph.person.model_dump(mode="json")
    if layer == "links":
        return {"links": [link.model_dump(mode="json") for link in graph.links]}
    return graph.model_dump(mode="json")


@tool(context=True)
def write_graph(user_id: str, layer: str, patch: dict, tool_context: ToolContext) -> str:
    """Add or update goals or links in the Living Graph.

    Existing entries with the same id are replaced; new ids are appended. Nothing
    is ever deleted by this tool -- to stop working on a goal, use
    set_goal_status instead.

    Args:
        user_id: Whose graph to change.
        layer: Either "goals" or "links". To change what is known about the
            person, use update_person_model.
        patch: For "goals", {"goals": [ ... ]} where each entry is a complete
            goal object including its routes and tasks. For "links",
            {"links": [ ... ]}.

    Returns:
        A description of what changed, naming the ids affected.

    Raises:
        GraphToolError: If the layer is not "goals" or "links", or the patch does
            not carry the matching key.
    """
    if layer not in ("goals", "links"):
        raise GraphToolError(f"write_graph handles 'goals' and 'links', not {layer!r}")

    incoming = patch.get(layer)
    if not isinstance(incoming, list):
        raise GraphToolError(f'patch must be {{"{layer}": [...]}}; got keys {sorted(patch)}')

    def change(graph: LivingGraph) -> None:
        if layer == "goals":
            graph.goals = _upsert_by_id(graph.goals, incoming, Goal)
        else:
            graph.links.extend(Link.model_validate(raw) for raw in incoming)

    _store(tool_context).mutate(user_id, change)

    ids = [raw.get("id", "?") for raw in incoming] if layer == "goals" else [str(len(incoming))]
    return f"wrote {len(incoming)} {layer} entr{'y' if len(incoming) == 1 else 'ies'}: {ids}"


@tool(context=True)
def update_person_model(user_id: str, patch: dict, tool_context: ToolContext) -> str:
    """Record something observed about how this person actually operates.

    Structural facts only. Record what happened, never why you think it happened.
    "6pm gym declined 4 of 5 weekdays" is a fact. "They are not committed to the
    gym" is not, and does not belong in this system.

    List fields are appended to, without duplicates. The preferences dictionary
    is merged.

    Args:
        user_id: Whose person model to update.
        patch: Any of: {"preferences": {"learning_mode": "video"}},
            {"constraints": ["no work before 10am"]},
            {"honoured_slots": ["Tue 07:00"]}, {"abandoned_slots": ["Wed 18:00"]},
            {"recurring_blockers": ["..."]}, {"resources_served": ["..."]}.

    Returns:
        A description of what was recorded.

    Raises:
        GraphToolError: If the patch names a field the person model does not have.
    """
    list_fields = (
        "constraints",
        "honoured_slots",
        "abandoned_slots",
        "recurring_blockers",
        "resources_served",
    )
    allowed = {"preferences", *list_fields}
    unknown = sorted(set(patch) - allowed)
    if unknown:
        raise GraphToolError(f"person model has no field(s) {unknown}; expected {sorted(allowed)}")

    def change(graph: LivingGraph) -> None:
        person = graph.person
        for key, value in patch.get("preferences", {}).items():
            person.preferences[str(key)] = str(value)
        for name in list_fields:
            target = getattr(person, name)
            for value in patch.get(name, []):
                if value not in target:
                    target.append(value)

    _store(tool_context).mutate(user_id, change)
    return f"recorded person-layer update: {sorted(patch)}"


@tool(context=True)
def record_diagnosis(user_id: str, diagnosis: dict, tool_context: ToolContext) -> str:
    """File a diagnosis against the task it explains.

    Records the slip on the task and, when the diagnosis is confident and
    structural, notes the blocker as recurring so the same cause is recognised
    faster next time.

    Args:
        user_id: Whose graph this diagnosis belongs to.
        diagnosis: A complete diagnosis: task_id, blocker_type, evidence,
            confidence, proposed_action and requires_user_decision.

    Returns:
        A description of what was filed.

    Raises:
        GraphToolError: If the diagnosis names a task that is not in the graph.
    """
    parsed = Diagnosis.model_validate(diagnosis)

    def change(graph: LivingGraph) -> None:
        task = graph.task_by_id(parsed.task_id)
        if task is None:
            raise GraphToolError(f"no task {parsed.task_id!r} in the graph")
        if parsed.blocker_type == "UNMET_DEPENDENCY":
            task.status = "blocked"
        if parsed.confidence >= 0.7 and parsed.blocker_type != "UNKNOWN":
            note = f"{parsed.blocker_type}: {parsed.evidence}"
            if note not in graph.person.recurring_blockers:
                graph.person.recurring_blockers.append(note)

    _store(tool_context).mutate(user_id, change)
    return (
        f"filed {parsed.blocker_type} against {parsed.task_id} "
        f"(confidence {parsed.confidence:.2f}, "
        f"{'needs the user' if parsed.requires_user_decision else 'actionable alone'})"
    )


@tool(context=True)
def record_completion(
    user_id: str,
    task_id: str,
    did_it: bool,
    tool_context: ToolContext,
    note: str = "",
) -> str:
    """Record what the user said actually happened with a task.

    **This is ground truth and it overrides every inference.** The calendar can
    show that an invite was declined and the inbox can show that a mail was never
    sent, but nothing anywhere can show whether somebody actually did a
    five-minute recording. The person was there; the system was not.

    When the user gives a reason for not doing something, it is written to the
    task as a known blocker, and Second does not ask about it again. Being asked
    the same question twice is how a system tells you it was not listening.

    Args:
        user_id: Whose graph this is.
        task_id: The task being reported on.
        did_it: True if the user says they did it.
        note: Anything they said about it, in their own words. Optional, and the
            most valuable field here when it is present.

    Returns:
        A description of what was recorded, including any slip that was reversed.

    Raises:
        GraphToolError: If the task is not in the graph.
    """
    outcome: list[str] = []

    def change(graph: LivingGraph) -> None:
        task = graph.task_by_id(task_id)
        if task is None:
            raise GraphToolError(f"no task {task_id!r} in the graph")

        clock = run_scope(tool_context.invocation_state).get("clock")
        slot = task.scheduled_slots[-1] if task.scheduled_slots else None
        label = clock.slot_label(slot) if clock and slot else None

        if note:
            # Kept on BOTH branches. "I did it, I just never opened the calendar"
            # is an explanation, and it is the explanation behind demo beat 4 --
            # a task that slipped into slots nothing was competing for. Taking it
            # in and discarding it is how a system asks the same question twice.
            task.known_blocker = note
            outcome.append("recorded the reason, so it will not ask again")

        if did_it:
            task.status = "done"
            # An inferred slip the user has just contradicted is wrong, not
            # merely outweighed. Remove it rather than averaging it.
            reversed_slips = [slip for slip in task.slips if slip.noticed_by != "user"]
            if reversed_slips and task.slip_count:
                task.slip_count = max(0, task.slip_count - 1)
                task.slips = [slip for slip in task.slips if slip.noticed_by == "user"]
                outcome.append("reversed an inferred slip")
            if label and label not in graph.person.honoured_slots:
                graph.person.honoured_slots.append(label)
                outcome.append(f"learned {label} as honoured")
            if label in graph.person.abandoned_slots:
                graph.person.abandoned_slots.remove(label)
            return

        task.slip_count += 1
        task.slips.append(
            Slip(
                on=clock.today if clock else date.today(),
                scheduled_for=slot,
                noticed_by="user",
                note=note,
            )
        )
        if label and task.slip_count >= 2 and label not in graph.person.abandoned_slots:
            graph.person.abandoned_slots.append(label)
            outcome.append(f"learned {label} as abandoned")

    _store(tool_context).mutate(user_id, change)

    verdict = "done" if did_it else "not done"
    tail = f"; {', '.join(outcome)}" if outcome else ""
    return f"{task_id} marked {verdict} on the user's own report{tail}"


@tool(context=True)
def set_goal_status(user_id: str, goal_id: str, status: str, tool_context: ToolContext) -> str:
    """Pause, retire or reactivate a goal.

    Retiring or pausing a goal frees the calendar time its routes were holding,
    which the Scheduler can then give to the goals still active. Nothing is
    deleted -- a retired goal keeps its history and can be reactivated.

    Args:
        user_id: Whose goal this is.
        goal_id: The goal to change.
        status: "active", "paused" or "retired".

    Returns:
        A description of the change, including how many scheduled slots were
        freed.

    Raises:
        GraphToolError: If the status is not one of the three, or the goal is not
            in the graph.
    """
    if status not in ("active", "paused", "retired"):
        raise GraphToolError(f"status must be active, paused or retired; got {status!r}")

    freed: list[int] = []

    def change(graph: LivingGraph) -> None:
        goal = next((candidate for candidate in graph.goals if candidate.id == goal_id), None)
        if goal is None:
            raise GraphToolError(f"no goal {goal_id!r} in the graph")
        goal.status = status  # type: ignore[assignment]
        if status in ("paused", "retired"):
            freed.append(
                sum(len(task.scheduled_slots) for route in goal.routes for task in route.tasks)
            )

    _store(tool_context).mutate(user_id, change)

    if freed and freed[0]:
        return f"{goal_id} is now {status}; {freed[0]} scheduled slot(s) are free to reallocate"
    return f"{goal_id} is now {status}"


ALL_GRAPH_TOOLS = (
    read_graph,
    write_graph,
    update_person_model,
    record_diagnosis,
    record_completion,
    set_goal_status,
)
