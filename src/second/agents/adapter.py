"""Changes the plan when the plan is what went wrong.

The Adapter is the act-alone half of the Daily graph's branch. It runs only
after a ``Diagnosis`` that was confident, carried evidence and said Second can
resolve this without the user -- ``can_act_alone`` is the strict complement of
``needs_user_decision``, so arriving at this node is itself the permission to
change something. There is no second gate here and there should not be one: an
Adapter that re-litigates the diagnosis either does nothing or does the
Diagnostician's job with less evidence than the Diagnostician had.

**What it can see is deliberately thin.** Its only incoming edge is from the
Diagnostician, and ``Graph._build_node_input`` (graph.py:1204-1245) hands a node
the original task text plus one block per *direct* dependency -- so the whole of
this agent's input is one Diagnosis. It arrives as raw JSON, because
``AgentResult.__str__`` (agent_result.py:63-77) returns
``structured_output.model_dump_json()`` and returns *before* the text loop, which
means any prose the Diagnostician also produced is dropped on the floor. The
Observer's report does not reach here, and neither does the calendar or the
inbox. Everything beyond those six fields is read back out of the Living Graph.

**The decision that is easy to get wrong is postponement.** Moving slipped work
to tomorrow satisfies every surface test -- something changed, the graph was
written, a sentence can be produced about it -- and changes nothing, because the
thing that beat the work at 18:00 on Monday beats it again at 18:00 on Tuesday.
So the rule the prompt leads with is a test on the outcome rather than on the
edit: if the same collision, the same vagueness or the same missing dependency
would produce the same slip next time, the adaptation failed and the honest move
is to say the slot itself is the problem and hand that finding on.

**Three tools, and the gaps between them are the design.** ``read_graph`` comes
first because ``write_graph`` upserts whole goals -- a partial goal replaces the
entry, so a stale or hand-rebuilt object silently erases routes, slip history and
the ``blocked`` status ``record_diagnosis`` just wrote. ``reschedule_event``
moves an event the user owns and refuses everything else; that refusal is the
product working and is reported rather than routed around. There is no
``create_event`` and no calendar read here, which is intentional: a slot this
agent cannot verify or create is work it describes and passes on instead of
inventing.

No structured output, so ``structured_output_prompt`` is ``None``. The Preparer's
only incoming edge is from this node, which makes this agent's final message the
entire contents of the Preparer's input -- the Diagnosis does not reach it. The
prompt therefore treats the closing message as the deliverable and fixes its
shape, because a handoff that reads well to a human and omits the task id is a
handoff that cost the next node its subject.
"""

from __future__ import annotations

from strands import Agent

from second.agents._base import build_agent
from second.core.deps import AgentDeps

REQUIRED_TOOLS: tuple[str, ...] = ("read_graph", "reschedule_event", "adapt_task")
OUTPUT_MODEL = None


def build(deps: AgentDeps) -> Agent:
    """Construct the Adapter.

    Args:
        deps: What PLATFORM injected -- the model, exactly the three tools named
            in ``REQUIRED_TOOLS``, the audit hooks, the user id and the clock.

    Returns:
        The agent, ready for PLATFORM to wire in as the ``adapter`` node.
    """
    return build_agent(
        "adapter", deps, REQUIRED_TOOLS, OUTPUT_MODEL,
        structured_output_prompt=None,
    )
