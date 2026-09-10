"""One ordered log of everything the system did during a run.

**Register this on the graph AND on every node agent.** A ``Graph`` keeps its own
``HookRegistry`` (``multiagent/graph.py:553``) which only ever emits the
multi-agent events -- node start/stop and invocation start/stop. Tool events fire
on each *agent's* registry, from ``tools/executors/_executor.py``. So a provider
handed only to ``GraphBuilder.set_hook_providers`` produces an **empty tool
audit log, with no error and no warning**.

The answer is not two logs. It is one instance registered in both places;
``register_hooks`` is called once per registry and subscribes to whatever that
registry can actually deliver. ``scripts/phase0_proof.py`` claim 5 asserts this
boundary rather than assuming it.

The audit trail is the demo's evidence that Second did what it says. It is
deliberately not control flow: a failure to record must never fail a run.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from strands.hooks import (
    AfterMultiAgentInvocationEvent,
    AfterNodeCallEvent,
    AfterToolCallEvent,
    BeforeMultiAgentInvocationEvent,
    BeforeNodeCallEvent,
    HookProvider,
    HookRegistry,
)

from second.core.models import AuditEntry

logger = logging.getLogger(__name__)

WRITE_TOOLS = frozenset(
    {
        "create_event",
        "reschedule_event",
        "draft_email",
        "write_graph",
        "update_person_model",
        "record_diagnosis",
        "set_goal_status",
    }
)
"""Tools that change something -- on the calendar, in the inbox, or in the graph.

Kept as data rather than inferred from the name, because ``search_gmail`` and
``set_goal_status`` are not distinguishable by shape and a judge reading the log
should see exactly which rows were mutations."""

_MAX_PAYLOAD_CHARS = 300


def _summarise(value: Any) -> str:
    """Render a tool input for the log without dumping an email body into it."""
    text = str(value)
    return text if len(text) <= _MAX_PAYLOAD_CHARS else text[: _MAX_PAYLOAD_CHARS - 1] + "…"


@dataclass
class AuditLogHook(HookProvider):
    """Collects audit entries for one run.

    Args:
        run_id: Correlates every row from a single graph execution. Generated if
            not supplied.
        store: Optional ``LivingGraphStore``. When set, :meth:`flush` persists;
            when not, entries stay in memory, which is what tests want.
        user_id: Whose audit log these rows belong to.
    """

    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    store: Any = None
    user_id: str = "demo"
    entries: list[AuditEntry] = field(default_factory=list)

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        """Subscribe to whatever this particular registry can deliver.

        Called once for the graph's registry and once per node agent. Subscribing
        to all of them in one method is safe: a registry that never fires an
        event simply never calls back.
        """
        registry.add_callback(BeforeMultiAgentInvocationEvent, self._on_run_start)
        registry.add_callback(AfterMultiAgentInvocationEvent, self._on_run_end)
        registry.add_callback(BeforeNodeCallEvent, self._on_node_start)
        registry.add_callback(AfterNodeCallEvent, self._on_node_end)
        registry.add_callback(AfterToolCallEvent, self._on_tool_call)

    # -- run spans ------------------------------------------------------

    def _on_run_start(self, event: BeforeMultiAgentInvocationEvent) -> None:
        self._record(kind="node", actor="graph", action="run_start")

    def _on_run_end(self, event: AfterMultiAgentInvocationEvent) -> None:
        self._record(kind="node", actor="graph", action="run_end")

    # -- node spans -----------------------------------------------------

    def _on_node_start(self, event: BeforeNodeCallEvent) -> None:
        self._record(kind="node", actor=event.node_id, action="node_start")

    def _on_node_end(self, event: AfterNodeCallEvent) -> None:
        """Record a node's completion, and its typed result if it produced one.

        ``AfterNodeCallEvent`` carries no result, so read it off the graph state.

        Known hole, documented rather than worked around: this does **not** fire
        for an *interrupted* node (``graph.py:1149-1151`` guards the ``finally``
        on ``status != INTERRUPTED``), and such a node also has no entry in
        ``state.results`` because the interrupt path returns before that write.
        Second routes on conditional edges rather than Strands ``Interrupt``s, so
        its nodes complete normally and this hole stays closed -- but do not
        assume the mirror is total if tool-level interventions are adopted later.
        """
        outcome = ""
        try:
            node_result = event.source.state.results.get(event.node_id)
            structured = getattr(getattr(node_result, "result", None), "structured_output", None)
            if structured is not None:
                outcome = type(structured).__name__
        except Exception:  # noqa: BLE001 - the audit log never breaks a run
            logger.debug("could not read node result for %s", event.node_id, exc_info=True)

        self._record(
            kind="node",
            actor=event.node_id,
            action="node_end",
            payload={"produced": outcome} if outcome else {},
        )

    # -- tool calls -----------------------------------------------------

    def _on_tool_call(self, event: AfterToolCallEvent) -> None:
        """Record a completed tool call, whether it succeeded or raised.

        ``event.exception`` is populated only when the tool *raised*. A tool that
        hand-builds an error dict instead passes straight through the decorator
        and leaves this ``None`` -- which is why the standing rule is to raise.
        """
        name = event.tool_use.get("name", "?")
        self._record(
            kind="tool",
            actor=getattr(event.agent, "name", "?"),
            action=name,
            payload={"input": _summarise(event.tool_use.get("input"))},
            is_write=name in WRITE_TOOLS,
            failed=event.exception is not None,
        )

    # -- internals ------------------------------------------------------

    def _record(
        self,
        *,
        kind: str,
        actor: str,
        action: str,
        payload: dict[str, str] | None = None,
        is_write: bool = False,
        failed: bool = False,
    ) -> None:
        self.entries.append(
            AuditEntry(
                at=datetime.now(timezone.utc),
                run_id=self.run_id,
                kind=kind,  # type: ignore[arg-type]
                actor=actor,
                action=action,
                payload=payload or {},
                is_write=is_write,
                failed=failed,
            )
        )

    def writes(self) -> list[AuditEntry]:
        """Just the rows that changed something. What a reviewer actually wants."""
        return [entry for entry in self.entries if entry.is_write]

    def flush(self) -> None:
        """Persist and clear. Safe to call when no store is configured."""
        if self.store is None or not self.entries:
            return
        self.store.append_audit(self.user_id, self.entries)
        self.entries = []
