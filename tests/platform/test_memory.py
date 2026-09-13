"""Memory: every source asked, every item evidenced, and a broken source that says so.

The failure these guard against is the quiet one. A calendar that cannot be read returning an
empty list reads as "nothing to remember today", which is the most confident wrong answer the tab
could give, and an item with no evidence is a nag wearing the voice of a fact.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from second.core.clock import Clock
from second.core.models import BriefJudgement, MemoryItem, PreparedAction, Reminder
from second.graphs.brief import assemble, blocks_on
from second.graphs.memory import (
    Collected,
    MemoryContext,
    SourceUnavailable,
    collect_memory,
    default_sources,
)
from second.testing import demo_scenario
from second.testing.fake_connectors import read_fake_calendar
from second.tools._google import GoogleCredentialsMissing

TZ = "Europe/London"
TODAY = date(2026, 9, 10)

WEDDING = Reminder(
    what="Your sister asked whether the flights are booked. You have not replied.",
    evidence="m-wedding, “Wedding week - are you booked yet?”, received 9 days ago.",
    source="email",
)
LEAVE_DRAFT = PreparedAction(
    kind="email_draft",
    summary="Leave request for the wedding week, drafted and waiting in Gmail.",
    external_ref="draft-0001",
    awaiting="Read it and press send.",
)
LEAVE_DRAFT_FOR_T_LEAVE = LEAVE_DRAFT.model_copy(update={"task_id": "t-leave"})
"""The same draft, naming the task it carries forward, as the fixture's Preparer does."""


@pytest.fixture
def clock() -> Clock:
    return Clock.fixed(TODAY, zone_name=TZ)


@pytest.fixture
def graph():
    return demo_scenario.living_graph()


def event(event_id: str, title: str, hour: int, minutes: int = 60, **extra) -> dict:
    """One event in the connector's own shape."""
    start = datetime(2026, 9, 10, hour, 0)
    end = start.replace(hour=hour + minutes // 60, minute=minutes % 60)
    return {
        "id": event_id,
        "title": title,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "status": extra.get("status", "confirmed"),
        "is_owner": extra.get("is_owner", True),
        "attendees": extra.get("attendees", 1),
        "response": extra.get("response", "accepted"),
    }


TODAYS_CALENDAR = [
    # Second's own block: same title and start as the t-recording slot placed today.
    event("rec", "Record five minutes and listen back", 8),
    event("lunch", "Lunch with Sam", 12, status="cancelled"),
    event("dentist", "Dentist", 14, response="declined"),
    event("engsync", "Eng sync", 18, is_owner=False, attendees=9),
]


def calendar(events):
    return lambda start, end: list(events)


def memory_for(graph, clock, *, brief=None, read=calendar(TODAYS_CALENDAR), sources=None):
    context = MemoryContext(user_id="demo", graph=graph, clock=clock, brief=brief)
    return collect_memory(context, sources if sources is not None else default_sources(read))


def status(memory, name):
    return next(source for source in memory.sources if source.name == name)


def a_brief(graph, clock, **judged):
    return assemble(
        graph=graph,
        clock=clock,
        judgement=BriefJudgement(reminders=[WEDDING], notify=True, **judged),
        prepared=[LEAVE_DRAFT],
    )


# -- evidence ----------------------------------------------------------------


def test_every_item_carries_evidence(graph, clock):
    memory = memory_for(graph, clock, brief=a_brief(graph, clock))

    assert {item.source for item in memory.items} == {"graph", "calendar", "email"}
    for item in memory.items:
        assert item.evidence.strip(), f"{item.what!r} from {item.source} cites nothing"


def test_an_item_without_evidence_cannot_be_built():
    """Built in Python, so refused at construction where a test sees it, not filtered later.

    Mutation-tested: removing ``MemoryItem._no_evidence_no_item`` makes this fail.
    """
    with pytest.raises(ValidationError):
        MemoryItem(what="Book flights", evidence="   ", source="graph", kind="deadline")


# -- the graph ---------------------------------------------------------------


def test_the_graph_source_remembers_deadlines_and_standing_rules(graph, clock):
    memory = memory_for(graph, clock)
    graph_items = [item for item in memory.items if item.source == "graph"]

    leave = next(item for item in graph_items if item.kind == "deadline" and "Request leave" in item.what)
    assert leave.due == date(2026, 9, 15)
    assert "nothing booked" in leave.evidence

    rules = [item.what for item in graph_items if item.kind == "constraint"]
    assert rules == ["No meetings before 09:00", "Sundays are family"]

    assert "The morning run has not happened yet today" in status(memory, "graph").reason


def test_todays_placed_blocks_are_on_today_with_true_evidence(graph, clock):
    """Memory said "On today 0" while Today and Schedule each showed three blocks.

    The calendar here holds Second's own 08:00 recording event, so this also proves the block is
    listed once, not once from the plan and again from the calendar.

    Mutation-tested: removing the placed-block items from ``GraphSource.collect`` empties the plan
    events and this fails.
    """
    memory = memory_for(graph, clock)
    events = [item for item in memory.items if item.kind == "event" and item.source == "graph"]

    assert [(item.what, item.at) for item in events] == [
        (block.title, block.start) for block in blocks_on(graph, clock, TODAY)
    ]
    assert [item.what for item in events] == [
        "Record five minutes and listen back",
        "Draft the talk pitch",
        "Gym session",
    ]
    assert events[0].evidence == (
        "In today's plan from 08:00 to 09:00: “Record five minutes and listen back”, "
        "towards “Get comfortable speaking to a room”."
    )
    assert events[2].evidence == (
        "In today's plan from 18:00 to 19:00: “Gym session”, towards “Train three times a week”."
    )

    recording = [item for item in memory.items if "Record five minutes" in item.what]
    assert len(recording) == 1, "listed once, from the plan, and left out of the calendar's items"


def test_a_deadline_and_the_draft_that_meets_it_are_one_item(graph, clock):
    """The leave request was listed as "nothing booked" and, separately, as "a draft is waiting".

    Mutation-tested: making the fold never match (``candidate.task_id == risk.task_id`` to
    ``False``) lists the two items again and this fails.
    """
    brief = a_brief(graph, clock)
    brief.prepared = [LEAVE_DRAFT_FOR_T_LEAVE]

    memory = memory_for(graph, clock, brief=brief)
    leave = [item for item in memory.items if "leave" in item.what.lower()]

    assert len(leave) == 1
    assert leave[0].kind == "waiting_on_you"
    assert leave[0].what == "Request leave for the wedding week, due Tue 15 Sep"
    assert leave[0].due == date(2026, 9, 15)
    assert leave[0].evidence == "Due Tue 15 Sep. A draft is waiting in Gmail (draft-0001): read it and press send."
    assert "nothing booked" not in leave[0].evidence


def test_a_draft_that_names_no_task_is_not_folded_on_similar_wording(graph, clock):
    """"Leave request for the wedding week" looks like "Request leave for the wedding week". Folding on
    that would be a guess, so without a task id both stay, each saying only what is true of it."""
    memory = memory_for(graph, clock, brief=a_brief(graph, clock))

    kinds = sorted(item.kind for item in memory.items if "leave" in item.what.lower())
    assert kinds == ["deadline", "waiting_on_you"]


def test_what_the_user_told_second_is_remembered(graph, clock):
    graph.task_by_id("t-flights").known_blocker = "Waiting on my manager to approve leave"
    graph.task_by_id("t-club").known_blocker = "Club is cancelled this week"
    graph.task_by_id("t-club").status = "done"

    told = [item for item in memory_for(graph, clock).items if item.kind == "told_second"]

    assert [item.what for item in told] == ["Book flights to Lisbon: Waiting on my manager to approve leave"]
    assert "Waiting on my manager to approve leave" in told[0].evidence


def test_prepared_work_still_waiting_on_the_user_is_remembered(graph, clock):
    brief = a_brief(graph, clock)
    brief.prepared.append(PreparedAction(kind="nothing", summary="Nothing needed preparing."))

    waiting = [item for item in memory_for(graph, clock, brief=brief).items if item.kind == "waiting_on_you"]

    assert [item.what for item in waiting] == [LEAVE_DRAFT.summary]
    assert waiting[0].evidence == "On today's brief. A draft is waiting in Gmail (draft-0001): read it and press send."


# -- the calendar ------------------------------------------------------------


def test_the_calendar_leaves_seconds_own_blocks_to_the_schedule(graph, clock):
    """The recording is already in today's plan; the Eng sync is not, and it takes 18:00."""
    memory = memory_for(graph, clock)
    events = [item for item in memory.items if item.source == "calendar"]

    assert [item.what for item in events] == ["Eng sync"]
    assert events[0].kind == "event"
    assert events[0].at == clock.local(datetime(2026, 9, 10, 18, 0))
    assert events[0].evidence == (
        "Calendar: “Eng sync”, 18:00 to 19:00, 9 attendees, organised by someone else."
    )

    reason = status(memory, "calendar").reason
    assert "Read 4 events" in reason
    assert "1 already listed from today's plan" in reason
    assert "1 cancelled" in reason and "1 declined" in reason


def test_a_calendar_that_cannot_be_read_is_not_connected_and_the_graph_still_speaks(graph, clock):
    """Failure direction: lose the calendar, keep the tab.

    Mutation-tested: removing the per-source ``except Exception`` in ``collect_memory`` makes the
    whole read raise, and this fails.
    """

    def no_credentials(start, end):
        raise GoogleCredentialsMissing("no runtime Google token at 'token.json'")

    memory = memory_for(graph, clock, read=no_credentials)

    calendar_status = status(memory, "calendar")
    assert calendar_status.connected is False
    assert "GoogleCredentialsMissing" in calendar_status.reason
    assert "token" in calendar_status.reason

    assert status(memory, "graph").connected is True
    assert [item for item in memory.items if item.source == "graph"], "the graph still has things to say"


def test_an_empty_calendar_reads_as_read_not_as_broken(graph, clock):
    memory = memory_for(graph, clock, read=calendar([]))

    assert status(memory, "calendar").connected is True
    assert "nothing in it" in status(memory, "calendar").reason


def test_the_fake_calendar_reader_is_the_fake_connector():
    """The demo calendar holds three weeks of history and nothing on the demo day itself.

    Pinned because it decides what the memory fixture can show: with the fake connector, today's
    calendar is honestly empty.
    """
    today_start, today_end = Clock.fixed(TODAY, zone_name=TZ).window()
    yesterday_start, _ = Clock.fixed(date(2026, 9, 9), zone_name=TZ).window()

    assert read_fake_calendar(today_start, today_end) == []
    assert "Eng sync" in {event["title"] for event in read_fake_calendar(yesterday_start, today_start)}


# -- email -------------------------------------------------------------------


def test_no_morning_run_yet_is_connected_and_empty_not_disconnected(graph, clock):
    """The screen said the inbox was not connected when the morning run simply had not happened.

    Mutation-tested: raising ``SourceUnavailable`` again when there is no brief makes this fail.
    """
    without = memory_for(graph, clock)

    email = status(without, "email")
    assert (email.connected, email.items, email.reason) == (
        True,
        0,
        "The morning run has not read your email yet today.",
    )
    assert not [item for item in without.items if item.source == "email"]


def test_a_morning_run_that_could_not_judge_leaves_email_not_connected(graph, clock):
    """connected:false is kept for a read that failed: here the run happened and produced no judgement."""
    brief = assemble(graph=graph, clock=clock, judgement=None)

    email = status(memory_for(graph, clock, brief=brief), "email")

    assert email.connected is False
    assert "could not finish reading your email" in email.reason


def test_a_quiet_morning_run_says_it_found_nothing(graph, clock):
    brief = assemble(graph=graph, clock=clock, judgement=BriefJudgement(notify=False, silence_reason="Quiet."))

    email = status(memory_for(graph, clock, brief=brief), "email")

    assert (email.connected, email.items) == (True, 0)
    assert email.reason == "The morning run read your email today and found nothing to remind you of."


def test_nothing_a_user_reads_uses_internal_words_or_repr_quotes(graph, clock):
    graph.task_by_id("t-flights").known_blocker = "Waiting on my manager"
    brief = a_brief(graph, clock)
    brief.prepared = [LEAVE_DRAFT_FOR_T_LEAVE]

    memory = memory_for(graph, clock, brief=brief)

    texts = [text for item in memory.items for text in (item.what, item.evidence)]
    texts += [source.reason for source in memory.sources]
    for text in texts:
        for jargon in ("rung", "intake", "Living Graph", "person layer", "email_draft", "day(s)"):
            assert jargon not in text, f"{jargon!r} in {text!r}"
        assert "'" not in text.replace("'s ", " ").replace("n't", ""), f"repr quotes in {text!r}"


def test_email_reminders_come_only_from_the_cached_brief(graph, clock):
    without = memory_for(graph, clock)
    assert not [item for item in without.items if item.source == "email"]

    with_brief = memory_for(graph, clock, brief=a_brief(graph, clock))
    emails = [item for item in with_brief.items if item.source == "email"]
    assert status(with_brief, "email").connected is True
    assert [(item.what, item.evidence, item.kind) for item in emails] == [
        (WEDDING.what, WEDDING.evidence, "reminder")
    ]


def test_an_unsupported_reminder_is_counted_out_loud_not_hidden(graph, clock):
    brief = a_brief(graph, clock)
    brief.reminders.append(Reminder(what="Reply to someone", evidence="", source="email"))

    memory = memory_for(graph, clock, brief=brief)

    assert len([item for item in memory.items if item.source == "email"]) == 1
    assert "1 reminder cited no evidence" in status(memory, "email").reason


# -- the seam ----------------------------------------------------------------


def test_every_registered_source_is_listed_with_a_reason(graph, clock):
    memory = memory_for(graph, clock)

    assert [source.name for source in memory.sources] == ["graph", "calendar", "email"]
    assert all(source.reason.strip() for source in memory.sources)


def test_a_new_source_is_one_class(graph, clock):
    """What a future Slack or notes source looks like, and what happens when it cannot connect."""

    class Notes:
        name = "notes"

        def collect(self, context):
            raise SourceUnavailable("Notes is not connected yet.")

    class Pinned:
        name = "pinned"

        def collect(self, context):
            return Collected(
                items=[MemoryItem(what="Call the venue", evidence="Pinned by you", source="graph", kind="told_second")],
                note="One pinned note.",
            )

    memory = memory_for(graph, clock, sources=[Notes(), Pinned()])

    assert [(source.name, source.connected, source.reason) for source in memory.sources] == [
        ("notes", False, "Notes is not connected yet."),
        ("pinned", True, "One pinned note."),
    ]
    assert [item.what for item in memory.items] == ["Call the venue"]
