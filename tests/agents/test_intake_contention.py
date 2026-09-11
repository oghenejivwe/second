"""The Intake chain: speech becomes a ladder, routes, and contended slots.

Run against the real ``build_intake_graph`` with the real agent modules, so the
conditional edge that stops on unclear speech and the write ordering between the
Cascader and the Scheduler are both exercised rather than described.

The Scheduler is the hardest agent in the package and the one thing here that a
calendar app does not do: it resolves several goals competing for the same week
and then says out loud what lost and why. Most of this file is about that.
"""

from __future__ import annotations

from second.core.clock import Clock
from second.core.models import CascadeResult, ExtractionResult, ScheduleDecision
from second.core.models import SCHEDULABLE_HORIZONS
from second.graphs.composition import ToolRegistry
from second.graphs.conditions import typed_result
from second.graphs.intake import build_intake_graph
from second.testing import demo_scenario
from second.testing.fake_connectors import ALL_FAKE_CONNECTORS
from second.testing.scripted_model import Structured, Text, ToolUse
from second.tools.graph_tools import ALL_GRAPH_TOOLS

USER = demo_scenario.USER_ID
CLOCK = Clock.fixed(demo_scenario.TODAY, zone_name="Europe/London")

TRANSCRIPT = (
    "I want to build a company that outlives me, and I should get properly fit this year, "
    "and I need to be at my sister's wedding in Lisbon"
)

# -- the Extractor ----------------------------------------------------------

CLEAR = {
    "goals": [
        {
            "id": "g-outlast",
            "title": "Build a company that outlives me",
            "horizon": "life",
            "contributes_to": None,
            "extraction_confidence": 0.91,
        }
    ],
    "clarifying_questions": [],
}

MUDDY = {
    "goals": [
        {
            "id": "g-vague",
            "title": "something about fitness maybe",
            "horizon": "year",
            "extraction_confidence": 0.4,
        }
    ],
    "clarifying_questions": ["Did you mean running, or the gym?"],
}

# -- the Cascader -----------------------------------------------------------

LADDER = [
    {
        "id": "g-outlast",
        "title": "Build a company that outlives me",
        "horizon": "life",
        "contributes_to": None,
        "status": "active",
        "routes": [],
        "extraction_confidence": 0.91,
    },
    {
        "id": "g-durable",
        "title": "A business that runs without me in the room",
        "horizon": "three_year",
        "contributes_to": "g-outlast",
        "status": "active",
        "routes": [],
        "extraction_confidence": 0.8,
    },
    {
        "id": "g-handover",
        "title": "Hand over the two things only I can do",
        "horizon": "year",
        "contributes_to": "g-durable",
        "status": "active",
        "routes": [],
        "extraction_confidence": 0.8,
    },
]

CASCADED = {
    "goals": LADDER[1:],
    "rationale": "They keep Tuesday evenings and nothing else reliably, so the year rung is "
    "shaped around one weekly block rather than a daily practice.",
    "clarifying_questions": [],
}

ONE_RUNG_ONLY = {
    "goals": [LADDER[1]],
    "rationale": "Stopped at three years.",
    "clarifying_questions": [],
}

CASCADER_WRITES = [
    ToolUse("read_graph", {"user_id": USER, "layer": "person"}),
    ToolUse("write_graph", {"user_id": USER, "layer": "goals", "patch": {"goals": LADDER}}),
    Structured(CASCADED),
]

# -- the Route Planner ------------------------------------------------------

PROPOSED_TASKS = ("t-handover-notes", "t-handover-pair", "t-wedding-leave")

ROUTES = {
    "routes": [
        {
            "id": "r-handover",
            "goal_id": "g-handover",
            "title": "Write down the two things only I can do",
            "cadence": "Tuesdays 19:00",
            "rationale": "Tuesday 19:00 is the slot they actually keep - it is in honoured_slots.",
            "status": "proposed",
            "tasks": [
                {
                    "id": "t-handover-notes",
                    "route_id": "r-handover",
                    "title": "Write three sentences on what only I can do",
                },
                {
                    "id": "t-handover-pair",
                    "route_id": "r-handover",
                    "title": "Pair with someone on the first of them",
                    "depends_on": ["t-handover-notes"],
                },
            ],
        },
        {
            "id": "r-wedding",
            "goal_id": "g-lisbon",
            "title": "Clear the week",
            "cadence": "One-off, this week",
            "rationale": "Fixed date, so everything else moves around it.",
            "status": "proposed",
            "tasks": [
                {
                    "id": "t-wedding-leave",
                    "route_id": "r-wedding",
                    "title": "Confirm the leave dates",
                    "deadline": "2026-09-15",
                }
            ],
        },
    ],
    "rationale": "Both routes want Tuesday evening; the wedding has a fixed date and wins it.",
    "clarifying_questions": [],
}

ROUTE_PLANNER_ASKS = {
    "routes": [],
    "rationale": "Cannot propose a cadence without knowing how much time they have.",
    "clarifying_questions": ["How many evenings a week can you give this?"],
}

# -- the Scheduler ----------------------------------------------------------

CONTENDED = {
    "placed": [
        {
            "task_id": "t-wedding-leave",
            "start": "2026-09-15T12:00:00",
            "duration_min": 30,
            "calendar_event_id": "created001",
        },
        {
            "task_id": "t-handover-notes",
            "start": "2026-09-16T07:00:00",
            "duration_min": 60,
            "calendar_event_id": "created002",
        },
    ],
    "deprioritised": [
        {
            "task_id": "t-handover-pair",
            "wanted": "Tue 19:00",
            "lost_to": "Speaking club, which is the one slot they have kept every week",
            "reason": "It also depends on t-handover-notes, which is not done until Wednesday, "
            "and g-lisbon has a fixed deadline five days out.",
        }
    ],
    "rationale": "The wedding has a date nobody can move, so it took the first free slot. The "
    "handover work serves a fifteen-year goal with no deadline, so it took what was left and "
    "one task waited.",
}

DROPS_A_TASK = {
    "placed": CONTENDED["placed"],
    "deprioritised": [],
    "rationale": "Everything fitted.",
}

SCHEDULER_PLACES = [
    ToolUse("read_graph", {"user_id": USER, "layer": "all"}),
    ToolUse(
        "find_free_slots",
        {"start": "2026-09-11T00:00:00", "end": "2026-09-18T00:00:00", "duration_min": 60},
    ),
    ToolUse(
        "create_event",
        {"title": "Confirm the leave dates", "start": "2026-09-15T12:00:00", "duration_min": 30},
    ),
]


def intake(store, model, **kwargs):
    """The real Intake graph: real agent modules, real tools, scripted choices."""
    return build_intake_graph(
        store=store,
        user_id=USER,
        clock=CLOCK,
        model=model,
        registry=ToolRegistry([*ALL_GRAPH_TOOLS, *ALL_FAKE_CONNECTORS]),
        **kwargs,
    )


def order(result) -> list[str]:
    return [node.node_id for node in result.execution_order]


def full_run(store, router, scheduler_turn):
    return router(
        {
            "extractor": [ToolUse("read_graph", {"user_id": USER, "layer": "goals"}), Structured(CLEAR)],
            "cascader": CASCADER_WRITES,
            "route_planner": [
                ToolUse("read_graph", {"user_id": USER, "layer": "all"}),
                Structured(ROUTES),
            ],
            "scheduler": [*SCHEDULER_PLACES, Structured(scheduler_turn)],
        }
    )


# -- contention -------------------------------------------------------------


async def test_a_contended_week_says_what_lost_and_why(store, router):
    """An empty ``deprioritised`` on a contended week is a bug, not a clean run.

    Placing one task in one free slot is a calendar app. Saying which goal lost
    the slot, to what, and on what grounds is the part that is not copied in a
    weekend.

    Mutation: script the Scheduler to return ``deprioritised: []`` and this goes
    red -- see ``test_nothing_the_route_planner_proposed_is_silently_dropped``.
    """
    _, model = full_run(store, router, CONTENDED)
    result = await intake(store, model, include_resource_finder=False).run(TRANSCRIPT)

    decision = typed_result(result, "scheduler", ScheduleDecision)
    assert decision.placed, "nothing was placed at all"
    assert decision.deprioritised, "a contended week with nothing deprioritised is a bug"

    for lost in decision.deprioritised:
        assert lost.wanted.strip(), "a deprioritised task must name the slot it wanted"
        assert lost.lost_to.strip(), "and what took that slot instead"
        assert lost.reason.strip(), "and the ground on which it lost"


async def test_nothing_the_route_planner_proposed_is_silently_dropped(store, router):
    """Every task reaches a slot or reaches the list of what did not.

    This is the guard that matters. A scheduler reporting only what it placed is
    hiding the decision it actually made, and the user cannot argue with a
    decision they cannot see.
    """
    _, model = full_run(store, router, CONTENDED)
    result = await intake(store, model, include_resource_finder=False).run(TRANSCRIPT)

    decision = typed_result(result, "scheduler", ScheduleDecision)
    accounted = {placement.task_id for placement in decision.placed} | {
        lost.task_id for lost in decision.deprioritised
    }
    missing = set(PROPOSED_TASKS) - accounted
    assert not missing, f"proposed and then never mentioned again: {sorted(missing)}"


async def test_a_scheduler_that_hides_a_task_fails_the_same_guard(store, router):
    """The control for the test above: the assertion can actually fail."""
    _, model = full_run(store, router, DROPS_A_TASK)
    result = await intake(store, model, include_resource_finder=False).run(TRANSCRIPT)

    decision = typed_result(result, "scheduler", ScheduleDecision)
    accounted = {placement.task_id for placement in decision.placed} | {
        lost.task_id for lost in decision.deprioritised
    }
    assert set(PROPOSED_TASKS) - accounted, (
        "this fixture deliberately drops a task; if it is accounted for, the guard above "
        "is asserting something that cannot fail"
    )


# -- nothing is planned on a misheard goal ----------------------------------


async def test_unclear_speech_reaches_no_calendar_at_all(store, router):
    """The Intake graph stops after the Extractor, on purpose.

    ``extraction_confidence`` is a routing field. Below the floor, or with any
    clarifying question, the run ends here -- so nothing is decomposed, nothing
    is planned, and nothing is written into a real week on a guess.
    """
    routed, model = router(
        {
            "extractor": [
                ToolUse("read_graph", {"user_id": USER, "layer": "goals"}),
                Structured(MUDDY),
            ]
        }
    )
    composed = intake(store, model, include_resource_finder=False)
    state = {"second": {"store": store, "user_id": USER, "clock": CLOCK}}
    result = await composed.graph.invoke_async("umm, fitness stuff", state)

    assert [node.node_id for node in result.execution_order] == ["extractor"]
    assert routed.ran("cascader") == 0, "a misheard goal was decomposed anyway"
    assert routed.ran("scheduler") == 0

    effects = state["second"].get("fake_effects", [])
    assert not any(effect["kind"] == "create_event" for effect in effects)

    extraction = typed_result(result, "extractor", ExtractionResult)
    assert extraction.clarifying_questions, "stopping without asking anything helps nobody"


async def test_clear_speech_runs_the_whole_chain(store, router):
    """The complement, so the stop above is a decision and not a dead edge."""
    _, model = full_run(store, router, CONTENDED)
    result = await intake(store, model, include_resource_finder=False).run(TRANSCRIPT)

    assert order(result) == ["extractor", "cascader", "route_planner", "scheduler"]


# -- the ladder survives a failure further down -----------------------------


async def test_the_ladder_is_persisted_before_anything_is_scheduled(store, router):
    """Why the Cascader has ``write_graph`` and the Extractor does not.

    Here the Route Planner asks a question instead of proposing routes, so the
    Scheduler places nothing and writes nothing. The goals the person actually
    spoke must still be in the graph afterwards. **Failure direction: a
    scheduling failure costs the routes, not the ladder.**
    """
    _, model = router(
        {
            "extractor": [Structured(CLEAR)],
            "cascader": CASCADER_WRITES,
            "route_planner": [
                ToolUse("read_graph", {"user_id": USER, "layer": "all"}),
                Structured(ROUTE_PLANNER_ASKS),
            ],
            "scheduler": [
                ToolUse("read_graph", {"user_id": USER, "layer": "all"}),
                Structured({"placed": [], "deprioritised": [], "rationale": "No routes to place."}),
            ],
        }
    )
    await intake(store, model, include_resource_finder=False).run(TRANSCRIPT)

    goals = {goal.id: goal for goal in store.load(USER).goals}
    assert "g-outlast" in goals, "the ambition the user spoke was lost"
    assert "g-handover" in goals, "the rung that can hold work was lost"
    assert goals["g-handover"].contributes_to == "g-durable"


async def test_cascading_does_not_stop_one_rung_short(store, router):
    """A life goal walked down to three years is progress and is not done.

    Three years still cannot hold a calendar slot, so the chain has to reach
    ``year`` or nearer before it stops.
    """
    _, model = full_run(store, router, CONTENDED)
    result = await intake(store, model, include_resource_finder=False).run(TRANSCRIPT)

    cascade = typed_result(result, "cascader", CascadeResult)
    horizons = {goal.horizon for goal in cascade.goals}
    assert horizons & SCHEDULABLE_HORIZONS, (
        f"cascaded to {sorted(horizons)} and stopped; nothing there can hold a slot"
    )

    graph = store.load(USER)
    bottom = next(goal for goal in cascade.goals if goal.horizon in SCHEDULABLE_HORIZONS)
    chain = [rung.id for rung in graph.ladder(bottom.id)]
    assert chain[-1] == "g-outlast", f"the ladder does not reach the ambition: {chain}"


async def test_a_cascade_that_stops_at_three_years_fails_the_same_guard(store, router):
    """The control: the guard above is not asserting something always true."""
    _, model = router(
        {
            "extractor": [Structured(CLEAR)],
            "cascader": [
                ToolUse("read_graph", {"user_id": USER, "layer": "person"}),
                Structured(ONE_RUNG_ONLY),
            ],
            "route_planner": [Structured(ROUTE_PLANNER_ASKS)],
            "scheduler": [
                Structured({"placed": [], "deprioritised": [], "rationale": "Nothing to place."})
            ],
        }
    )
    result = await intake(store, model, include_resource_finder=False).run(TRANSCRIPT)

    cascade = typed_result(result, "cascader", CascadeResult)
    assert not {goal.horizon for goal in cascade.goals} & SCHEDULABLE_HORIZONS
