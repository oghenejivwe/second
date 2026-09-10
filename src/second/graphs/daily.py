"""The Daily graph. This is the product.

    observer ──► diagnostician ──┬──[can act alone]──► adapter ──► preparer ──┐
        │                        │                                            ▼
        │                        └──[needs the user]───────────────────► communicator
        └──────────[once diagnosed]──────────────────────────────────────────▲

Second compares the plan against what actually happened, works out *structurally*
why something slipped, and then either changes the plan itself or asks one
honest question. It never does both, and most days it does neither out loud.

**The branch is the whole architecture.** ``requires_user_decision`` is a typed
field on a Pydantic model, read by a conditional edge. Nothing parses natural
language to decide whether to interrupt someone.

**The Communicator has two incoming edges and that is deliberate.** A Strands node
becomes ready when *any* incoming edge condition is satisfied
(``graph.py:966-982``), not when all of them are. So on the ask path it runs
straight after the Diagnostician, and on the act-alone path it runs after the
Preparer -- one node, two routes in, exactly one taken.

**Context isolation across this graph**, enforced in ``composition.py``:

===============  ==========================================================
observer         raw calendar, raw email -- the only node that sees them
diagnostician    a sanitised evidence bundle; cannot reach Gmail or Calendar
adapter          the verdict, plus the ability to move an event
preparer         can draft an email; nothing in this system can send one
communicator     no tools at all, so it cannot look anything up to pad with
===============  ==========================================================
"""

from __future__ import annotations

from datetime import date
from typing import Any

from strands.multiagent.graph import GraphBuilder

from second.core.clock import Clock
from second.settings import MAX_MODEL_CALLS_PER_NODE
from second.graphs.composition import (
    AgentSpec,
    ComposedGraph,
    ToolRegistry,
    apply_guardrails,
    build_model,
    build_node_agent,
    default_registry,
    resolve_clock,
    load_agent_spec,
)
from second.graphs.conditions import can_act_alone, diagnosis_has_run, needs_user_decision
from second.hooks.audit import AuditLogHook
from second.hooks.guard import RunawayGuard

NODES = ("observer", "diagnostician", "adapter", "preparer", "communicator")


def build_daily_graph(
    *,
    store: Any,
    user_id: str,
    clock: Clock | None = None,
    model: Any = None,
    registry: ToolRegistry | None = None,
    specs: dict[str, AgentSpec] | None = None,
    context: dict[str, dict[str, Any]] | None = None,
) -> ComposedGraph:
    """Assemble the Daily graph.

    Args:
        store: The Living Graph store, injected into the run.
        user_id: Whose day this is.
        clock: What time it is for this user, in their own timezone. Resolved
            from their Google Calendar when not supplied -- nobody is asked. Pass
            ``Clock.fixed(...)`` to pin a scenario.
        model: Model provider. Defaults to Bedrock; pass a ``ScriptedModel`` to
            run the whole graph offline.
        registry: Tool registry. Defaults to every tool that currently exists.
        specs: Agent specs by node id, for injecting stubs before AGENTS lands.
            Any node not supplied is loaded from ``second.agents.<node>``.
        context: Per-node sanitised context, keyed by node id. This is how the
            Diagnostician receives evidence without being handed the inbox.

    Returns:
        A :class:`ComposedGraph` ready to ``await .run(...)``.
    """
    clock = clock or resolve_clock()
    model = model or build_model()
    registry = registry or default_registry()
    specs = specs or {}
    context = context or {}
    audit = AuditLogHook(store=store, user_id=user_id)
    guard = RunawayGuard(max_model_calls=MAX_MODEL_CALLS_PER_NODE)

    agents = {
        node_id: build_node_agent(
            specs.get(node_id) or load_agent_spec(node_id),
            model=model,
            registry=registry,
            hooks=[audit, guard],
            user_id=user_id,
            clock=clock,
            context=context.get(node_id, {}),
        )
        for node_id in NODES
    }

    builder = GraphBuilder()
    for node_id, agent in agents.items():
        builder.add_node(agent, node_id)

    builder.add_edge("observer", "diagnostician")

    # The branch. Strict complements of one predicate, because sibling edges are
    # independent OR-gates -- if both were true, both nodes would run.
    builder.add_edge("diagnostician", "adapter", condition=can_act_alone)
    builder.add_edge("diagnostician", "communicator", condition=needs_user_decision)

    builder.add_edge("adapter", "preparer")
    builder.add_edge("preparer", "communicator")

    # The Communicator has to cite the email a forgotten commitment came from,
    # and it has no tools. This carries the Observer's sanitised report to it on
    # both paths. Gated rather than bare -- see diagnosis_has_run.
    builder.add_edge("observer", "communicator", condition=diagnosis_has_run)

    builder.set_entry_point("observer")
    builder.set_hook_providers([audit])
    apply_guardrails(builder)

    return ComposedGraph(
        graph=builder.build(), audit=audit, store=store, user_id=user_id, clock=clock
    )
