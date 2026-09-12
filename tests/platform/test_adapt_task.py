"""The Adapter's tool, and why it exists.

The first full live Daily run died at the Adapter with
``MaxTokensReachedException``. It was doing exactly what the prompt told it to:
read the whole goal and send the whole goal back, every route, every task, every
slip, to change three fields. A goal with eight scheduled slots and four slip
records does not fit in an 8192-token completion, so the model truncated
mid-object and the write failed. Twice, before one happened to fit.

The failure was loud, which was luck. The same mechanism fails silently: a
partial goal that *does* validate replaces the whole entry and erases the slip
history the next diagnosis is built on. The adapter's own docstring warned about
this and defended against it with a sentence in a prompt.

``adapt_task`` makes the defence structural. It has parameters for the four
things an adaptation may change and no parameters for anything else, so the
history cannot be erased by a tool call that does not have the words for it.
"""

from __future__ import annotations

import json
from datetime import date, datetime

import boto3
import pytest
from moto import mock_aws
from strands import Agent
from strands.multiagent.graph import GraphBuilder

from second.core.clock import Clock
from second.core.models import Goal, LivingGraph, Route, Slip, Task
from second.hooks.audit import AuditLogHook
from second.persistence.store import LivingGraphStore
from second.settings import NAMESPACE
from second.testing.scripted_model import ScriptedModel, Text, ToolUse
from second.tools.graph_tools import ALL_GRAPH_TOOLS

REGION = "us-west-2"
USER = "demo"
TODAY = date(2026, 9, 10)
TOOL_NAMES = [tool.tool_name for tool in ALL_GRAPH_TOOLS]


def _gym_goal() -> Goal:
    """A goal shaped like the one that blew the token budget.

    Five past slots, one upcoming, four slips. This is the object the old design
    asked the model to retype in full to change the time.
    """
    return Goal(
        id="g-fitness",
        title="Train three times a week",
        horizon="year",
        routes=[
            Route(
                id="r-gym",
                goal_id="g-fitness",
                title="Gym after work",
                cadence="Mon/Wed/Fri 18:00",
                rationale="Fits the evenings they said were free.",
                status="approved",
                tasks=[
                    Task(
                        id="t-gym",
                        route_id="r-gym",
                        title="Gym session",
                        deadline=date(2026, 12, 1),
                        depends_on=["t-induction"],
                        scheduled_slots=[
                            datetime(2026, 8, 20, 18, 0),
                            datetime(2026, 8, 22, 18, 0),
                            datetime(2026, 8, 24, 18, 0),
                            datetime(2026, 8, 27, 18, 0),
                            datetime(2026, 8, 29, 18, 0),
                            datetime(2026, 9, 11, 18, 0),
                        ],
                        slip_count=4,
                        slips=[
                            Slip(
                                on=date(2026, 8, day),
                                scheduled_for=datetime(2026, 8, day, 18, 0),
                                noticed_by="calendar",
                                note="declined, collided with Eng sync",
                            )
                            for day in (20, 22, 24, 27)
                        ],
                        known_blocker="Eng sync at 18:00",
                    )
                ],
            )
        ],
    )


@pytest.fixture
def seeded():
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
        store = LivingGraphStore(table=table)
        store.save(LivingGraph(user_id=USER, goals=[_gym_goal()]))
        yield store


def call(store, tool_input: dict) -> AuditLogHook:
    """Run one adapt_task call through a real Graph and hand back the audit.

    The audit rather than a return value, because ``@tool`` catches every
    exception and formats it into an error tool result -- that is the documented
    design, and it is why a refusal has to be read from the log instead of caught.
    The log now carries the reason, which is what makes this readable at all.
    """
    audit = AuditLogHook(run_id="test-run", user_id=USER)
    agent = Agent(
        name="adapter",
        model=ScriptedModel(
            [ToolUse("adapt_task", tool_input), Text("done")], agent_tool_names=TOOL_NAMES
        ),
        tools=list(ALL_GRAPH_TOOLS),
        system_prompt="Adapt the plan.",
        hooks=[audit],
    )
    builder = GraphBuilder()
    builder.add_node(agent, "adapter")
    builder.set_entry_point("adapter")
    builder.set_max_node_executions(10)
    builder.set_hook_providers([audit])
    builder.build()(
        "go",
        invocation_state={
            NAMESPACE: {
                "store": store,
                "user_id": USER,
                "clock": Clock.fixed(TODAY, zone_name="Europe/London"),
            }
        },
    )
    return audit


def refusal(store, tool_input: dict) -> str:
    """Make the call, assert it was refused, and return why."""
    audit = call(store, tool_input)
    row = next(entry for entry in audit.entries if entry.action == "adapt_task")
    assert row.failed is True, "expected adapt_task to refuse this"
    return row.payload["error"]


def task_after(store) -> Task:
    return store.load(USER).task_by_id("t-gym")


def route_after(store) -> Route:
    return store.load(USER).goals[0].routes[0]


# -- the thing that could not be guaranteed before ---------------------------


def test_moving_the_time_leaves_every_past_slot_exactly_as_it_was(seeded):
    """Past slots are the record the slips hang off. Rewriting them erases the
    evidence of why the adaptation was needed at all."""
    call(
        seeded,
        {
            "user_id": USER,
            "task_id": "t-gym",
            "reason": "18:00 is recorded as abandoned; 07:00 is uncontested.",
            "future_slots": ["2026-09-11T07:00:00", "2026-09-14T07:00:00"],
        },
    )

    task = task_after(seeded)
    assert task.scheduled_slots[:5] == [
        datetime(2026, 8, 20, 18, 0),
        datetime(2026, 8, 22, 18, 0),
        datetime(2026, 8, 24, 18, 0),
        datetime(2026, 8, 27, 18, 0),
        datetime(2026, 8, 29, 18, 0),
    ]
    assert task.scheduled_slots[5:] == [
        datetime(2026, 9, 11, 7, 0),
        datetime(2026, 9, 14, 7, 0),
    ]


def test_the_slip_history_survives_an_adaptation(seeded):
    """There is no parameter for slips, so no adaptation can drop them.

    Under write_graph this was guaranteed only by the model copying four slip
    objects back verbatim -- which is also what exhausted the token budget.
    """
    before = task_after(seeded)

    call(
        seeded,
        {
            "user_id": USER,
            "task_id": "t-gym",
            "reason": "Moving to a slot nothing competes for.",
            "future_slots": ["2026-09-11T07:00:00"],
        },
    )

    after = task_after(seeded)
    assert after.slip_count == 4
    assert after.slips == before.slips
    assert after.depends_on == ["t-induction"]
    assert after.deadline == date(2026, 12, 1)
    assert after.known_blocker == "Eng sync at 18:00"
    assert after.status == before.status
    assert after.route_id == "r-gym"


def test_the_call_is_a_fraction_of_the_goal_it_replaces(seeded):
    """The defect was size. A whole-goal write does not fit in a completion."""
    whole_goal = json.dumps(json.loads(_gym_goal().model_dump_json()))
    adaptation = json.dumps(
        {
            "user_id": USER,
            "task_id": "t-gym",
            "reason": "18:00 is recorded as abandoned on Mon, Wed and Fri; 07:00 is uncontested.",
            "future_slots": ["2026-09-11T07:00:00", "2026-09-14T07:00:00"],
            "cadence": "Mon/Wed/Fri 07:00",
            "rationale": "07:00 matches a stated early day shape and nothing competes for it.",
        }
    )

    assert len(adaptation) * 2 < len(whole_goal), (
        f"adaptation {len(adaptation)}B vs whole goal {len(whole_goal)}B -- "
        f"the point of this tool is that the model never emits the second one"
    )


# -- each blocker type's edit ------------------------------------------------


def test_rewording_a_task_leaves_its_schedule_alone(seeded):
    """UNDEFINED_SCOPE: the sentence was the problem, not the time."""
    before = task_after(seeded).scheduled_slots

    call(
        seeded,
        {
            "user_id": USER,
            "task_id": "t-gym",
            "reason": "The task named no finishable output.",
            "new_title": "Twenty minutes on the rower",
        },
    )

    task = task_after(seeded)
    assert task.title == "Twenty minutes on the rower"
    assert task.scheduled_slots == before


def test_the_route_rationale_moves_with_the_cadence(seeded):
    """A rationale describing the old time makes the graph lie."""
    call(
        seeded,
        {
            "user_id": USER,
            "task_id": "t-gym",
            "reason": "18:00 loses to a meeting that is not theirs to move.",
            "future_slots": ["2026-09-11T07:00:00"],
            "cadence": "Mon/Wed/Fri 07:00",
            "rationale": "18:00 is recorded as abandoned; 07:00 fits a stated early day shape.",
        },
    )

    route = route_after(seeded)
    assert route.cadence == "Mon/Wed/Fri 07:00"
    assert "abandoned" in route.rationale
    assert route.status == "approved"


def test_clearing_the_schedule_still_keeps_the_past(seeded):
    """An empty list is a real instruction -- unschedule it -- and distinct from
    omitting the field, which means leave the schedule alone."""
    call(
        seeded,
        {
            "user_id": USER,
            "task_id": "t-gym",
            "reason": "Unscheduling until the dependency clears.",
            "future_slots": [],
        },
    )

    slots = task_after(seeded).scheduled_slots
    assert len(slots) == 5
    assert all(slot.date() < TODAY for slot in slots)


# -- what it refuses ---------------------------------------------------------


def test_an_id_that_is_not_in_the_graph_is_refused(seeded):
    """"An id you cannot find is an id you must not act on" -- now enforced."""
    why = refusal(
        seeded,
        {
            "user_id": USER,
            "task_id": "t-nonexistent",
            "reason": "Trying to move something that does not exist.",
            "future_slots": ["2026-09-11T07:00:00"],
        },
    )
    assert "no task 't-nonexistent'" in why


def test_a_change_with_no_reason_is_refused(seeded):
    """The reason lands in the audit row. An unexplained change is not an
    adaptation, it is a mutation with a timestamp."""
    why = refusal(
        seeded,
        {
            "user_id": USER,
            "task_id": "t-gym",
            "reason": "   ",
            "future_slots": ["2026-09-11T07:00:00"],
        },
    )
    assert "needs a reason" in why


def test_a_call_that_changes_nothing_is_refused(seeded):
    """Catches a model that calls the tool to look busy."""
    why = refusal(seeded, {"user_id": USER, "task_id": "t-gym", "reason": "Thinking about it."})
    assert "nothing to change" in why


def test_a_slot_that_is_not_a_datetime_is_refused(seeded):
    why = refusal(
        seeded,
        {
            "user_id": USER,
            "task_id": "t-gym",
            "reason": "Moving to the morning.",
            "future_slots": ["tomorrow at 7"],
        },
    )
    assert "not an ISO datetime" in why


def test_nothing_is_written_when_the_call_is_refused(seeded):
    """The mutate callback raises before save, so a bad call leaves no trace."""
    before = seeded.load(USER).version

    refusal(
        seeded,
        {
            "user_id": USER,
            "task_id": "t-nonexistent",
            "reason": "Should not write.",
            "future_slots": ["2026-09-11T07:00:00"],
        },
    )

    assert seeded.load(USER).version == before


# -- least privilege ---------------------------------------------------------


def test_the_adapter_can_no_longer_reach_write_graph():
    """The whole-goal upsert is still there for agents that build goals. The
    Adapter is not one of them, and a tool it cannot call is a tool it cannot
    truncate."""
    from second.agents import adapter

    assert "adapt_task" in adapter.REQUIRED_TOOLS
    assert "write_graph" not in adapter.REQUIRED_TOOLS


def test_adapt_task_is_audited_as_a_write():
    """It changes the plan. A change the audit does not show is a change nobody
    can review."""
    from second.hooks.audit import WRITE_TOOLS

    assert "adapt_task" in WRITE_TOOLS
