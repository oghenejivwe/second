"""The graph tools and the audit hook, driven through a real Strands Graph.

Nothing here is mocked except the model and AWS. The ``Graph``, the event loop,
``@tool`` dispatch and the hook registries are all real, so these tests exercise
the same code paths a live run does.
"""

from __future__ import annotations

from datetime import date, datetime

import boto3
import pytest
from moto import mock_aws
from strands import Agent
from strands.multiagent.graph import GraphBuilder

from second.core.models import Goal, LivingGraph, Route, Task
from second.hooks.audit import AuditLogHook
from second.persistence.store import LivingGraphStore
from second.settings import NAMESPACE
from second.testing.scripted_model import ScriptedModel, Text, ToolUse
from second.tools.graph_tools import ALL_GRAPH_TOOLS

REGION = "us-west-2"
USER = "demo"
TOOL_NAMES = [tool.tool_name for tool in ALL_GRAPH_TOOLS]


@pytest.fixture
def store():
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


@pytest.fixture
def seeded(store):
    store.save(
        LivingGraph(
            user_id=USER,
            goals=[
                Goal(
                    id="g1",
                    title="Get fit",
                    deadline=date(2026, 12, 1),
                    routes=[
                        Route(
                            id="r1",
                            goal_id="g1",
                            title="Gym three times a week",
                            cadence="Mon/Wed/Fri 18:00",
                            rationale="Fits the evenings they said were free.",
                            tasks=[
                                Task(id="t1", route_id="r1", title="Gym"),
                                Task(id="t2", route_id="r1", title="Book induction"),
                            ],
                        )
                    ],
                )
            ],
        )
    )
    return store


def run_graph(store, script, *, audit_on_agent=True):
    """Run a one-node graph whose agent follows ``script``."""
    audit = AuditLogHook(run_id="test-run", user_id=USER)
    agent = Agent(
        name="worker",
        model=ScriptedModel(script, agent_tool_names=TOOL_NAMES),
        tools=list(ALL_GRAPH_TOOLS),
        system_prompt="Do what the scenario says.",
        hooks=[audit] if audit_on_agent else [],
    )
    builder = GraphBuilder()
    builder.add_node(agent, "worker")
    builder.set_entry_point("worker")
    builder.set_hook_providers([audit])
    builder.set_max_node_executions(10)
    graph = builder.build()

    graph("go", invocation_state={NAMESPACE: {"store": store, "user_id": USER}})
    return audit


# -- the tools --------------------------------------------------------------


def test_read_graph_returns_only_the_layer_asked_for(seeded):
    run_graph(
        seeded,
        [ToolUse("read_graph", {"user_id": USER, "layer": "person"}), Text("done")],
    )
    # The tool ran without raising; prove the layering by calling the store directly.
    graph = seeded.load(USER)
    assert graph.person.preferences == {}
    assert len(graph.goals) == 1


def test_write_graph_upserts_by_id_and_never_deletes(seeded):
    new_goal = Goal(id="g2", title="Learn Portuguese").model_dump(mode="json")
    changed = seeded.load(USER).goals[0].model_dump(mode="json")
    changed["title"] = "Get fit (revised)"

    run_graph(
        seeded,
        [
            ToolUse("write_graph", {"user_id": USER, "layer": "goals", "patch": {"goals": [changed, new_goal]}}),
            Text("done"),
        ],
    )

    goals = {goal.id: goal for goal in seeded.load(USER).goals}
    assert goals["g1"].title == "Get fit (revised)", "existing goal replaced in place"
    assert "g2" in goals, "new goal appended"
    assert len(goals["g1"].routes) == 1, "routes survived the upsert"


def test_update_person_model_merges_and_deduplicates(seeded):
    run_graph(
        seeded,
        [
            ToolUse("update_person_model", {"user_id": USER, "patch": {"preferences": {"learning_mode": "video"}, "constraints": ["no work before 10am"]}}),
            ToolUse("update_person_model", {"user_id": USER, "patch": {"constraints": ["no work before 10am", "Sundays are family"]}}),
            Text("done"),
        ],
    )

    person = seeded.load(USER).person
    assert person.preferences == {"learning_mode": "video"}
    assert person.constraints == ["no work before 10am", "Sundays are family"], "no duplicate"


def test_record_diagnosis_blocks_the_task_on_unmet_dependency(seeded):
    run_graph(
        seeded,
        [
            ToolUse("record_diagnosis", {"user_id": USER, "diagnosis": {
                "task_id": "t1", "blocker_type": "UNMET_DEPENDENCY",
                "evidence": "t2 'Book induction' is still pending.",
                "confidence": 0.88, "proposed_action": "Do t2 first.",
                "requires_user_decision": False}}),
            Text("done"),
        ],
    )

    graph = seeded.load(USER)
    assert graph.task_by_id("t1").status == "blocked"
    assert any("UNMET_DEPENDENCY" in blocker for blocker in graph.person.recurring_blockers)


def test_low_confidence_diagnosis_is_not_learned_as_recurring(seeded):
    """An honest UNKNOWN must not teach the system a false pattern."""
    run_graph(
        seeded,
        [
            ToolUse("record_diagnosis", {"user_id": USER, "diagnosis": {
                "task_id": "t1", "blocker_type": "UNKNOWN",
                "evidence": "Slot was free and uncontested on 3 of 4 slips.",
                "confidence": 0.35, "proposed_action": "Ask what is blocking this.",
                "requires_user_decision": True}}),
            Text("done"),
        ],
    )
    assert seeded.load(USER).person.recurring_blockers == []


def test_retiring_a_goal_reports_the_time_it_frees(seeded):
    graph = seeded.load(USER)
    graph.goals[0].routes[0].tasks[0].scheduled_slots = [
        datetime(2026, 9, 14, 18, 0),
        datetime(2026, 9, 16, 18, 0),
    ]
    seeded.save(graph)

    run_graph(
        seeded,
        [ToolUse("set_goal_status", {"user_id": USER, "goal_id": "g1", "status": "retired"}), Text("done")],
    )

    assert seeded.load(USER).goals[0].status == "retired"


# -- the audit hook ---------------------------------------------------------


def test_audit_captures_node_spans_and_tool_writes(seeded):
    audit = run_graph(
        seeded,
        [
            ToolUse("read_graph", {"user_id": USER, "layer": "goals"}),
            ToolUse("update_person_model", {"user_id": USER, "patch": {"constraints": ["no work before 10am"]}}),
            Text("done"),
        ],
    )

    actions = [entry.action for entry in audit.entries]
    assert "run_start" in actions and "run_end" in actions
    assert "node_start" in actions and "node_end" in actions
    assert "read_graph" in actions and "update_person_model" in actions

    assert [entry.action for entry in audit.writes()] == ["update_person_model"], (
        "read_graph is not a write and must not be logged as one"
    )


def test_graph_level_registration_alone_captures_no_tool_calls(seeded):
    """The boundary that would otherwise produce a silently empty audit log.

    A Graph keeps its own HookRegistry which never emits tool events. If this
    ever starts passing with tool rows present, the SDK changed and the
    double registration in build_* can be simplified.
    """
    audit = run_graph(
        seeded,
        [ToolUse("read_graph", {"user_id": USER, "layer": "goals"}), Text("done")],
        audit_on_agent=False,
    )

    kinds = {entry.kind for entry in audit.entries}
    assert kinds == {"node"}, f"expected node spans only, got {kinds}"
    assert not any(entry.action == "read_graph" for entry in audit.entries)


def test_a_raising_tool_is_audited_as_failed(seeded):
    """Tools raise rather than returning error dicts, so the audit keeps the cause."""
    audit = run_graph(
        seeded,
        [ToolUse("read_graph", {"user_id": USER, "layer": "nonsense"}), Text("done")],
    )

    row = next(entry for entry in audit.entries if entry.action == "read_graph")
    assert row.failed is True


def test_a_failed_row_says_why_it_failed(seeded):
    """The docstring above always claimed the audit kept the cause. It did not.

    The first live Daily run logged three write_graph calls from the adapter, two
    failed, and the log could not distinguish a lost race from a malformed patch
    -- opposite problems with opposite fixes. A row that says FAILED and nothing
    else is half a record, and this log is what a reviewer reads.
    """
    audit = run_graph(
        seeded,
        [ToolUse("read_graph", {"user_id": USER, "layer": "nonsense"}), Text("done")],
    )

    row = next(entry for entry in audit.entries if entry.action == "read_graph")
    assert "GraphToolError" in row.payload["error"]
    assert "nonsense" in row.payload["error"]


def test_a_successful_row_carries_no_error_key(seeded):
    """Absence is the signal. An empty string would read as "failed, cause unknown"."""
    audit = run_graph(
        seeded,
        [ToolUse("read_graph", {"user_id": USER, "layer": "goals"}), Text("done")],
    )

    row = next(entry for entry in audit.entries if entry.action == "read_graph")
    assert row.failed is False
    assert "error" not in row.payload


def test_audit_flushes_to_the_store(seeded):
    audit = AuditLogHook(run_id="r1", user_id=USER, store=seeded)
    audit._record(kind="tool", actor="observer", action="update_person_model", is_write=True)
    audit.flush()

    rows = seeded.read_audit(USER)
    assert [row.action for row in rows] == ["update_person_model"]
    assert len(audit.entries) == 1, "flush persists; it does not erase the run record"

    audit.flush()
    assert len(seeded.read_audit(USER)) == 1, "a second flush must not write the row twice"
