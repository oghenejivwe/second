"""Silence, and what the user says back.

Two scored behaviours, both easy to claim and hard to demonstrate.

**Silence** now means ``notify`` is false and ``decisions`` is empty -- not that
there is no brief. The day is a fact computed from the Living Graph and it is
there whenever somebody looks; what stays rare is the interruption. These tests
go through ``service.run_daily`` rather than the graph directly, because
``assemble()`` is where a model's judgement meets the guards that overrule it.

**Feedback** is the one flow where somebody's own words become mutations, and it
is split across two agents on purpose: the node that interprets speech cannot
write, and the node that writes never sees the sentence.
"""

from __future__ import annotations

from second.core.clock import Clock
from second.core.models import FeedbackResult
from second.graphs import service
from second.graphs.composition import ToolRegistry
from second.graphs.conditions import typed_result
from second.graphs.feedback import build_feedback_graph
from second.testing import demo_scenario
from second.testing.fake_connectors import ALL_FAKE_CONNECTORS
from second.testing.scripted_model import Structured, Text, ToolUse
from second.tools.graph_tools import ALL_GRAPH_TOOLS

from tests.agents.test_daily_honesty import (
    ADAPTER_MOVES_IT,
    CONFIDENT_CONFLICT,
    GYM_LOST_AGAIN,
    HONEST_UNKNOWN,
    OBSERVER_READS_THE_WORLD,
    PREPARER_DRAFTS_LEAVE,
    UNCONTESTED_SLIP,
)

USER = demo_scenario.USER_ID
CLOCK = Clock.fixed(demo_scenario.TODAY, zone_name="Europe/London")
REGISTRY = ToolRegistry([*ALL_GRAPH_TOOLS, *ALL_FAKE_CONNECTORS])

NOTHING_WORTH_SAYING = {
    "reminders": [],
    "decisions": [],
    "notify": False,
    "silence_reason": "Nothing in the day needs them; the recording question can wait.",
}

EVIDENCED_REMINDER = {
    "reminders": [
        {
            "what": "Your sister asked whether the flights are booked. Nothing was sent back.",
            "evidence": 'm-wedding, "Wedding week - are you booked yet?"',
            "source": "email",
        }
    ],
    "decisions": [],
    "notify": False,
    "silence_reason": "One forgotten reply, not worth a push on its own.",
}

UNEVIDENCED_REMINDER = {
    "reminders": [{"what": "You should book the flights.", "evidence": "", "source": "email"}],
    "decisions": [],
    "notify": False,
    "silence_reason": "",
}


# -- silence ----------------------------------------------------------------


async def test_a_quiet_day_still_returns_the_whole_day(store, router):
    """Existing is not interrupting.

    The schedule came from the Living Graph and is true regardless of what the
    Communicator concluded, so a quiet day is a full brief nobody is pushed at --
    not a missing one. A user who opens the app to an empty screen learns not to
    open the app.
    """
    _, model = router(
        {
            "observer": [*OBSERVER_READS_THE_WORLD, Structured(UNCONTESTED_SLIP)],
            "diagnostician": [Structured(HONEST_UNKNOWN)],
            "communicator": [Structured(NOTHING_WORTH_SAYING)],
        }
    )
    brief = await service.run_daily(
        USER, today=demo_scenario.TODAY, model=model, registry=REGISTRY
    )

    assert brief.is_quiet, "nothing needed the user, so nothing should have been pushed"
    assert brief.notify is False
    assert brief.decisions == []
    assert brief.silence_reason, "quietness must be auditable, not indistinguishable from failure"
    assert brief.blocks, "the day is a fact and it is there whether or not it interrupts"


async def test_a_decision_always_earns_a_notification(store, router):
    """The Communicator cannot talk itself out of raising something it asked for.

    ``assemble()`` forces ``notify`` whenever there is a decision, whatever the
    model concluded.
    """
    asks_but_says_dont_push = {
        "reminders": [],
        "decisions": [
            {
                "question": "What is getting in the way of the 08:00 recording?",
                "task_id": "t-recording",
                "evidence": "Three slots, all free, all missed.",
                "options": ["The hour is wrong", "Five minutes is too much"],
            }
        ],
        "notify": False,
        "silence_reason": "I would rather not bother them.",
    }
    _, model = router(
        {
            "observer": [*OBSERVER_READS_THE_WORLD, Structured(UNCONTESTED_SLIP)],
            "diagnostician": [Structured(HONEST_UNKNOWN)],
            "communicator": [Structured(asks_but_says_dont_push)],
        }
    )
    brief = await service.run_daily(
        USER, today=demo_scenario.TODAY, model=model, registry=REGISTRY
    )

    assert brief.notify is True, "a question was raised and the user was never told"
    assert brief.is_quiet is False


async def test_work_carried_to_the_last_click_always_earns_a_notification(store, router):
    """Something is sitting in their drafts waiting on one action.

    The same override, reached the other way: the act path produces a
    ``PreparedAction`` and ``assemble()`` notifies on it regardless of the
    Communicator's own judgement.
    """
    _, model = router(
        {
            "observer": [*OBSERVER_READS_THE_WORLD, Structured(GYM_LOST_AGAIN)],
            "diagnostician": [Structured(CONFIDENT_CONFLICT)],
            "adapter": ADAPTER_MOVES_IT,
            "preparer": PREPARER_DRAFTS_LEAVE,
            "communicator": [Structured(NOTHING_WORTH_SAYING)],
        }
    )
    brief = await service.run_daily(
        USER, today=demo_scenario.TODAY, model=model, registry=REGISTRY
    )

    assert brief.prepared, "the Preparer's work never reached the brief"
    assert brief.prepared[0].awaiting.strip(), "a prepared action must name the one thing left"
    assert brief.notify is True


async def test_every_reminder_that_reaches_the_user_cites_its_source(store, router):
    """This product does not nag. A reminder with no evidence is a defect."""
    _, model = router(
        {
            "observer": [*OBSERVER_READS_THE_WORLD, Structured(UNCONTESTED_SLIP)],
            "diagnostician": [Structured(HONEST_UNKNOWN)],
            "communicator": [Structured(EVIDENCED_REMINDER)],
        }
    )
    brief = await service.run_daily(
        USER, today=demo_scenario.TODAY, model=model, registry=REGISTRY
    )

    assert brief.reminders
    for reminder in brief.reminders:
        assert reminder.evidence.strip(), f"unevidenced reminder reached the user: {reminder.what}"
        assert reminder.source in ("email", "calendar", "graph")


async def test_an_unevidenced_reminder_is_not_rejected_by_the_contract(store, router):
    """A finding, asserted so it cannot quietly stop being true.

    ``Reminder.evidence`` is a plain required ``str`` with no minimum length, so
    an empty one validates and reaches the brief. The rule "a reminder with no
    evidence is a defect" lives in a docstring and in this package's prompts --
    nothing in the type system enforces it, unlike ``Diagnosis.evidence``, which
    coerces. Handed to PLATFORM; this test records the gap rather than papering
    over it.
    """
    _, model = router(
        {
            "observer": [*OBSERVER_READS_THE_WORLD, Structured(UNCONTESTED_SLIP)],
            "diagnostician": [Structured(HONEST_UNKNOWN)],
            "communicator": [Structured(UNEVIDENCED_REMINDER)],
        }
    )
    brief = await service.run_daily(
        USER, today=demo_scenario.TODAY, model=model, registry=REGISTRY
    )

    assert brief.reminders[0].evidence == "", (
        "if this now fails, the contract gained a guard and this test should become "
        "an assertion that the reminder was dropped"
    )


# -- what the user says back ------------------------------------------------

DID_IT_ANYWAY = {
    "completions": [
        {
            "task_id": "t-recording",
            "did_it": True,
            "note": "did it, just never opened the calendar",
        }
    ],
    "updates": [],
    "intentions": [],
    "acknowledgement": "",
}

DID_NOT_DO_IT = {
    "completions": [{"task_id": "t-recording", "did_it": False, "note": "ran out of morning"}],
    "updates": [],
    "intentions": [],
    "acknowledgement": "",
}


def feedback(store, model):
    """The real Feedback graph: real agent modules, real tools."""
    return build_feedback_graph(
        store=store, user_id=USER, clock=CLOCK, model=model, registry=REGISTRY
    )


def updater_applies(payload):
    completion = payload["completions"][0]
    return [
        ToolUse(
            "record_completion",
            {
                "user_id": USER,
                "task_id": completion["task_id"],
                "did_it": completion["did_it"],
                "note": completion["note"],
            },
        ),
        Text("Recorded one completion. Nothing else in the result was applicable."),
    ]


async def test_the_users_own_answer_beats_the_inference(store, router):
    """Not averaged, not weighed. The person was there; the system was not.

    ``t-recording`` carries three inferred slips in the seeded world. The user
    says they did it, and the slip that was inferred and then contradicted is
    removed rather than outweighed -- which also teaches the slot as one they
    keep, since they evidently kept it.
    """
    before = store.load(USER).task_by_id("t-recording")
    assert before.slip_count == 3 and before.status == "pending"

    _, model = router(
        {
            "interpreter": [
                ToolUse("read_graph", {"user_id": USER, "layer": "goals"}),
                Structured(DID_IT_ANYWAY),
            ],
            "graph_updater": updater_applies(DID_IT_ANYWAY),
        }
    )
    await feedback(store, model).run("yeah I did the recording, just never opened the calendar")

    after = store.load(USER).task_by_id("t-recording")
    assert after.status == "done"
    assert after.slip_count < before.slip_count, "an inferred slip survived being contradicted"


async def test_a_reason_given_for_a_missed_task_is_never_asked_about_twice(store, router):
    """``known_blocker`` is the "we heard you the first time" field.

    Being asked the same question twice is how a system tells somebody it was
    not listening, so a reason they volunteered is written against the task and
    the check-in stops raising it.
    """
    before = store.load(USER).task_by_id("t-recording")
    assert before.known_blocker is None

    _, model = router(
        {
            "interpreter": [Structured(DID_NOT_DO_IT)],
            "graph_updater": updater_applies(DID_NOT_DO_IT),
        }
    )
    await feedback(store, model).run("no, ran out of morning again")

    after = store.load(USER).task_by_id("t-recording")
    assert after.known_blocker == "ran out of morning"


async def test_a_task_the_user_did_not_do_keeps_its_history(store, router):
    """The control. ``did_it=False`` must not reverse anything."""
    before = store.load(USER).task_by_id("t-recording")

    _, model = router(
        {
            "interpreter": [Structured(DID_NOT_DO_IT)],
            "graph_updater": updater_applies(DID_NOT_DO_IT),
        }
    )
    await feedback(store, model).run("no, ran out of morning again")

    after = store.load(USER).task_by_id("t-recording")
    assert after.status != "done"
    assert after.slip_count >= before.slip_count, "a slip was reversed on a 'no'"


async def test_a_reason_given_alongside_a_yes_is_currently_discarded(store, router):
    """A finding, recorded so it cannot quietly stop being true.

    ``record_completion`` writes ``known_blocker`` only on the ``did_it=False``
    branch; the ``True`` branch returns before reaching it. So "I did it, I just
    never opened the calendar" -- which is precisely the explanation for a task
    that keeps looking missed while being done -- is taken in and dropped.

    That note is the one thing the system could not have inferred. Handed to
    PLATFORM; this test asserts the current behaviour so the handoff is a fact
    rather than a recollection.
    """
    _, model = router(
        {
            "interpreter": [Structured(DID_IT_ANYWAY)],
            "graph_updater": updater_applies(DID_IT_ANYWAY),
        }
    )
    await feedback(store, model).run("yeah I did it, just never opened the calendar")

    after = store.load(USER).task_by_id("t-recording")
    assert after.known_blocker is None, (
        "if this now fails, record_completion learned to keep the reason on a yes, "
        "and this test should assert the note was stored instead"
    )


async def test_the_node_that_interprets_speech_cannot_write(store, router):
    """The isolation, asserted through the audit log rather than the declaration.

    Only the Graph Updater may produce a write in this graph. A misheard
    instruction therefore has to survive being typed before it can reach
    anything.
    """
    _, model = router(
        {
            "interpreter": [
                ToolUse("read_graph", {"user_id": USER, "layer": "goals"}),
                Structured(DID_IT_ANYWAY),
            ],
            "graph_updater": updater_applies(DID_IT_ANYWAY),
        }
    )
    composed = feedback(store, model)
    await composed.run("yeah I did the recording")

    writers = {entry.actor for entry in composed.audit.entries if entry.is_write}
    assert writers == {"graph_updater"}, f"something else wrote: {sorted(writers)}"


async def test_the_interpreter_hands_on_validated_types(store, router):
    """What the Graph Updater acts on is typed, resolved and already checked."""
    routed, model = router(
        {
            "interpreter": [Structured(DID_IT_ANYWAY)],
            "graph_updater": updater_applies(DID_IT_ANYWAY),
        }
    )
    result = await feedback(store, model).run("yeah I did the recording")

    interpreted = typed_result(result, "interpreter", FeedbackResult)
    assert interpreted.completions[0].task_id == "t-recording"

    prompt = routed.prompt_for("graph_updater")
    assert '"task_id":"t-recording"' in prompt.replace(" ", "")
    assert "From interpreter" in prompt


async def test_the_raw_sentence_does_reach_the_node_that_writes(store, router):
    """A finding, and it contradicts what ``graphs/feedback.py`` claims.

    That module's docstring says the Graph Updater "never sees the raw
    sentence". It does. ``Graph._build_node_input`` (``graph.py:1226-1229``)
    prepends ``"Original Task: ..."`` to **every** node's input, and
    ``service.run_feedback`` passes the user's own utterance as the graph task --
    so it is broadcast to both nodes, not handed only to the Interpreter.

    The isolation that does hold is the one that matters most: the Interpreter
    has no write tool, and the Graph Updater has no read tool and acts on typed
    entries. But the stated claim is stronger than the wiring, and a security
    property nobody has checked is a security property that is not there.
    Handed to PLATFORM.
    """
    routed, model = router(
        {
            "interpreter": [Structured(DID_IT_ANYWAY)],
            "graph_updater": updater_applies(DID_IT_ANYWAY),
        }
    )
    sentence = "yeah I did the recording, just never opened the sodding calendar"
    await feedback(store, model).run(sentence)

    prompt = routed.prompt_for("graph_updater")
    assert "sodding" in prompt, (
        "if this now fails, the raw utterance was taken off the graph task and the "
        "isolation claim in graphs/feedback.py became true -- rewrite this as the "
        "assertion that it is absent"
    )
