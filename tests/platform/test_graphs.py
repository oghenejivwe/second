"""The three graphs, routed by typed fields, run offline end to end.

Every node here is a real ``Agent`` with a real ``@tool`` set and a real
structured-output model. Only the model provider and AWS are substituted, so
these tests exercise the same edges, conditions and readiness logic a live run
does.
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws
from strands import Agent

from second.core.deps import AgentDeps, ToolPrivilegeError
from second.core.models import (
    BriefJudgement,
    Diagnosis,
    ExtractionResult,
    Goal,
    LivingGraph,
    Route,
    Task,
)
from second.graphs import service
from second.graphs.composition import AgentSpec, MissingTool, ToolRegistry, build_node_agent
from second.graphs.daily import build_daily_graph
from second.graphs.intake import build_intake_graph
from second.persistence.store import LivingGraphStore
from second.testing.scripted_model import ScriptedModel, Structured, Text
from second.tools.graph_tools import ALL_GRAPH_TOOLS

REGION = "us-west-2"
USER = "demo"


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
        store = LivingGraphStore(table=table)
        store.save(
            LivingGraph(
                user_id=USER,
                goals=[
                    Goal(
                        id="g1",
                        title="Get fit",
                        routes=[
                            Route(
                                id="r1",
                                goal_id="g1",
                                title="Gym",
                                cadence="Mon/Wed/Fri 18:00",
                                rationale="Evenings they said were free.",
                                tasks=[Task(id="t1", route_id="r1", title="Gym")],
                            )
                        ],
                    )
                ],
            )
        )
        service.set_store(store)
        yield store
        service.set_store(None)


def stub(node_id: str, script, *, tools=(), output_model=None) -> AgentSpec:
    """An agent spec whose model reads from a script."""

    def factory(deps: AgentDeps) -> Agent:
        return Agent(
            name=node_id,
            model=ScriptedModel(script, agent_tool_names=[tool.tool_name for tool in deps.tools]),
            tools=list(deps.tools),
            hooks=list(deps.hooks),
            structured_output_model=output_model,
            system_prompt=f"stub {node_id}",
        )

    return AgentSpec(node_id, tuple(tools), output_model, factory)


CONFIDENT = {
    "task_id": "t1",
    "blocker_type": "CALENDAR_CONFLICT",
    "evidence": "18:00 gym declined 4 of 5 weekdays; each collided with 'Eng sync'.",
    "confidence": 0.91,
    "proposed_action": "Move the block to 07:00, where nothing competes.",
    "requires_user_decision": False,
}
HONEST_UNKNOWN = {**CONFIDENT, "blocker_type": "UNKNOWN", "confidence": 0.35, "requires_user_decision": True}
UNSURE = {**CONFIDENT, "confidence": 0.65}

SPEAKS = {
    "reminders": [],
    "decisions": [
        {
            "question": "The 18:00 gym slot keeps losing. Move it to 07:00?",
            "task_id": "t1",
            "evidence": "18:00 lost to meetings 4 of 5 days.",
            "options": ["Move to 07:00", "Drop to twice a week", "Leave it"],
        }
    ],
    "notify": True,
    "silence_reason": "",
}
STAYS_QUIET = {
    "reminders": [],
    "decisions": [],
    "notify": False,
    "silence_reason": "Nothing slipped and nothing needs a decision.",
}


def daily(store, diagnosis: dict, communique: dict = SPEAKS):
    """Build a Daily graph whose diagnosis and communique are given."""
    return build_daily_graph(
        store=store,
        user_id=USER,
        model=object(),  # never used: every node carries its own scripted model
        registry=ToolRegistry(ALL_GRAPH_TOOLS),
        specs={
            "observer": stub("observer", [Text("18:00 gym declined 4 of 5 weekdays.")]),
            "diagnostician": stub("diagnostician", [Structured(diagnosis)], output_model=Diagnosis),
            "adapter": stub("adapter", [Text("Moved the gym block to 07:00.")]),
            "preparer": stub("preparer", [Text("Drafted nothing; the change needs no message.")]),
            "communicator": stub("communicator", [Structured(communique)], output_model=BriefJudgement),
        },
    )


# -- the branch -------------------------------------------------------------


@pytest.mark.asyncio
async def test_confident_diagnosis_takes_the_autonomous_path(store):
    result = await daily(store, CONFIDENT).run("go")
    visited = [node.node_id for node in result.execution_order]

    assert visited == ["observer", "diagnostician", "adapter", "preparer", "communicator"]


@pytest.mark.asyncio
async def test_honest_unknown_bypasses_the_adapter_and_asks(store):
    """The demo moment: Second cannot tell, so it asks instead of inventing."""
    result = await daily(store, HONEST_UNKNOWN).run("go")
    visited = [node.node_id for node in result.execution_order]

    assert visited == ["observer", "diagnostician", "communicator"]
    assert "adapter" not in visited and "preparer" not in visited


@pytest.mark.asyncio
async def test_low_confidence_asks_even_when_the_diagnosis_is_structural(store):
    """CALENDAR_CONFLICT at 0.65 is still below the floor. Confidence alone routes."""
    result = await daily(store, UNSURE).run("go")
    assert [node.node_id for node in result.execution_order] == ["observer", "diagnostician", "communicator"]


@pytest.mark.asyncio
async def test_exactly_one_branch_fires(store):
    """Sibling edges are OR-gates, not a switch.

    If the two conditions ever stop being strict complements, both the Adapter
    and the Communicator run. Asserting the exact path is what catches that.
    """
    for diagnosis, expect_adapter in ((CONFIDENT, True), (HONEST_UNKNOWN, False), (UNSURE, False)):
        result = await daily(store, diagnosis).run("go")
        visited = [node.node_id for node in result.execution_order]

        assert ("adapter" in visited) is expect_adapter, f"wrong branch for {diagnosis['blocker_type']}"
        assert ("preparer" in visited) is expect_adapter, "preparer must follow the adapter, or neither"
        assert visited.count("communicator") == 1, "communicator ran twice"
        assert visited.count("diagnostician") == 1


@pytest.mark.asyncio
async def test_a_diagnostician_that_produced_nothing_routes_to_asking(store):
    """Failure direction: ask.

    A run that hits a turn or token limit exits with structured_output None and
    no exception. Second must not treat 'we do not know' as 'nothing is wrong'.
    """
    composed = build_daily_graph(
        store=store,
        user_id=USER,
        model=object(),
        registry=ToolRegistry(ALL_GRAPH_TOOLS),
        specs={
            "observer": stub("observer", [Text("something slipped")]),
            "diagnostician": stub("diagnostician", [Text("I have no idea")]),  # no output model
            "adapter": stub("adapter", [Text("should not run")]),
            "preparer": stub("preparer", [Text("should not run")]),
            "communicator": stub("communicator", [Structured(SPEAKS)], output_model=BriefJudgement),
        },
    )
    result = await composed.run("go")
    visited = [node.node_id for node in result.execution_order]

    assert visited == ["observer", "diagnostician", "communicator"]


# -- the silence path -------------------------------------------------------


@pytest.mark.asyncio
async def test_a_quiet_day_still_returns_a_brief(store):
    """Existing is not interrupting. The day is there; the push is not."""
    brief = await service.run_daily(
        USER,
        model=object(),
        registry=ToolRegistry(ALL_GRAPH_TOOLS),
        specs=_specs(STAYS_QUIET),
    )
    assert brief is not None, "a brief is always returned"
    assert brief.is_quiet
    assert brief.notify is False
    assert brief.decisions == []
    assert brief.silence_reason, "quietness is auditable, not an absence"


@pytest.mark.asyncio
async def test_a_decision_earns_a_notification(store):
    brief = await service.run_daily(
        USER, model=object(), registry=ToolRegistry(ALL_GRAPH_TOOLS), specs=_specs(SPEAKS)
    )
    assert brief.notify is True
    assert brief.decisions[0].evidence, "every decision cites its evidence"
    assert brief.decisions[0].options, "a question arrives with researched answers"


def _specs(communique: dict) -> dict[str, AgentSpec]:
    return {
        "observer": stub("observer", [Text("observed")]),
        "diagnostician": stub("diagnostician", [Structured(CONFIDENT)], output_model=Diagnosis),
        "adapter": stub("adapter", [Text("adapted")]),
        "preparer": stub("preparer", [Text("prepared")]),
        "communicator": stub("communicator", [Structured(communique)], output_model=BriefJudgement),
    }


# -- intake -----------------------------------------------------------------


CLEAR = {
    "goals": [{"id": "g9", "title": "Master public speaking", "extraction_confidence": 0.92}],
    "clarifying_questions": [],
}
MUDDY = {
    "goals": [{"id": "g9", "title": "something about fitness maybe", "extraction_confidence": 0.4}],
    "clarifying_questions": ["Did you mean running, or the gym?"],
}


def intake(store, extraction: dict):
    return build_intake_graph(
        store=store,
        user_id=USER,
        model=object(),
        registry=ToolRegistry(ALL_GRAPH_TOOLS),
        include_resource_finder=False,
        specs={
            "extractor": stub("extractor", [Structured(extraction)], output_model=ExtractionResult),
            "cascader": stub("cascader", [Text("nothing longer than a year to walk down")]),
            "route_planner": stub("route_planner", [Text("two routes proposed")]),
            "scheduler": stub("scheduler", [Text("placed, and said what lost")]),
        },
    )


@pytest.mark.asyncio
async def test_clear_speech_reaches_the_scheduler(store):
    result = await intake(store, CLEAR).run("I want to get better at speaking")
    assert [node.node_id for node in result.execution_order] == [
        "extractor",
        "cascader",
        "route_planner",
        "scheduler",
    ]


@pytest.mark.asyncio
async def test_unclear_speech_stops_before_anything_is_scheduled(store):
    """Nothing goes in a real calendar on a misheard goal."""
    result = await intake(store, MUDDY).run("umm, fitness stuff")
    visited = [node.node_id for node in result.execution_order]

    assert visited == ["extractor"]
    assert "cascader" not in visited, "nothing is decomposed from a misheard goal either"
    assert "scheduler" not in visited


# -- least privilege --------------------------------------------------------


def test_an_agent_wired_with_the_wrong_tools_fails_at_construction():
    """A Diagnostician that could reach draft_email must never reach a run."""
    spec = stub("diagnostician", [Text("x")], tools=("read_graph",))
    registry = ToolRegistry(ALL_GRAPH_TOOLS)

    deps = AgentDeps(model=object(), tools=registry.resolve(("read_graph", "write_graph")))
    from second.core.deps import assert_privileges

    with pytest.raises(ToolPrivilegeError) as excinfo:
        assert_privileges("diagnostician", spec.required_tools, deps)
    assert "write_graph" in str(excinfo.value)


def test_a_tool_nobody_has_built_yet_names_its_owner():
    spec = stub("observer", [Text("x")], tools=("read_graph", "search_gmail"))

    with pytest.raises(MissingTool) as excinfo:
        build_node_agent(
            spec,
            model=object(),
            registry=ToolRegistry(ALL_GRAPH_TOOLS),
            hooks=[],
            user_id=USER,
        )
    assert "search_gmail" in str(excinfo.value)
    assert "CONNECTORS" in str(excinfo.value)


# -- the observer -> communicator edge --------------------------------------


@pytest.mark.asyncio
async def test_the_observer_report_reaches_the_communicator_on_both_paths(store):
    """The Communicator must cite the email a forgotten commitment came from.

    It has no tools, and its typed dependencies carry no inbox evidence, so
    without this edge it could never produce a legal Reminder.
    """
    for diagnosis, expected in ((CONFIDENT, "adapter"), (HONEST_UNKNOWN, "communicator")):
        composed = daily(store, diagnosis)
        result = await composed.run("go")
        visited = [node.node_id for node in result.execution_order]

        assert visited.count("communicator") == 1, (
            f"communicator ran {visited.count('communicator')} times on the "
            f"{expected} path -- the observer edge is firing readiness"
        )
        prompt = composed.graph.nodes["communicator"].executor.model.calls[0]["prompt_text"]
        assert "18:00 gym declined" in prompt, "the Observer's text did not reach it"


@pytest.mark.asyncio
async def test_an_ungated_observer_edge_would_run_the_communicator_twice(store):
    """The trap this gate exists to avoid, demonstrated rather than asserted.

    A node is ready when any incoming edge FROM THE JUST-COMPLETED BATCH is
    satisfied (graph.py:965-981). A bare observer->communicator edge is therefore
    satisfied the moment the Observer finishes, and again after the Preparer.
    """
    from strands.multiagent.graph import GraphBuilder

    from second.graphs.composition import ToolRegistry, build_node_agent
    from second.graphs.conditions import can_act_alone, needs_user_decision
    from second.hooks.audit import AuditLogHook

    audit = AuditLogHook(user_id=USER)
    registry = ToolRegistry(ALL_GRAPH_TOOLS)
    specs = _specs(SPEAKS)

    builder = GraphBuilder()
    for node_id, spec_obj in specs.items():
        builder.add_node(
            build_node_agent(spec_obj, model=object(), registry=registry, hooks=[audit], user_id=USER),
            node_id,
        )
    builder.add_edge("observer", "diagnostician")
    builder.add_edge("diagnostician", "adapter", condition=can_act_alone)
    builder.add_edge("diagnostician", "communicator", condition=needs_user_decision)
    builder.add_edge("adapter", "preparer")
    builder.add_edge("preparer", "communicator")
    builder.add_edge("observer", "communicator")  # <- ungated, the bug
    builder.set_entry_point("observer")
    builder.set_max_node_executions(12)

    from second.testing.scripted_model import ScriptedTurnsExhausted

    with pytest.raises((ScriptedTurnsExhausted, Exception)) as excinfo:
        await builder.build().invoke_async("go", {"second": {"store": store, "user_id": USER}})

    assert "turn 2" in str(excinfo.value) or "exhausted" in str(excinfo.value).lower(), (
        f"expected the communicator to be asked twice, got: {excinfo.value}"
    )
