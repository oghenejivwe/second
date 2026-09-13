"""Generate the web fixtures from the real code, not by hand.

**Why this exists.** SURFACES has to build four screens against payloads the
backend cannot serve yet: ``second.agents`` does not exist, so every graph run
raises ``MissingAgent``, and there are no AWS credentials, so the store cannot
be reached. The brief's default is "build against a fixture and keep going".

A hand-written fixture would have been the obvious move and it would have been
wrong. It drifts from ``core/models.py`` the first time PLATFORM lands a field,
and it drifts silently -- the screens keep rendering, against a shape the API
never sends. So every fixture here comes out of the real thing:

* ``moto`` gives real DynamoDB semantics in-process, so the real
  ``LivingGraphStore`` is exercised.
* ``ScriptedModel`` supplies the model's *choices* while the real ``Graph``,
  the real ``@tool`` dispatch and the real hook registries run.
* The payloads are dumped from ``second.graphs.service`` -- the same functions
  the routes call -- so a fixture cannot have a shape the route does not.

Run it whenever the contract moves:

    python web/scripts/make_fixtures.py

Two things are deliberately pinned rather than discovered:

``TIMEZONE``
    ``resolve_clock()`` falls back to the machine's zone until CONNECTORS lands
    ``get_calendar_timezone``, which would make these fixtures depend on where
    the generator ran. Pinned to the demo's own zone instead.

``demo_scenario.TODAY``
    The scenario's fixed "now". A fixture that changes shape overnight is worse
    than no fixture.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

import boto3
from moto import mock_aws
from strands import Agent

from second.core.clock import Clock
from second.core.deps import AgentDeps
from second.core.models import (
    BriefJudgement,
    Diagnosis,
    ExtractionResult,
    ObservationReport,
    PreparedAction,
    ScheduleDecision,
)
from second.graphs import service
from second.graphs.brief import blocks_on
from second.graphs.composition import AgentSpec, ToolRegistry
from second.graphs.wording import plural, quoted
from second.persistence.store import LivingGraphStore
from second.testing import demo_scenario
from second.testing.fake_connectors import ALL_FAKE_CONNECTORS, read_fake_calendar
from second.testing.scripted_model import ScriptedModel, Structured, Text, ToolUse
from second.tools.graph_tools import ALL_GRAPH_TOOLS

OUT = Path(__file__).resolve().parent.parent / "src" / "fixtures"
TIMEZONE = "Europe/London"
REGION = "us-west-2"
TABLE = "second_graph"
USER = demo_scenario.USER_ID
TODAY = demo_scenario.TODAY

NEXT_MORNING = TODAY + timedelta(days=1)
"""The second day of the scenario.

Originally a workaround: ``build_check_in`` reconciles ``clock.today - 1``, and
the seeded world had nothing scheduled on 2026-09-09, so the check-in came back
empty and ``DailyBrief.check_in`` was always ``None`` on the demo day. Reported
to PLATFORM, who seeded the day before; TODAY now yields two items, one of them
the honest ``unknown``.

Kept anyway, because the two days show different shapes and both are worth
being able to put on screen: TODAY has three blocks and a two-item check-in,
this one has a single block and three items. Nothing is hand-edited either way
-- it is the same ``run_daily`` on a different date."""

WINDOW_START = demo_scenario.HISTORY_START.isoformat() + "T00:00:00"
WINDOW_END = (TODAY + timedelta(days=1)).isoformat() + "T00:00:00"


# ---------------------------------------------------------------------------
# Scaffolding
# ---------------------------------------------------------------------------


def spec(node_id: str, script: list[Any], *, tools: tuple[str, ...] = (), output_model=None) -> AgentSpec:
    """A stub agent that follows a script. AGENTS will replace every one of these."""

    def factory(deps: AgentDeps) -> Agent:
        return Agent(
            name=node_id,
            model=ScriptedModel(script, agent_tool_names=[tool.tool_name for tool in deps.tools]),
            tools=list(deps.tools),
            hooks=list(deps.hooks),
            structured_output_model=output_model,
            system_prompt=f"fixture stub for {node_id}",
        )

    return AgentSpec(node_id, tools, output_model, factory)


def registry() -> ToolRegistry:
    return ToolRegistry([*ALL_GRAPH_TOOLS, *ALL_FAKE_CONNECTORS])


def fixed_clock(on=None) -> Clock:
    return Clock.fixed(on or TODAY, zone_name=TIMEZONE)


@contextmanager
def pinned_zone():
    """Make ``service`` resolve the demo's zone without asking a real calendar.

    ``service._clock_for`` calls ``resolve_clock()``, which reads the timezone from Google when a
    token is configured and from the machine otherwise. Either way the fixture would depend on
    where it was generated, which is the thing ``TIMEZONE`` above is pinned to prevent. Used around
    the schedule and memory fixtures only, so every earlier fixture is generated exactly as before.
    """
    with mock.patch.object(service, "resolve_clock", lambda *_args, **_kwargs: fixed_clock()):
        yield


def write(name: str, payload: Any) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  {name:26} {path.stat().st_size:>7,} bytes")


def fresh_store(stack) -> LivingGraphStore:
    """A real store, real DynamoDB semantics, seeded with the demo world."""
    boto3.client("dynamodb", region_name=REGION).create_table(
        TableName=TABLE,
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
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    store = LivingGraphStore(table=table)
    store.save(demo_scenario.living_graph())
    service.set_store(store)
    return store


# ---------------------------------------------------------------------------
# The Observer's report, built from whatever actually sat on yesterday
# ---------------------------------------------------------------------------


def observation_report(reconciling) -> dict[str, Any]:
    """The slots on one day, each with the evidence the check-in will show.

    Derived from the graph rather than hardcoded, so this cannot quietly stop
    matching the scenario. Deliberately mixed: two things the calendar explains,
    one it does not. ``unknown`` with empty evidence is the honest row -- Second
    saying plainly that it could not tell -- and the check-in has to look
    different for it.
    """
    graph = demo_scenario.living_graph()
    clock = fixed_clock(reconciling)

    evidence = {
        "t-gym": (
            "missed",
            "18:00 invite declined; 'Eng sync' (9 attendees) ran at the same time.",
            "calendar",
        ),
        "t-club": ("honoured", "19:00 'Speaking club' accepted and not cancelled.", "calendar"),
        "t-pitch": ("missed", "The 17:00 slot was declined and no draft reached the inbox.", "calendar"),
    }

    observations = []
    for block in blocks_on(graph, clock, reconciling):
        outcome, quote, source = evidence.get(block.task_id, ("unknown", "", "none"))
        observations.append(
            {
                "task_id": block.task_id,
                "scheduled_for": block.start.isoformat(),
                "outcome": outcome,
                "evidence": quote,
                "source": source,
            }
        )

    return {
        "observations": observations,
        "notes": "The 18:00 weekday slot has collided with a standing meeting for three weeks.",
    }


def gym_adaptation(run_day, new_hour: int = 7) -> dict[str, Any]:
    """The Adapter's move for the gym conflict, as the ``adapt_task`` call it makes.

    This replaced a helper that retyped the whole ``g-fitness`` goal with one slot
    changed, for a whole-goal ``write_graph``. The real Adapter no longer has
    ``write_graph``. On a live model that mechanism ran out of output tokens
    mid-goal, and a truncated goal that validated would have erased the slip
    history. So a fixture showing the Adapter calling it would put the one thing
    it cannot do at the centre of the demo's audit panel.

    It also fixes what the old version got wrong by the Adapter prompt's own
    rule. It moved the slot but left the route saying "Mon/Wed/Fri 18:00" with a
    rationale about free evenings, which is a graph that lies. This moves every
    upcoming slot, sets the cadence to match, and rewrites the rationale to cite
    the person-layer fact behind the new time.

    Slots are computed from the run's own date, because the check-in variant runs
    the next morning and a hardcoded date would hand it a slot already in the past.
    """
    graph = demo_scenario.living_graph()
    task = graph.task_by_id("t-gym")
    assert task is not None, "demo_scenario lost t-gym"

    upcoming = {
        slot.replace(hour=new_hour, minute=0)
        for slot in task.scheduled_slots
        if slot.date() >= run_day
    }
    for offset in range(7):
        day = run_day + timedelta(days=offset)
        if day.strftime("%a") in ("Mon", "Wed", "Fri"):
            upcoming.add(datetime(day.year, day.month, day.day, new_hour, 0))

    return {
        "user_id": USER,
        "task_id": "t-gym",
        "reason": (
            "18:00 is recorded as abandoned on Mon, Wed and Fri and loses to Eng sync, "
            "which has nine attendees and is not theirs to move; 07:00 is uncontested."
        ),
        "future_slots": [slot.isoformat() for slot in sorted(upcoming)],
        "cadence": "Mon/Wed/Fri 07:00",
        "rationale": (
            "18:00 is recorded as abandoned on Mon, Wed and Fri; 07:00 is uncontested "
            "and matches a stated early day shape."
        ),
    }


# ---------------------------------------------------------------------------
# Daily: the three states Today actually has
# ---------------------------------------------------------------------------

GYM_CONFLICT = {
    "task_id": "t-gym",
    "blocker_type": "CALENDAR_CONFLICT",
    "evidence": "18:00 gym declined 4 of 5 weekdays; each collided with 'Eng sync' (9 attendees, not owned).",
    "confidence": 0.92,
    "proposed_action": "Move the gym block to 07:00, which is free every weekday.",
    "requires_user_decision": False,
}

HONEST_UNKNOWN = {
    "task_id": "t-recording",
    "blocker_type": "UNKNOWN",
    "evidence": None,
    "confidence": 0.3,
    "proposed_action": "Ask what is actually getting in the way of the morning recording.",
    "requires_user_decision": True,
}

LEAVE_DRAFT = {
    "kind": "email_draft",
    "summary": "Leave request for the wedding week, drafted and waiting in Gmail.",
    "detail": (
        "To: manager@example.com\n"
        "Subject: Annual leave request: wedding week\n\n"
        "Hi,\n\n"
        "I'd like to request leave for the week of 28 September. My sister's wedding is in "
        "Lisbon that week and I need to travel on the Friday before.\n\n"
        "Thanks"
    ),
    "external_ref": "draft-0001",
    "awaiting": "Read it and press send.",
    # The task the draft carries forward, so Memory can show the leave deadline and this draft as
    # one item. A scripted choice like every other field here, and the id is the graph's own.
    "task_id": "t-leave",
}


def received(message_id: str) -> str:
    """The reminder's evidence, with the message's age read from the message's own date.

    This was the literal "received 6 days ago" while the message was nine days old. A hand-written
    age is true for exactly one value of ``demo_scenario.TODAY``, and it had already stopped being.
    """
    message = next(message for message in demo_scenario.inbox() if message["id"] == message_id)
    age = (TODAY - date.fromisoformat(message["date"][:10])).days
    return f"{message_id}, {quoted(message['subject'])}, received {plural(age, 'day')} ago."


REMINDER = {
    "what": "Your sister asked whether the flights are booked. You have not replied.",
    "evidence": received("m-wedding"),
    "source": "email",
}


def daily_specs(
    *, diagnosis: dict, judgement: dict, prepared: dict | None, reconciling
) -> dict[str, AgentSpec]:
    """One scripted Daily graph. The path taken depends only on the diagnosis."""
    preparer_script: list[Any] = [
        ToolUse("search_gmail", {"query": "in:sent leave", "max_results": 5}),
    ]
    if prepared is None:
        preparer_script.append(Text("Nothing needed preparing. The plan already reaches everything."))
    else:
        preparer_script.append(
            ToolUse(
                "draft_email",
                {
                    "to": demo_scenario.MANAGER_EMAIL,
                    "subject": "Annual leave request: wedding week",
                    "body": "Hi,\n\nI'd like to request leave for the week of the wedding.\n\nThanks",
                },
            )
        )
        preparer_script.append(Structured(prepared))

    return {
        "observer": spec(
            "observer",
            [
                ToolUse("get_calendar_events", {"start": WINDOW_START, "end": WINDOW_END}),
                ToolUse("search_gmail", {"query": "wedding", "max_results": 5}),
                ToolUse(
                    "update_person_model",
                    {"user_id": USER, "patch": {"abandoned_slots": ["Wed 18:00"]}},
                ),
                Structured(observation_report(reconciling)),
            ],
            tools=("read_graph", "get_calendar_events", "search_gmail", "update_person_model"),
            output_model=ObservationReport,
        ),
        "diagnostician": spec(
            "diagnostician",
            [
                ToolUse("read_graph", {"user_id": USER, "layer": "goals"}),
                Structured(diagnosis),
            ],
            tools=("read_graph", "record_diagnosis"),
            output_model=Diagnosis,
        ),
        "adapter": spec(
            "adapter",
            [
                # The refusal comes first, and it is the most important row in the
                # audit panel: the Eng sync has nine attendees and the user does
                # not own it, so the tool refuses rather than the prompt talking
                # the model out of it. A rail nobody can see working is a rail a
                # judge has to take on trust.
                ToolUse(
                    "reschedule_event",
                    {"event_id": "engsync000", "new_start": f"{TODAY}T07:00:00"},
                ),
                ToolUse("reschedule_event", {"event_id": "gym000", "new_start": f"{TODAY}T07:00:00"}),
                # The graph change goes through adapt_task, which is the only write
                # the real Adapter has. There is no links write any more: the
                # Adapter cannot write links, and a fixture that showed it doing so
                # would be the one dishonesty this app's own comments forbid.
                ToolUse("adapt_task", gym_adaptation(reconciling + timedelta(days=1))),
                Text("Moved the gym block to 07:00. The 18:00 slot is gone, not postponed."),
            ],
            tools=("read_graph", "reschedule_event", "adapt_task"),
        ),
        "preparer": spec(
            "preparer",
            preparer_script,
            tools=("read_graph", "search_gmail", "draft_email", "web_search"),
            output_model=PreparedAction if prepared else None,
        ),
        "communicator": spec(
            "communicator",
            [Structured(judgement)],
            output_model=BriefJudgement,
        ),
    }


QUIET = {
    "reminders": [],
    "decisions": [],
    "notify": False,
    "silence_reason": "Nothing slipped that Second could not handle, and nothing needs deciding.",
}

PREPARED_JUDGEMENT = {
    "reminders": [REMINDER],
    "decisions": [],
    "notify": True,
    "silence_reason": "",
}

DECISION_JUDGEMENT = {
    "reminders": [REMINDER],
    "decisions": [
        {
            "question": "The 08:00 recording has not happened three weeks running. What is in the way?",
            "task_id": "t-recording",
            "evidence": (
                "Three slips at 08:00 and nothing in the calendar or the inbox explains any of them. "
                "Second has no evidence either way."
            ),
            "options": [
                "Too early -- move it later",
                "I do not want to hear myself back",
                "Nothing in the way, I just did not do it",
            ],
        }
    ],
    "notify": True,
    "silence_reason": "",
}


async def make_daily_fixtures() -> None:
    """Four briefs, one per state Today has to render."""
    variants = [
        ("brief-quiet.json", TODAY, GYM_CONFLICT, QUIET, None, None),
        ("brief-prepared.json", TODAY, GYM_CONFLICT, PREPARED_JUDGEMENT, LEAVE_DRAFT, "audit.json"),
        ("brief-decision.json", TODAY, HONEST_UNKNOWN, DECISION_JUDGEMENT, None, None),
        ("brief-checkin.json", NEXT_MORNING, GYM_CONFLICT, QUIET, None, None),
    ]

    for name, on, diagnosis, judgement, prepared, audit_name in variants:
        with mock_aws():
            store = fresh_store(None)
            brief = await service.run_daily(
                USER,
                today=on,
                model=object(),
                registry=registry(),
                specs=daily_specs(
                    diagnosis=diagnosis,
                    judgement=judgement,
                    prepared=prepared,
                    reconciling=on - timedelta(days=1),
                ),
            )
            write(name, brief.model_dump(mode="json"))

            if audit_name:
                entries = service.read_audit(USER, limit=200)
                write(audit_name, [entry.model_dump(mode="json") for entry in entries])

            # The Adapter moved the gym slots and rewrote the route's cadence and
            # rationale. The Living Graph screen has to show the world AFTER a
            # run, not before it, so both states are checked in and the screen
            # can diff them.
            if name == "brief-prepared.json":
                write("living-graph-after-run.json", store.load(USER).model_dump(mode="json"))

                # Memory and Schedule come from the same store as this brief, after the run, so the
                # three screens agree about the day. Memory reads what the run left behind: the
                # email reminder and the prepared draft live on the cached brief. Schedule reads the
                # graph the Adapter rewrote: the gym route is now Mon/Wed/Fri 07:00 and its
                # rationale cites the abandoned 18:00 slots, so the gym sits at 07:00 here exactly
                # as on Today. The refusal story is carried by the proposed blocks' why, but not in
                # this default week: the Adapter placed the gym on every Mon/Wed/Fri up to Wed 16,
                # so there is no gym proposal and no 18:00 refusal to show. The first gym proposal,
                # with that rationale as its why, is Fri 18 Sep, which only a 14-day span reaches.
                with pinned_zone():
                    memory = service.get_memory(USER, today=on, calendar=read_fake_calendar)
                    schedule = service.get_schedule(USER, today=on)
                write("memory.json", memory.model_dump(mode="json"))
                write("schedule.json", schedule.model_dump(mode="json"))

            if name == "brief-quiet.json":
                # Memory beside the quiet brief: no reminder and no draft, because this run produced
                # neither. The frontend picks this or memory.json by which brief is on screen.
                with pinned_zone():
                    memory = service.get_memory(USER, today=on, calendar=read_fake_calendar)
                write("memory-quiet.json", memory.model_dump(mode="json"))

            service.set_store(None)


# ---------------------------------------------------------------------------
# Intake: the two states Record has to render
# ---------------------------------------------------------------------------

CLEAR_EXTRACTION = {
    "goals": [
        {
            "id": "g-writing",
            "title": "Write in public every week",
            "horizon": "year",
            "extraction_confidence": 0.93,
        }
    ],
    "clarifying_questions": [],
}

MUDDY_EXTRACTION = {
    "goals": [
        {
            "id": "g-fitness-maybe",
            "title": "something about being fitter",
            "horizon": "year",
            "extraction_confidence": 0.41,
        }
    ],
    "clarifying_questions": [
        "When you said fitter, did you mean running, climbing, or the gym?",
        "Is there a date you want to be ready by?",
    ],
}

def writing_goal() -> dict[str, Any]:
    """The goal one clear intake produces, complete with its route and task.

    A scripted Route Planner that only talks writes nothing, which left the
    Scheduler placing ``t-writing-1`` into a graph that had never heard of it --
    and the Record screen said so, correctly, on screen. The screen was right;
    the fixture was wrong. So the node writes the goal it planned, exactly as a
    real one would, and the placement then refers to something that exists.
    """
    return {
        "id": "g-writing",
        "title": "Write in public every week",
        "horizon": "year",
        "contributes_to": "g-raise",
        "status": "active",
        "extraction_confidence": 0.93,
        "routes": [
            {
                "id": "r-writing",
                "goal_id": "g-writing",
                "title": "One short piece, Friday mornings",
                "cadence": "Weekly, Friday 07:00",
                "rationale": (
                    "07:00 is the only slot this person has actually kept, and they said they "
                    "learn by making something rather than by reading about it."
                ),
                "status": "proposed",
                "tasks": [
                    {
                        "id": "t-writing-1",
                        "route_id": "r-writing",
                        "title": "Draft and publish one short piece",
                        "scheduled_slots": [f"{TODAY + timedelta(days=2)}T07:00:00"],
                    }
                ],
            }
        ],
    }


PLACED = {
    "placed": [
        {"task_id": "t-writing-1", "start": f"{TODAY + timedelta(days=2)}T07:00:00", "duration_min": 60},
    ],
    "deprioritised": [
        {
            "task_id": "t-gym",
            "wanted": "Wed 18:00",
            "lost_to": "Eng sync, which you do not own",
            "reason": "Declined four of the last five weeks at that time.",
        }
    ],
    "rationale": (
        "The 07:00 slot is the only one this person has actually kept. Writing took it; "
        "the gym keeps losing 18:00 to a standing meeting, so it was not placed there again."
    ),
}


def intake_specs(extraction: dict, *, plan: bool) -> dict[str, AgentSpec]:
    return {
        "extractor": spec(
            "extractor",
            [Structured(extraction)],
            tools=("read_graph",),
            output_model=ExtractionResult,
        ),
        "cascader": spec("cascader", [Text("Nothing longer than a year needed walking down.")]),
        "route_planner": spec(
            "route_planner",
            [
                ToolUse(
                    "write_graph",
                    {"user_id": USER, "layer": "goals", "patch": {"goals": [writing_goal()]}},
                )
                if plan
                else Text("nothing to plan against"),
                Text("One route: a short piece every Friday at 07:00."),
            ],
            tools=("read_graph", "write_graph"),
        ),
        "scheduler": spec(
            "scheduler",
            [
                ToolUse("find_free_slots", {"start": WINDOW_START, "end": WINDOW_END, "duration_min": 60}),
                Structured(PLACED) if plan else Text("nothing to place"),
            ],
            tools=("read_graph", "find_free_slots", "create_event", "write_graph"),
            output_model=ScheduleDecision if plan else None,
        ),
    }


async def make_intake_fixtures() -> None:
    variants = [
        ("intake-planned.json", CLEAR_EXTRACTION, True, "I want to write in public every week."),
        (
            "intake-questions.json",
            MUDDY_EXTRACTION,
            False,
            "umm, I guess I want to be fitter, sort of, this year maybe",
        ),
    ]

    for name, extraction, plan, transcript in variants:
        with mock_aws():
            fresh_store(None)
            result = await service.run_intake(
                USER,
                transcript,
                today=TODAY,
                model=object(),
                registry=registry(),
                include_resource_finder=False,
                specs=intake_specs(extraction, plan=plan),
            )
            write(name, result.model_dump(mode="json"))
            service.set_store(None)


# ---------------------------------------------------------------------------
# Goals: what retiring actually did
# ---------------------------------------------------------------------------


def make_goal_fixtures() -> None:
    with mock_aws():
        fresh_store(None)
        write("living-graph.json", service.load_living_graph(USER).model_dump(mode="json"))

        change = service.set_goal_status(USER, "g-speaking", "retired", today=TODAY)
        write("goal-retired.json", change.model_dump(mode="json"))
        service.set_store(None)

    with mock_aws():
        fresh_store(None)
        change = service.set_goal_status(USER, "g-lisbon", "paused", today=TODAY)
        write("goal-paused.json", change.model_dump(mode="json"))
        service.set_store(None)


# ---------------------------------------------------------------------------
# The recurring question: answered, and skipped
# ---------------------------------------------------------------------------

WEEK_DEADLINE = TODAY + timedelta(days=8)
"""Friday 18 September on the demo date. Derived, so the spoken answer and the goal cannot disagree."""

WEEK_ANSWER = (
    "Send the leave request today, and book the flights to Lisbon by "
    f"{WEEK_DEADLINE:%A} {WEEK_DEADLINE.day} {WEEK_DEADLINE:%B}."
)

LEAVE_SLOT = datetime.combine(TODAY, datetime.min.time()).replace(hour=12)
FLIGHTS_SLOT = LEAVE_SLOT + timedelta(days=1)


def lisbon_week_goal(*, placed: bool) -> dict[str, Any]:
    """The week goal the answer becomes, with its route and two tasks.

    Written twice, as a real run writes it: by the Route Planner without slots, then by the
    Scheduler with the slots it chose. ``placed`` says which of the two this is.
    """
    return {
        "id": "g-lisbon-week",
        "title": "Send the leave request and book the Lisbon flights",
        "horizon": "week",
        "contributes_to": "g-lisbon",
        "deadline": WEEK_DEADLINE.isoformat(),
        "status": "active",
        "extraction_confidence": 0.95,
        "routes": [
            {
                "id": "r-lisbon-week",
                "goal_id": "g-lisbon-week",
                "title": "Leave request first, then the flights",
                "cadence": "One-off, this week",
                "rationale": (
                    "Booking the flights has slipped twice because leave was not confirmed, so the "
                    "request goes first. Both sit at midday because nothing goes before 09:00 for you."
                ),
                "status": "proposed",
                "tasks": [
                    {
                        "id": "t-lisbon-leave",
                        "route_id": "r-lisbon-week",
                        "title": "Send the leave request",
                        "deadline": TODAY.isoformat(),
                        "scheduled_slots": [LEAVE_SLOT.isoformat()] if placed else [],
                    },
                    {
                        "id": "t-lisbon-flights",
                        "route_id": "r-lisbon-week",
                        "title": "Book the flights to Lisbon",
                        "depends_on": ["t-lisbon-leave"],
                        "deadline": WEEK_DEADLINE.isoformat(),
                        "scheduled_slots": [FLIGHTS_SLOT.isoformat()] if placed else [],
                    },
                ],
            }
        ],
    }


def assert_the_week_slots_are_free() -> None:
    """Stop the generator rather than script a placement into a slot that is not free.

    Each slot must be one the fake calendar offers, at or after 09:00 (the person's own rule), still
    ahead on the demo clock, inside the deadline, and clear of every block already placed that day.
    """
    graph = demo_scenario.living_graph()
    clock = fixed_clock()
    offered = {slot["start"] for slot in demo_scenario.free_slots(60)}
    for slot in (LEAVE_SLOT, FLIGHTS_SLOT):
        begins = clock.local(slot)
        assert slot.isoformat() in offered, f"{slot} is not a free slot in the fake calendar"
        assert slot.hour >= 9, f"{slot} breaks the rule 'No meetings before 09:00'"
        assert begins > clock.now, f"{slot} is already in the past"
        assert slot.date() <= WEEK_DEADLINE, f"{slot} is after the deadline"
        for block in blocks_on(graph, clock, slot.date()):
            ends = block.start + timedelta(minutes=block.duration_min)
            assert not (block.start < begins + timedelta(hours=1) and begins < ends), (
                f"{slot} overlaps {block.title} at {block.start:%H:%M}"
            )


def answer_specs() -> dict[str, AgentSpec]:
    shallow = {key: value for key, value in lisbon_week_goal(placed=False).items() if key != "routes"}
    decision = {
        "placed": [
            {"task_id": "t-lisbon-leave", "start": LEAVE_SLOT.isoformat(), "duration_min": 60},
            {"task_id": "t-lisbon-flights", "start": FLIGHTS_SLOT.isoformat(), "duration_min": 60},
        ],
        "deprioritised": [],
        "rationale": (
            "12:00 today is the first free slot after 09:00, so the leave request goes there. The "
            "flights wait on it, so they take 12:00 tomorrow, the next free slot after 09:00 and a "
            "week before the deadline. Nothing already placed had to move."
        ),
    }
    return {
        "extractor": spec(
            "extractor",
            [Structured({"goals": [shallow], "clarifying_questions": []})],
            tools=("read_graph",),
            output_model=ExtractionResult,
        ),
        "cascader": spec("cascader", [Text("Already a week goal. Nothing to walk down.")]),
        "route_planner": spec(
            "route_planner",
            [
                ToolUse(
                    "write_graph",
                    {"user_id": USER, "layer": "goals", "patch": {"goals": [lisbon_week_goal(placed=False)]}},
                ),
                Text("One route: the leave request, then the flights."),
            ],
            tools=("read_graph", "write_graph"),
        ),
        "scheduler": spec(
            "scheduler",
            [
                ToolUse(
                    "find_free_slots",
                    {
                        "start": f"{TODAY}T09:00:00",
                        "end": f"{WEEK_DEADLINE + timedelta(days=1)}T00:00:00",
                        "duration_min": 60,
                    },
                ),
                ToolUse(
                    "create_event",
                    {"title": "Send the leave request", "start": LEAVE_SLOT.isoformat(), "duration_min": 60},
                ),
                ToolUse(
                    "create_event",
                    {"title": "Book the flights to Lisbon", "start": FLIGHTS_SLOT.isoformat(), "duration_min": 60},
                ),
                ToolUse(
                    "write_graph",
                    {"user_id": USER, "layer": "goals", "patch": {"goals": [lisbon_week_goal(placed=True)]}},
                ),
                Structured(decision),
            ],
            tools=("read_graph", "find_free_slots", "create_event", "write_graph"),
            output_model=ScheduleDecision,
        ),
    }


async def make_question_fixtures() -> None:
    """The week question, answered through the real intake path, and skipped."""
    assert_the_week_slots_are_free()

    with mock_aws():
        fresh_store(None)
        with pinned_zone():
            result = await service.answer_question(
                USER,
                "week",
                WEEK_ANSWER,
                today=TODAY,
                model=object(),
                registry=registry(),
                include_resource_finder=False,
                specs=answer_specs(),
            )
        write("question-answer-week.json", result.model_dump(mode="json"))
        service.set_store(None)

    with mock_aws():
        fresh_store(None)
        with pinned_zone():
            skipped = service.skip_question(USER, "week", today=TODAY)
        write("question-skip-week.json", skipped.model_dump(mode="json"))
        service.set_store(None)


# ---------------------------------------------------------------------------
# The schema, for the type layer
# ---------------------------------------------------------------------------


def make_schema() -> None:
    """One JSON Schema document for every model the browser ever sees.

    ``mode="serialization"`` rather than ``"validation"``, deliberately: it
    describes the types the API *sends* rather than the ones it will accept, and
    where a field's input and output types differ it is the output the screens
    have to render.

    One thing it does **not** do, checked rather than assumed: neither mode marks
    a defaulted field as ``required``, so ``DailyBrief.blocks`` comes out
    optional even though ``model_dump`` always emits it. ``gen-types.mjs`` fixes
    that on the TypeScript side and says why.
    """
    from pydantic.json_schema import models_json_schema

    from second.core import models as contract

    exported = [
        contract.AuditEntry,
        contract.CascadeResult,
        contract.CheckIn,
        contract.CheckInItem,
        contract.CompletionReport,
        contract.DailyBrief,
        contract.Decision,
        contract.Deprioritised,
        contract.Diagnosis,
        contract.ExtractionResult,
        contract.FeedbackResult,
        contract.FeedbackUpdate,
        contract.Goal,
        contract.GoalStatusChange,
        contract.HorizonAsked,
        contract.HorizonQuestion,
        contract.IntakeResult,
        contract.Link,
        contract.LivingGraph,
        contract.Memory,
        contract.MemoryItem,
        contract.MemorySourceStatus,
        contract.Observation,
        contract.ObservationReport,
        contract.PersonModel,
        contract.Placement,
        contract.PreparedAction,
        contract.Reminder,
        contract.Risk,
        contract.Route,
        contract.RoutePlan,
        contract.Schedule,
        contract.ScheduleDay,
        contract.ScheduleDecision,
        contract.ScheduledBlock,
        contract.SkippedProposal,
        contract.Slip,
        contract.Task,
    ]

    _, schema = models_json_schema(
        [(model, "serialization") for model in exported],
        title="SecondContract",
        ref_template="#/$defs/{model}",
    )

    # json-schema-to-typescript emits an interface per $defs entry, but only if
    # the document itself is an object schema it can enter. Without this it
    # compiles the top level to `unknown` and drops every definition.
    schema["type"] = "object"
    schema["properties"] = {
        _camel_to_snake(model.__name__): {"$ref": f"#/$defs/{model.__name__}"} for model in exported
    }
    schema["additionalProperties"] = False

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT.parent / "types" / "contract.schema.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(f"  {'contract.schema.json':26} {path.stat().st_size:>7,} bytes  ({len(exported)} models)")


def _camel_to_snake(name: str) -> str:
    out: list[str] = []
    for index, char in enumerate(name):
        if char.isupper() and index:
            out.append("_")
        out.append(char.lower())
    return "".join(out)


# ---------------------------------------------------------------------------


def main() -> None:
    print(f"Generating fixtures into {OUT}")
    print(f"  user={USER} today={TODAY} zone={TIMEZONE}")
    make_goal_fixtures()
    asyncio.run(make_daily_fixtures())
    asyncio.run(make_intake_fixtures())
    asyncio.run(make_question_fixtures())
    make_schema()
    print("Done.")


if __name__ == "__main__":
    main()
