"""Putting the demo world into a real table, and refusing to destroy one.

``demo_scenario.living_graph()`` had three callers: the tests, ``live_daily.py``
under ``moto``, and nothing else. ``bootstrap_aws.py`` creates the table and
leaves it empty, and ``LivingGraphStore.load`` returns an empty graph for an
unknown user rather than raising -- so a real deployment came up clean, served a
day with nothing in it, and never said why.

The danger in fixing that is the obvious one: a seeder that overwrites is a
seeder that can delete a graph holding slip history nothing can reconstruct.
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from second.persistence.store import LivingGraphStore
from second.settings import AWS_REGION, TABLE_NAME
from second.testing import demo_scenario

from scripts import seed_graph


@pytest.fixture
def aws():
    """A real table with nothing in it, under moto."""
    with mock_aws():
        LivingGraphStore(table_name=TABLE_NAME, region=AWS_REGION).ensure_table()
        yield boto3.resource("dynamodb", region_name=AWS_REGION).Table(TABLE_NAME)


def stored() -> object:
    return LivingGraphStore(table_name=TABLE_NAME, region=AWS_REGION).load(demo_scenario.USER_ID)


def tasks_of(graph) -> dict:
    return {t.id: t for g in graph.goals for r in g.routes for t in r.tasks}


# -- the gap this closes -----------------------------------------------------


def test_a_dry_run_writes_nothing(aws):
    """The default is report-only. A seeder whose default is 'write' is one that
    gets run by accident against the wrong table."""
    assert seed_graph.main([]) == 0

    assert stored().goals == []


def test_applying_puts_the_whole_world_in_the_table(aws):
    assert seed_graph.main(["--apply"]) == 0

    graph = stored()
    expected = demo_scenario.living_graph()
    assert len(graph.goals) == len(expected.goals)
    assert tasks_of(graph).keys() == tasks_of(expected).keys()


def test_the_slip_history_survives_the_round_trip(aws):
    """The reason the script reads back rather than trusting the write.

    The store round-trips through DynamoDB's Decimal types. A field that
    serialises but does not deserialise would otherwise surface much later,
    inside an agent, as a task that mysteriously has no history.
    """
    seed_graph.main(["--apply"])

    written = tasks_of(demo_scenario.living_graph())
    read = tasks_of(stored())
    for task_id, task in written.items():
        assert len(read[task_id].slips) == len(task.slips), task_id
        assert read[task_id].slip_count == task.slip_count, task_id
        assert read[task_id].scheduled_slots == task.scheduled_slots, task_id


def test_the_person_layer_survives_too(aws):
    """abandoned_slots is what stops the Adapter proposing a time already proven
    not to work. An empty one reads as "never tried", which is a different world."""
    seed_graph.main(["--apply"])

    person = stored().person
    assert person.abandoned_slots == demo_scenario.living_graph().person.abandoned_slots
    assert person.constraints == demo_scenario.living_graph().person.constraints


# -- refusing to destroy anything -------------------------------------------


def test_it_will_not_overwrite_an_existing_graph(aws):
    """Slip history cannot be reconstructed. Overwriting it silently would
    destroy the evidence every later diagnosis is built on."""
    seed_graph.main(["--apply"])
    before = stored()

    assert seed_graph.main(["--apply"]) == 1, "a second --apply must refuse"

    after = stored()
    assert after.version == before.version, "the refused run must not have written"


def test_replace_is_the_deliberate_way_through(aws):
    seed_graph.main(["--apply"])
    before = stored()

    assert seed_graph.main(["--apply", "--replace"]) == 0

    after = stored()
    assert after.version == before.version + 1
    assert len(after.goals) == len(demo_scenario.living_graph().goals)


def test_replacing_beats_the_optimistic_lock_rather_than_disabling_it(aws):
    """A fresh graph is version 0, which only matches an empty slot. Replacing
    adopts the stored version so the lock still holds -- it is not bypassed, and
    a concurrent writer still loses."""
    seed_graph.main(["--apply"])
    store = LivingGraphStore(table_name=TABLE_NAME, region=AWS_REGION)

    # Somebody else writes between our read and our write.
    meddled = store.load(demo_scenario.USER_ID)
    meddled.person.constraints.append("added by somebody else")
    theirs = store.save(meddled)

    assert seed_graph.main(["--apply", "--replace"]) == 0

    # Built on THEIR version, not the one the seeder first read. Adopting a stale
    # version would have raised VersionConflict, which is the lock doing its job.
    assert stored().version == theirs.version + 1


def test_a_missing_table_is_reported_not_raised():
    """First run, before bootstrap_aws.py. It should say which script to run."""
    with mock_aws():
        assert seed_graph.main(["--apply"]) == 1


# -- the census --------------------------------------------------------------


def test_the_report_counts_what_is_actually_there():
    """The printed census is how an operator decides whether to type --apply, so
    it has to be derived rather than written down."""
    graph = demo_scenario.living_graph()
    lines = "\n".join(seed_graph.describe(graph))

    routes = sum(len(g.routes) for g in graph.goals)
    slips = sum(len(t.slips) for t in tasks_of(graph).values())
    assert f"goals            {len(graph.goals)}" in lines
    assert f"routes           {routes}" in lines
    assert f"tasks            {len(tasks_of(graph))}" in lines
    assert f"slip records     {slips}" in lines


def test_a_damaged_round_trip_is_caught_by_the_script_itself(aws, monkeypatch):
    """The script must verify against what came BACK, not what it sent.

    Every other test here reads the store independently, so all of them passed
    when the read-back was mutated to reuse the in-memory graph -- the
    verification block was dead code that looked like a safety net. This makes
    the store hand back a damaged graph and requires the script to notice.
    """
    real = LivingGraphStore(table_name=TABLE_NAME, region=AWS_REGION)
    loads = {"count": 0}

    class DropsSlipsOnTheWayBack:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def load(self, user_id):
            loads["count"] += 1
            graph = real.load(user_id)
            if loads["count"] > 1:  # the post-write read
                for goal in graph.goals:
                    for route in goal.routes:
                        for task in route.tasks:
                            task.slips = []
            return graph

        def save(self, graph):
            return real.save(graph)

    monkeypatch.setattr(seed_graph, "LivingGraphStore", DropsSlipsOnTheWayBack)

    assert seed_graph.main(["--apply"]) == 1, "a graph that came back damaged must fail the run"


def test_a_clean_round_trip_through_the_same_seam_passes(aws, monkeypatch):
    """The control for the test above: same interception, nothing damaged."""
    real = LivingGraphStore(table_name=TABLE_NAME, region=AWS_REGION)

    class Passthrough:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def load(self, user_id):
            return real.load(user_id)

        def save(self, graph):
            return real.save(graph)

    monkeypatch.setattr(seed_graph, "LivingGraphStore", Passthrough)

    assert seed_graph.main(["--apply"]) == 0
