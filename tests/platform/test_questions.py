"""The recurring question: asked on a cadence, anchored to a real gap, remembered once answered.

A question asked every time the tab opens is a nag, and a question that forgets it was answered
is worse. So the cadence is pinned from both sides, and ``asked_on`` is proven to survive the one
place it could be lost: the round trip through DynamoDB.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import get_args

import pytest
from strands import Agent

from second.core.clock import Clock
from second.core.deps import AgentDeps
from second.core.models import ExtractionResult, Goal, IntakeResult, LivingGraph, QuestionHorizon
from second.graphs import service
from second.graphs.composition import AgentSpec
from second.graphs.questions import ANCHOR_RUNGS, anchor_for, due_questions
from second.persistence.serde import to_item
from second.testing import demo_scenario
from second.testing.scripted_model import ScriptedModel, Structured, Text, ToolUse
from second.settings import QUESTION_CADENCE_DAYS

TZ = "Europe/London"
TODAY = date(2026, 9, 10)
USER = demo_scenario.USER_ID


@pytest.fixture
def graph():
    return demo_scenario.living_graph()


@pytest.fixture
def pinned(monkeypatch):
    """Pin the zone so the service never asks a real Google Calendar what timezone it is in."""
    monkeypatch.setattr(service, "resolve_clock", lambda *_args, **_kwargs: Clock.fixed(TODAY, zone_name=TZ))


def horizons(questions):
    return [question.horizon for question in questions]


# -- the contract ------------------------------------------------------------


def test_the_cadence_and_the_contract_name_the_same_horizons():
    """Two lists that agree today and drift silently are the bug; this holds them together."""
    assert set(QUESTION_CADENCE_DAYS) == set(get_args(QuestionHorizon))
    assert set(QUESTION_CADENCE_DAYS) <= set(ANCHOR_RUNGS)
    assert QUESTION_CADENCE_DAYS == {"week": 2, "month": 3}


# -- when it is asked --------------------------------------------------------


def test_never_asked_means_one_question_per_horizon(graph):
    questions = due_questions(graph, TODAY)

    assert horizons(questions) == ["week", "month"]
    for question in questions:
        assert "Never asked before." in question.evidence
        assert f"this {question.horizon}" in question.question
        assert "by when" in question.question


@pytest.mark.parametrize("horizon", sorted(QUESTION_CADENCE_DAYS))
def test_a_question_is_not_asked_again_inside_its_cadence_and_is_after_it(graph, horizon):
    """Mutation-tested: changing ``>=`` to ``>`` in ``is_due`` keeps the question away a day too
    long and this fails; dropping the check altogether asks it every day and this fails."""
    every = QUESTION_CADENCE_DAYS[horizon]
    graph.person.asked_on[horizon] = TODAY

    for elapsed in range(every):
        assert horizon not in horizons(due_questions(graph, TODAY + timedelta(days=elapsed)))

    asked = [question for question in due_questions(graph, TODAY + timedelta(days=every)) if question.horizon == horizon]
    assert len(asked) == 1
    assert f"Last asked {every} days ago, on {TODAY.isoformat()}." in asked[0].evidence


# -- what it is anchored to --------------------------------------------------


def test_the_week_question_names_the_nearest_goal_with_nothing_at_the_week_rung(graph):
    week = next(question for question in due_questions(graph, TODAY) if question.horizon == "week")

    assert week.anchor_goal_id == "g-lisbon"
    assert week.question == (
        "What do you want to do this week towards “Be at my sister's wedding in Lisbon”, and by when?"
    )
    assert week.evidence == (
        "Nothing is planned for this week under “Be at my sister's wedding in Lisbon”. Never asked before."
    )


def test_the_month_question_names_a_year_goal_with_no_month_under_it(graph):
    """Two year goals qualify; the one with the nearer deadline is the one asked about.

    The speaking goal has sessions placed this month (club Fri 11, recording and pitch today), so
    its evidence must not say nothing is planned: it counts them.
    """
    month = next(question for question in due_questions(graph, TODAY) if question.horizon == "month")

    assert month.anchor_goal_id == "g-speaking"
    assert month.question == (
        "What do you want to do this month towards “Get comfortable speaking to a room”, and by when?"
    )
    assert month.evidence == (
        "“Get comfortable speaking to a room” has 3 sessions placed this month but no goal set "
        "for the month. Never asked before."
    )


@pytest.mark.parametrize("graph_goals", [[Goal(id="g1", title="Outlive me", horizon="life")], None])
def test_no_question_evidence_uses_internal_words(graph, graph_goals):
    """A user reads these. "rung" is how the code thinks about horizons, not how a person talks."""
    if graph_goals is not None:
        graph = LivingGraph(user_id=USER, goals=graph_goals)
    graph.person.asked_on = {}
    for day in (TODAY, TODAY + timedelta(days=5)):
        for question in due_questions(graph, day):
            for text in (question.question, question.evidence):
                for jargon in ("rung", "intake", "Living Graph", "'"):
                    assert jargon not in text.replace("'s ", ""), f"{jargon!r} in {text!r}"


def test_an_active_child_at_the_rung_moves_the_anchor_and_a_paused_one_does_not(graph):
    child = Goal(id="g-lisbon-week", title="Sort the trip this week", horizon="week", contributes_to="g-lisbon")
    graph.goals.append(child)
    assert anchor_for(graph, "week").id == "g-speaking"

    child.status = "paused"
    assert anchor_for(graph, "week").id == "g-lisbon"


def test_with_no_anchor_the_question_is_general():
    graph = LivingGraph(user_id=USER, goals=[Goal(id="g1", title="Outlive me", horizon="life")])

    week = next(question for question in due_questions(graph, TODAY) if question.horizon == "week")

    assert week.anchor_goal_id is None
    assert week.question == "What do you want to do this week, and by when?"
    assert week.evidence.strip()


# -- asked_on in the store ---------------------------------------------------


def test_asked_on_round_trips_through_the_store(empty_store):
    """Dates become ISO strings in DynamoDB and must come back as dates, or the cadence
    arithmetic breaks on the first read."""
    graph = demo_scenario.living_graph()
    graph.person.asked_on = {"week": date(2026, 9, 8), "month": date(2026, 9, 7)}

    empty_store.save(graph)

    raw = empty_store.table.get_item(Key={"pk": f"USER#{USER}", "sk": "GRAPH"})["Item"]
    assert raw["graph"]["person"]["asked_on"] == {"week": "2026-09-08", "month": "2026-09-07"}

    loaded = empty_store.load(USER)
    assert loaded.person.asked_on == {"week": date(2026, 9, 8), "month": date(2026, 9, 7)}
    assert all(isinstance(value, date) for value in loaded.person.asked_on.values())


def test_a_graph_written_before_asked_on_existed_still_loads(empty_store):
    item = to_item(demo_scenario.living_graph())
    del item["person"]["asked_on"]
    empty_store.table.put_item(Item={"pk": f"USER#{USER}", "sk": "GRAPH", "version": 1, "graph": item})

    assert empty_store.load(USER).person.asked_on == {}


# -- skipping and answering --------------------------------------------------


def test_skipping_records_asked_on_and_quiets_the_question(store, pinned):
    version = store.load(USER).version

    skipped = service.skip_question(USER, "week", today=TODAY)

    assert (skipped.asked_on, skipped.next_due) == (TODAY, TODAY + timedelta(days=2))
    written = store.load(USER)
    assert written.person.asked_on == {"week": TODAY}
    assert written.version == version + 1, "written through the optimistic lock, once"

    quiet = service.get_memory(USER, today=TODAY + timedelta(days=1), calendar=lambda start, end: [])
    assert horizons(quiet.questions) == ["month"]
    back = service.get_memory(USER, today=TODAY + timedelta(days=2), calendar=lambda start, end: [])
    assert horizons(back.questions) == ["week", "month"]


async def test_answering_records_asked_on_and_goes_through_intake(store, pinned, monkeypatch):
    heard = {}

    async def intake(user_id, transcript, **kwargs):
        heard["transcript"] = transcript
        return IntakeResult(graph=store.load(user_id))

    monkeypatch.setattr(service, "run_intake", intake)

    result = await service.answer_question(USER, "month", "Give the talk at the club, by the 30th", today=TODAY)

    assert "What do you want to do this month towards “Get comfortable speaking to a room”" in heard["transcript"]
    assert "Give the talk at the club, by the 30th" in heard["transcript"]
    assert result.graph.person.asked_on == {"month": TODAY}, "the caller gets the graph as written"
    assert store.load(USER).person.asked_on == {"month": TODAY}


async def test_an_answer_that_stops_for_clarifying_questions_leaves_the_question_due(store, pinned, monkeypatch):
    """Intake asked instead of planning, so nothing was planned and the question must not go quiet.

    Mutation-tested: removing the ``if result.clarifying_questions: return result`` guard in
    ``answer_question`` records ``asked_on`` and this fails.
    """
    asked = ["By when do you need the flights booked?"]

    async def unclear(user_id, transcript, **kwargs):
        return IntakeResult(graph=store.load(user_id), clarifying_questions=asked)

    monkeypatch.setattr(service, "run_intake", unclear)
    version = store.load(USER).version

    result = await service.answer_question(USER, "week", "the flights, soonish", today=TODAY)

    assert result.clarifying_questions == asked, "the user is shown what intake needs to know"
    assert result.schedule is None
    assert store.load(USER).person.asked_on == {}
    assert store.load(USER).version == version, "nothing was written"
    still = service.get_memory(USER, today=TODAY, calendar=lambda start, end: [])
    assert "week" in horizons(still.questions)


async def test_an_intake_that_fails_leaves_the_question_standing(store, pinned, monkeypatch):
    """Mutation-tested: recording ``asked_on`` before intake runs makes this fail -- the answer
    would be lost and the question would still go quiet."""

    async def broken(*_args, **_kwargs):
        raise RuntimeError("the extractor is down")

    monkeypatch.setattr(service, "run_intake", broken)

    with pytest.raises(RuntimeError):
        await service.answer_question(USER, "week", "Book the flights by Friday", today=TODAY)

    assert store.load(USER).person.asked_on == {}


def test_a_horizon_second_does_not_ask_about_is_refused_and_nothing_is_written(store, pinned):
    version = store.load(USER).version

    with pytest.raises(ValueError):
        service.skip_question(USER, "decade", today=TODAY)

    assert store.load(USER).version == version


def spec(node_id, script, *, tools=(), output_model=None) -> AgentSpec:
    def factory(deps: AgentDeps) -> Agent:
        return Agent(
            name=node_id,
            model=ScriptedModel(script, agent_tool_names=[tool.tool_name for tool in deps.tools]),
            tools=list(deps.tools),
            hooks=list(deps.hooks),
            structured_output_model=output_model,
            system_prompt=f"test stub for {node_id}",
        )

    return AgentSpec(node_id, tools, output_model, factory)


async def test_an_answer_becomes_a_goal_with_a_deadline_through_the_real_intake_graph(store, pinned, registry):
    """The whole path, with only the model's choices scripted: the answer is planned by the
    same Intake graph a brain dump is, and the question is marked answered afterwards."""
    goal = {
        "id": "g-lisbon-week",
        "title": "Book the Lisbon flights",
        "horizon": "week",
        "contributes_to": "g-lisbon",
        "deadline": (TODAY + timedelta(days=4)).isoformat(),
        "status": "active",
    }
    specs = {
        "extractor": spec(
            "extractor",
            [Structured({"goals": [goal], "clarifying_questions": []})],
            tools=("read_graph",),
            output_model=ExtractionResult,
        ),
        "cascader": spec("cascader", [Text("Nothing longer than a year to walk down.")]),
        "route_planner": spec(
            "route_planner",
            [
                ToolUse("write_graph", {"user_id": USER, "layer": "goals", "patch": {"goals": [goal]}}),
                Text("Planned."),
            ],
            tools=("read_graph", "write_graph"),
        ),
        "scheduler": spec("scheduler", [Text("Nothing to place yet.")]),
    }

    result = await service.answer_question(
        USER,
        "week",
        "Book the flights by Monday",
        today=TODAY,
        model=object(),
        registry=registry,
        include_resource_finder=False,
        specs=specs,
    )

    assert isinstance(result, IntakeResult)
    planned = result.graph.goal_by_id("g-lisbon-week")
    assert planned is not None and planned.deadline == TODAY + timedelta(days=4)
    assert result.graph.person.asked_on == {"week": TODAY}
