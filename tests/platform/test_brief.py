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
