"""The Feedback graph. What the user says back changes the plan.

    interpreter ──► graph_updater

Two nodes rather than one, and the split is the point: **the node that
interprets speech cannot write, and the node that writes cannot interpret.**

The Interpreter reads the graph and turns "too much", "that time doesn't work",
"I prefer reading" into typed ``FeedbackUpdate`` entries. It has no write tools,
so a misheard instruction cannot reach the calendar directly. The Graph Updater
receives those typed updates -- already validated, already constrained to the
three legal targets -- and applies them. It never sees the raw sentence.

This is the same isolation principle as the Daily graph's Diagnostician, applied
to the one flow where the user's own words become mutations.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from strands.multiagent.graph import GraphBuilder

from second.graphs.composition import (
    AgentSpec,
    ComposedGraph,
    ToolRegistry,
    apply_guardrails,
    build_model,
    build_node_agent,
    default_registry,
    load_agent_spec,
)
from second.hooks.audit import AuditLogHook

NODES = ("interpreter", "graph_updater")


def build_feedback_graph(
    *,
    store: Any,
    user_id: str,
    today: date | None = None,
    model: Any = None,
    registry: ToolRegistry | None = None,
    specs: dict[str, AgentSpec] | None = None,
    context: dict[str, dict[str, Any]] | None = None,
) -> ComposedGraph:
    """Assemble the Feedback graph.

    Args:
        store: The Living Graph store, injected into the run.
        user_id: Whose feedback this is.
        today: Injected rather than read from the clock.
        model: Model provider. Pass a ``ScriptedModel`` to run offline.
        registry: Tool registry. Defaults to every tool that currently exists.
        specs: Agent specs by node id, for injecting stubs.
        context: Per-node sanitised context, keyed by node id.

    Returns:
        A :class:`ComposedGraph` ready to ``await .run(feedback_text)``.
    """
    model = model or build_model()
    registry = registry or default_registry()
    specs = specs or {}
    context = context or {}
    audit = AuditLogHook(store=store, user_id=user_id)

    builder = GraphBuilder()
    for node_id in NODES:
        builder.add_node(
            build_node_agent(
                specs.get(node_id) or load_agent_spec(node_id),
                model=model,
                registry=registry,
                hooks=[audit],
                user_id=user_id,
                today=today,
                context=context.get(node_id, {}),
            ),
            node_id,
        )

    builder.add_edge("interpreter", "graph_updater")
    builder.set_entry_point("interpreter")
    builder.set_hook_providers([audit])
    apply_guardrails(builder)

    return ComposedGraph(graph=builder.build(), audit=audit, store=store, user_id=user_id)
