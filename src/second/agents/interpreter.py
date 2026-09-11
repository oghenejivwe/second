"""The Interpreter: what the user said back, turned into typed changes.

The entry node of the Feedback graph, and the only node that ever sees the raw
sentence. It reads the graph, resolves what was said to real ids, and emits
typed entries. That is all it does.

**It has no write tools, and the absence is the design.** The node that
interprets speech cannot write, and the node that writes -- the Graph Updater --
never sees the sentence. So a misheard instruction cannot reach a calendar
directly: it has to survive being turned into a validated ``FeedbackResult``
first, constrained to three legal targets. This is the same isolation principle
as the Daily graph's Diagnostician, applied to the one flow where somebody's own
words become mutations.

``FeedbackResult`` covers both directions of the daily loop in one pass:
``completions`` is the user reporting backwards on what actually happened, and
that is **ground truth that beats every inference the system made** -- the person
was there and the system was not. ``updates`` and ``intentions`` are everything
else.

The failure that matters here is inventing a ``task_id`` to make a sentence fit
the schema. A write addressed to an id that does not exist is a write that
silently does nothing, and the user is told their correction was applied.
"""

from __future__ import annotations

from strands import Agent

from second.agents._base import build_agent
from second.core.deps import AgentDeps
from second.core.models import FeedbackResult

REQUIRED_TOOLS: tuple[str, ...] = ("read_graph",)
OUTPUT_MODEL = FeedbackResult

FORCED_OUTPUT_PROMPT = """Format what the person said as a FeedbackResult. Every task_id in
completions must be one you actually matched against a task you read in the graph -- if you
could not match what they said to a real id, leave it out rather than inventing one, because a
write addressed to an id that does not exist silently does nothing while the user is told their
correction landed. Put their own words in note verbatim; that reason becomes the thing that
stops Second asking about the same task again. Every list here is allowed to be empty, and
acknowledgement is usually empty -- returning nothing but an empty result is a complete answer
when somebody said something that changes nothing."""


def build(deps: AgentDeps) -> Agent:
    """Build the Interpreter.

    Args:
        deps: What PLATFORM injected -- the model, ``read_graph``, the hooks, the
            user id and the clock.

    Returns:
        The agent, ready for PLATFORM to wire in as the Feedback graph's entry
        node.
    """
    return build_agent(
        "interpreter", deps, REQUIRED_TOOLS, OUTPUT_MODEL,
        structured_output_prompt=FORCED_OUTPUT_PROMPT,
    )
