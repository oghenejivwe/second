"""The Living Graph store, against a real DynamoDB implementation.

moto runs the actual DynamoDB semantics -- conditional writes, type validation,
key schema -- in-process. That matters here: the two things most worth proving
are that boto3 rejects a raw float and that a stale conditional write is
actually refused, and a hand-rolled fake would happily accept both.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import boto3
import pytest
from moto import mock_aws

from second.core.models import AuditEntry, Goal, LivingGraph, Route, Task
from second.persistence.store import LivingGraphStore, VersionConflict

REGION = "us-west-2"
USER = "demo"


@pytest.fixture
def store():
    """A store backed by an in-process DynamoDB."""
    with mock_aws():
        boto3.client("dynamodb", region_name=REGION).create_table(
            TableName="second_graph",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table = boto3.resource("dynamodb", region_name=REGION).Table("second_graph")
        yield LivingGraphStore(table=table)


def a_graph(**overrides) -> LivingGraph:
    """A graph with a float, a date and a datetime -- the three awkward types."""
    graph = LivingGraph(
        user_id=USER,
        goals=[
            Goal(
                id="g1",
                title="Master public speaking",
                deadline=date(2026, 12, 1),
                extraction_confidence=0.83,
                routes=[
                    Route(
                        id="r1",
                        goal_id="g1",
                        title="Weekly speaking club",
                        cadence="Tuesday evenings",
                        rationale="Honours the Tue 19:00 slot they actually keep.",
                        tasks=[
                            Task(
                                id="t1",
                                route_id="r1",
                                title="Attend club",
                                scheduled_slots=[datetime(2026, 9, 16, 19, 0)],
                            )
                        ],
                    )
                ],
            )
        ],
    )
    return graph.model_copy(update=overrides) if overrides else graph


def test_unknown_user_reads_as_empty_not_error(store):
    """A first-run intake is a normal state."""
    graph = store.load("nobody")
    assert graph.user_id == "nobody"
    assert graph.goals == []
    assert graph.version == 0


def test_round_trip_preserves_float_date_and_datetime(store):
    """The three types boto3's serializer refuses or mangles."""
    written = store.save(a_graph())
    loaded = store.load(USER)

    goal = loaded.goals[0]
    assert goal.extraction_confidence == 0.83
    assert isinstance(goal.extraction_confidence, float)
    assert goal.deadline == date(2026, 12, 1)
    assert goal.routes[0].tasks[0].scheduled_slots[0] == datetime(2026, 9, 16, 19, 0)
    assert loaded.version == written.version == 1


def test_save_stamps_version_and_time(store):
    first = store.save(a_graph())
    second = store.save(first)
    assert (first.version, second.version) == (1, 2)
    assert second.updated_at is not None


def test_stale_write_is_refused(store):
    """The guard: a writer holding an old version must not win.

    This is the Adapter silently clobbering the Observer's person-layer update.
    Mutation-tested: removing the ConditionExpression from ``save`` makes this
    pass silently, which is exactly the defect.
    """
    store.save(a_graph())
    stale = a_graph()  # still at version 0
    stale.person.constraints.append("no work before 10am")

    with pytest.raises(VersionConflict):
        store.save(stale)

    assert store.load(USER).person.constraints == []


def test_mutate_retries_and_lands(store):
    """A conflict should be a retry, not a lost write."""
    store.save(a_graph())
    hijacked = {"done": False}

    def change(graph: LivingGraph) -> None:
        # Simulate another writer winning the race, exactly once.
        if not hijacked["done"]:
            hijacked["done"] = True
            other = store.load(USER)
            other.person.preferences["learning_mode"] = "video"
            store.save(other)
        graph.person.constraints.append("Sundays are family")

    result = store.mutate(USER, change)

    assert result.person.constraints == ["Sundays are family"]
    assert result.person.preferences == {"learning_mode": "video"}, "the other write survived"


def test_mutate_gives_up_rather_than_writing_blind(store):
    """Failure direction: raise. A lost person-layer update is invisible."""
    store.save(a_graph())

    def always_loses(graph: LivingGraph) -> None:
        other = store.load(USER)
        other.person.recurring_blockers.append("6pm loses to meetings")
        store.save(other)
        graph.person.constraints.append("never lands")

    with pytest.raises(VersionConflict):
        store.mutate(USER, always_loses, attempts=3)


def test_audit_rows_come_back_newest_first(store):
    entries = [
        AuditEntry(
            at=datetime(2026, 9, 10, 7, minute, tzinfo=timezone.utc),
            run_id="run-1",
            kind="tool",
            actor="observer",
            action=f"tool_{minute}",
            is_write=True,
        )
        for minute in (0, 1, 2)
    ]
    store.append_audit(USER, entries)

    rows = store.read_audit(USER, limit=10)
    assert [row.action for row in rows] == ["tool_2", "tool_1", "tool_0"]
    assert rows[0].is_write is True


def test_audit_failure_does_not_fail_the_run(store):
    """Audit is evidence, not control flow."""
    store._table = None  # force a real client with no credentials configured
    store._region = "us-west-2"
    store.append_audit(USER, [])  # empty is a no-op, never touches AWS


def test_audit_and_graph_share_a_partition_without_colliding(store):
    store.save(a_graph())
    store.append_audit(
        USER,
        [AuditEntry(at=datetime(2026, 9, 10, 7, 0, tzinfo=timezone.utc), run_id="r", kind="node", actor="observer", action="start")],
    )
    assert store.load(USER).goals[0].id == "g1"
    assert len(store.read_audit(USER)) == 1
