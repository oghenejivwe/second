"""Local time, discovered rather than asked for.

The bug this prevents is invisible until it is embarrassing: every wall-clock
claim Second makes -- "6pm loses to meetings", "Tuesdays 19:00 is the slot they
keep", "no work before 10am" -- is wrong by an hour or by a day if the timezone
is wrong, and nothing crashes.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from second.core.clock import Clock, resolve_timezone

LONDON = "Europe/London"
LA = "America/Los_Angeles"


# -- resolution order -------------------------------------------------------


def test_an_explicit_timezone_wins():
    zone, source = resolve_timezone(explicit=LA, calendar_timezone=LONDON)
    assert (str(zone), source) == (LA, "explicit")


def test_the_calendar_beats_the_machine():
    """The calendar is the authority: the user set it, and it travels with them."""
    zone, source = resolve_timezone(explicit=None, calendar_timezone=LONDON)
    assert (str(zone), source) == (LONDON, "calendar")


def test_a_nonsense_timezone_falls_through_instead_of_crashing():
    zone, source = resolve_timezone(explicit="Mars/Olympus_Mons", calendar_timezone=LONDON)
    assert (str(zone), source) == (LONDON, "calendar")


def test_no_hints_still_produces_a_usable_clock():
    zone, source = resolve_timezone()
    assert zone is not None
    assert source in ("system", "utc")


def test_a_guessed_timezone_is_marked_untrustworthy():
    """So the Scheduler can decline to be precise about times it inferred."""
    assert Clock.detect(calendar_timezone=LONDON).is_trustworthy is True
    assert Clock.detect().is_trustworthy is False


# -- the property that actually matters -------------------------------------


def test_the_same_instant_is_a_different_slot_in_a_different_place():
    """The Person layer's entire claim is that it knows which slots you keep.

    Compute a slot label in the wrong timezone and "Tue 19:00" silently becomes
    a slot the user has never once attended.
    """
    instant = datetime(2026, 9, 15, 18, 0, tzinfo=timezone.utc)

    in_london = Clock(zone=ZoneInfo(LONDON), now=instant).slot_label(instant)
    in_la = Clock(zone=ZoneInfo(LA), now=instant).slot_label(instant)

    assert in_london == "Tue 19:00"
    assert in_la == "Tue 11:00"
    assert in_london != in_la


def test_a_naive_datetime_is_read_as_local():
    """The Living Graph stores wall-clock time, because that is what a plan is.

    A user reads "19:00" off their own calendar. Storing that as UTC and
    converting on the way out would move the plan whenever they travelled.
    """
    clock = Clock(zone=ZoneInfo(LONDON), now=datetime(2026, 9, 15, 12, tzinfo=ZoneInfo(LONDON)))
    assert clock.slot_label(datetime(2026, 9, 15, 19, 0)) == "Tue 19:00"


def test_a_slot_keeps_its_label_across_a_clock_change():
    """Why this uses IANA names and not fixed offsets.

    The demo spans three weeks of history. A fixed offset misplaces every event
    on the far side of a DST boundary -- so a weekly 19:00 commitment would look
    like it moved, and the Observer would report a slip that never happened.
    """
    clock = Clock(zone=ZoneInfo(LONDON), now=datetime(2026, 10, 20, 12, tzinfo=ZoneInfo(LONDON)))

    before_change = clock.slot_label(datetime(2026, 10, 20, 19, 0))
    after_change = clock.slot_label(datetime(2026, 11, 3, 19, 0))

    assert before_change == after_change == "Tue 19:00"


@pytest.mark.parametrize(
    "moment,expected",
    [
        (datetime(2026, 9, 14, 7, 0), "Mon 07:00"),
        (datetime(2026, 9, 16, 18, 0), "Wed 18:00"),
        (datetime(2026, 9, 20, 9, 30), "Sun 09:30"),
    ],
)
def test_slot_labels_match_the_person_layer_format(moment, expected):
    """These strings are compared against PersonModel.honoured_slots verbatim."""
    clock = Clock(zone=ZoneInfo(LONDON), now=datetime(2026, 9, 14, 9, tzinfo=ZoneInfo(LONDON)))
    assert clock.slot_label(moment) == expected


# -- windows and description ------------------------------------------------


def test_today_is_the_users_today_not_utcs():
    """Late evening in Los Angeles is already tomorrow in UTC."""
    late = datetime(2026, 9, 15, 23, 30, tzinfo=ZoneInfo(LA))
    clock = Clock(zone=ZoneInfo(LA), now=late)

    assert clock.today == date(2026, 9, 15)
    assert late.astimezone(timezone.utc).date() == date(2026, 9, 16)


def test_a_query_window_spans_whole_local_days():
    clock = Clock.fixed(date(2026, 9, 10), zone_name=LONDON)
    start, end = clock.window(days_back=2, days_forward=1)

    assert start.startswith("2026-09-08T00:00:00")
    assert end.startswith("2026-09-12T00:00:00"), "end is exclusive: through the end of the 11th"


def test_fixed_pins_a_scenario():
    clock = Clock.fixed(date(2026, 9, 10), zone_name=LONDON, at=time(9, 0))
    assert clock.today == date(2026, 9, 10)
    assert clock.now.hour == 9
    assert clock.is_trustworthy


def test_describe_reads_as_a_sentence_and_flags_a_guess():
    trusted = Clock.fixed(date(2026, 9, 10), zone_name=LONDON)
    assert "Thursday 10 September 2026" in trusted.describe()
    assert LONDON in trusted.describe()
    assert "guessed" not in trusted.describe()

    guessed = Clock(zone=ZoneInfo("UTC"), now=datetime(2026, 9, 10, tzinfo=timezone.utc), source="utc")
    assert "guessed" in guessed.describe()
