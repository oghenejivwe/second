"""The Intake graph. Loose speech becomes a plan in someone's real calendar.

    extractor ──[clear]──► cascader ──► route_planner ──► scheduler ──► resource_finder

    extractor ──[unclear]──► (ends here)

**When the graph stops after the Extractor, that is the design.** If it is not
clear what someone wants, the honest move is to ask before building a plan on a
guess -- the same principle as the Daily graph's ``UNKNOWN``, one stage earlier.
The clarifying questions come back in ``ExtractionResult`` and the caller puts
them to the user. Nothing is scheduled on a misheard goal.

**The Cascader is what makes a fifteen-year ambition usable.** "A billion-dollar
company in fifteen years" is a real goal and it is not a task. It becomes a
three-year goal, which becomes this year's, which becomes something that occupies
Tuesday morning. Only the near rungs -- quarter, month, week, day -- can hold
routes and tasks, so everything longer is walked down first. Without this step
the Route Planner is handed an ambition and invents a plausible-sounding plan for
it, which is the failure mode this whole product exists to avoid.

The Resource Finder is optional because it is first on the project's cut list.
Dropping it costs the graph nothing structurally -- the Scheduler has already
placed the work by then.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from strands.multiagent.graph import GraphBuilder

from second.core.clock import Clock
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
from second.graphs.conditions import extraction_is_clear
from second.hooks.audit import AuditLogHook

CORE_NODES = ("extractor", "cascader", "route_planner", "scheduler")
OPTIONAL_NODES = ("resource_finder",)


def build_intake_graph(
    *,
    store: Any,
    user_id: str,
    clock: Clock | None = None,
    model: Any = None,
    registry: ToolRegistry | None = None,
    specs: dict[str, AgentSpec] | None = None,
    context: dict[str, dict[str, Any]] | None = None,
    include_resource_finder: bool = True,
) -> ComposedGraph:
    """Assemble the Intake graph.

    Args:
        store: The Living Graph store, injected into the run.
        user_id: Whose goals these are.
        clock: What time it is for this user, in their own timezone. Resolved
            from their Google Calendar when not supplied -- nobody is asked. Pass
            ``Clock.fixed(...)`` to pin a scenario.
        model: Model provider. Pass a ``ScriptedModel`` to run offline.
        registry: Tool registry. Defaults to every tool that currently exists.
        specs: Agent specs by node id, for injecting stubs.
        context: Per-node sanitised context, keyed by node id.
        include_resource_finder: Set false to run without it -- it is the first
            thing cut if the schedule tightens.

    Returns:
        A :class:`ComposedGraph` ready to ``await .run(transcript)``.
    """
    clock = clock or resolve_clock()
    model = model or build_model()
    registry = registry or default_registry()
    specs = specs or {}
    context = context or {}
    audit = AuditLogHook(store=store, user_id=user_id)

    node_ids = list(CORE_NODES) + (list(OPTIONAL_NODES) if include_resource_finder else [])

    builder = GraphBuilder()
    for node_id in node_ids:
        builder.add_node(
            build_node_agent(
                specs.get(node_id) or load_agent_spec(node_id),
                model=model,
                registry=registry,
                hooks=[audit],
                user_id=user_id,
                clock=clock,
                context=context.get(node_id, {}),
            ),
            node_id,
        )

    # The only conditional edge in this graph. There is no complementary edge:
    # when extraction is unclear the graph simply ends, and the caller asks.
    builder.add_edge("extractor", "cascader", condition=extraction_is_clear)
    builder.add_edge("cascader", "route_planner")
    builder.add_edge("route_planner", "scheduler")
    if include_resource_finder:
        builder.add_edge("scheduler", "resource_finder")

    builder.set_entry_point("extractor")
    builder.set_hook_providers([audit])
    apply_guardrails(builder)

    return ComposedGraph(graph=builder.build(), audit=audit, store=store, user_id=user_id)
