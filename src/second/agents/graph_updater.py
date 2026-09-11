"""The Graph Updater: typed changes become writes, and nothing else becomes anything.

The Feedback graph's terminal node. It receives the Interpreter's already
validated ``FeedbackResult`` and applies it. **It never sees the raw sentence**,
which is the whole point of splitting the two: the node that interprets speech
cannot write, and the node that writes cannot interpret. Whatever reaches here
has already survived being turned into one of three legal targets.

So its job is narrow on purpose -- apply exactly what is typed in front of it and
report what it did not apply. An ambiguity resolved here is a guess written into
somebody's calendar, which is the one place a guess must never reach.

``record_completion`` is the important tool. It is the only route by which the
user's own account of what happened enters the system, and it does things a
plain write cannot: marks the task done, **reverses an inferred slip the user
contradicted**, learns the slot as honoured or abandoned, and -- on a task they
say they did *not* do -- writes their stated reason to ``task.known_blocker`` so
Second never asks about that task again.

Note that the reason is kept only on the negative branch
(``tools/graph_tools.py``: the ``did_it`` path returns before reaching it). "I
did do it, I just never opened the calendar" is the explanation for a task that
looks missed while being done, and it is currently taken in and discarded. That
is PLATFORM's to change; this agent passes the note through either way so it is
there the day the tool keeps it.

**The trap in this module is ``write_graph`` and it is worth naming.** The tool
upserts by id and a partial goal replaces the whole entry -- and this agent has
no ``read_graph``, so it cannot re-read a goal in order to send it back whole.
That is a deliberate privilege boundary rather than an oversight: a node that can
write but not read should only write what it was handed. The prompt therefore
says to use ``write_graph`` only when the ``FeedbackResult`` carries enough to
reconstruct a complete goal, and otherwise to report rather than write. **Failure
direction: an unapplied preference is recoverable next run; a goal that lost its
routes to a partial write is not.**
"""

from __future__ import annotations

from strands import Agent

from second.agents._base import build_agent
from second.core.deps import AgentDeps

REQUIRED_TOOLS: tuple[str, ...] = (
    "write_graph",
    "update_person_model",
    "set_goal_status",
    "record_completion",
)
OUTPUT_MODEL = None


def build(deps: AgentDeps) -> Agent:
    """Build the Graph Updater.

    Args:
        deps: What PLATFORM injected -- the model, the four write tools declared
            in :data:`REQUIRED_TOOLS`, the hooks, the user id and the clock.

    Returns:
        The agent, ready for PLATFORM to wire in after the Interpreter.
    """
    return build_agent("graph_updater", deps, REQUIRED_TOOLS, OUTPUT_MODEL)
