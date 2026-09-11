"""The daily brief: computed facts, plus the model's judgement.

Today's schedule is a fact already in the Living Graph. Asking a model to list it
invites it to invent a block, and one imaginary meeting costs the user their
trust in the other five. So these tests pin the arithmetic.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from second.core.clock import Clock
from second.core.models import (
    BriefJudgement,
    Decision,
    Goal,
    LivingGraph,
    PreparedAction,
    Reminder,
    Route,
    Task,
)
from second.graphs.brief import assemble, deadline_risks, todays_blocks
from second.testing import demo_scenario

TZ = "Europe/London"
TODAY = date(2026, 9, 10)


@pytest.fixture
def clock() -> Clock:
    return Clock.fixed(TODAY, zone_name=TZ)


@pytest.fixture
def graph() -> LivingGraph:
    return demo_scenario.living_graph()


# -- the schedule -----------------------------------------------------------


def test_only_todays_slots_appear(graph, clock):
    blocks = todays_blocks(graph, clock)
    assert blocks, "the seeded world has work today"
    assert all(block.start.date() == TODAY for block in blocks)


def test_a_block_carries_the_whole_ladder_up_to_the_ambition(graph, clock):
    """The day has to answer 'why this, today?' without following ids."""
    block = next(block for block in todays_blocks(graph, clock) if block.task_id == "t-recording")

    assert block.goal_title == "Get comfortable speaking to a room"
    assert block.serves == ["Raise a Series A", "Build a company that outlives me"]
    assert block.horizon == "year"


def test_blocks_come_back_in_time_order(graph, clock):
    graph.goals[3].routes[0].tasks[0].scheduled_slots.append(datetime(2026, 9, 10, 6, 0))
    blocks = todays_blocks(graph, clock)
    assert [block.start for block in blocks] == sorted(block.start for block in blocks)


def test_retiring_a_goal_frees_its_time(graph, clock):
    """The Goals screen claims retiring redistributes time. This is why it can."""
    before = len(todays_blocks(graph, clock))
    assert before > 0

    speaking = graph.goal_by_id("g-speaking")
    speaking.status = "retired"

    assert len(todays_blocks(graph, clock)) < before


def test_completed_work_does_not_reappear(graph, clock):
    task = graph.task_by_id("t-recording")
    task.status = "done"
    assert not any(block.task_id == "t-recording" for block in todays_blocks(graph, clock))


# -- deadline risk ----------------------------------------------------------


def test_a_deadline_with_nothing_booked_is_at_risk(graph, clock):
    risks = {risk.task_id: risk for risk in deadline_risks(graph, clock)}
    assert "t-leave" in risks
    assert "nothing booked" in risks["t-leave"].evidence
    assert risks["t-leave"].days_left == 5


def test_a_blocked_task_names_what_is_blocking_it(graph, clock):
    """UNMET_DEPENDENCY, surfaced as a fact rather than a diagnosis."""
    graph.task_by_id("t-flights").status = "blocked"

    risk = next(risk for risk in deadline_risks(graph, clock) if risk.task_id == "t-flights")
    assert "Request leave for the wedding week" in risk.evidence


def test_a_distant_deadline_is_not_todays_problem(graph, clock):
    task = graph.task_by_id("t-leave")
    task.deadline = TODAY + timedelta(days=90)
    assert not any(risk.task_id == "t-leave" for risk in deadline_risks(graph, clock))


def test_risks_are_ordered_by_urgency(graph, clock):
    risks = deadline_risks(graph, clock)
    assert [risk.days_left for risk in risks] == sorted(risk.days_left for risk in risks)


def test_work_with_a_slot_booked_in_time_is_not_flagged(graph, clock):
    task = graph.task_by_id("t-leave")
    task.scheduled_slots = [datetime(2026, 9, 11, 10, 0)]
    assert not any(risk.task_id == "t-leave" for risk in deadline_risks(graph, clock))


# -- assembly ---------------------------------------------------------------


def test_a_missing_judgement_still_shows_the_day(graph, clock):
    """Failure direction: still show the day.

    The schedule came from the graph and is true whether or not the Communicator
    managed to produce a typed result. A user who opens the app to an error
    learns not to open the app.
    """
    brief = assemble(graph=graph, clock=clock, judgement=None)

    assert brief.blocks, "the schedule survives a failed judgement"
    assert brief.at_risk
    assert brief.notify is False
    assert brief.silence_reason


def test_a_decision_forces_a_notification_whatever_the_model_said(graph, clock):
    """It cannot talk itself out of telling the user it is waiting on them.

    Mutation-tested: dropping the `or bool(judgement.decisions)` clause in
    assemble() makes this pass silently, which is a question the user never sees.
    """
    judgement = BriefJudgement(
        decisions=[Decision(question="Move the gym to 07:00?", evidence="lost 4 of 5 days")],
        notify=False,
        silence_reason="I decided this was not worth mentioning",
    )
    brief = assemble(graph=graph, clock=clock, judgement=judgement)
    assert brief.notify is True
    assert brief.is_quiet is False


def test_prepared_work_forces_a_notification(graph, clock):
    """If Second did work for you, you get told. That is the whole promise."""
    prepared = [
        PreparedAction(
            kind="email_draft",
            summary="Leave request for the wedding week",
            awaiting="Read it and press send.",
        )
    ]
    brief = assemble(graph=graph, clock=clock, judgement=BriefJudgement(notify=False), prepared=prepared)
    assert brief.notify is True


def test_a_genuinely_quiet_day_stays_quiet(graph, clock):
    judgement = BriefJudgement(notify=False, silence_reason="Nothing slipped, nothing needs deciding.")
    brief = assemble(graph=graph, clock=clock, judgement=judgement)

    assert brief.is_quiet
    assert brief.blocks, "quiet does not mean empty -- the day is still there"
    assert brief.silence_reason


def test_reminders_carry_their_source(graph, clock):
    """A reminder with no evidence is a nag, and this product does not nag."""
    judgement = BriefJudgement(
        reminders=[
            Reminder(
                what="Your sister asked whether the flights are booked. You never replied.",
                evidence="m-wedding, 'Wedding week - are you booked yet?'",
                source="email",
            )
        ],
        notify=True,
    )
    brief = assemble(graph=graph, clock=clock, judgement=judgement)
    assert brief.reminders[0].evidence
    assert brief.reminders[0].source == "email"


# -- the ladder -------------------------------------------------------------


def test_an_ambition_with_no_children_and_no_routes_is_stalled():
    graph = LivingGraph(
        user_id="demo",
        goals=[Goal(id="g1", title="Build something that outlives me", horizon="life")],
    )
    assert [goal.id for goal in graph.stalled_ambitions()] == ["g1"]


def test_one_rung_of_cascading_is_not_enough():
    """The ladder has to reach something workable, not just get shorter.

    A life goal decomposed into a three-year goal is progress and it is not
    done -- three years is still not a horizon that holds a calendar slot. The
    Cascader keeps walking until something lands at a year or nearer.
    """
    graph = LivingGraph(
        user_id="demo",
        goals=[
            Goal(id="g1", title="Build something that outlives me", horizon="life"),
            Goal(id="g2", title="Raise a Series A", horizon="three_year", contributes_to="g1"),
        ],
    )
    assert [goal.id for goal in graph.stalled_ambitions()] == ["g2"], (
        "g1 is served; g2 is now the one with nothing under it"
    )


def test_a_ladder_that_reaches_a_workable_horizon_is_done():
    graph = LivingGraph(
        user_id="demo",
        goals=[
            Goal(id="g1", title="Build something that outlives me", horizon="life"),
            Goal(id="g2", title="Raise a Series A", horizon="three_year", contributes_to="g1"),
            Goal(id="g3", title="Get to $1M ARR", horizon="year", contributes_to="g2"),
        ],
    )
    assert graph.stalled_ambitions() == []
    assert [goal.title for goal in graph.ladder("g3")] == [
        "Get to $1M ARR",
        "Raise a Series A",
        "Build something that outlives me",
    ]


def test_a_year_goal_can_hold_work_without_being_decomposed():
    """A yearly goal with a weekly cadence needs no further laddering."""
    goal = Goal(id="g1", title="Speak well", horizon="year")
    assert goal.is_schedulable
    assert not Goal(id="g2", title="Outlive me", horizon="life").is_schedulable


def test_a_broken_parent_link_is_reported_separately_from_a_stalled_one():
    graph = LivingGraph(
        user_id="demo",
        goals=[Goal(id="g2", title="Orphan", horizon="year", contributes_to="missing")],
    )
    assert [goal.id for goal in graph.broken_links()] == ["g2"]
    assert graph.stalled_ambitions() == []


def test_a_cycle_in_the_ladder_does_not_hang_the_day():
    """Failure direction: a short chain, not no day."""
    graph = LivingGraph(
        user_id="demo",
        goals=[
            Goal(id="a", title="A", horizon="year", contributes_to="b"),
            Goal(id="b", title="B", horizon="decade", contributes_to="a"),
        ],
    )
    assert [goal.id for goal in graph.ladder("a")] == ["a", "b"]


# -- no evidence, no diagnosis ----------------------------------------------


def test_a_diagnosis_with_no_evidence_is_downgraded_to_unknown():
    """The rule forced tool choice would otherwise remove.

    Strands forces the tool call, so on the re-ask a model cannot decline. If
    `evidence` were required and non-nullable it would have to write something --
    and the cheapest something is an invented quote attached to a confident
    conclusion. The schema gives it somewhere honest to land instead.
    """
    from second.core.models import Diagnosis

    d = Diagnosis(
        task_id="t-recording",
        blocker_type="CALENDAR_CONFLICT",
        evidence=None,
        confidence=0.95,
        proposed_action="Move it to the morning.",
        requires_user_decision=False,
    )

    assert d.blocker_type == "UNKNOWN", "a claim with nothing behind it is not a claim"
    assert d.confidence <= 0.3
    assert d.requires_user_decision is True


def test_whitespace_is_not_evidence():
    from second.core.models import Diagnosis

    d = Diagnosis(
        task_id="t1", blocker_type="UNMET_DEPENDENCY", evidence="   ",
        confidence=0.9, proposed_action="do the other one first",
        requires_user_decision=False,
    )
    assert d.blocker_type == "UNKNOWN"


def test_real_evidence_is_left_alone():
    from second.core.models import Diagnosis

    d = Diagnosis(
        task_id="t-gym",
        blocker_type="CALENDAR_CONFLICT",
        evidence="18:00 gym declined 4 of 5 weekdays; each collided with 'Eng sync'.",
        confidence=0.92,
        proposed_action="Move the block to 07:00.",
        requires_user_decision=False,
    )
    assert d.blocker_type == "CALENDAR_CONFLICT"
    assert d.confidence == 0.92
    assert d.requires_user_decision is False


def test_an_evidenceless_diagnosis_routes_to_asking():
    """End to end: the coercion reaches the conditional edge."""
    from second.core.models import Diagnosis
    from second.graphs.conditions import can_act_alone, needs_user_decision

    class _State:
        results = {}

    d = Diagnosis(
        task_id="t1", blocker_type="CALENDAR_CONFLICT", evidence=None,
        confidence=0.99, proposed_action="x", requires_user_decision=False,
    )

    class _Node:
        result = type("R", (), {"structured_output": d})()

    state = _State()
    state.results = {"diagnostician": _Node()}

    assert needs_user_decision(state) is True
    assert can_act_alone(state) is False


# -- retiring a goal --------------------------------------------------------


def test_retiring_reports_the_slots_it_freed(store, today):
    """SURFACES may not compute a plan in the client, so give it the data.

    A schedule Second did not make is a schedule Second cannot stand behind.
    """
    from second.graphs import service

    result = service.set_goal_status("demo", "g-speaking", "retired", today=today)

    assert result.freed, "the goal was holding upcoming slots"
    assert result.freed_minutes == sum(b.duration_min for b in result.freed)
    assert all(b.goal_id == "g-speaking" for b in result.freed)
    assert result.graph.goal_by_id("g-speaking").status == "retired"


def test_it_says_freed_not_redistributed(store, today):
    """The Scheduler has not run. Claiming a reallocation would be fiction."""
    from second.graphs import service

    note = service.set_goal_status("demo", "g-speaking", "retired", today=today).note
    assert "free" in note.lower()
    assert "next daily run" in note.lower(), "it says WHEN the reallocation happens"


def test_reactivating_frees_nothing(store, today):
    from second.graphs import service

    service.set_goal_status("demo", "g-speaking", "retired", today=today)
    result = service.set_goal_status("demo", "g-speaking", "active", today=today)

    assert result.freed == []
    assert result.graph.goal_by_id("g-speaking").status == "active"


def test_retiring_a_goal_that_holds_nothing_says_so(store, today):
    from second.graphs import service

    result = service.set_goal_status("demo", "g-company", "paused", today=today)
    assert result.freed == []
    assert "no upcoming slots" in result.note


def test_an_unknown_goal_raises_rather_than_silently_doing_nothing(store, today):
    from second.graphs import service

    with pytest.raises(ValueError):
        service.set_goal_status("demo", "g-nope", "retired", today=today)


def test_the_preparer_having_nothing_to_do_does_not_force_a_notification(graph, clock):
    """The quiet day the product promises, now reachable on the autonomous path.

    Forced tool choice means the Preparer cannot decline to emit. Without a
    "nothing" value it always returned something, so assemble() always saw
    prepared work and always notified -- and "the Adapter fixed it, nothing needs
    you" could never happen. AGENTS found it.
    """
    from second.core.models import BriefJudgement, PreparedAction

    nothing = PreparedAction(kind="nothing", summary="Nothing needed carrying today.")
    brief = assemble(
        graph=graph,
        clock=clock,
        judgement=BriefJudgement(notify=False, silence_reason="The gym moved itself. Nothing needs you."),
        prepared=[nothing],
    )

    assert brief.is_quiet, "an autonomous day with nothing prepared is a quiet day"
    assert brief.prepared == [], "'nothing' is not prepared work"
    assert brief.blocks, "quiet still shows the day"


def test_real_prepared_work_still_notifies(graph, clock):
    from second.core.models import BriefJudgement, PreparedAction

    draft = PreparedAction(
        kind="email_draft", summary="Leave request drafted.", awaiting="Read it and press send."
    )
    brief = assemble(graph=graph, clock=clock, judgement=BriefJudgement(notify=False), prepared=[draft])
    assert brief.notify is True
    assert len(brief.prepared) == 1


# -- reading the day is free ------------------------------------------------


def test_reading_the_day_does_not_run_the_graph(store, today):
    """GET /api/today used to invoke five agents. SURFACES found it.

    Nothing here touches a model: if there is no cached brief the day is
    assembled from the Living Graph alone, because the schedule and the deadline
    risks are facts and cost nothing.
    """
    from second.graphs import service

    brief = service.get_today("demo", today)

    assert brief.blocks, "the schedule is there without a model call"
    assert brief.at_risk
    assert brief.decisions == [], "the judgement-shaped parts are absent, not invented"
    assert brief.notify is False


def test_a_computed_brief_comes_back_as_it_was(store, today):
    """What run_daily produced is what a later read returns."""
    from second.core.models import BriefJudgement, Decision
    from second.graphs.brief import assemble
    from second.graphs import service

    computed = assemble(
        graph=store.load("demo"),
        clock=Clock.fixed(today, zone_name=TZ),
        judgement=BriefJudgement(
            decisions=[Decision(question="Move the gym to 07:00?", evidence="lost 4 of 5 days")],
            notify=True,
        ),
    )
    store.save_brief("demo", computed)

    read_back = service.get_today("demo", today)
    assert read_back.notify is True
    assert read_back.decisions[0].question == "Move the gym to 07:00?"
    assert len(read_back.blocks) == len(computed.blocks)


def test_the_status_route_reads_config_rather_than_asserting_it(store):
    """SURFACES refused to hardcode a model claim. This is why they were right."""
    from second.graphs import service

    status = service.runtime_status()
    assert status["provider"] in ("anthropic", "bedrock")
    assert status["model"], "the model is read, not written down"
    assert status["timezone_source"] in ("explicit", "calendar", "system", "utc")
    assert isinstance(status["timezone_trustworthy"], bool)
