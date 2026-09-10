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
    Communique,
    Diagnosis,
    ExtractionResult,
    Goal,
    LivingGraph,
    Route,
    Task,
    TodayCard,
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
    "should_speak": True,
    "card": {"task_id": "t1", "headline": "Gym moved to 07:00", "evidence": "18:00 lost to meetings 4 of 5 days."},
    "silence_reason": "",
}
STAYS_QUIET = {"should_speak": False, "card": None, "silence_reason": "Nothing slipped and nothing needs a decision."}


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
            "communicator": stub("communicator", [Structured(communique)], output_model=Communique),
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
            "communicator": stub("communicator", [Structured(SPEAKS)], output_model=Communique),
        },
    )
    result = await composed.run("go")
    visited = [node.node_id for node in result.execution_order]

    assert visited == ["observer", "diagnostician", "communicator"]


# -- the silence path -------------------------------------------------------


@pytest.mark.asyncio
async def test_silence_returns_no_card(store):
    """Silence is a typed decision, not an empty string."""
    card = await service.run_daily(
        USER,
        model=object(),
        registry=ToolRegistry(ALL_GRAPH_TOOLS),
        specs=_specs(STAYS_QUIET),
    )
    assert card is None


@pytest.mark.asyncio
async def test_speaking_returns_the_card(store):
    card = await service.run_daily(
        USER, model=object(), registry=ToolRegistry(ALL_GRAPH_TOOLS), specs=_specs(SPEAKS)
    )
    assert isinstance(card, TodayCard)
    assert card.headline == "Gym moved to 07:00"
    assert card.evidence, "every message cites its evidence"


def _specs(communique: dict) -> dict[str, AgentSpec]:
    return {
        "observer": stub("observer", [Text("observed")]),
        "diagnostician": stub("diagnostician", [Structured(CONFIDENT)], output_model=Diagnosis),
        "adapter": stub("adapter", [Text("adapted")]),
        "preparer": stub("preparer", [Text("prepared")]),
        "communicator": stub("communicator", [Structured(communique)], output_model=Communique),
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
            "route_planner": stub("route_planner", [Text("two routes proposed")]),
            "scheduler": stub("scheduler", [Text("placed, and said what lost")]),
        },
    )


@pytest.mark.asyncio
async def test_clear_speech_reaches_the_scheduler(store):
    result = await intake(store, CLEAR).run("I want to get better at speaking")
    assert [node.node_id for node in result.execution_order] == ["extractor", "route_planner", "scheduler"]


@pytest.mark.asyncio
async def test_unclear_speech_stops_before_anything_is_scheduled(store):
    """Nothing goes in a real calendar on a misheard goal."""
    result = await intake(store, MUDDY).run("umm, fitness stuff")
    visited = [node.node_id for node in result.execution_order]

    assert visited == ["extractor"]
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
