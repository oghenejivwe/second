"""The Daily loop, run end to end on the seeded world with the real agents.

Every node here is the actual module from ``second.agents`` -- no stub specs --
wired by the actual ``build_daily_graph``, calling the actual tools against real
DynamoDB semantics. Only the model's *choices* are scripted, which is the point:
the machinery is PLATFORM's and proved elsewhere, and what these tests prove is
that the agents drop into it and that their typed fields route the run.

The file is organised around the two behaviours the product is judged on: the
honest ``UNKNOWN``, and the confident diagnosis Second resolves on its own.
"""

from __future__ import annotations

from second.core.clock import Clock
from second.core.models import BriefJudgement, Diagnosis, ObservationReport
from second.graphs.composition import ToolRegistry
from second.graphs.conditions import typed_result
from second.graphs.daily import build_daily_graph
from second.testing import demo_scenario
from second.testing.fake_connectors import ALL_FAKE_CONNECTORS
from second.testing.scripted_model import Structured, Text, ToolUse
from second.tools.graph_tools import ALL_GRAPH_TOOLS

USER = demo_scenario.USER_ID
DEMO_TZ = "Europe/London"
CLOCK = Clock.fixed(demo_scenario.TODAY, zone_name=DEMO_TZ)

WINDOW_START = (demo_scenario.HISTORY_START).isoformat() + "T00:00:00"
WINDOW_END = "2026-09-11T00:00:00"


# -- the Observer's two reports ---------------------------------------------

UNCONTESTED_SLIP = {
    "observations": [
        {
            "task_id": "t-recording",
            "scheduled_for": "2026-09-05T08:00:00",
            "outcome": "unknown",
            "evidence": "08:00 slot confirmed and uncontested on all three dates; "
            "nothing in the calendar or the mailbox either way.",
            "source": "none",
        }
    ],
    "notes": 'Commitment: sister asked whether the flights are booked and no reply was sent - '
    'm-wedding, "Wedding week - are you booked yet?"; the hotel block closes end of month.',
}

GYM_LOST_AGAIN = {
    "observations": [
        {
            "task_id": "t-gym",
            "scheduled_for": "2026-09-03T18:00:00",
            "outcome": "missed",
            "evidence": "Gym session 18:00 declined 4 of 5 weekdays; each collided with "
            "'Eng sync' 18:00, 9 attendees, is_owner false.",
            "source": "calendar",
        }
    ],
    "notes": 'Commitment: sister asked whether the flights are booked and no reply was sent - '
    'm-wedding, "Wedding week - are you booked yet?".',
}


# -- the Diagnostician's verdicts -------------------------------------------

HONEST_UNKNOWN = {
    "task_id": "t-recording",
    "blocker_type": "UNKNOWN",
    "evidence": None,
    "confidence": 0.3,
    "proposed_action": "Ask what is getting in the way of the 08:00 recording. Picked over "
    "t-gym because the gym has a structural cause Second can act on alone.",
    "requires_user_decision": True,
}

CONFIDENT_CONFLICT = {
    "task_id": "t-gym",
    "blocker_type": "CALENDAR_CONFLICT",
    "evidence": "Gym session 18:00, response declined; 'Eng sync' 18:00, 9 attendees, "
    "is_owner false.",
    "confidence": 0.92,
    "proposed_action": "Move the gym block to 07:00, which is free every weekday.",
    "requires_user_decision": False,
}

CONFIDENT_BUT_UNEVIDENCED = {
    "task_id": "t-recording",
    "blocker_type": "CALENDAR_CONFLICT",
    "evidence": None,
    "confidence": 0.95,
    "proposed_action": "Move it to 07:00.",
    "requires_user_decision": False,
}


# -- what the other nodes do ------------------------------------------------

ASK_THE_USER = {
    "reminders": [
        {
            "what": "Your sister asked whether the flights are booked. Nothing was sent back.",
            "evidence": 'm-wedding, "Wedding week - are you booked yet?"',
            "source": "email",
        }
    ],
    "decisions": [
        {
            "question": "What is getting in the way of the 08:00 recording?",
            "task_id": "t-recording",
            "evidence": "Three slots, all free, all missed. Nothing explains it.",
            "options": ["The hour is wrong", "Five minutes is still too much", "Something else"],
        }
    ],
    "notify": True,
    "silence_reason": "",
}

STAY_QUIET = {
    "reminders": [],
    "decisions": [],
    "notify": False,
    "silence_reason": "The 18:00 gym conflict was resolved without the user; nothing needs them.",
}

ADAPTER_MOVES_IT = [
    ToolUse("read_graph", {"user_id": USER, "layer": "goals"}),
    ToolUse("reschedule_event", {"event_id": "gym000", "new_start": "2026-09-14T07:00:00"}),
    Text(
        "t-gym, CALENDAR_CONFLICT. Evidence: 18:00 declined four of five weekdays, each "
        "colliding with 'Eng sync' (9 attendees, not the user's event). Moved the block to "
        "07:00, which is free every weekday. The 18:00 slot is gone, not postponed. "
        "Still outstanding: nothing for this task."
    ),
]

PREPARER_DRAFTS_LEAVE = [
    ToolUse("search_gmail", {"query": "in:sent leave", "max_results": 5}),
    ToolUse("search_gmail", {"query": "leave policy notice", "max_results": 3}),
    ToolUse(
        "draft_email",
        {
            "to": demo_scenario.MANAGER_EMAIL,
            "subject": "Annual leave request: wedding week",
            "body": "Hi,\n\nI would like to request annual leave for the week of my sister's "
            "wedding. HR asks for 14 days notice, which this clears.\n\nThanks",
        },
    ),
    Structured(
        {
            "kind": "email_draft",
            "summary": "Leave request for the wedding week, drafted and not sent.",
            "detail": "To manager@example.com - 'Annual leave request: wedding week'.",
            "external_ref": "draft002",
            "awaiting": "Read and send the leave request in your drafts.",
        }
    ),
]

OBSERVER_READS_THE_WORLD = [
    ToolUse("read_graph", {"user_id": USER, "layer": "goals"}),
    ToolUse("get_calendar_events", {"start": WINDOW_START, "end": WINDOW_END}),
    ToolUse("search_gmail", {"query": "wedding flights", "max_results": 5}),
]


def daily(store, model):
    """The real Daily graph: real agent modules, real tools, scripted choices."""
    return build_daily_graph(
        store=store,
        user_id=USER,
        clock=CLOCK,
        model=model,
        registry=ToolRegistry([*ALL_GRAPH_TOOLS, *ALL_FAKE_CONNECTORS]),
    )


def order(result) -> list[str]:
    return [node.node_id for node in result.execution_order]


# -- 1. the honest UNKNOWN --------------------------------------------------


async def test_an_unexplained_slip_asks_the_user_and_never_touches_the_plan(store, router):
    """Demo beat 4. Three slips into slots that were completely free.

    There is no structural explanation, so the only honest answer is UNKNOWN and
    the only honest action is to ask. The Adapter and the Preparer must not run:
    changing somebody's plan on the strength of a cause you could not name is
    exactly what this product promises not to do.
    """
    routed, model = router(
        {
            "observer": [*OBSERVER_READS_THE_WORLD, Structured(UNCONTESTED_SLIP)],
            "diagnostician": [
                ToolUse("read_graph", {"user_id": USER, "layer": "goals"}),
                ToolUse("record_diagnosis", {"user_id": USER, "diagnosis": HONEST_UNKNOWN}),
                Structured(HONEST_UNKNOWN),
            ],
            "communicator": [Structured(ASK_THE_USER)],
        }
    )
    result = await daily(store, model).run("Yesterday's plan against what actually happened.")

    assert order(result) == ["observer", "diagnostician", "communicator"]
    assert routed.ran("adapter") == 0, "the plan was changed on an unexplained slip"
    assert routed.ran("preparer") == 0

    diagnosis = typed_result(result, "diagnostician", Diagnosis)
    assert diagnosis.blocker_type == "UNKNOWN"
    assert diagnosis.evidence is None, "an honest UNKNOWN cites nothing, because it has nothing"

    judgement = typed_result(result, "communicator", BriefJudgement)
    assert len(judgement.decisions) == 1
    assert judgement.decisions[0].task_id == "t-recording"
    assert judgement.decisions[0].options, "a bare question costs a round trip"


async def test_a_confident_verdict_with_nothing_to_cite_still_asks(store, router):
    """The rail that holds against a model trying to sound sure.

    Strands produces structured output by *forcing* a tool call, so on the second
    pass the model cannot decline -- which makes "confident, and no evidence" the
    likeliest way this agent fails. ``Diagnosis`` coerces it
    (``models.py:386-405``): blocker becomes UNKNOWN, confidence is capped, and
    ``requires_user_decision`` is set, so the run routes to asking no matter what
    the model claimed.

    Mutation: delete ``_no_evidence_means_unknown`` from ``models.py`` and this
    run reaches the Adapter instead.
    """
    routed, model = router(
        {
            "observer": [*OBSERVER_READS_THE_WORLD, Structured(UNCONTESTED_SLIP)],
            "diagnostician": [
                ToolUse("read_graph", {"user_id": USER, "layer": "goals"}),
                Structured(CONFIDENT_BUT_UNEVIDENCED),
            ],
            "communicator": [Structured(ASK_THE_USER)],
        }
    )
    result = await daily(store, model).run("go")

    diagnosis = typed_result(result, "diagnostician", Diagnosis)
    assert diagnosis.blocker_type == "UNKNOWN"
    assert diagnosis.confidence <= 0.3
    assert diagnosis.requires_user_decision is True

    assert order(result) == ["observer", "diagnostician", "communicator"]
    assert routed.ran("adapter") == 0


async def test_an_honest_unknown_does_not_teach_the_system_a_false_pattern(store, router):
    """``record_diagnosis`` learns a recurring blocker only when it is sure.

    A system that files "I could not tell" as a known cause will recognise it
    faster next time, and be wrong faster.
    """
    _, model = router(
        {
            "observer": [*OBSERVER_READS_THE_WORLD, Structured(UNCONTESTED_SLIP)],
            "diagnostician": [
                ToolUse("record_diagnosis", {"user_id": USER, "diagnosis": HONEST_UNKNOWN}),
                Structured(HONEST_UNKNOWN),
            ],
            "communicator": [Structured(ASK_THE_USER)],
        }
    )
    await daily(store, model).run("go")

    assert store.load(USER).person.recurring_blockers == []


async def test_a_confident_structural_verdict_is_learned(store, router):
    """The complement of the test above, so the guard is a control and not a floor."""
    _, model = router(
        {
            "observer": [*OBSERVER_READS_THE_WORLD, Structured(GYM_LOST_AGAIN)],
            "diagnostician": [
                ToolUse("record_diagnosis", {"user_id": USER, "diagnosis": CONFIDENT_CONFLICT}),
                Structured(CONFIDENT_CONFLICT),
            ],
            "adapter": ADAPTER_MOVES_IT,
            "preparer": PREPARER_DRAFTS_LEAVE,
            "communicator": [Structured(STAY_QUIET)],
        }
    )
    await daily(store, model).run("go")

    blockers = store.load(USER).person.recurring_blockers
    assert blockers, "a confident structural cause should be recognised faster next time"
    assert any("CALENDAR_CONFLICT" in blocker for blocker in blockers)


# -- 2. the confident, autonomous day ---------------------------------------


async def test_a_structural_cause_is_resolved_without_the_user(store, router):
    """Demo beat 1, the whole act-alone path."""
    routed, model = router(
        {
            "observer": [*OBSERVER_READS_THE_WORLD, Structured(GYM_LOST_AGAIN)],
            "diagnostician": [
                ToolUse("read_graph", {"user_id": USER, "layer": "goals"}),
                Structured(CONFIDENT_CONFLICT),
            ],
            "adapter": ADAPTER_MOVES_IT,
            "preparer": PREPARER_DRAFTS_LEAVE,
            "communicator": [Structured(STAY_QUIET)],
        }
    )
    result = await daily(store, model).run("go")

    assert order(result) == ["observer", "diagnostician", "adapter", "preparer", "communicator"]
    assert routed.ran("communicator") == 1, "the Communicator must run exactly once"


async def test_the_adapter_changes_the_plan_rather_than_postponing_it(store, router):
    """"Move it to tomorrow" is a failed adaptation.

    The gym does not move to tomorrow at 18:00. It moves to 07:00, because 18:00
    loses to Eng sync every weekday and always will.
    """
    _, model = router(
        {
            "observer": [*OBSERVER_READS_THE_WORLD, Structured(GYM_LOST_AGAIN)],
            "diagnostician": [Structured(CONFIDENT_CONFLICT)],
            "adapter": ADAPTER_MOVES_IT,
            "preparer": PREPARER_DRAFTS_LEAVE,
            "communicator": [Structured(STAY_QUIET)],
        }
    )
    composed = daily(store, model)
    state = {"second": {"store": store, "user_id": USER, "clock": CLOCK}}
    await composed.graph.invoke_async("go", state)

    moves = [e for e in state["second"]["fake_effects"] if e["kind"] == "reschedule_event"]
    assert moves, "the Adapter did not change anything"
    assert "T07:00" in moves[0]["new_start"], "the slot itself was the problem; 18:00 must go"


async def test_nothing_is_ever_sent_only_drafted(store, router):
    """The rail that matters most, asserted through my own Preparer."""
    _, model = router(
        {
            "observer": [*OBSERVER_READS_THE_WORLD, Structured(GYM_LOST_AGAIN)],
            "diagnostician": [Structured(CONFIDENT_CONFLICT)],
            "adapter": ADAPTER_MOVES_IT,
            "preparer": PREPARER_DRAFTS_LEAVE,
            "communicator": [Structured(STAY_QUIET)],
        }
    )
    composed = daily(store, model)
    state = {"second": {"store": store, "user_id": USER, "clock": CLOCK}}
    await composed.graph.invoke_async("go", state)

    kinds = [effect["kind"] for effect in state["second"]["fake_effects"]]
    assert "draft_email" in kinds
    assert not any("send" in kind for kind in kinds), f"something tried to send: {kinds}"

    draft = next(e for e in state["second"]["fake_effects"] if e["kind"] == "draft_email")
    assert draft["to"] == demo_scenario.MANAGER_EMAIL
    assert "[" not in draft["body"], "a placeholder is not work carried to the last click"


async def test_the_preparer_receives_the_diagnosis_through_the_adapters_own_words(store, router):
    """The Preparer's only dependency is the Adapter, which has no typed output.

    ``AgentResult.__str__`` (``agent_result.py:63-77``) returns the text of an
    untyped node, and ``_build_node_input`` (``graph.py:1204-1245``) gives a node
    its direct dependencies only -- so the Adapter's final message is the entire
    channel, and the Adapter's prompt requires it to restate the task and the
    blocker. This asserts the channel is actually carrying them.
    """
    routed, model = router(
        {
            "observer": [*OBSERVER_READS_THE_WORLD, Structured(GYM_LOST_AGAIN)],
            "diagnostician": [Structured(CONFIDENT_CONFLICT)],
            "adapter": ADAPTER_MOVES_IT,
            "preparer": PREPARER_DRAFTS_LEAVE,
            "communicator": [Structured(STAY_QUIET)],
        }
    )
    await daily(store, model).run("go")

    prompt = routed.prompt_for("preparer")
    assert "t-gym" in prompt
    assert "CALENDAR_CONFLICT" in prompt
    assert "Eng sync" in prompt


# -- 3. the gated observer edge ---------------------------------------------


async def test_the_observers_report_reaches_the_communicator_on_the_ask_path(store, router):
    """Without it the Communicator has no evidence for any reminder at all."""
    routed, model = router(
        {
            "observer": [*OBSERVER_READS_THE_WORLD, Structured(UNCONTESTED_SLIP)],
            "diagnostician": [Structured(HONEST_UNKNOWN)],
            "communicator": [Structured(ASK_THE_USER)],
        }
    )
    await daily(store, model).run("go")

    prompt = routed.prompt_for("communicator")
    assert "m-wedding" in prompt, "the commitment never reached the node that reports it"
    assert "From observer" in prompt
    assert routed.ran("communicator") == 1


async def test_the_observers_report_reaches_the_communicator_on_the_act_path(store, router):
    routed, model = router(
        {
            "observer": [*OBSERVER_READS_THE_WORLD, Structured(GYM_LOST_AGAIN)],
            "diagnostician": [Structured(CONFIDENT_CONFLICT)],
            "adapter": ADAPTER_MOVES_IT,
            "preparer": PREPARER_DRAFTS_LEAVE,
            "communicator": [Structured(STAY_QUIET)],
        }
    )
    await daily(store, model).run("go")

    prompt = routed.prompt_for("communicator")
    assert "m-wedding" in prompt
    assert "From preparer" in prompt, "the act path must also carry what was prepared"
    assert routed.ran("communicator") == 1, "the gate stops the Communicator running twice"


# -- 4. the Observer's own promises -----------------------------------------


async def test_the_observer_report_is_the_diagnosticians_whole_world(store, router):
    """It arrives as JSON in the prompt, not through a context dict.

    The Diagnostician holds no calendar or Gmail tool, so this block is provably
    everything it can see.
    """
    routed, model = router(
        {
            "observer": [*OBSERVER_READS_THE_WORLD, Structured(UNCONTESTED_SLIP)],
            "diagnostician": [Structured(HONEST_UNKNOWN)],
            "communicator": [Structured(ASK_THE_USER)],
        }
    )
    result = await daily(store, model).run("go")

    report = typed_result(result, "observer", ObservationReport)
    assert report.observations[0].outcome == "unknown"
    assert report.observations[0].source == "none"
    assert report.observations[0].evidence, "even an unknown carries an evidence line"

    prompt = routed.prompt_for("diagnostician")
    assert '"outcome":"unknown"' in prompt.replace(" ", "")
    assert "t-recording" in prompt
