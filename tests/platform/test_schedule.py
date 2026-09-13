"""Every day has a schedule: what is placed, and what the routes' own cadence proposes.

Proposals are arithmetic on the user's own words, so these tests pin the arithmetic. Most of all
they pin the three refusals, because each opposite behaviour is a plan the user has already shown
they will not keep: a guessed cadence, a slot they keep abandoning, a block on top of another.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from pydantic import ValidationError

from second.core.clock import Clock
from second.core.models import ScheduledBlock
from second.graphs.brief import blocks_on
from second.graphs.schedule import CadenceUnreadable, build_schedule, parse_cadence
from second.testing import demo_scenario

TZ = "Europe/London"
TODAY = date(2026, 9, 10)


@pytest.fixture
def clock() -> Clock:
    return Clock.fixed(TODAY, zone_name=TZ)


@pytest.fixture
def graph():
    return demo_scenario.living_graph()


def proposed(schedule):
    return [block for day in schedule.days for block in day.blocks if block.status == "proposed"]


def refused(schedule):
    return [skip for day in schedule.days for skip in day.skipped]


# -- reading a cadence -------------------------------------------------------


@pytest.mark.parametrize(
    ("cadence", "weekdays", "at", "fortnightly"),
    [
        ("Tuesdays 19:00", {1}, time(19, 0), False),
        ("Mon/Wed/Fri 18:00", {0, 2, 4}, time(18, 0), False),
        ("Weekday mornings 08:00", {0, 1, 2, 3, 4}, time(8, 0), False),
        ("Daily 07:30", set(range(7)), time(7, 30), False),
        ("every day at 21:00", set(range(7)), time(21, 0), False),
        ("Every other Thursday", {3}, None, True),
        ("Weekly, Friday 07:00", {4}, time(7, 0), False),
        ("Weekends 09:00", {5, 6}, time(9, 0), False),
        ("Fortnightly on Thursdays 17:00", {3}, time(17, 0), True),
    ],
)
def test_the_common_cadence_shapes_are_read(cadence, weekdays, at, fortnightly):
    read = parse_cadence(cadence)
    assert set(read.weekdays) == weekdays
    assert read.at == at
    assert read.fortnightly is fortnightly


@pytest.mark.parametrize(
    ("cadence", "weekdays"),
    [
        ("Mon-Fri", {0, 1, 2, 3, 4}),
        ("Mon - Fri 07:00", {0, 1, 2, 3, 4}),
        ("Mon–Fri", {0, 1, 2, 3, 4}),
        ("Monday to Friday", {0, 1, 2, 3, 4}),
        ("Tuesday through Thursday", {1, 2, 3}),
        ("Mon until Wed", {0, 1, 2}),
        ("between Monday and Friday", {0, 1, 2, 3, 4}),
        ("Sat-Sun 09:00", {5, 6}),
        ("Mon-Wed, Fri", {0, 1, 2, 4}),
    ],
)
def test_a_day_range_covers_every_day_in_it(cadence, weekdays):
    """"Mon-Fri" was read as Monday and Friday, dropping three days without a word.

    Mutation-tested: removing ``days.update(range(start, end + 1))`` in ``_read_days`` leaves only
    the two ends and this fails.
    """
    assert set(parse_cadence(cadence).weekdays) == weekdays


@pytest.mark.parametrize(
    ("cadence", "at"),
    [
        ("7:30 pm Tuesdays", time(19, 30)),
        ("Tuesdays 7pm", time(19, 0)),
        ("Tuesdays 7 p.m.", time(19, 0)),
        ("Tuesdays 7am", time(7, 0)),
        ("Tuesdays 12am", time(0, 0)),
        ("Tuesdays 12pm", time(12, 0)),
        ("Tuesdays 12:30am", time(0, 30)),
        ("Tuesdays noon", time(12, 0)),
        ("Tuesdays 19:00", time(19, 0)),
    ],
)
def test_am_and_pm_are_read_on_a_24_hour_clock(cadence, at):
    """"7:30 pm Tuesdays" was read as 07:30 and "Tuesdays 7pm" as no time at all.

    Mutation-tested: dropping the twelve hours added for pm in ``_read_time`` reads 7pm as 07:00 and
    this fails.
    """
    read = parse_cadence(cadence)
    assert read.weekdays == frozenset({1})
    assert read.at == at


@pytest.mark.parametrize(
    ("cadence", "weekdays"),
    [
        ("Sun 09:00", {6}),
        ("Sat/Sun", {5, 6}),
        ("on Sun", {6}),
        ("Sat mornings 09:00", {5}),
        ("Weekdays 06:00 at sun up", {0, 1, 2, 3, 4}),
    ],
)
def test_an_abbreviated_day_counts_only_where_it_is_plainly_a_day(cadence, weekdays):
    """"sun" in "at sun up" is the sun, not Sunday.

    Mutation-tested: making ``_counts_as_day`` return True for every abbreviation puts Sunday into
    the weekday cadence and this fails.
    """
    assert set(parse_cadence(cadence).weekdays) == weekdays


@pytest.mark.parametrize(
    "cadence",
    [
        "One-off, before the end of the month",
        "When I feel like it",
        "Once a month",
        "Every other day",
        "Tue 07:00 and 19:00",
        "Every day except Sunday 07:00",
        "",
        # a range that runs backwards is not wrapped round the weekend
        "Fri-Mon",
        "Friday to Monday",
        "Sunday through Saturday",
        # a frequency or an exception the parser cannot honour
        "twice a week",
        "Twice a week, evenings",
        "3 times a week",
        "three times a week",
        "Mon/Wed/Fri, 3x a week",
        "Weekdays 07:00, not in August",
        "Tuesdays 19:00, not on bank holidays",
        "Weekdays except Friday",
        "every other day at 07:00",
        "Fortnightly",
        "every third Tuesday",
        # "sun" in a phrase is not Sunday, and a time relative to sunrise is not a clock time
        "Before sun up",
        "sun up",
        # times that are not times
        "Tue 13pm",
        "Tuesdays at 7",
        # a choice of days is not both days
        "Tue or Thu 19:00",
    ],
)
def test_a_cadence_second_cannot_read_is_refused_with_a_reason(cadence):
    """"Once a month" is in here to prove "month" is never read as Monday.

    Mutation-tested: removing the ``_FREQUENCY`` refusal in ``parse_cadence`` reads
    "Mon/Wed/Fri, 3x a week" as three fixed days and this fails.
    """
    with pytest.raises(CadenceUnreadable) as refused_with:
        parse_cadence(cadence)
    assert str(refused_with.value).strip()
    assert "'" not in str(refused_with.value).replace("'s", ""), "quoted in typographic quotes, not repr"


# -- the shape of the week ---------------------------------------------------


def test_every_day_in_the_span_is_present_even_an_empty_one(graph, clock):
    """An empty Saturday and a Saturday the server forgot must look different."""
    schedule = build_schedule(graph, clock)

    assert [day.on for day in schedule.days] == [TODAY + timedelta(days=offset) for offset in range(7)]
    saturday = next(day for day in schedule.days if day.on == date(2026, 9, 12))
    assert saturday.blocks == []


def test_placed_blocks_are_exactly_what_blocks_on_says(graph, clock):
    """Placed work is read through the brief's own function, never re-derived."""
    for day in build_schedule(graph, clock).days:
        placed = [block for block in day.blocks if block.status == "placed"]
        assert placed == blocks_on(graph, clock, day.on)


def test_the_demo_week(graph, clock):
    """What the demo world proposes, pinned so a change to it is a deliberate one."""
    schedule = build_schedule(graph, clock)

    assert sorted((block.task_id, block.start.isoformat()) for block in proposed(schedule)) == [
        ("t-club", "2026-09-15T19:00:00+01:00"),
        ("t-recording", "2026-09-11T08:00:00+01:00"),
        ("t-recording", "2026-09-14T08:00:00+01:00"),
        ("t-recording", "2026-09-15T08:00:00+01:00"),
        ("t-recording", "2026-09-16T08:00:00+01:00"),
    ]


# -- the three refusals ------------------------------------------------------


def test_an_abandoned_slot_is_never_proposed(graph, clock):
    """The gym has failed at 18:00 on Mon, Wed and Fri. Proposing it there again is the one move
    the person layer exists to prevent, and the refusal is recorded so the empty evening explains
    itself.

    Mutation-tested: removing the abandoned-slot check in ``_propose`` puts the gym back at 18:00
    on three days and this fails.
    """
    schedule = build_schedule(graph, clock)

    labels = {clock.slot_label(block.start) for block in proposed(schedule)}
    assert not labels & set(graph.person.abandoned_slots)

    gym = [skip for skip in refused(schedule) if skip.task_id == "t-gym"]
    assert {skip.wanted for skip in gym} == {"Fri 18:00", "Mon 18:00", "Wed 18:00"}
    for skip in gym:
        assert "abandoned" in skip.reason
        assert skip.wanted in skip.reason, "the refusal cites the slot it refused"


def test_an_unreadable_cadence_is_skipped_with_a_reason_not_guessed(graph, clock):
    """"One-off, before the end of the month" has no day in it. Picking one would be inventing a
    slot.

    Mutation-tested: dropping the ``unplaceable(...)`` call on ``CadenceUnreadable`` makes the
    route vanish without a word and this fails.
    """
    schedule = build_schedule(graph, clock)

    travel = [skip for skip in schedule.skipped if skip.route_id == "r-travel"]
    assert len(travel) == 1
    assert travel[0].on is None
    assert travel[0].wanted == "One-off, before the end of the month"
    assert "one-off" in travel[0].reason
    assert not [block for block in proposed(schedule) if block.task_id in ("t-leave", "t-flights")]


def test_nothing_is_proposed_after_the_goal_deadline(graph, clock):
    """None of the speaking tasks has a deadline of its own, so only the goal's can stop them.

    Mutation-tested: removing the goal-deadline check in ``_propose`` proposes the club and the
    recording on Tue 15 and Wed 16 and this fails.
    """
    graph.goal_by_id("g-speaking").deadline = date(2026, 9, 14)
    assert all(task.deadline is None for route in graph.goal_by_id("g-speaking").routes for task in route.tasks)

    schedule = build_schedule(graph, clock)

    late = [block for block in proposed(schedule) if block.goal_id == "g-speaking" and block.start.date() > date(2026, 9, 14)]
    assert late == []
    assert [block.start.date() for block in proposed(schedule) if block.task_id == "t-recording"] == [
        date(2026, 9, 11),
        date(2026, 9, 14),
    ], "days up to and including the deadline are still proposed"

    after = [skip for skip in refused(schedule) if skip.on is not None and skip.on > date(2026, 9, 14)]
    assert {(skip.task_id, skip.on) for skip in after} >= {
        ("t-club", date(2026, 9, 15)),
        ("t-recording", date(2026, 9, 15)),
        ("t-recording", date(2026, 9, 16)),
    }
    for skip in after:
        if skip.task_id in ("t-club", "t-recording"):
            assert skip.reason == (
                "“Get comfortable speaking to a room”, the goal this serves, has a deadline of "
                "Mon 14 Sep, and this day is after it."
            )


def test_a_proposal_never_overlaps_a_placed_block(graph, clock):
    """A placed block is a promise. A proposal on top of it is a double booking.

    Mutation-tested: removing the overlap check in ``_propose`` proposes the club at 19:00 on
    top of a gym session placed at 19:30 and this fails.
    """
    graph.task_by_id("t-gym").scheduled_slots.append(datetime(2026, 9, 15, 19, 30))

    schedule = build_schedule(graph, clock)
    tuesday = next(day for day in schedule.days if day.on == date(2026, 9, 15))

    assert not [block for block in tuesday.blocks if block.task_id == "t-club"]
    clash = next(skip for skip in tuesday.skipped if skip.task_id == "t-club")
    assert "Gym session" in clash.reason

    for day in schedule.days:
        placed = [block for block in day.blocks if block.status == "placed"]
        for block in (block for block in day.blocks if block.status == "proposed"):
            ends = block.start + timedelta(minutes=block.duration_min)
            for other in placed:
                assert not (
                    block.start < other.start + timedelta(minutes=other.duration_min) and other.start < ends
                ), f"{block.task_id} proposed on top of {other.task_id} on {day.on}"


# -- what is never proposed --------------------------------------------------


def test_a_day_the_route_already_holds_gets_no_second_block(graph, clock):
    """Thursday already has the recording placed at 08:00; a projection does not add another."""
    thursday = build_schedule(graph, clock).days[0]

    assert [block.status for block in thursday.blocks] == ["placed", "placed", "placed"]


def test_done_work_is_never_proposed(graph, clock):
    graph.task_by_id("t-recording").status = "done"

    schedule = build_schedule(graph, clock)

    assert not [block for block in proposed(schedule) if block.task_id == "t-recording"]


def test_a_paused_goal_and_an_unapproved_route_propose_nothing(graph, clock):
    """Pausing a goal frees its time, and a route the user never approved is not their plan."""
    graph.goal_by_id("g-speaking").status = "paused"
    graph.goal_by_id("g-fitness").routes[0].status = "proposed"

    schedule = build_schedule(graph, clock)

    assert proposed(schedule) == []
    assert not [skip for skip in refused(schedule) if skip.task_id == "t-gym"]


def test_a_route_with_only_blocked_work_says_so(graph, clock):
    graph.task_by_id("t-recording").status = "blocked"

    schedule = build_schedule(graph, clock)

    daily = next(skip for skip in schedule.skipped if skip.route_id == "r-daily")
    assert "blocked" in daily.reason


def test_nothing_is_proposed_in_the_past(graph, clock):
    """The clock reads 09:00, so an 08:00 recording today is already gone."""
    task = graph.task_by_id("t-recording")
    task.scheduled_slots = [slot for slot in task.scheduled_slots if slot.date() != TODAY]

    thursday = build_schedule(graph, clock).days[0]

    assert not [block for block in thursday.blocks if block.task_id == "t-recording"]
    assert any("already passed" in skip.reason for skip in thursday.skipped)


# -- alternating weeks and borrowed times ------------------------------------


def test_every_other_week_counts_from_the_most_recent_slot(graph, clock):
    """The pitch was last placed Thu 10 Sep, so the next one is Thu 24, not Thu 17."""
    schedule = build_schedule(graph, clock, days=15)

    pitches = [block for block in proposed(schedule) if block.task_id == "t-pitch"]
    assert [block.start.date() for block in pitches] == [date(2026, 9, 24)]
    assert pitches[0].start.time() == time(17, 0)
    assert "names no time" in pitches[0].why, "a borrowed time says where it came from"


def test_a_cadence_with_no_time_and_no_history_is_not_given_one(graph, clock):
    graph.task_by_id("t-pitch").scheduled_slots = []

    schedule = build_schedule(graph, clock, days=15)

    pitch = next(skip for skip in schedule.skipped if skip.route_id == "r-pitch")
    assert "names no time" in pitch.reason
    assert not [block for block in proposed(schedule) if block.task_id == "t-pitch"]


# -- telling a proposal from a plan ------------------------------------------


def test_a_proposed_block_is_marked_and_says_why(graph, clock):
    """The screen must be able to tell a projection from a booking, and say what it rests on."""
    club = next(block for block in proposed(build_schedule(graph, clock)) if block.task_id == "t-club")

    assert club.status == "proposed"
    assert "Tuesdays 19:00" in club.why
    assert "Tue 19:00 is a slot you keep" in club.why
    assert club.serves == ["Raise a Series A", "Build a company that outlives me"]


def test_a_proposal_with_no_reason_cannot_be_built():
    """Mutation-tested: removing ``ScheduledBlock._a_proposal_says_why`` makes this fail."""
    fields = dict(
        task_id="t1",
        goal_id="g1",
        goal_title="Goal",
        horizon="year",
        title="Task",
        start=datetime(2026, 9, 11, 8, 0),
        duration_min=60,
    )
    assert ScheduledBlock(**fields).status == "placed", "a placed block needs no why"
    with pytest.raises(ValidationError):
        ScheduledBlock(**fields, status="proposed", why="  ")


def test_building_a_schedule_changes_nothing_in_the_graph(graph, clock):
    """Proposals are never written anywhere, not even into the object they were read from."""
    before = graph.model_dump()
    build_schedule(graph, clock, days=28)
    assert graph.model_dump() == before


def test_a_schedule_needs_at_least_one_day(graph, clock):
    with pytest.raises(ValueError):
        build_schedule(graph, clock, days=0)
