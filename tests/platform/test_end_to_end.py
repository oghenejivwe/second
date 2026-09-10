"""The whole Daily loop, running offline against the seeded demo world.

Every node is a real ``Agent`` calling real ``@tool`` functions against real
DynamoDB semantics. Only the model's *choices* are scripted -- which is the point:
this proves the machinery, and AGENTS supplies the judgement.

This is also the file that demonstrates the four safety rails, because a rail
nobody tested is decoration.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from strands import Agent

from second.core.deps import AgentDeps
from second.core.models import Communique, Diagnosis
from second.graphs.composition import AgentSpec
from second.graphs.daily import build_daily_graph
from second.testing import demo_scenario
from second.testing.scripted_model import ScriptedModel, Structured, Text, ToolUse

USER = demo_scenario.USER_ID
WINDOW_START = demo_scenario.HISTORY_START.isoformat() + "T00:00:00"
WINDOW_END = (demo_scenario.TODAY + timedelta(days=1)).isoformat() + "T00:00:00"


def spec(node_id: str, script, *, tools=(), output_model=None) -> AgentSpec:
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


GYM_CONFLICT = {
    "task_id": "t-gym",
    "blocker_type": "CALENDAR_CONFLICT",
    "evidence": "18:00 gym declined 4 of 5 weekdays; each collided with 'Eng sync' (9 attendees, not owned).",
    "confidence": 0.92,
    "proposed_action": "Move the gym block to 07:00, which is free every weekday.",
    "requires_user_decision": False,
}

SPEAKS = {
    "should_speak": True,
    "card": {
        "task_id": "t-gym",
        "headline": "Gym moved to 07:00. Leave request drafted.",
        "evidence": "18:00 lost to Eng sync 4 of 5 weekdays. Nothing matching a leave request was ever sent.",
        "prepared": {
            "kind": "email_draft",
            "summary": "Leave request for the wedding week",
            "awaiting": "Read it and press send.",
        },
    },
    "silence_reason": "",
}


def daily_with_real_tools(store, *, adapter_script=None):
    """A Daily graph whose nodes actually call the connector and graph tools."""
    from second.graphs.composition import ToolRegistry
    from second.testing.fake_connectors import ALL_FAKE_CONNECTORS
    from second.tools.graph_tools import ALL_GRAPH_TOOLS

    return build_daily_graph(
        store=store,
        user_id=USER,
        today=demo_scenario.TODAY,
        model=object(),
        registry=ToolRegistry([*ALL_GRAPH_TOOLS, *ALL_FAKE_CONNECTORS]),
        specs={
            "observer": spec(
                "observer",
                [
                    ToolUse("get_calendar_events", {"start": WINDOW_START, "end": WINDOW_END}),
                    ToolUse("update_person_model", {"user_id": USER, "patch": {"abandoned_slots": ["Mon 18:00"]}}),
                    Text("Gym declined 4 of 5. Club attended every week."),
                ],
                tools=("read_graph", "get_calendar_events", "search_gmail", "update_person_model"),
            ),
            "diagnostician": spec(
                "diagnostician",
                [
                    ToolUse("read_graph", {"user_id": USER, "layer": "goals"}),
                    Structured(GYM_CONFLICT),
                ],
                tools=("read_graph", "record_diagnosis"),
                output_model=Diagnosis,
            ),
            "adapter": spec(
                "adapter",
                adapter_script
                or [
                    ToolUse("reschedule_event", {"event_id": "gym000", "new_start": "2026-09-14T07:00:00"}),
                    Text("Moved the gym block to 07:00. The 18:00 slot is gone, not postponed."),
                ],
                tools=("read_graph", "reschedule_event", "write_graph"),
            ),
            "preparer": spec(
                "preparer",
                [
                    ToolUse("search_gmail", {"query": "in:sent leave", "max_results": 5}),
                    ToolUse("search_gmail", {"query": "policy", "max_results": 3}),
                    ToolUse(
                        "draft_email",
                        {
                            "to": demo_scenario.MANAGER_EMAIL,
                            "subject": "Annual leave request: wedding week",
                            "body": "Hi,\n\nI'd like to request leave for the week of the wedding.\n\nThanks",
                        },
                    ),
                    Text("Drafted the leave request. Not sent."),
                ],
                tools=("read_graph", "search_gmail", "draft_email", "web_search"),
            ),
            "communicator": spec("communicator", [Structured(SPEAKS)], output_model=Communique),
        },
    )


# -- the loop ---------------------------------------------------------------


async def test_the_whole_daily_loop_runs_on_the_seeded_world(store):
    composed = daily_with_real_tools(store)
    result = await composed.run("Yesterday's plan against what actually happened.")

    assert [node.node_id for node in result.execution_order] == [
        "observer",
        "diagnostician",
        "adapter",
        "preparer",
        "communicator",
    ]


async def test_the_observer_writes_what_it_saw_to_the_person_layer(store):
    await daily_with_real_tools(store).run("go")

    person = store.load(USER).person
    assert "Mon 18:00" in person.abandoned_slots
    assert person.abandoned_slots.count("Mon 18:00") == 1, "already present; must not duplicate"


async def test_nothing_is_ever_sent_only_drafted(store):
    """The rail that matters most. Second drafts; the user sends."""
    composed = daily_with_real_tools(store)
    state = {"second": {"store": store, "user_id": USER}}
    await composed.graph.invoke_async("go", state)

    effects = state["second"]["fake_effects"]
    kinds = [effect["kind"] for effect in effects]

    assert "draft_email" in kinds
    assert not any("send" in kind for kind in kinds), f"something tried to send: {kinds}"

    draft = next(effect for effect in effects if effect["kind"] == "draft_email")
    assert draft["to"] == demo_scenario.MANAGER_EMAIL
    assert draft["body"].strip(), "a draft awaiting one click must actually be written"


async def test_the_adapter_cannot_move_someone_elses_meeting(store):
    """Failure direction: refuse.

    The Eng sync has nine attendees and the user does not own it. Moving it is
    an apology to nine people; refusing it is a line in a log.
    """
    composed = daily_with_real_tools(
        store,
        adapter_script=[
            ToolUse("reschedule_event", {"event_id": "engsync000", "new_start": "2026-09-14T07:00:00"}),
            Text("I could not move that one."),
        ],
    )
    await composed.run("go")

    failed = [entry for entry in composed.audit.entries if entry.failed]
    assert [entry.action for entry in failed] == ["reschedule_event"]


async def test_there_is_no_way_to_delete_a_calendar_event(registry):
    """The guarantee is structural: no such tool exists to be called."""
    assert "delete_event" not in registry.names()
    assert not any("delete" in name for name in registry.names())


# -- the audit trail --------------------------------------------------------


async def test_the_audit_records_every_write_and_no_reads_as_writes(store):
    composed = daily_with_real_tools(store)
    await composed.run("go")

    rows = store.read_audit(USER, limit=100)
    assert rows, "the audit was flushed to the store"

    writes = {row.action for row in rows if row.is_write}
    reads = {row.action for row in rows if row.kind == "tool" and not row.is_write}

    assert writes == {"update_person_model", "reschedule_event", "draft_email"}
    assert "get_calendar_events" in reads and "search_gmail" in reads
    assert not writes & reads, "a tool is a read or a write, never both"


async def test_every_node_appears_in_the_audit(store):
    composed = daily_with_real_tools(store)
    await composed.run("go")

    nodes = {entry.actor for entry in composed.audit.entries if entry.action == "node_start"}
    assert nodes == {"observer", "diagnostician", "adapter", "preparer", "communicator"}


# -- the fakes themselves ---------------------------------------------------


async def test_the_seeded_world_carries_all_four_demo_beats(store):
    graph = store.load(USER)
    events = demo_scenario.calendar_events()

    # 1. a recurring conflict that always loses
    declined = [event for event in events if event["response"] == "declined"]
    assert len(declined) == 4, "the gym should have lost four times"

    # 2. a task dragged across four days
    pitch = [event for event in events if event["title"] == "Draft the talk pitch"]
    assert len(pitch) == 4
    assert sum(1 for event in pitch if event["status"] == "cancelled") == 3, (
        "a drag is only visible as separate cancelled events"
    )

    # 3. a booking blocked by something unsent
    flights = graph.task_by_id("t-flights")
    assert flights.depends_on == ["t-leave"]
    assert not any("leave" in item["subject"].lower() for item in demo_scenario.sent_items())

    # 4. an honest unknown: slips into slots that were free
    recording = graph.task_by_id("t-recording")
    assert recording.slip_count == 3
    recording_events = [event for event in events if event["title"] == "Record five minutes"]
    assert all(event["status"] == "confirmed" for event in recording_events)
    assert all(event["response"] == "none" for event in recording_events), (
        "nothing conflicted; there is no structural explanation, so the answer is UNKNOWN"
    )


@pytest.mark.parametrize(
    "needle,expected_id",
    [("AB-4471-92X", "m-policy"), ("hotel block", "m-wedding"), ("14 days", "m-leavepolicy")],
)
def test_the_planted_facts_are_findable_by_content_not_date(needle, expected_id):
    """Searches key on content, so a demo does not depend on a backdated timestamp.

    This matters because seeding backdated mail needs a scope the runtime agent
    deliberately does not have. If a beat only works when the email is old, the
    beat is fragile.
    """
    match = next(
        message
        for message in demo_scenario.inbox()
        if needle.lower() in (message["subject"] + message["body"]).lower()
    )
    assert match["id"] == expected_id
