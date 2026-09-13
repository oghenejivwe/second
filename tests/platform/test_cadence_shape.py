"""A cadence is read only in an order Second knows, and every other order is refused with its reason.

Wrong orders used to be refused one phrase at a time, and every review found another that slipped
through and was guessed: a time in front exempt from the check for a time after some of the days,
and a part of the day lent from one group of days to the next. These pin the allowlist instead,
each order next to the one beside it that must not read.
"""

from __future__ import annotations

from datetime import time

import pytest

from second.graphs.schedule import CadenceUnreadable, parse_cadence

WEEKDAYS = {0, 1, 2, 3, 4}


def refusal(cadence: str) -> str:
    with pytest.raises(CadenceUnreadable) as refused_with:
        parse_cadence(cadence)
    return str(refused_with.value)


# -- the two guesses the last review found ------------------------------------


@pytest.mark.parametrize(
    "cadence",
    [
        "07:00 Mon and Wed 07:00",
        "7pm Mon, Wed 7pm and Fri",
        "7pm Monday and 7pm Wednesday",
        "19:00 Tuesdays and Thursdays 19:00",
        "7:30 pm Tuesdays, Thursdays 7:30pm and Saturdays",
    ],
)
def test_a_cadence_that_opens_with_a_time_and_writes_another_is_refused(cadence):
    """"7pm Mon, Wed 7pm and Fri" put Friday at 19:00. The check for a time written after only some
    of the days only looked after the first day, so a time in front was never checked at all.

    Mutation-tested: making ``_refuse_unread_order`` accept every order reads Friday at 19:00 and
    this fails.
    """
    assert "opens with a time and writes a time again later" in refusal(cadence)


@pytest.mark.parametrize(
    "cadence",
    [
        "Mon mornings and Wed 08:00",
        "Mon mornings and Wed 19:00",
        "Tuesday evenings and Thursday 19:00",
        "Weekday mornings and Sat 09:00",
        "Sat mornings, Sun 9am",
    ],
)
def test_a_part_of_the_day_on_some_days_and_a_time_on_others_is_refused(cadence):
    """"Mon mornings and Wed 08:00" gave Monday the 08:00 written beside Wednesday, and Wednesday
    the morning written beside Monday. With 19:00 it was refused, but as a time outside the morning,
    which is not what is wrong with it.

    Mutation-tested: making ``_refuse_unread_order`` accept every order reads Monday and Wednesday
    at 08:00 and this fails.
    """
    assert "beside some of its days and a time beside others" in refusal(cadence)


@pytest.mark.parametrize(
    ("cadence", "reason"),
    [
        ("Mon mornings and Wed", "names the morning beside only some of its days"),
        ("Mon mornings and Wed mornings 08:00", "puts a time beside only some of its days"),
        ("Mon 8am and Wed mornings", "puts a time after only some of its days"),
    ],
)
def test_a_part_of_the_day_or_a_time_beside_only_some_groups_is_refused(cadence, reason):
    assert reason in refusal(cadence)


# -- the reviewer's minors -----------------------------------------------------


@pytest.mark.parametrize(
    "cadence", ["Tuesdays midnight", "Tuesdays 12am", "Saturdays 12 a.m.", "Mon/Wed 00:00", "Weekdays at midnight"]
)
def test_midnight_beside_a_named_day_is_refused(cadence):
    """"Tuesdays 12am" is the first minute of Tuesday to a clock and the end of Tuesday night to most
    people. It was read as Tuesday 00:00 without the word "night" to set off the night-time rule.

    Mutation-tested: removing the midnight refusal in ``parse_cadence`` reads Tuesday 00:00 and this
    fails.
    """
    reason = refusal(cadence)
    assert "names midnight" in reason and "Second will not guess which day you meant" in reason


@pytest.mark.parametrize(
    ("cadence", "weekdays", "at"),
    [
        ("Tuesdays 1am", {1}, time(1, 0)),
        ("Tuesdays 12:30am", {1}, time(0, 30)),
        ("Daily midnight", set(range(7)), time(0, 0)),
    ],
)
def test_a_time_after_midnight_and_midnight_every_day_still_read(cadence, weekdays, at):
    """Only midnight sits on the line between two days, and a cadence on every day has no
    neighbouring day to put it on by mistake."""
    read = parse_cadence(cadence)
    assert (set(read.weekdays), read.at) == (weekdays, at)


@pytest.mark.parametrize("cadence", ["3 mornings/week", "2 sessions / week", "3 evenings/fortnight"])
def test_a_count_per_week_with_a_slash_gets_the_frequency_reason(cadence):
    """"3 mornings/week" was told to write its 3 as a clock time."""
    reason = refusal(cadence)
    assert "how many times, not which days" in reason
    assert "19:00" not in reason


@pytest.mark.parametrize(
    ("cadence", "written"),
    [
        ("mon, wed fri 07:00", "Mon/Wed/Fri"),
        ("mon wed, fri 07:00", "Mon/Wed/Fri"),
        ("mon wed & fri", "Mon/Wed/Fri"),
        ("mon-wed fri 18:00", "Mon-Wed/Fri"),
        ("tue thu 7pm and sat sun 7pm", "Tue/Thu and Sat/Sun"),
    ],
)
def test_the_spaced_days_suggestion_carries_every_day_in_the_list(cadence, written):
    """"mon, wed fri" was told to write Wed/Fri, and following that advice drops Monday."""
    assert f"Write them as {written}." in refusal(cadence)


@pytest.mark.parametrize(
    ("cadence", "weekdays", "at"),
    [("Wed 7pm; Sun 7pm", {2, 6}, time(19, 0)), ("Mondays; Wednesdays 07:00", {0, 2}, time(7, 0))],
)
def test_a_semicolon_separates_a_list_like_a_comma(cadence, weekdays, at):
    read = parse_cadence(cadence)
    assert (set(read.weekdays), read.at) == (weekdays, at)


@pytest.mark.parametrize("cadence", ["Mon 7pm; Wed", "Weekdays 07:00; Sat"])
def test_a_day_after_a_semicolon_is_refused_for_its_missing_time_not_as_a_word(cadence):
    """"Mon 7pm; Wed" was refused for the word "wed", as if Wednesday were not a day."""
    assert "a time after only some of its days" in refusal(cadence)


# -- groups that a length or punctuation separates ----------------------------


@pytest.mark.parametrize(
    "cadence",
    [
        "Mondays 30 minutes, Wednesdays 19:00",
        "Saturdays 1 hour, Sundays 10am",
        "Weekdays 15 minutes and Saturdays 9am",
        "Mondays for an hour and Wednesdays 7pm",
        "Tuesday 20 mins; Thursday 7pm",
        "Mon 30 minutes, Wed 7pm",
        "Mondays 30 minutes, Wednesdays 30 minutes at 19:00",
        "Mondays 30 minutes and Wednesday evenings 7pm",
        "Weekdays 15 minutes, weekends 1 hour at 9am",
        "Saturday 2 hours; Sunday at noon",
        "Tuesdays, 1 hour. Thursdays 19:00, 1 hour",
        "Mondays. Wednesdays 19:00",
        "Mondays (Wednesdays 19:00)",
    ],
)
def test_a_time_beside_only_the_group_after_a_length_or_a_stop_is_refused(cadence):
    """"Mondays 30 minutes, Wednesdays 19:00" put Monday at 19:00. Lengths and punctuation were
    blanked before the shape was built, so the two day names sat side by side and were read as one
    group sharing the time written only beside Wednesday.

    Mutation-tested: letting ``_shape`` join neighbouring days whatever lies between them reads
    these again, Monday at 19:00, and this fails.
    """
    assert "puts a time beside only some of its days" in refusal(cadence)


@pytest.mark.parametrize(
    ("cadence", "weekdays", "at", "fortnightly"),
    [
        ("Weekday mornings 08:00", WEEKDAYS, time(8, 0), False),
        ("Tuesdays 19:00", {1}, time(19, 0), False),
        ("Mon/Wed/Fri 07:00", {0, 2, 4}, time(7, 0), False),
        ("Mon/Wed/Fri 18:00", {0, 2, 4}, time(18, 0), False),
        ("Every other Thursday", {3}, None, True),
        ("Weekday mornings, 15 minutes", WEEKDAYS, None, False),
        ("Tuesdays 19:00 for 90 minutes", {1}, time(19, 0), False),
        ("Mon, Wed & Fri at 6:30am", {0, 2, 4}, time(6, 30), False),
        ("Monday to Friday 07:00", WEEKDAYS, time(7, 0), False),
        ("Mon – Fri 07:00", WEEKDAYS, time(7, 0), False),
        ("Monday through Wednesday, and Friday 07:00", {0, 1, 2, 4}, time(7, 0), False),
        ("Wed 7pm and Sun 7pm", {2, 6}, time(19, 0), False),
        # Groups that each say nothing but their days borrow nothing from each other.
        ("Weekdays 15 minutes, Saturdays 30 minutes", {0, 1, 2, 3, 4, 5}, None, False),
        ("Mondays 30 minutes at 19:00, Wednesdays 19:00", {0, 2}, time(19, 0), False),
    ],
)
def test_days_joined_only_by_list_or_range_words_are_still_one_group(cadence, weekdays, at, fortnightly):
    read = parse_cadence(cadence)
    assert (set(read.weekdays), read.at, read.fortnightly) == (weekdays, at, fortnightly)


@pytest.mark.parametrize(
    "cadence", ["every other 15 minutes Mon", "every other for 90 minutes Mon", "every other 30 minutes week on Mon"]
)
def test_every_other_does_not_reach_across_a_length(cadence):
    """"every other 15 minutes Mon" read as every other Monday: the length was blanked first, and
    "every other" matched across the gap it left.

    Mutation-tested: removing the check for a length inside the marker reads every other Monday and
    this fails.
    """
    assert "has a length in the middle of saying what alternates" in refusal(cadence)


@pytest.mark.parametrize("cadence", ["Tuesdays ~7pm", "Tuesdays ~ 19:00", "Weekends ~noon"])
def test_a_tilde_before_a_time_is_refused_like_around(cadence):
    """"Tuesdays ~7pm" put the block at exactly 19:00. The tilde is "around" written as a symbol.

    Mutation-tested: removing the tilde from ``_RELATIVE_TIME`` reads Tuesday at 19:00 and this
    fails.
    """
    assert "gives a time relative to something else" in refusal(cadence)


@pytest.mark.parametrize(("cadence", "at"), [("Tuesdays 19:00, ~90 minutes", time(19, 0)), ("Tuesdays ~90 minutes", None)])
def test_a_tilde_before_a_length_goes_with_the_length(cadence, at):
    read = parse_cadence(cadence)
    assert (set(read.weekdays), read.at) == ({1}, at)


# -- the allowlist, order by order ---------------------------------------------

# D is days (one day, or days joined into a list or range), P a part of the day, T a time, W
# "weekly" and F every other week. A read is pinned to its days, time and fortnight; a refusal to
# the words of its reason.
SHAPES = [
    ("D", "Tuesdays", ({1}, None, False)),
    ("DP", "Weekday mornings, 15 minutes", (WEEKDAYS, None, False)),
    ("DT", "Mon/Wed/Fri 07:00", ({0, 2, 4}, time(7, 0), False)),
    ("DT", "Weekdays and Sat 9am", ({0, 1, 2, 3, 4, 5}, time(9, 0), False)),
    ("DT", "Monday to Friday 06:30", (WEEKDAYS, time(6, 30), False)),
    ("DPT", "Weekday mornings 08:00", (WEEKDAYS, time(8, 0), False)),
    ("PD", "Evenings, Tue/Thu", ({1, 3}, None, False)),
    ("PDT", "Mornings, Sat at 09:00", ({5}, time(9, 0), False)),
    ("TD", "07:00 Mon/Wed/Fri", ({0, 2, 4}, time(7, 0), False)),
    ("TD", "7:30 pm Tuesdays", ({1}, time(19, 30), False)),
    ("TDP", "7pm Tuesday evenings", ({1}, time(19, 0), False)),
    ("WDT", "Weekly on Sundays 10:00", ({6}, time(10, 0), False)),
    ("DTW", "Tuesdays 19:00 weekly", ({1}, time(19, 0), False)),
    ("FD", "Every other Thursday", ({3}, None, True)),
    ("FDT", "every 2 weeks on Tuesday 17:00", ({1}, time(17, 0), True)),
    ("DTF", "Thursdays 17:00, fortnightly", ({3}, time(17, 0), True)),
    ("DTDT", "Wed 7pm and Sun 7pm", ({2, 6}, time(19, 0), False)),
    ("DTDT", "Wednesday 7pm Sunday 7pm", ({2, 6}, time(19, 0), False)),
    ("DPTDT", "Mon mornings 8am and Wed 8am", ({0, 2}, time(8, 0), False)),
    ("DPTDPT", "Tuesday evenings 19:00 and Thursday evenings 19:00", ({1, 3}, time(19, 0), False)),
    ("DPDP", "Tuesday evenings and Thursday evenings", ({1, 3}, None, False)),
    ("DTDTDT", "Weekdays 7am, Saturdays 7am and Sundays 7am", (set(range(7)), time(7, 0), False)),
    ("DD", "Weekdays 15 minutes, Saturdays 30 minutes", ({0, 1, 2, 3, 4, 5}, None, False)),
    ("DDT", "Mondays 30 minutes, Wednesdays 19:00", "puts a time beside only some of its days"),
    ("DDT", "Mondays. Wednesdays 19:00", "puts a time beside only some of its days"),
    ("DDPT", "Mondays 30 minutes and Wednesday evenings 7pm", "puts a time beside only some of its days"),
    ("DDP", "Mondays 30 minutes, Wednesday evenings", "names the evening beside only some of its days"),
    ("TDT", "07:00 Mon and Wed 07:00", "opens with a time and writes a time again later"),
    ("TDTD", "7pm Mon, Wed 7pm and Fri", "opens with a time and writes a time again later"),
    ("DPDT", "Mon mornings and Wed 08:00", "names the morning beside some of its days and a time beside others"),
    ("DPD", "Mon mornings and Wed", "names the morning beside only some of its days"),
    ("DPDPT", "Mon mornings and Wed mornings 08:00", "puts a time beside only some of its days"),
    ("DTD", "Weekdays 07:00 and Sat", "puts a time after only some of its days"),
    ("DTDP", "Mon 8am and Wed mornings", "puts a time after only some of its days"),
    ("DTP", "Tuesdays 7pm in the evening", "is written as days, then a time, then a part of the day."),
    ("PTD", "Mornings 8am Mon/Wed", "is written as a part of the day, then a time, then days."),
    ("DTT", "Tuesdays 19:00 at 7pm", "is written as days, then a time, then a time."),
    ("PDTDT", "Mornings, Mon 8am and Wed 8am", "is written as a part of the day, then days, then a time"),
    ("DFT", "Tuesdays every other week 19:00", "says how often it repeats in the middle of the cadence"),
    ("DWDT", "Monday weekly and Wednesday 7pm", "says how often it repeats in the middle of the cadence"),
    ("WFD", "Weekly, every other Thursday", "says both every week and every other week"),
]


def test_the_shape_table_is_big_enough_to_mean_something():
    assert len(SHAPES) >= 30
    assert sum(isinstance(expected, str) for _, _, expected in SHAPES) >= 10, "refusals as well as reads"


@pytest.mark.parametrize(("shape", "cadence", "expected"), SHAPES, ids=[f"{s}:{c}" for s, c, _ in SHAPES])
def test_each_order_reads_as_pinned_or_is_refused_with_its_reason(shape, cadence, expected):
    """Mutation-tested: making ``_refuse_unread_order`` accept every order reads every refusal here
    and this fails."""
    if isinstance(expected, str):
        assert expected in refusal(cadence), f"{shape} {cadence!r}"
        return
    weekdays, at, fortnightly = expected
    read = parse_cadence(cadence)
    assert (set(read.weekdays), read.at, read.fortnightly) == (weekdays, at, fortnightly), f"{shape} {cadence!r}"
