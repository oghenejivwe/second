"""The Extractor: loose speech becomes a shortlist of goals, or a question.

This is the entry node of the Intake graph and the only one that ever sees the
raw transcript. What it emits decides whether anything else runs at all:
``extraction_is_clear`` (``graphs/conditions.py``) stops the graph here when any
goal scores below the confidence floor or any clarifying question was asked, so
**nothing reaches a real calendar on a misheard goal**. That makes
``extraction_confidence`` a routing field rather than a decoration, and the
prompt says so at length.

The goals it emits are deliberately shallow -- ``Goal.routes`` stays empty and
the Route Planner fills it in three nodes later. Deep nesting costs tokens and
accuracy on a structured-output call, and one model never has to produce the
whole tree at once.

**The distinction that is easy to get wrong is horizon versus deadline.** They
are different things: the horizon is the rung on the ladder, the deadline is a
date. "A billion-dollar company in fifteen years" is a ``life`` goal carrying a
deadline fifteen years out, and shrinking it to ``year`` to make it schedulable
produces a plan nobody believes. Only ``year`` and nearer can hold calendar work;
everything longer is the Cascader's problem, and handing it a real ambition
intact is the whole point of this node.
"""

from __future__ import annotations

from strands import Agent

from second.agents._base import build_agent
from second.core.deps import AgentDeps
from second.core.models import ExtractionResult

REQUIRED_TOOLS: tuple[str, ...] = ("read_graph",)
OUTPUT_MODEL = ExtractionResult

FORCED_OUTPUT_PROMPT = """Format what you heard as an ExtractionResult. Use only what the
person actually said: one goal per distinct thing they want, titles in their own words, and no
goal assembled out of two half-sentences. Set extraction_confidence to how sure you are that
each goal is real and distinct as stated -- a score below 0.7 stops the whole intake before
anything is scheduled, which is the correct outcome for a goal you are guessing at, so score
honestly rather than confidently. If something was genuinely unclear, put a question in
clarifying_questions instead of inventing the goal it would have produced. Leave every routes
list empty; routes are planned later by a different agent."""


def build(deps: AgentDeps) -> Agent:
    """Build the Extractor.

    Args:
        deps: What PLATFORM injected -- the model, ``read_graph``, the hooks, the
            user id and the clock.

    Returns:
        The agent, ready for PLATFORM to wire in as the Intake graph's entry node.
    """
    return build_agent(
        "extractor", deps, REQUIRED_TOOLS, OUTPUT_MODEL,
        structured_output_prompt=FORCED_OUTPUT_PROMPT,
    )
