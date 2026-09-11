"""The Feedback graph. What the user says back changes the plan.

    interpreter ──► graph_updater

Two nodes rather than one, and the split is the point: **the node that
interprets speech cannot write, and the node that writes cannot interpret.**

The Interpreter reads the graph and turns "too much", "that time doesn't work",
"I prefer reading" into typed ``FeedbackUpdate`` entries. It has no write tools,
so a misheard instruction cannot reach the calendar directly. The Graph Updater
receives those typed updates -- already validated, already constrained to the
three legal targets -- and applies them.

**Correction, 2026-09-11.** This docstring used to claim the Graph Updater "never
sees the raw sentence". It does: ``_build_node_input`` prepends
``"Original Task: ..."`` to every node (``graph.py:1226-1229``) and the utterance
is the task. AGENTS found it.

The isolation that actually holds is the useful one and it is unchanged -- no
write tool on the interpreting side, no read tool on the writing side, and only
typed ``FeedbackUpdate`` entries crossing between them. But the claim was
stronger than the wiring, and a security property that is asserted rather than
enforced is worse than none, because it stops being checked.

This is the same isolation principle as the Daily graph's Diagnostician, applied
to the one flow where the user's own words become mutations.
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
    model_for,
    build_node_agent,
    default_registry,
    resolve_clock,
    load_agent_spec,
)
from second.hooks.audit import AuditLogHook
from second.hooks.guard import RunawayGuard

NODES = ("interpreter", "graph_updater")


def build_feedback_graph(
    *,
    store: Any,
    user_id: str,
    clock: Clock | None = None,
    model: Any = None,
    registry: ToolRegistry | None = None,
    specs: dict[str, AgentSpec] | None = None,
    context: dict[str, dict[str, Any]] | None = None,
) -> ComposedGraph:
    """Assemble the Feedback graph.

    Args:
        store: The Living Graph store, injected into the run.
        user_id: Whose feedback this is.
        clock: What time it is for this user, in their own timezone. Resolved
            from their Google Calendar when not supplied -- nobody is asked. Pass
            ``Clock.fixed(...)`` to pin a scenario.
        model: Model provider. Pass a ``ScriptedModel`` to run offline.
        registry: Tool registry. Defaults to every tool that currently exists.
        specs: Agent specs by node id, for injecting stubs.
        context: Per-node sanitised context, keyed by node id.

    Returns:
        A :class:`ComposedGraph` ready to ``await .run(feedback_text)``.
    """
    clock = clock or resolve_clock()
    shared_model = model
    registry = registry or default_registry()
    specs = specs or {}
    context = context or {}
    audit = AuditLogHook(store=store, user_id=user_id)
    guard = RunawayGuard(max_model_calls=MAX_MODEL_CALLS_PER_NODE)

    builder = GraphBuilder()
    for node_id in NODES:
        builder.add_node(
            build_node_agent(
                specs.get(node_id) or load_agent_spec(node_id),
                model=shared_model or model_for(node_id),
                registry=registry,
                hooks=[audit, guard],
                user_id=user_id,
                clock=clock,
                context=context.get(node_id, {}),
            ),
            node_id,
        )

    builder.add_edge("interpreter", "graph_updater")
    builder.set_entry_point("interpreter")
    builder.set_hook_providers([audit])
    apply_guardrails(builder)

    return ComposedGraph(
        graph=builder.build(), audit=audit, store=store, user_id=user_id, clock=clock
    )
