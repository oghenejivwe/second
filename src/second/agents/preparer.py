"""Carries the work up to the last click, and stops there.

The Preparer is Second's governing principle made executable. Every other node in
the Daily graph decides something; this one does the work that decision implies,
up to but never including the step only the user can take. Not "write your leave
email" but a leave email drafted, addressed, dated and sitting in their drafts.
Not "book flights" but options priced beside each other. What reaches the user is
a decision, not a chore.

It runs on the act-alone path only (``daily.py:121``), after the Adapter has
already changed the plan, and the Adapter is its single direct dependency. The
Adapter has no structured output, so what arrives is the Adapter's final message
text and nothing else: ``Graph._build_node_input`` (``graph.py:1204-1245``)
appends one stringified block per DIRECT dependency, and ``AgentResult.__str__``
(``agent_result.py:63-77``) returns ``structured_output.model_dump_json()`` for a
typed node and only falls through to the text loop for an untyped one. The
``Diagnosis`` is two hops upstream and never reaches here at all. So the task id
and the blocker are recoverable only insofar as the Adapter restated them in
prose, which is why the prompt tells the model to mine that block for them and to
fall back to the graph when it is silent.

The decision that is easy to get wrong is *what* to prepare. The Adapter's own
work is usually already complete -- a block moved from 18:00 to 07:00 leaves the
user nothing to do, and an email announcing that move is invented work. The
useful prepared action is almost always for a *different* task: the nearest
deadline that is blocked on something outside the calendar. In the seeded world
the Adapter moves the gym and the Preparer drafts the leave request, and those
being two unrelated tasks is deliberate rather than a seam.

``draft_email`` is the only write this agent has, and there is no send tool
anywhere in this system. The practical consequence for this agent is narrower
than the rule that produces it: the body has to be finished, because nobody fills
in a blank before it goes. ``search_gmail`` with ``in:sent`` is how it
establishes a negative, and that a thing was never sent is frequently the whole
finding -- it is the finding demo beat 3 turns on.

Emits :class:`~second.core.models.PreparedAction`, which PLATFORM lifts straight
into ``DailyBrief.prepared`` (``service.py:217``) and which on its own is enough
to set ``notify`` (``brief.py:251,269``). One prepared action per run: a brief
carrying three of them is a to-do list, which is the thing this product exists
not to be.
"""

from __future__ import annotations

from strands import Agent

from second.agents._base import build_agent
from second.core.deps import AgentDeps
from second.core.models import PreparedAction

REQUIRED_TOOLS: tuple[str, ...] = ("read_graph", "search_gmail", "draft_email", "web_search")
OUTPUT_MODEL = PreparedAction

FORCED_OUTPUT_PROMPT = """Format what you have already done as a PreparedAction, reporting
only what actually happened. Your tools are gone on this pass, so nothing further can be
prepared here: external_ref must be null unless a tool you already called returned an id, and
where one did, copy that id exactly rather than reconstructing a plausible-looking one. Put
the real artefact in detail -- the draft body exactly as you passed it to draft_email, the
options exactly as you compared them, the value exactly as you read it -- and never describe a
draft as having been sent. If you prepared nothing, say that plainly in summary, leave detail
empty and external_ref null, and make awaiting the single thing the user still has to do."""


def build(deps: AgentDeps) -> Agent:
    """Construct the Preparer.

    Args:
        deps: What PLATFORM injected -- the model, the four declared tools, the
            audit hooks, the user id and the clock.

    Returns:
        The agent, ready for PLATFORM to wire into the Daily graph's fourth node.
    """
    return build_agent(
        "preparer", deps, REQUIRED_TOOLS, OUTPUT_MODEL,
        structured_output_prompt=FORCED_OUTPUT_PROMPT,
    )
