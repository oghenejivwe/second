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
        # An abbreviation followed by a time counts even when it does not stand alone. The time used
        # to be blanked before this was checked, so "Weekly, Fri 07:00" named no day at all.
        ("Weekly, Fri 07:00", {4}),
        ("Weekdays and Sat 9am", {0, 1, 2, 3, 4, 5}),
        ("Mornings, Sat at 09:00", {5}),
    ],
)
def test_an_abbreviated_day_counts_only_where_it_is_plainly_a_day(cadence, weekdays):
    """Mutation-tested: dropping the time mark from ``_counts_as_day`` leaves "Fri" in "Weekly, Fri
    07:00" uncounted, it is refused as a word Second does not read, and this fails."""
    assert set(parse_cadence(cadence).weekdays) == weekdays


def test_sun_in_a_phrase_is_refused_by_name_not_read_as_sunday():
    """"sun" in "at sun up" is the sun, not Sunday, so it is a word the parser does not read.

    Mutation-tested: making ``_counts_as_day`` return True for every abbreviation reads "sun" as
    Sunday, the reason names only “up”, and this fails.
    """
    with pytest.raises(CadenceUnreadable) as refused_with:
        parse_cadence("Weekdays 06:00 at sun up")
    assert "“sun”" in str(refused_with.value)


# -- the cadence faults the review found --------------------------------------


@pytest.mark.parametrize(
    "cadence",
    [
        "Every other weekday 08:00",
        "every other weekday",
        "Every second weekday",
        "every 2nd weekday, 20 minutes",
        "Alternate weekdays at 7am",
        "Every other weekend 09:00",
    ],
)
def test_every_other_weekday_is_refused_not_read_as_every_weekday(cadence):
    """(1a) "Every other weekday 08:00" was read as every weekday, twice the rhythm the user chose.

    Mutation-tested: removing the ``_ALTERNATE_GROUP`` refusal lets the allowlist refuse it on the
    word “other” instead, so this reason check fails. With the allowlist also removed it read as
    five weekdays.
    """
    with pytest.raises(CadenceUnreadable) as refused_with:
        parse_cadence(cadence)
    assert "alternates over a group of days" in str(refused_with.value)


@pytest.mark.parametrize(
    ("cadence", "words"),
    [
        ("Tuesdays 19:00 during term time", ["during", "term", "time"]),
        ("Weekdays 07:00 if it is dry", ["if", "it", "is", "dry"]),
        ("Mon/Wed/Fri 07:00 in winter", ["in", "winter"]),
        ("Tuesdays 19:00, weather permitting", ["weather", "permitting"]),
        ("Weekday mornings 08:00 while the kids are at school", ["while", "the", "kids", "are", "school"]),
        ("Gym Mon/Wed/Fri 07:00", ["gym"]),
        ("Weeknights 20:00", ["weeknights"]),
        ("Weekdays at 07:00 until the wedding", ["until", "the", "wedding"]),
        ("next Tuesday 19:00", ["next"]),
        ("When I feel like it", ["when", "i", "feel", "like", "it"]),
    ],
)
def test_a_word_the_parser_does_not_read_refuses_the_cadence_and_is_named(cadence, words):
    """(1b) Only listed qualifiers used to be refused, so "during term time" was silently dropped
    and the rhythm proposed all year.

    Mutation-tested: removing the leftover-word refusal in ``parse_cadence`` reads "Tuesdays 19:00
    during term time" as every Tuesday and this fails.
    """
    with pytest.raises(CadenceUnreadable) as refused_with:
        parse_cadence(cadence)
    reason = str(refused_with.value)
    for word in words:
        assert f"“{word}”" in reason, f"{word!r} not named in {reason!r}"


@pytest.mark.parametrize(
    ("cadence", "weekdays", "at"),
    [
        ("Weekday mornings, 15 minutes", {0, 1, 2, 3, 4}, None),
        ("Tuesdays 19:00 for 90 minutes", {1}, time(19, 0)),
        ("Tuesdays 19:00, 1 hour", {1}, time(19, 0)),
        ("Mon/Wed/Fri 07:00 for an hour", {0, 2, 4}, time(7, 0)),
        ("Saturdays 09:00, half an hour", {5}, time(9, 0)),
        ("Thursdays 18:00 for 2 hrs", {3}, time(18, 0)),
        ("Weekdays 07:30, 20 mins", {0, 1, 2, 3, 4}, time(7, 30)),
        ("Tuesdays at 7pm for 1 hour 30 minutes", {1}, time(19, 0)),
        ("Fridays 17:00 (1h)", {4}, time(17, 0)),
        ("Weekdays 08:00 for about 45 min", {0, 1, 2, 3, 4}, time(8, 0)),
    ],
)
def test_a_session_length_is_set_aside_not_read_as_a_time(cadence, weekdays, at):
    """(1c) "Weekday mornings, 15 minutes" is the Route Planner prompt's own example, and its 15 was
    refused as a number that is not a time, so a route written as instructed got no proposals.

    Mutation-tested: making ``_DURATION`` match nothing refuses all of these on the bare number and
    this fails.
    """
    read = parse_cadence(cadence)
    assert set(read.weekdays) == weekdays
    assert read.at == at
    assert read.fortnightly is False


def test_the_route_planners_own_example_proposes_with_a_borrowed_time(graph, clock):
    """End to end: a route written the way route_planner.md shows gets proposals, and the time it
    borrows is said to be borrowed."""
    graph.goal_by_id("g-speaking").routes[1].cadence = "Weekday mornings, 15 minutes"

    schedule = build_schedule(graph, clock)

    recordings = [block for block in proposed(schedule) if block.task_id == "t-recording"]
    assert [block.start.isoformat() for block in recordings] == [
        "2026-09-11T08:00:00+01:00",
        "2026-09-14T08:00:00+01:00",
        "2026-09-15T08:00:00+01:00",
        "2026-09-16T08:00:00+01:00",
    ]
    assert all("names no time" in block.why for block in recordings)


def test_a_borrowed_time_outside_the_named_part_of_the_day_is_not_used(graph, clock):
    """"Weekday evenings" with a last slot at 08:00 would propose an evening session at breakfast."""
    graph.goal_by_id("g-speaking").routes[1].cadence = "Weekday evenings, 15 minutes"

    schedule = build_schedule(graph, clock)

    assert not [block for block in proposed(schedule) if block.task_id == "t-recording"]
    daily = next(skip for skip in schedule.skipped if skip.route_id == "r-daily")
    assert "08:00, is not in the evening" in daily.reason


@pytest.mark.parametrize(
    "cadence", ["every 2 weeks on Tuesday", "every two weeks on Tuesday", "Every 2 weeks, Tuesdays 19:00"]
)
def test_every_2_weeks_and_every_two_weeks_are_both_fortnightly(cadence):
    """(1e) "every 2 weeks on Tuesday" was refused as not repeating every other week, while "every
    two weeks on Tuesday" read, because a bare number in the other-interval rule caught the 2.

    Mutation-tested: putting ``\\d+`` back in the weeks branch of ``_OTHER_INTERVAL`` refuses the
    numeric spellings and this fails.
    """
    read = parse_cadence(cadence)
    assert read.weekdays == frozenset({1})
    assert read.fortnightly is True


def test_a_time_outside_the_named_part_of_the_day_is_refused():
    with pytest.raises(CadenceUnreadable) as refused_with:
        parse_cadence("Tuesday mornings at 19:00")
    assert "not in the morning" in str(refused_with.value)


@pytest.mark.parametrize(
    "cadence",
    ["Weekday mornings 08:00", "Tuesdays 19:00", "Mon/Wed/Fri 07:00", "Mon/Wed/Fri 18:00", "Every other Thursday"],
)
def test_every_demo_cadence_still_reads(cadence):
    parse_cadence(cadence)


@pytest.mark.parametrize(
    ("cadence", "weekdays", "at", "fortnightly"),
    [
        ("Weekday mornings 08:00", {0, 1, 2, 3, 4}, time(8, 0), False),
        ("Tuesdays 19:00", {1}, time(19, 0), False),
        ("Mon/Wed/Fri 07:00", {0, 2, 4}, time(7, 0), False),
        ("Mon/Wed/Fri 18:00", {0, 2, 4}, time(18, 0), False),
        ("Every other Thursday", {3}, None, True),
    ],
)
def test_the_demo_cadences_read_as_pinned_after_the_guessing_fixes(cadence, weekdays, at, fortnightly):
    """The three refusals below must not cost the demo a single proposal."""
    read = parse_cadence(cadence)
    assert (set(read.weekdays), read.at, read.fortnightly) == (weekdays, at, fortnightly)


def test_the_demo_one_off_is_still_refused():
    with pytest.raises(CadenceUnreadable) as refused_with:
        parse_cadence("One-off, before the end of the month")
    assert "one-off" in str(refused_with.value)


@pytest.mark.parametrize(
    "cadence",
    ["Every other Tuesday and Thursday", "every other Tue/Thu 19:00", "Fortnightly on Mon-Wed"],
)
def test_a_fortnight_over_more_than_one_day_is_refused(cadence):
    """"Every other Tuesday and Thursday" made both days fortnightly. It could as well mean Tuesday
    fortnightly and Thursday weekly, and the parser cannot tell which days alternate.

    Mutation-tested: removing the more-than-one-day fortnight refusal in ``parse_cadence`` reads
    both days as fortnightly and this fails.
    """
    with pytest.raises(CadenceUnreadable) as refused_with:
        parse_cadence(cadence)
    assert "cannot tell which of the days alternate" in str(refused_with.value)


@pytest.mark.parametrize(
    ("cadence", "weekday"),
    [("Every other Thursday", 3), ("every 2 weeks on Tuesday", 1)],
)
def test_a_fortnight_on_one_day_still_reads(cadence, weekday):
    read = parse_cadence(cadence)
    assert read.weekdays == frozenset({weekday})
    assert read.fortnightly is True


@pytest.mark.parametrize("cadence", ["Friday nights 1am", "Friday nights 4:59am", "Friday nights midnight"])
def test_a_night_time_after_midnight_is_refused_not_put_on_the_wrong_day(cadence):
    """"Friday nights 1am" is 01:00 on Saturday, and it was proposed at 01:00 on Friday, the night
    before the one the user meant.

    Mutation-tested: removing the after-midnight refusal in ``parse_cadence`` reads it as Friday
    01:00 and this fails.
    """
    with pytest.raises(CadenceUnreadable) as refused_with:
        parse_cadence(cadence)
    reason = str(refused_with.value)
    assert "midnight" in reason and "falls on the next day" in reason


def test_a_night_time_before_midnight_still_reads():
    read = parse_cadence("Friday nights 23:00")
    assert (read.weekdays, read.at, read.part) == (frozenset({4}), time(23, 0), "night")


@pytest.mark.parametrize(
    "cadence",
    ["Mon 7pm and Wed", "Monday 7pm and Wednesday", "Mon 7pm and Wed/Fri", "Weekdays 07:00 and Sat"],
)
def test_a_time_after_only_some_of_the_days_is_refused(cadence):
    """"Monday 7pm and Wednesday" put Wednesday at 19:00, a time the user only wrote beside Monday.

    Mutation-tested: letting ``_one_time`` return the time when days follow it reads Wednesday at
    19:00 and this fails.
    """
    with pytest.raises(CadenceUnreadable) as refused_with:
        parse_cadence(cadence)
    assert "a time after only some of its days" in str(refused_with.value)


@pytest.mark.parametrize(
    ("cadence", "weekdays", "at"),
    [
        ("Wed 7pm and Sun 7pm", {2, 6}, time(19, 0)),
        ("7:30 pm Tuesdays", {1}, time(19, 30)),
        ("Mon, Wed & Fri at 6:30am", {0, 2, 4}, time(6, 30)),
        ("Weekdays and Sat 9am", {0, 1, 2, 3, 4, 5}, time(9, 0)),
    ],
)
def test_a_time_every_day_shares_still_reads(cadence, weekdays, at):
    read = parse_cadence(cadence)
    assert (set(read.weekdays), read.at) == (weekdays, at)


def test_days_with_different_times_are_refused_as_not_one_cadence():
    with pytest.raises(CadenceUnreadable) as refused_with:
        parse_cadence("Mon 7pm and Wed 8pm")
    assert "two different times are not one cadence" in str(refused_with.value)


def test_two_times_on_one_day_are_still_refused_as_a_choice():
    with pytest.raises(CadenceUnreadable) as refused_with:
        parse_cadence("Tue 07:00 and 19:00")
    assert "more than one time" in str(refused_with.value)


def test_a_count_of_mornings_a_week_gets_a_frequency_reason_not_a_clock_time_reason():
    with pytest.raises(CadenceUnreadable) as refused_with:
        parse_cadence("3 mornings a week")
    reason = str(refused_with.value)
    assert "how many times, not which days" in reason
    assert "19:00" not in reason


def test_abbreviated_days_with_only_spaces_between_are_refused_with_how_to_write_them():
    with pytest.raises(CadenceUnreadable) as refused_with:
        parse_cadence("mon wed fri 07:00")
    assert "Write them as Mon/Wed/Fri" in str(refused_with.value)


# A model writes cadences in many small variations. Each is pinned to what it reads as, or to a
# refusal: never to "whatever the parser did".
READ = [
    ("Tuesdays 19:00", {1}, time(19, 0), False),
    ("TUESDAYS 7PM", {1}, time(19, 0), False),
    ("tuesdays, 7:30 p.m.", {1}, time(19, 30), False),
    ("Mon, Wed & Fri at 6:30am", {0, 2, 4}, time(6, 30), False),
    ("Mon–Fri 07:15, 20 mins", {0, 1, 2, 3, 4}, time(7, 15), False),
    ("Monday to Thursday, 12:30", {0, 1, 2, 3}, time(12, 30), False),
    ("from Mon to Fri at 07:00", {0, 1, 2, 3, 4}, time(7, 0), False),
    ("Every weekday at 8.30am", {0, 1, 2, 3, 4}, time(8, 30), False),
    ("Every weekday morning at 7:30 for 25 minutes", {0, 1, 2, 3, 4}, time(7, 30), False),
    ("Daily, 10 minutes", set(range(7)), None, False),
    ("Every day at 21:00 for half an hour", set(range(7)), time(21, 0), False),
    ("Saturday mornings at 9am, about an hour", {5}, time(9, 0), False),
    ("Thursday evenings 18:30, 1 hour", {3}, time(18, 30), False),
    ("Mondays and Thursdays, 12:30 pm, 45 min", {0, 3}, time(12, 30), False),
    ("Weekends at noon", {5, 6}, time(12, 0), False),
    ("Tue/Thu 06:45", {1, 3}, time(6, 45), False),
    ("Weekly on Sundays 10:00", {6}, time(10, 0), False),
    ("Wednesdays, 1.5 hours", {2}, None, False),
    ("Weekly, Tuesday evenings", {1}, None, False),
    ("Every other Friday 17:00 (1h)", {4}, time(17, 0), True),
    ("Fortnightly on Wednesdays, 2 hours", {2}, None, True),
    ("every 2 weeks on Tuesday at 7pm", {1}, time(19, 0), True),
    ("Sat & Sun 09:00", {5, 6}, time(9, 0), False),
]

REFUSED = [
    "Every other weekday 08:00",
    "3 times a week, 30 minutes",
    "As often as possible",
    "Sat & Sun, 10:00 - 11:30",
    "Monday to Thursday, 07:00-ish",
    "Tuesday mornings at 19:00",
    "Mondays 7",
    "Mon/Wed/Fri 7-8am",
    "Every 3 weeks on Monday",
    "Weekdays 07:00, except bank holidays",
    "Most weekdays, 08:00",
    "Tuesdays or Thursdays at 19:00",
    "Mornings and evenings on weekdays",
    "Once a week, 45 minutes",
    "Weekday mornings 08:00 when not travelling",
    # "19h" and "7h" are clock times in some countries. Read as lengths, the cadence had no time.
    "Tuesdays 19h",
    "Tuesdays at 7h",
]


@pytest.mark.parametrize(("cadence", "weekdays", "at", "fortnightly"), READ)
def test_realistic_cadences_read_as_pinned(cadence, weekdays, at, fortnightly):
    read = parse_cadence(cadence)
    assert (set(read.weekdays), read.at, read.fortnightly) == (weekdays, at, fortnightly)


@pytest.mark.parametrize("cadence", REFUSED)
def test_realistic_cadences_refused_as_pinned(cadence):
    with pytest.raises(CadenceUnreadable) as refused_with:
        parse_cadence(cadence)
    assert str(refused_with.value).strip()


def test_the_realistic_list_is_big_enough_to_mean_something():
    assert len(READ) + len(REFUSED) >= 25


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
