"""The Resource Finder: the thing they need is already there at 07:00.

The governing principle applied to preparation rather than to action. Not a
search to run and not a reminder to go and find something -- the actual material,
attached to the slot, before the slot arrives.

It carries ``write_graph`` because ``Task.resource_url`` exists and nothing else
in the system can ever set it: the field, and ``ScheduledBlock.resource_url``
that renders it, would otherwise be decorative. ``update_person_model`` maintains
``PersonModel.resources_served``, which is how the same link never arrives twice
-- being handed the same thing twice is how a system tells somebody it was not
paying attention.

It emits no structured output. Nothing is downstream of it; it is the Intake
graph's terminal node and PLATFORM can build the graph without it
(``intake.py``: ``OPTIONAL_NODES``), because it is first on the project's cut
list. Dropping it costs the graph nothing structurally -- the Scheduler has
already placed the work by then.
"""

from __future__ import annotations

from strands import Agent

from second.agents._base import build_agent
from second.core.deps import AgentDeps

REQUIRED_TOOLS: tuple[str, ...] = (
    "read_graph",
    "web_search",
    "update_person_model",
    "write_graph",
)
OUTPUT_MODEL = None


def build(deps: AgentDeps) -> Agent:
    """Build the Resource Finder.

    Args:
        deps: What PLATFORM injected -- the model, the four tools declared in
            :data:`REQUIRED_TOOLS`, the hooks, the user id and the clock.

    Returns:
        The agent, ready for PLATFORM to wire in as the Intake graph's optional
        last node.
    """
    return build_agent("resource_finder", deps, REQUIRED_TOOLS, OUTPUT_MODEL)
