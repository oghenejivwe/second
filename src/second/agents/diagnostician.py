"""Why one task slipped, decided from quoted evidence or not decided at all.

The Diagnostician is the node the Daily graph turns on. It reads the Observer's
sanitised ``ObservationReport`` and the Living Graph, picks the single slipped
task worth the day's attention, names the structural cause, and says whether
Second can fix it alone. Its fields *are* the routing:
:mod:`second.graphs.conditions` reads ``requires_user_decision``, ``confidence``
and ``blocker_type`` off the typed result and sends the run to the Adapter or to
the Communicator. Nothing downstream parses its prose, so prose that disagrees
with the fields changes nothing and is simply a lie in the audit log.

**It cannot reach Gmail or the calendar, and that is the design, not an
oversight.** Its two tools are ``read_graph`` and ``record_diagnosis``.
Everything it knows about what actually happened arrives already quoted, inside
the report. That is what makes the evidence rule enforceable rather than
aspirational: this agent cannot go and find a better-sounding quote, so every
quote it cites is one the Observer genuinely read out of the inbox or the
calendar. The graph supplies structure -- ``depends_on``, ``slip_count``,
``scheduled_slots``, ``status`` -- and never supplies a quote.

The one decision here that is easy to get wrong is the empty one. Strands
produces structured output by registering the schema as one more tool and
re-asking with tool choice forced when the model ends a turn without calling it
(``event_loop.py:574-575``); on that forced pass the agent's own tools are gone
and it cannot decline. A model in that position fills every field it is offered,
``evidence`` included, including on a day when nothing it read explains anything
-- which is precisely how a real calendar quote ends up attached to a conclusion
it does not support. ``Diagnosis.evidence`` is nullable for that reason, and the
validator at ``models.py:386-404`` coerces an evidenceless diagnosis to
``UNKNOWN`` with confidence capped at 0.3 and ``requires_user_decision`` set, so
an honest blank routes to an honest question automatically. The prompt and
:data:`FORCED_OUTPUT_PROMPT` exist because that coercion is a floor, not a
guarantee: a model can defeat it any day it likes by reaching for a quote, and
the only real defence is that it arrives at the blank deliberately.

``record_diagnosis`` is called before the typed answer rather than after, and the
same object goes into both. It files the slip against the task and learns the
blocker as recurring only when confidence is at least 0.7 and the type is not
``UNKNOWN`` (``graph_tools.py``), so an honest unknown cannot teach the person
layer a pattern that is not there.

Input reaches this node as the original task text plus one stringified block per
direct dependency (``graph.py:1204-1245``), and a typed upstream node stringifies
to its model's JSON alone: ``AgentResult.__str__`` returns
``structured_output.model_dump_json()`` and returns *before* the text loop
(``agent_result.py:63-77``), so any prose the Observer also wrote is silently
dropped. The Observer is this node's only direct dependency, so the prompt tells
the model to expect exactly one JSON object with ``observations`` and ``notes``,
and where to find the quotes inside it.
"""

from __future__ import annotations

from strands import Agent

from second.agents._base import build_agent
from second.core.deps import AgentDeps
from second.core.models import Diagnosis

REQUIRED_TOOLS: tuple[str, ...] = ("read_graph", "record_diagnosis")
OUTPUT_MODEL = Diagnosis

FORCED_OUTPUT_PROMPT = """Return the diagnosis you actually reasoned to, not a
tidier one. `evidence` must be text you read verbatim in the observation report
above -- an observation's `evidence` string or the report's `notes`; if the
strongest line you have only describes the slot rather than explaining why the
work did not happen, that line is not evidence and `evidence` must be null.
Null is the correct answer whenever nothing structural explains the slip: set
`blocker_type` to UNKNOWN, keep `confidence` low, set `requires_user_decision`
to true, and make `proposed_action` the question you would ask the user. Never
reconstruct a quote from memory or from graph fields, never write "no evidence
found" into `evidence` when you mean null, and never name a `task_id` that did
not appear in the report or in the graph you read."""


def build(deps: AgentDeps) -> Agent:
    """Construct the Diagnostician for one run of the Daily graph.

    Args:
        deps: What PLATFORM injected -- the model, exactly ``read_graph`` and
            ``record_diagnosis``, the audit hooks, the retry policy, the user id
            and the user's own clock.

    Returns:
        The agent, emitting a :class:`~second.core.models.Diagnosis` whose typed
        fields the Daily graph's conditional edges route on.
    """
    return build_agent(
        "diagnostician", deps, REQUIRED_TOOLS, OUTPUT_MODEL,
        structured_output_prompt=FORCED_OUTPUT_PROMPT,
    )
