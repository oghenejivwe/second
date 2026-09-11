"""The Observer: yesterday's plan against what the calendar and the inbox actually show.

This is the entry node of the Daily graph and the only node in the whole system
that ever sees a raw calendar entry or a raw email. Everything after it works
from what it hands back: the Diagnostician has neither Calendar nor Gmail in its
toolbox, and the Communicator has no tools at all. The report is therefore not a
summary of the run so far, it is the run's entire evidence base, and anything the
Observer leaves out is unrecoverable downstream. That is the reason this agent
reads three weeks of calendar rather than seven days -- a task recreated on four
consecutive days is only a drag if you can see the three cancellations it left
behind, and a 18:00 slot that always loses is only a pattern at four instances.

It emits an :class:`~second.core.models.ObservationReport`: one
:class:`~second.core.models.Observation` per task that had a slot worth checking,
plus a ``notes`` field carrying two things -- structural context that belongs to
no single task, and the commitments the user made in mail and has not acted on.
The second is load-bearing in a way that is easy to miss. The Communicator builds
every ``Reminder`` with a cited source and has no way to look anything up, so a
commitment the Observer does not write into ``notes`` is a reminder the user can
never receive.

**The decision that is easy to get wrong is ``outcome``.** Two of its three values
are comfortable and one is not. A calendar can prove an invite was declined and a
mailbox can prove a message was never sent, but nothing in either records whether
somebody actually spent five minutes recording their voice. An Observer that
rounds that silence up to "missed" -- or down to "honoured" -- manufactures the
evidence the Diagnostician then reasons from, and the whole chain is built on a
guess that reads as a fact. ``unknown`` with ``source: "none"`` and an evidence
line that plainly says there was nothing is the correct, and harder, answer. The
prompt spends most of its length on this.

Three pieces of SDK behaviour shape the module. As the entry node the Observer
has no satisfied dependencies, so ``Graph._build_node_input``
(``multiagent/graph.py:1204-1245``) hands it the bare task string with no
"Inputs from previous nodes" block at all -- there is nothing to parse out of the
input and the prompt does not pretend otherwise. Downstream,
``AgentResult.__str__`` (``agent/agent_result.py:62-77``) returns
``structured_output.model_dump_json()`` and returns *before* the text loop, so any
prose this node also produces is silently dropped: the report is the only thing
that travels, which is why every finding has to land in a field. And Strands
produces that report by registering the schema as a tool; if the model ends a
turn without calling it, the loop re-asks once with ``forced_mode`` on, and at
``event_loop/event_loop.py:573-577`` the tool specs are replaced by the schema
tool alone. On that second pass Calendar, Gmail and the graph are gone. That is
why :data:`FORCED_OUTPUT_PROMPT` restates the honest-unknown rule rather than
leaving the SDK's one-line default as the model's last instruction before it must
answer with nothing to check against.
"""

from __future__ import annotations

from strands import Agent

from second.agents._base import build_agent
from second.core.deps import AgentDeps
from second.core.models import ObservationReport

REQUIRED_TOOLS: tuple[str, ...] = (
    "read_graph",
    "get_calendar_events",
    "search_gmail",
    "update_person_model",
)
OUTPUT_MODEL = ObservationReport

FORCED_OUTPUT_PROMPT = """Format what you found as an ObservationReport, using only what you
actually read in this conversation. Every task_id and every scheduled_for must come from the
graph you read, and every evidence line must quote or describe something that was in the
calendar or the mailbox in front of you -- if you cannot check it now, you cannot claim it.
outcome has three values and "unknown" is the right one whenever nothing in the calendar or
the inbox showed either way whether the work happened: pair it with source "none" and an
evidence line that says plainly there was no signal, never with a quote you have reconstructed
from memory. Leave no evidence field empty. In notes, keep the structural context and one line
per commitment you found, each carrying its message id and subject in quotes; if you found no
commitments, write that you found none rather than producing one."""


def build(deps: AgentDeps) -> Agent:
    """Build the Observer.

    Args:
        deps: What PLATFORM injected -- the model, the four tools declared in
            :data:`REQUIRED_TOOLS`, the audit hooks, the user id and the clock.

    Returns:
        The agent, ready for PLATFORM to wire in as the Daily graph's entry node.
    """
    return build_agent(
        "observer", deps, REQUIRED_TOOLS, OUTPUT_MODEL,
        structured_output_prompt=FORCED_OUTPUT_PROMPT,
    )
