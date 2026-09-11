"""The Cascader: a fifteen-year ambition becomes something that occupies Tuesday.

"Build a billion-dollar company" is a real goal and it is not a task. Without
this node the Route Planner is handed an ambition and invents a plausible plan
for it, which is precisely the failure this product exists to avoid. So the
Cascader walks a long-horizon goal down one rung at a time -- life to decade to
three_year to year -- setting ``contributes_to`` on each, until something lands
at a horizon that can actually hold a calendar slot
(``SCHEDULABLE_HORIZONS`` in ``core/models.py``).

**One rung is not enough, and that is the mistake worth guarding against.** A
life goal decomposed to three_year is progress and it is not done: three years
still cannot hold a slot. PLATFORM has a test named
``test_one_rung_of_cascading_is_not_enough`` asserting exactly this.

This is the only node in the Intake chain other than the Scheduler that can
write, and the reason is a failure-direction argument rather than a convenience
one. Nothing downstream of here persists a goal until the Scheduler succeeds, so
without a write the ladder is lost whenever scheduling fails -- and a system that
loses the ambitions somebody just spoke aloud, because a later node fell over, is
not one they try twice. **Failure direction: a scheduling failure costs the
routes, not the ladder.**
"""

from __future__ import annotations

from strands import Agent

from second.agents._base import build_agent
from second.core.deps import AgentDeps
from second.core.models import CascadeResult

REQUIRED_TOOLS: tuple[str, ...] = ("read_graph", "write_graph")
OUTPUT_MODEL = CascadeResult

FORCED_OUTPUT_PROMPT = """Format the decomposition you worked out as a CascadeResult. Only
include goals you actually created, each with contributes_to pointing at the rung directly
above it, and keep walking down until at least one of them sits at year, quarter, month, week
or day -- stopping at decade or three_year leaves an ambition that still cannot hold a calendar
slot. A plausible-sounding ladder for somebody else's fifteen years is the most confident wrong
thing this product can produce, so where you genuinely do not know which way an ambition should
be cashed out, put the question in clarifying_questions and leave that branch uncascaded rather
than inventing it. The rationale must cite something you actually read in the person layer."""


def build(deps: AgentDeps) -> Agent:
    """Build the Cascader.

    Args:
        deps: What PLATFORM injected -- the model, ``read_graph`` and
            ``write_graph``, the hooks, the user id and the clock.

    Returns:
        The agent, ready for PLATFORM to wire in after the Extractor.
    """
    return build_agent(
        "cascader", deps, REQUIRED_TOOLS, OUTPUT_MODEL,
        structured_output_prompt=FORCED_OUTPUT_PROMPT,
    )
