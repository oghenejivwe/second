"""The Route Planner: a goal becomes a cadence this particular person could keep.

A route is one concrete way of reaching a goal -- a rhythm and a set of tasks,
proposed by Second and approved by the user. It is not a restatement of the goal
and it is not a motivational plan.

It reads the ladder back out of the graph rather than out of its input. The
Cascader wrote it there, and the graph is the authority: ``_build_node_input``
(``multiagent/graph.py:1204-1245``) hands this node only its direct dependency,
so the Cascader's ``CascadeResult`` carries the *new* rungs and not the goals
that passed through untouched.

**It has no write tool, deliberately.** It proposes; the Scheduler persists what
it proposes alongside the slots it found, in one write. Two nodes writing the
same routes at two different times is how a route ends up in the graph with no
slot and no owner.

The judgement that is easy to get wrong is task size. A task that cannot be
started in one sitting is the thing that gets dragged across four days, and a
dragged task is later diagnosed as ``UNDEFINED_SCOPE`` -- which is the system
noticing, weeks late, a decision that was made here.
"""

from __future__ import annotations

from strands import Agent

from second.agents._base import build_agent
from second.core.deps import AgentDeps
from second.core.models import RoutePlan

REQUIRED_TOOLS: tuple[str, ...] = ("read_graph",)
OUTPUT_MODEL = RoutePlan

FORCED_OUTPUT_PROMPT = """Format your proposal as a RoutePlan. Every goal_id must be one you
actually read out of the graph and every route must belong to a goal at horizon year, quarter,
month, week or day -- nothing longer can hold a route. Each rationale has to name a specific
fact about this person from the person layer, because a rationale that would fit any user is
one you have not earned. Leave scheduled_slots, slip_count, slips and status off every task:
placing work in time is the next agent's job and two agents owning one field is how a plan
goes wrong. If you cannot tell how much time somebody has for something, ask in
clarifying_questions rather than inventing a cadence they will abandon in week two."""


def build(deps: AgentDeps) -> Agent:
    """Build the Route Planner.

    Args:
        deps: What PLATFORM injected -- the model, ``read_graph``, the hooks, the
            user id and the clock.

    Returns:
        The agent, ready for PLATFORM to wire in between the Cascader and the
        Scheduler.
    """
    return build_agent(
        "route_planner", deps, REQUIRED_TOOLS, OUTPUT_MODEL,
        structured_output_prompt=FORCED_OUTPUT_PROMPT,
    )
