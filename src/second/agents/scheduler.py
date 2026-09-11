"""Places the week's work into real calendar slots, and says what lost.

This is the last node in the Intake chain that writes anything durable. The
Cascader has already put the goal ladder in the Living Graph; the Route Planner
has proposed routes but persisted nothing, because a ``RoutePlan`` is a proposal
carried in a message rather than a row. So **routes and scheduled slots reach the
graph here or they do not reach it at all**, and a Scheduler that places events
without calling ``write_graph`` leaves a calendar full of blocks the Daily graph
has never heard of.

What it sees is deliberately narrow. Its only direct dependency is the Route
Planner, so its input is the original transcript followed by one block holding
that node's ``RoutePlan`` as raw JSON -- ``Graph._build_node_input``
(graph.py:1204-1245) prefixes the task, then writes ``From <node_id>:`` and the
stringified result, and ``AgentResult.__str__`` (agent_result.py:63-77) returns
``structured_output.model_dump_json()`` and returns *before* the text loop, so
any prose the Route Planner also wrote is gone. Everything else the Scheduler
needs -- the goal ladder, the deadlines, the person's constraints and their
honoured and abandoned slots -- it reads itself from the Living Graph, which is
both cheaper than threading it through three hops and more current.

It emits :class:`~second.core.models.ScheduleDecision`: what it placed, what it
could not, and how the competition between goals was resolved. ``deprioritised``
is the half that makes this a scheduler rather than a calendar app. Placing one
task in one free slot is arithmetic; deciding that a fifteen-year ambition's
weekly practice loses this Tuesday to a leave request due in five days, and
saying so in terms the user can argue with, is the judgement.

**The decision that is easy to get wrong is which constraint is which.** The
person layer holds two different kinds of fact that look alike in a prompt.
``constraints`` are rules -- "No meetings before 09:00" forecloses a whole band
of the day for anything that is a meeting, and no amount of deadline pressure
buys an exception. ``honoured_slots`` and ``abandoned_slots`` are evidence --
they say what this person has actually kept and actually missed, which outranks
an empty slot but does not outrank a rule. Collapsing the two produces either a
scheduler that ignores a stated boundary or one that treats a single missed
session as law. The prompt keeps them in that order on purpose, and it also asks
the model to reason out loud about the edge between them: "No meetings before
09:00" is a constraint about meetings, and a gym session at 07:00 is not a
meeting.

The structured-output override matters here for one specific field.
``Placement.calendar_event_id`` is nullable, and on the forced pass -- the
re-ask Strands makes when a turn ends without the schema tool, where the agent's
own tools are no longer in the spec (event_loop.py:574-575) -- the model can no
longer call ``create_event`` to find out what the id was. Without an override
telling it that null is the honest answer there, it writes a plausible-looking
id, and the Daily graph later goes looking for an event that was never created.
"""

from __future__ import annotations

from strands import Agent

from second.agents._base import build_agent
from second.core.deps import AgentDeps
from second.core.models import ScheduleDecision

REQUIRED_TOOLS: tuple[str, ...] = (
    "read_graph",
    "get_calendar_events",
    "find_free_slots",
    "create_event",
    "write_graph",
)
OUTPUT_MODEL = ScheduleDecision

FORCED_OUTPUT_PROMPT = """Format your work as a ScheduleDecision now.

You have no tools on this pass, so report only what you actually did. If you
called create_event and read an id out of its reply, put that id in
calendar_event_id; if you did not call it, or cannot see the id it returned,
leave calendar_event_id null. It is nullable for exactly this reason, and an
invented id sends the rest of the system looking for an event that does not
exist.

Every task in the route plan that you did not place belongs in deprioritised,
with the slot it wanted, what took that slot instead, and the reason. An empty
deprioritised list says every task fitted; only send one if that is true, and say
so in rationale. rationale explains how competition between goals was resolved --
which goal gave way to which, and what decided it. It does not list the
placements again."""


def build(deps: AgentDeps) -> Agent:
    """Build the Scheduler.

    Args:
        deps: The run's dependencies. Supplies the model, the five tools this
            agent declared, the audit hooks, the user id and the clock whose
            timezone the placements are written in.

    Returns:
        The configured ``Agent``, emitting ``ScheduleDecision``.
    """
    return build_agent(
        "scheduler",
        deps,
        REQUIRED_TOOLS,
        OUTPUT_MODEL,
        structured_output_prompt=FORCED_OUTPUT_PROMPT,
    )
