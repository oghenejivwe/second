"""The last node of the Daily graph: what to remind, and whether to interrupt.

The Communicator answers the two questions in a daily brief that arithmetic
cannot answer. *What did the user commit to and forget?* and *is any of this
worth interrupting them for?* Everything else in the brief -- today's blocks,
the deadline risks, the check-in -- is computed from the Living Graph in Python
by :func:`second.graphs.brief.assemble`, because a model asked to list somebody's
day will eventually invent a meeting, and one imaginary block costs the user
their trust in the other five.

**It has no tools, and that is the design rather than an omission.**
``REQUIRED_TOOLS`` is empty, ``composition.py`` injects nothing, and
:func:`~second.core.deps.assert_privileges` fails graph construction if anything
is handed to it anyway. So the whole of this agent's world is its input: it
physically cannot look something up to pad a thin day with, and a reminder it
cannot trace to a line of that input is a reminder it cannot write.

**Its input arrives as stringified upstream results, and which ones arrive
depends on the path the run took.** ``Graph._build_node_input``
(``graph.py:1204-1245``) prefixes the original task, then appends one
``From <node_id>:`` block per direct dependency whose edge condition holds, and
``AgentResult.__str__`` (``agent_result.py:63-77``) returns
``structured_output.model_dump_json()`` and returns *before* the text loop -- so
each block is raw JSON of one model and any prose that node also wrote is gone.
The gated ``observer -> communicator`` edge means the ObservationReport is there
on both paths. The ``diagnostician -> communicator`` edge carries
``needs_user_decision``, so the Diagnosis is a block on the **ask** path only; on
the act path the Diagnostician has already been overtaken by the Adapter and the
Preparer, and what arrives instead is a PreparedAction. The prompt therefore
tells the model to read whichever blocks are present rather than to expect a
fixed shape, and ties "raise a decision" to the Diagnosis block existing at all.

**The one thing that is easy to get wrong here is ``notify``.** It looks like a
judgement call in both directions and it is not:
``assemble`` computes ``judgement.notify or bool(judgement.decisions) or
bool(prepared)`` (``brief.py:269``), so PLATFORM only ever overrides it
*upward*. A false the model gets wrong is corrected by the code below it; a true
it gets wrong reaches the user's phone and cannot be taken back. The prompt is
written asymmetrically for that reason, and ``silence_reason`` is required on
every quiet day so that staying silent is an auditable decision rather than
something indistinguishable from a failed run.
"""

from __future__ import annotations

from strands import Agent

from second.agents._base import build_agent
from second.core.deps import AgentDeps
from second.core.models import BriefJudgement

REQUIRED_TOOLS: tuple[str, ...] = ()
OUTPUT_MODEL = BriefJudgement

FORCED_OUTPUT_PROMPT = """Emit the BriefJudgement now, using only what was in the
blocks you were given. An empty reminders list, an empty decisions list, notify
false and a one-sentence silence_reason is a complete and correct answer -- do
not fill a field because it exists. Every reminder needs an evidence string you
can point to in the Observer's notes or in one of its observations; if you
cannot point at it, drop the reminder rather than write one. Include a decision
only if a Diagnosis block was present and it said requires_user_decision true,
or its blocker_type was UNKNOWN, or its confidence was below 0.7 -- otherwise
decisions is empty. Set notify true only when you raised a decision or a
PreparedAction block is waiting on something only the user can do; when it is
false, silence_reason must say in one flat sentence what was handled without
them."""


def build(deps: AgentDeps) -> Agent:
    """Construct the Communicator.

    Args:
        deps: The run's dependencies. ``deps.tools`` must be empty; the
            assertion inside :func:`~second.agents._base.build_agent` enforces it.

    Returns:
        The agent, ready for PLATFORM to wire in as the Daily graph's terminal node.
    """
    return build_agent(
        "communicator", deps, REQUIRED_TOOLS, OUTPUT_MODEL,
        structured_output_prompt=FORCED_OUTPUT_PROMPT,
    )
