"""The fixture generator's own guards, checked without running the generator.

The generator stops rather than write a fixture that contradicts the world it came from. A guard
that never fires is indistinguishable from one that cannot, so these make each one fire.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from second.core.models import Goal
from second.graphs.schedule import build_schedule
from second.testing import demo_scenario

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "web" / "scripts" / "make_fixtures.py"


@pytest.fixture(scope="module")
def generator():
    spec = importlib.util.spec_from_file_location("make_fixtures", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def with_week_goal(generator, **task_titles):
    """The seeded graph, and the same graph with the week answer's goal added."""
    before = demo_scenario.living_graph()
    after = before.model_copy(deep=True)
    week = generator.lisbon_week_goal(placed=True)
    for task in week["routes"][0]["tasks"]:
        task["title"] = task_titles.get(task["id"], task["title"])
    after.goals.append(Goal.model_validate(week))
    return before, after


def test_the_week_answer_adds_only_new_work(generator):
    before, after = with_week_goal(generator)

    generator.assert_no_duplicate_tasks(before, after)


@pytest.mark.parametrize(
    "title",
    [
        "Book flights to Lisbon",
        "Book the flights to Lisbon",
        "request leave for the wedding week",
    ],
)
def test_a_new_task_that_repeats_an_existing_one_stops_the_generator(generator, title):
    """"Book the flights to Lisbon" beside "Book flights to Lisbon" is what the last answer fixture did.

    Mutation-tested: emptying the assertion in ``assert_no_duplicate_tasks`` lets these through and
    this fails.
    """
    before, after = with_week_goal(generator, **{"t-lisbon-hotel": title})

    with pytest.raises(AssertionError, match="duplicates"):
        generator.assert_no_duplicate_tasks(before, after)


def test_the_week_slots_respect_the_seeded_world(generator):
    """The generator runs the same check against the world after the morning run."""
    generator.assert_the_week_slots_are_honest(demo_scenario.living_graph())


def test_a_week_slot_on_top_of_a_placed_block_stops_the_generator(generator):
    graph = demo_scenario.living_graph()
    graph.task_by_id("t-gym").scheduled_slots.append(generator.HOTEL_SLOT)

    with pytest.raises(AssertionError, match="overlaps Gym session"):
        generator.assert_the_week_slots_are_honest(graph)


def test_the_graph_and_the_schedule_agree_about_the_gym_in_the_seeded_world(generator):
    graph = demo_scenario.living_graph()
    schedule = build_schedule(graph, generator.fixed_clock())

    generator.assert_one_gym("seeded", graph, schedule)


def test_a_graph_from_another_run_stops_the_generator(generator):
    """A graph whose gym moved to 07:00 beside a schedule still at 18:00 is two worlds on one screen.

    Mutation-tested: emptying the comparison in ``assert_one_gym`` lets this through and this fails.
    """
    graph = demo_scenario.living_graph()
    schedule = build_schedule(graph, generator.fixed_clock())
    gym = graph.task_by_id("t-gym")
    gym.scheduled_slots = [
        slot.replace(hour=7) if slot.date() == generator.TODAY else slot for slot in gym.scheduled_slots
    ]

    with pytest.raises(AssertionError, match="disagree about the gym"):
        generator.assert_one_gym("moved", graph, schedule)


def test_the_answer_and_the_frontend_quote_the_same_sentence(generator):
    """weekAnswer.ts, the browser's one copy of the sentence the answer fixture was generated from, matches."""
    assert generator.WEEK_ANSWER == "Confirm the hotel and buy travel insurance by Saturday 19 September."
    shared = (ROOT / "web" / "src" / "api" / "weekAnswer.ts").read_text(encoding="utf-8")
    assert f"'{generator.WEEK_ANSWER}'" in shared
