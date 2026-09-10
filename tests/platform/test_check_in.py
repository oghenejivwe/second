"""The daily reconciliation: what actually happened, from the only source that knows.

Second can infer a lot from a calendar and an inbox. It cannot infer whether
somebody did a five-minute recording, because nothing anywhere records that. So
it asks -- and it asks having already done the work, with its best guess and the
evidence attached, so the answer is one tap rather than an act of memory.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import boto3
import pytest
from moto import mock_aws
from strands import Agent

from second.core.clock import Clock
from second.core.deps import AgentDeps
from second.core.models import LivingGraph, Observation, ObservationReport
from second.graphs.brief import assemble, build_check_in
from second.graphs.composition import AgentSpec, ToolRegistry
from second.graphs.daily import build_daily_graph
from second.persistence.store import LivingGraphStore
from second.testing import demo_scenario
from second.testing.scripted_model import ScriptedModel, Text, ToolUse
from second.tools.graph_tools import ALL_GRAPH_TOOLS

TZ = "Europe/London"
TODAY = demo_scenario.TODAY
YESTERDAY = TODAY - timedelta(days=1)
USER = demo_scenario.USER_ID


@pytest.fixture
def clock() -> Clock:
    return Clock.fixed(TODAY, zone_name=TZ)


@pytest.fixture
def graph() -> LivingGraph:
    """The seeded world, with a slot on yesterday to reconcile."""
    g = demo_scenario.living_graph()
    g.task_by_id("t-recording").scheduled_slots.append(datetime(2026, 9, 9, 8, 0))
    g.task_by_id("t-gym").scheduled_slots.append(datetime(2026, 9, 9, 18, 0))
    return g


# -- what gets asked --------------------------------------------------------


def test_the_check_in_asks_about_yesterday_not_today(graph, clock):
    check_in = build_check_in(graph, clock)
    assert check_in.on == YESTERDAY
    assert all(item.scheduled_for.date() == YESTERDAY for item in check_in.items)


def test_it_arrives_pre_filled_with_the_evidence(graph, clock):
    """Second does the work before asking. The user corrects; they do not report."""
    observations = ObservationReport(
        observations=[
            Observation(
                task_id="t-gym",
                scheduled_for=datetime(2026, 9, 9, 18, 0),
                outcome="missed",
                evidence="18:00 invite declined; 'Eng sync' ran at the same time.",
                source="calendar",
            )
        ]
    )
    check_in = build_check_in(graph, clock, observations)
    gym = next(item for item in check_in.items if item.task_id == "t-gym")

    assert gym.inferred == "likely_missed"
    assert "declined" in gym.evidence


def test_what_cannot_be_inferred_is_asked_honestly(graph, clock):
    """No calendar signal exists for 'did you actually record five minutes'."""
    check_in = build_check_in(graph, clock, ObservationReport())
    recording = next(item for item in check_in.items if item.task_id == "t-recording")

    assert recording.inferred == "unknown"
    assert recording.evidence == "", "no evidence is better than invented evidence"
    assert recording in check_in.uncertain


def test_work_already_done_is_not_asked_about(graph, clock):
    """Confirming what the system already knows is the busywork this removes."""
    graph.task_by_id("t-recording").status = "done"
    ids = [item.task_id for item in build_check_in(graph, clock).items]
    assert "t-recording" not in ids


def test_a_day_with_nothing_scheduled_asks_nothing(clock):
    empty = LivingGraph(user_id=USER)
    assert build_check_in(empty, clock).needs_answer is False


def test_the_check_in_carries_the_goal_so_the_question_has_context(graph, clock):
    item = next(item for item in build_check_in(graph, clock).items if item.task_id == "t-recording")
    assert item.goal_title == "Get comfortable speaking to a room"


# -- how it reaches the user ------------------------------------------------


def test_the_check_in_rides_in_the_brief_and_does_not_notify(graph, clock):
    """It is daily and it is not an interruption.

    It sits inside a brief the user is already looking at, which is exactly what
    lets it be daily without breaking the promise that Second stays quiet.
    """
    brief = assemble(graph=graph, clock=clock, judgement=None)

    assert brief.check_in is not None
    assert brief.check_in.needs_answer
    assert brief.notify is False


def test_nothing_to_reconcile_means_no_check_in_section(clock):
    brief = assemble(graph=LivingGraph(user_id=USER), clock=clock, judgement=None)
    assert brief.check_in is None


# -- what the answer does ---------------------------------------------------


@pytest.fixture
def store(graph):
    with mock_aws():
        boto3.client("dynamodb", region_name="us-west-2").create_table(
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
        table = boto3.resource("dynamodb", region_name="us-west-2").Table("second_graph")
        store = LivingGraphStore(table=table)
        store.save(graph)
        yield store


def report(store, script):
    """Run a one-node graph that reports completions, as the Graph Updater does."""
    names = [tool.tool_name for tool in ALL_GRAPH_TOOLS]

    def factory(deps: AgentDeps) -> Agent:
        return Agent(
            name="graph_updater",
            model=ScriptedModel(script, agent_tool_names=names),
            tools=list(deps.tools),
            hooks=list(deps.hooks),
            system_prompt="stub",
        )

    composed = build_daily_graph(
        store=store,
        user_id=USER,
        clock=Clock.fixed(TODAY, zone_name=TZ),
        model=object(),
        registry=ToolRegistry(ALL_GRAPH_TOOLS),
        specs={
            node: AgentSpec(node, tuple(names) if node == "observer" else (), None, factory)
            for node in ("observer",)
        }
        | {
            node: AgentSpec(node, (), None, lambda deps, n=node: Agent(
                name=n, model=ScriptedModel([Text("ok")]), hooks=list(deps.hooks), system_prompt="stub"
            ))
            for node in ("diagnostician", "adapter", "preparer", "communicator")
        },
    )
    return composed


async def test_the_users_answer_marks_the_task_done(store):
    composed = report(
        store,
        [
            ToolUse("record_completion", {"user_id": USER, "task_id": "t-recording", "did_it": True}),
            Text("recorded"),
        ],
    )
    await composed.run("check-in")

    assert store.load(USER).task_by_id("t-recording").status == "done"


async def test_the_users_answer_beats_an_inferred_slip(store):
    """Not averaged, not weighed. The person was there; the system was not."""
    before = store.load(USER).task_by_id("t-recording").slip_count
    assert before == 3

    composed = report(
        store,
        [
            ToolUse("record_completion", {"user_id": USER, "task_id": "t-recording", "did_it": True}),
            Text("recorded"),
        ],
    )
    await composed.run("check-in")

    task = store.load(USER).task_by_id("t-recording")
    assert task.slip_count == before - 1, "an inferred slip the user contradicted is removed"


async def test_a_reason_is_recorded_so_it_never_asks_twice(store):
    """Being asked the same question twice is how a system says it was not listening."""
    composed = report(
        store,
        [
            ToolUse(
                "record_completion",
                {
                    "user_id": USER,
                    "task_id": "t-recording",
                    "did_it": False,
                    "note": "I do not have anywhere private to record at home.",
                },
            ),
            Text("recorded"),
        ],
    )
    await composed.run("check-in")

    task = store.load(USER).task_by_id("t-recording")
    assert task.known_blocker == "I do not have anywhere private to record at home."
    assert task.slips[-1].noticed_by == "user"


async def test_a_confirmed_completion_teaches_the_person_layer(store):
    composed = report(
        store,
        [
            ToolUse("record_completion", {"user_id": USER, "task_id": "t-gym", "did_it": True}),
            Text("recorded"),
        ],
    )
    await composed.run("check-in")

    person = store.load(USER).person
    assert any(slot.startswith("Wed") for slot in person.honoured_slots), (
        f"the confirmed slot should be learned as honoured: {person.honoured_slots}"
    )


async def test_a_completion_is_audited_as_a_write(store):
    composed = report(
        store,
        [
            ToolUse("record_completion", {"user_id": USER, "task_id": "t-gym", "did_it": True}),
            Text("recorded"),
        ],
    )
    await composed.run("check-in")

    writes = [entry.action for entry in composed.audit.writes()]
    assert "record_completion" in writes


async def test_reporting_on_a_task_that_does_not_exist_raises(store):
    composed = report(
        store,
        [
            ToolUse("record_completion", {"user_id": USER, "task_id": "nope", "did_it": True}),
            Text("done"),
        ],
    )
    await composed.run("check-in")

    failed = [entry for entry in composed.audit.entries if entry.failed]
    assert [entry.action for entry in failed] == ["record_completion"]
