"""Phase 0 exit criterion: prove the Strands primitives Second is built on.

Run:  .venv/Scripts/python.exe scripts/phase0_proof.py

No AWS credentials required. Every node runs against ``ScriptedModel``, which
speaks Bedrock's stream event shapes, so this exercises the real ``Graph``, the
real event loop, real ``@tool`` dispatch and real conditional edges.

Five claims are proved, each of which the build depends on:

  1. A node given ``structured_output_model`` can call its own tools AND return a
     typed Pydantic model in a single invocation. (Second's Diagnostician must
     read the graph and the inbox, then emit a typed Diagnosis.)
  2. That typed result reaches a dependent node as JSON in its prompt -- so
     sdk-python issue #1118 does not apply to 1.55.1, and the spec's
     "write to shared state, read it back explicitly" workaround is not forced.
  3. A conditional edge can route on a typed field. ``requires_user_decision``
     decides whether the Adapter acts or the Communicator asks. This is the
     architectural centrepiece: the decision to interrupt the user is a typed
     field, not a prompt hoping for the best.
  4. ``invocation_state`` is one dict shared by every node and every tool for the
     whole graph run, mutable from inside a tool. That is where the Living Graph
     lives during a run.
  5. One hook provider instance, registered on the graph AND on each node agent,
     covers every write the system makes. Graph-level registration alone is not
     enough -- a graph's registry only fires multi-agent events, never tool
     events. That boundary is why claim 5 is asserted rather than assumed.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pydantic import BaseModel, Field
from strands import Agent, ToolContext, tool
from strands.hooks import AfterToolCallEvent, BeforeNodeCallEvent, HookProvider, HookRegistry
from strands.multiagent.graph import GraphBuilder, GraphState

from second.testing.scripted_model import ScriptedModel, Structured, Text, ToolUse

USER_ID = "demo"


# --------------------------------------------------------------------------
# The typed field that routes the graph.
# --------------------------------------------------------------------------


class Diagnosis(BaseModel):
    """Why a task slipped, and whether Second can act on it alone."""

    task_id: str
    blocker_type: Literal[
        "MISSING_INFORMATION",
        "UNDEFINED_SCOPE",
        "UNMET_DEPENDENCY",
        "CALENDAR_CONFLICT",
        "UNKNOWN",
    ]
    evidence: str = Field(description="The calendar entry or email this conclusion rests on.")
    confidence: float
    proposed_action: str
    requires_user_decision: bool


def route_to_user(state: GraphState) -> bool:
    """True when Second must ask rather than act.

    Second interrupts the user only when the diagnosis says so, when it is not
    confident, or when it honestly cannot tell. Anything else it handles alone.
    """
    diagnosis = _diagnosis_from(state)
    if diagnosis is None:
        return True
    return (
        diagnosis.requires_user_decision
        or diagnosis.confidence < 0.7
        or diagnosis.blocker_type == "UNKNOWN"
    )


def route_to_adapter(state: GraphState) -> bool:
    """True when Second can change the plan without asking."""
    return not route_to_user(state)


def _diagnosis_from(state: GraphState) -> Diagnosis | None:
    node_result = state.results.get("diagnostician")
    if node_result is None:
        return None
    result = getattr(node_result, "result", None)
    structured = getattr(result, "structured_output", None)
    return structured if isinstance(structured, Diagnosis) else None


# --------------------------------------------------------------------------
# A tool that reads and writes the run-wide shared state.
# --------------------------------------------------------------------------


@tool(context=True)
def record_evidence(kind: str, detail: str, tool_context: ToolContext) -> str:
    """Attach a piece of observed evidence to the current run.

    Args:
        kind: What sort of evidence this is, e.g. "calendar" or "email".
        detail: The observation itself, quoted from the source.

    Returns:
        A confirmation naming how many pieces of evidence the run now holds.
    """
    ledger = tool_context.invocation_state.setdefault("evidence", [])
    ledger.append({"kind": kind, "detail": detail})
    return f"recorded {kind} evidence ({len(ledger)} total this run)"


@tool(context=True)
def read_evidence(tool_context: ToolContext) -> list[dict[str, str]]:
    """Read every piece of evidence recorded so far in this run.

    Returns:
        The evidence ledger, oldest first.
    """
    return list(tool_context.invocation_state.get("evidence", []))


# --------------------------------------------------------------------------
# One audit log for every write the system performs.
# --------------------------------------------------------------------------


@dataclass
class AuditLog(HookProvider):
    """One log of everything the system did during a run.

    A graph keeps its own ``HookRegistry`` (``Graph.hooks``, graph.py:553) and
    fires only the multi-agent events on it -- node start/stop and invocation
    start/stop. Tool events fire on the *agent's* registry. So a provider handed
    to ``set_hook_providers`` never sees a tool call.

    The fix is not two logs. It is one instance registered in both places: the
    graph, for node spans, and every node agent, for the writes inside them.
    ``register_hooks`` is called once per registry and subscribes to whatever
    that registry can actually deliver.
    """

    entries: list[dict[str, Any]] = field(default_factory=list)

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        """Subscribe to node spans and to tool completions."""
        registry.add_callback(BeforeNodeCallEvent, self._on_node_start)
        registry.add_callback(AfterToolCallEvent, self._on_tool_call)

    def _on_node_start(self, event: BeforeNodeCallEvent) -> None:
        self.entries.append({"kind": "node", "node": event.node_id, "tool": None})

    def _on_tool_call(self, event: AfterToolCallEvent) -> None:
        self.entries.append(
            {
                "kind": "tool",
                "agent": getattr(event.agent, "name", "?"),
                "tool": event.tool_use.get("name"),
                "input": event.tool_use.get("input"),
                "failed": event.exception is not None,
            }
        )


# --------------------------------------------------------------------------
# The graph. This is the shape of Second's Daily flow.
# --------------------------------------------------------------------------


def build_daily_graph(diagnosis_payload: dict[str, Any], audit: AuditLog):
    """Assemble observer -> diagnostician -> (adapter | communicator)."""
    observer = Agent(
        name="observer",
        model=ScriptedModel(
            [
                ToolUse("record_evidence", {"kind": "calendar", "detail": "6pm gym declined 4 of 5 weekdays"}),
                Text("Gym slot is losing to meetings. Recorded one piece of evidence."),
            ],
            agent_tool_names=["record_evidence", "read_evidence"],
        ),
        tools=[record_evidence, read_evidence],
        system_prompt="Compare the plan against what actually happened. Record what you observe.",
        hooks=[audit],
    )

    diagnostician = Agent(
        name="diagnostician",
        model=ScriptedModel(
            [
                ToolUse("read_evidence", {}),
                Structured(diagnosis_payload),
            ],
            agent_tool_names=["record_evidence", "read_evidence"],
        ),
        tools=[record_evidence, read_evidence],
        system_prompt="Classify the structural cause. Cite evidence. Never speculate about motivation.",
        structured_output_model=Diagnosis,
        hooks=[audit],
    )

    adapter = Agent(
        name="adapter",
        model=ScriptedModel([Text("Moved the gym block to 07:00. The 6pm slot is gone, not postponed.")]),
        system_prompt="Change the plan. Do not push the task to tomorrow.",
        hooks=[audit],
    )

    communicator = Agent(
        name="communicator",
        model=ScriptedModel([Text("I can't tell why this keeps slipping. What's blocking it?")]),
        system_prompt="Surface at most one thing, and only when a decision is genuinely needed.",
        hooks=[audit],
    )

    builder = GraphBuilder()
    builder.add_node(observer, "observer")
    builder.add_node(diagnostician, "diagnostician")
    builder.add_node(adapter, "adapter")
    builder.add_node(communicator, "communicator")

    builder.add_edge("observer", "diagnostician")
    builder.add_edge("diagnostician", "adapter", condition=route_to_adapter)
    builder.add_edge("diagnostician", "communicator", condition=route_to_user)

    builder.set_entry_point("observer")
    builder.set_max_node_executions(12)
    builder.set_hook_providers([audit])
    return builder.build()


# --------------------------------------------------------------------------


AUTONOMOUS = {
    "task_id": "gym-block",
    "blocker_type": "CALENDAR_CONFLICT",
    "evidence": "6pm gym declined 4 of 5 weekdays; each collided with 'Eng sync'.",
    "confidence": 0.91,
    "proposed_action": "Move the block to 07:00, where nothing competes.",
    "requires_user_decision": False,
}

HONEST_UNKNOWN = {
    "task_id": "gym-block",
    "blocker_type": "UNKNOWN",
    "evidence": "Slot was free and uncontested on 3 of 4 slips. No conflicting event found.",
    "confidence": 0.35,
    "proposed_action": "Ask what is actually blocking this.",
    "requires_user_decision": True,
}


def run_scenario(label: str, payload: dict[str, Any], expected_node: str, forbidden_node: str) -> list[str]:
    """Run one scenario and return the list of failed assertion messages."""
    audit = AuditLog()
    graph = build_daily_graph(payload, audit)
    shared: dict[str, Any] = {"user_id": USER_ID}

    result = graph(
        "Yesterday's plan versus what actually happened.",
        invocation_state=shared,
    )

    visited = [node.node_id for node in result.execution_order]
    diagnosis = _diagnosis_from(graph.state)
    failures: list[str] = []

    def check(ok: bool, claim: str, detail: str = "") -> None:
        status = "PASS" if ok else "FAIL"
        print(f"    [{status}] {claim}")
        if detail:
            print(f"           {detail}")
        if not ok:
            failures.append(f"{label}: {claim}")

    print(f"\n  {label}")
    print(f"    path: {' -> '.join(visited)}")

    check(
        isinstance(diagnosis, Diagnosis),
        "1. node returned a typed Diagnosis after calling its own tool",
        f"blocker_type={getattr(diagnosis, 'blocker_type', None)!r} "
        f"confidence={getattr(diagnosis, 'confidence', None)}",
    )

    downstream = next(
        (call for call in graph.nodes[expected_node].executor.model.calls),  # type: ignore[union-attr]
        None,
    )
    propagated = bool(downstream) and payload["blocker_type"] in downstream["prompt_text"]
    check(
        propagated,
        f"2. the typed result reached '{expected_node}' as JSON in its prompt",
        "issue #1118 does not apply to 1.55.1",
    )

    check(
        expected_node in visited and forbidden_node not in visited,
        f"3. conditional edge routed to '{expected_node}', not '{forbidden_node}'",
        "requires_user_decision / confidence / UNKNOWN decided the path",
    )

    check(
        len(shared.get("evidence", [])) == 1,
        "4. invocation_state was shared and mutated across nodes",
        f"evidence ledger written by observer, read by diagnostician: {shared.get('evidence')}",
    )

    tools_seen = [e["tool"] for e in audit.entries if e["kind"] == "tool"]
    nodes_seen = [e["node"] for e in audit.entries if e["kind"] == "node"]
    check(
        "record_evidence" in tools_seen
        and "read_evidence" in tools_seen
        and set(nodes_seen) == set(visited),
        "5. one audit instance captured node spans AND tool writes",
        f"nodes={nodes_seen} tools={tools_seen}",
    )

    return failures


def main() -> int:
    """Run both scenarios and report."""
    print("=" * 74)
    print("Phase 0 proof -- Strands 1.55.1 primitives, offline")
    print("=" * 74)

    failures = run_scenario(
        "Scenario A: confident structural cause -> Second acts alone",
        AUTONOMOUS,
        expected_node="adapter",
        forbidden_node="communicator",
    )
    failures += run_scenario(
        "Scenario B: honest UNKNOWN -> Second asks",
        HONEST_UNKNOWN,
        expected_node="communicator",
        forbidden_node="adapter",
    )

    print("\n" + "=" * 74)
    if failures:
        print(f"FAILED ({len(failures)}):")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("All claims proved. Phase 0 foundations are sound.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
