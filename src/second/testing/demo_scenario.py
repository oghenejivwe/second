"""The seeded demo world: three goals, three weeks of history, a blocked booking.

This is one canonical dataset used three ways, which is the point of it living
in one file:

  * **AGENTS** develops against it offline, so the Diagnostician is tuned on the
    same evidence the demo shows.
  * **CONNECTORS** seeds the real Google account from it, so the live system sees
    the same world.
  * **SURFACES** renders it as a fixture before the API exists.

Every date is relative to :data:`TODAY`. Nothing here reads the clock, because a
scenario that behaves differently on Wednesday is not a scenario.

**Four things are planted deliberately, one per demo beat:**

1. *A recurring 6pm conflict that always loses.* The gym block collides with
   "Eng sync" four weekdays out of five. The Diagnostician should reach
   ``CALENDAR_CONFLICT`` with high confidence, and the Adapter should move the
   block to 07:00 rather than push it to tomorrow.
2. *A task dragged across four days.* "Draft the talk pitch" exists as four
   separate events -- three cancelled, one live. There is no move history on a
   calendar event, so a task that was repeatedly rescheduled only looks like one
   if it was actually recreated. Patching one event four times leaves a single
   artefact and the whole story is invisible.
3. *A booking blocked by something unsent.* The Lisbon flights cannot be booked
   until leave is approved, and the leave request was never sent. The dependency
   is real and in the graph, so this is ``UNMET_DEPENDENCY`` -- and the Preparer
   can draft the leave email and stop there.
4. *An honest unknown.* "Five-minute daily recording" slipped three times into
   slots that were completely free. No conflict, no dependency, no missing
   information. There is nothing in the evidence that explains it, so the correct
   diagnosis is ``UNKNOWN`` and the correct action is to ask.

The fourth is the one that matters most. It is the only beat that cannot be faked
by a system that is merely fluent.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta

from second.core.models import Goal, Link, LivingGraph, PersonModel, Route, Slip, Task

TODAY = date.fromisoformat(os.environ.get("SECOND_DEMO_TODAY", "2026-09-10"))
"""The scenario's "now". Injected everywhere as ``deps.today``.

Frozen by default so tests reproduce, and overridable by ``SECOND_DEMO_TODAY`` so
the demo world can be moved to whatever day you are recording. Everything here is
relative to this date, so shifting it shifts the whole world -- the three weeks of
history, the slots today, the day the check-in reconciles."""

HISTORY_START = TODAY - timedelta(days=21)
USER_ID = "demo"
USER_EMAIL = "jivwewonder@gmail.com"
MANAGER_EMAIL = "manager@example.com"


def _at(day_offset: int, hour: int, minute: int = 0) -> datetime:
    """A datetime relative to the start of the history window."""
    return datetime.combine(HISTORY_START + timedelta(days=day_offset), datetime.min.time()).replace(
        hour=hour, minute=minute
    )


def _weekdays_in_history() -> list[int]:
    """Offsets of the weekdays in the three-week window."""
    return [
        offset
        for offset in range(21)
        if (HISTORY_START + timedelta(days=offset)).weekday() < 5
    ]


# ---------------------------------------------------------------------------
# The Living Graph
# ---------------------------------------------------------------------------


def _today_at(hour: int, minute: int = 0) -> datetime:
    """A slot on the demo day itself, so Today has a day to show."""
    return datetime.combine(TODAY, datetime.min.time()).replace(hour=hour, minute=minute)


def _yesterday_at(hour: int, minute: int = 0) -> datetime:
    """A slot on the day the check-in reconciles.

    Without at least one of these the check-in has nothing to ask about and
    ``DailyBrief.check_in`` is ``None`` -- so reconciliation, ``record_completion``
    and the pre-filled confirmation are all invisible on stage. AGENTS found that
    the seeded world had zero blocks on the reconciled day.
    """
    return datetime.combine(TODAY - timedelta(days=1), datetime.min.time()).replace(
        hour=hour, minute=minute
    )


def living_graph() -> LivingGraph:
    """The seeded graph as it stands the morning of the demo."""
    # The ladder. Two life-shaped ambitions, each cashed down to something that
    # can occupy a Tuesday morning. This is what lets the day answer "why this?"
    company = Goal(
        id="g-company",
        title="Build a company that outlives me",
        horizon="life",
        deadline=TODAY + timedelta(days=365 * 15),
        status="active",
        extraction_confidence=0.9,
    )
    raise_round = Goal(
        id="g-raise",
        title="Raise a Series A",
        horizon="three_year",
        contributes_to="g-company",
        deadline=TODAY + timedelta(days=365 * 3),
        status="active",
        extraction_confidence=0.9,
    )
    health = Goal(
        id="g-health",
        title="Still be climbing at sixty",
        horizon="life",
        deadline=None,
        status="active",
        extraction_confidence=0.85,
    )

    speaking = Goal(
        id="g-speaking",
        title="Get comfortable speaking to a room",
        horizon="year",
        contributes_to="g-raise",
        deadline=TODAY + timedelta(days=90),
        status="active",
        extraction_confidence=0.93,
        routes=[
            Route(
                id="r-club",
                goal_id="g-speaking",
                title="Weekly speaking club",
                cadence="Tuesdays 19:00",
                rationale="Tuesday evenings are the slot they actually keep.",
                status="approved",
                tasks=[
                    Task(
                        id="t-club",
                        route_id="r-club",
                        title="Attend speaking club",
                        scheduled_slots=[_at(offset, 19) for offset in (1, 8, 15, 22)],
                        status="pending",
                    )
                ],
            ),
            Route(
                id="r-daily",
                goal_id="g-speaking",
                title="Five-minute daily recording",
                cadence="Weekday mornings 08:00",
                rationale="Short enough to survive a bad morning.",
                status="approved",
                tasks=[
                    # Beat 4: slipped three times into slots that were free.
                    Task(
                        id="t-recording",
                        route_id="r-daily",
                        title="Record five minutes and listen back",
                        scheduled_slots=[_at(offset, 8) for offset in (2, 9, 16)] + [_yesterday_at(8), _today_at(8)],
                        slip_count=3,
                        slips=[
                            Slip(on=HISTORY_START + timedelta(days=offset), scheduled_for=_at(offset, 8))
                            for offset in (2, 9, 16)
                        ],
                        status="pending",
                    )
                ],
            ),
            Route(
                id="r-pitch",
                goal_id="g-speaking",
                title="Pitch one talk a fortnight",
                cadence="Every other Thursday",
                rationale="Forces the work to leave the practice room.",
                status="approved",
                tasks=[
                    # Beat 2: dragged across four days.
                    Task(
                        id="t-pitch",
                        route_id="r-pitch",
                        title="Draft the talk pitch",
                        scheduled_slots=[_at(offset, 17) for offset in (10, 11, 12, 13)] + [_today_at(17)],
                        slip_count=3,
                        slips=[
                            Slip(
                                on=HISTORY_START + timedelta(days=offset),
                                scheduled_for=_at(offset, 17),
                                note="moved to the next day",
                            )
                            for offset in (10, 11, 12)
                        ],
                        status="pending",
                    )
                ],
            ),
        ],
    )

    fitness = Goal(
        id="g-fitness",
        title="Train three times a week",
        horizon="year",
        contributes_to="g-health",
        deadline=None,
        status="active",
        extraction_confidence=0.88,
        routes=[
            Route(
                id="r-gym",
                goal_id="g-fitness",
                title="Gym after work",
                cadence="Mon/Wed/Fri 18:00",
                rationale="They said evenings were free. The calendar disagrees.",
                status="approved",
                tasks=[
                    # Beat 1: the recurring 6pm conflict.
                    Task(
                        id="t-gym",
                        route_id="r-gym",
                        title="Gym session",
                        scheduled_slots=[_at(offset, 18) for offset in (0, 2, 4, 7, 9)] + [_yesterday_at(18), _today_at(18)],
                        slip_count=4,
                        slips=[
                            Slip(
                                on=HISTORY_START + timedelta(days=offset),
                                scheduled_for=_at(offset, 18),
                                note="collided with Eng sync",
                            )
                            for offset in (0, 2, 4, 7)
                        ],
                        status="pending",
                    )
                ],
            )
        ],
    )

    # Deliberately unparented: not everything ladders up to an ambition, and a
    # system that insists otherwise makes people invent reasons for a wedding.
    lisbon = Goal(
        id="g-lisbon",
        title="Be at my sister's wedding in Lisbon",
        horizon="month",
        deadline=TODAY + timedelta(days=45),
        status="active",
        extraction_confidence=0.97,
        routes=[
            Route(
                id="r-travel",
                goal_id="g-lisbon",
                title="Book the trip",
                cadence="One-off, before the end of the month",
                rationale="Fixed date, so everything else moves around it.",
                status="approved",
                tasks=[
                    Task(
                        id="t-leave",
                        route_id="r-travel",
                        title="Request leave for the wedding week",
                        deadline=TODAY + timedelta(days=5),
                        status="pending",
                    ),
                    # Beat 3: blocked by something unsent.
                    Task(
                        id="t-flights",
                        route_id="r-travel",
                        title="Book flights to Lisbon",
                        depends_on=["t-leave"],
                        deadline=TODAY + timedelta(days=14),
                        scheduled_slots=[_at(17, 20), _at(19, 20)],
                        slip_count=2,
                        slips=[
                            Slip(
                                on=HISTORY_START + timedelta(days=offset),
                                scheduled_for=_at(offset, 20),
                                note="leave not yet confirmed",
                            )
                            for offset in (17, 19)
                        ],
                        status="pending",
                    ),
                ],
            )
        ],
    )

    person = PersonModel(
        preferences={"learning_mode": "video", "day_shape": "early"},
        constraints=["No meetings before 09:00", "Sundays are family"],
        honoured_slots=["Tue 19:00", "Sat 09:00"],
        abandoned_slots=["Mon 18:00", "Wed 18:00", "Fri 18:00"],
        recurring_blockers=[],
        resources_served=[],
    )

    links = [
        Link(
            kind="slot_abandoned_for_task",
            from_id="t-gym",
            to_ref="Wed 18:00",
            note="Four of five weekday sessions collided with Eng sync.",
        ),
        Link(
            kind="slot_honoured_for_task",
            from_id="t-club",
            to_ref="Tue 19:00",
            note="Attended every week.",
        ),
        Link(
            kind="route_suits_preference",
            from_id="r-daily",
            to_ref="learning_mode",
            note="Recording and listening back suits someone who learns by video.",
        ),
    ]

    return LivingGraph(
        user_id=USER_ID,
        goals=[company, raise_round, health, speaking, fitness, lisbon],
        person=person,
        links=links,
    )


# ---------------------------------------------------------------------------
# The calendar
# ---------------------------------------------------------------------------


def calendar_events() -> list[dict]:
    """Three weeks of calendar history, plus the week ahead.

    The shape here is the contract CONNECTORS matches. It is deliberately small:
    an agent reading a forty-key Google event payload spends tokens and attention
    on nothing.
    """
    events: list[dict] = []

    def add(event_id: str, title: str, start: datetime, minutes: int, **extra) -> None:
        events.append(
            {
                "id": event_id,
                "title": title,
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=minutes)).isoformat(),
                "status": extra.get("status", "confirmed"),
                "is_owner": extra.get("is_owner", True),
                "attendees": extra.get("attendees", 1),
                "response": extra.get("response", "accepted"),
            }
        )

    # The standing meeting that keeps winning. Not the user's -- they cannot move it.
    for offset in _weekdays_in_history():
        add(
            f"engsync{offset:03d}",
            "Eng sync",
            _at(offset, 18),
            60,
            is_owner=False,
            attendees=9,
            response="accepted",
        )

    # Beat 1: the gym, declined four times out of five.
    for index, offset in enumerate((0, 2, 4, 7, 9)):
        add(
            f"gym{offset:03d}",
            "Gym session",
            _at(offset, 18),
            60,
            response="declined" if index < 4 else "accepted",
        )

    # Honoured: the speaking club, every Tuesday.
    for offset in (1, 8, 15):
        add(f"club{offset:03d}", "Speaking club", _at(offset, 19), 90)

    # Beat 2: dragged across four days -- four events, three cancelled.
    for index, offset in enumerate((10, 11, 12, 13)):
        add(
            f"pitch{offset:03d}",
            "Draft the talk pitch",
            _at(offset, 17),
            45,
            status="cancelled" if index < 3 else "confirmed",
        )

    # Beat 4: the recording slots. Free, uncontested, and still missed.
    for offset in (2, 9, 16):
        add(f"record{offset:03d}", "Record five minutes", _at(offset, 8), 15, response="none")

    # Beat 3: booking attempts that went nowhere.
    for offset in (17, 19):
        add(f"flights{offset:03d}", "Book flights to Lisbon", _at(offset, 20), 30, response="none")

    return sorted(events, key=lambda event: event["start"])


def free_slots(duration_min: int = 60) -> list[dict]:
    """Genuinely free slots in the week ahead.

    07:00 is free every weekday, which is what makes the gym adaptation possible
    and is the point of this fixture. Evenings are contended, which is what makes
    the Scheduler's deprioritisation meaningful.
    """
    slots = []
    for offset in range(21, 28):
        day = HISTORY_START + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        for hour in (7, 12):
            start = datetime.combine(day, datetime.min.time()).replace(hour=hour)
            slots.append(
                {
                    "start": start.isoformat(),
                    "end": (start + timedelta(minutes=duration_min)).isoformat(),
                    "duration_min": duration_min,
                }
            )
    return slots


# ---------------------------------------------------------------------------
# The inbox
# ---------------------------------------------------------------------------


def inbox() -> list[dict]:
    """The seeded mailbox.

    Two messages carry demo weight: the insurance policy number the Preparer has
    to go and find, and the *absence* of a sent leave request, which is what makes
    the flight booking genuinely blocked rather than merely late.
    """
    return [
        {
            "id": "m-policy",
            "from": "no-reply@ableinsure.example",
            "to": USER_EMAIL,
            "subject": "Your travel insurance policy AB-4471-92X",
            "date": (HISTORY_START - timedelta(days=160)).isoformat(),
            "snippet": "Your annual multi-trip policy is confirmed. Policy number AB-4471-92X.",
            "body": (
                "Thank you for renewing.\n\n"
                "Policy number: AB-4471-92X\n"
                "Cover: Annual multi-trip, Europe\n"
                "Valid until: 2027-03-31\n\n"
                "Quote this number when arranging travel."
            ),
        },
        {
            "id": "m-wedding",
            "from": "sister@example.com",
            "to": USER_EMAIL,
            "subject": "Wedding week - are you booked yet?",
            "date": (HISTORY_START + timedelta(days=12)).isoformat(),
            "snippet": "Just checking you have flights sorted, the hotel block closes soon.",
            "body": (
                "Hi!\n\nJust checking you have flights sorted -- the hotel block "
                "closes at the end of the month. Let me know once you are booked."
            ),
        },
        {
            "id": "m-leavepolicy",
            "from": "hr@example.com",
            "to": USER_EMAIL,
            "subject": "Reminder: annual leave requests need 14 days notice",
            "date": (HISTORY_START + timedelta(days=3)).isoformat(),
            "snippet": "Requests must reach your manager at least 14 days before the first day of leave.",
            "body": (
                "A reminder that annual leave requests must reach your line manager "
                "at least 14 days before the first day of leave. Requests are "
                "approved in the HR portal once your manager confirms by email."
            ),
        },
        {
            "id": "m-engsync",
            "from": MANAGER_EMAIL,
            "to": USER_EMAIL,
            "subject": "Eng sync moving to 6pm permanently",
            "date": (HISTORY_START - timedelta(days=2)).isoformat(),
            "snippet": "From next week the sync is 18:00 daily to catch the US team.",
            "body": (
                "From next week the engineering sync moves to 18:00 daily so we "
                "overlap with the US team. It is a standing invite, no need to reply."
            ),
        },
    ]


def sent_items() -> list[dict]:
    """What the user actually sent.

    Deliberately empty of any leave request. The Preparer's job is to notice that
    ``t-flights`` depends on ``t-leave``, that nothing matching a leave request
    was ever sent, and to draft one -- and then stop.
    """
    return [
        {
            "id": "s-standup",
            "from": USER_EMAIL,
            "to": MANAGER_EMAIL,
            "subject": "Re: sprint planning",
            "date": (HISTORY_START + timedelta(days=6)).isoformat(),
            "snippet": "Works for me, see you then.",
            "body": "Works for me, see you then.",
        }
    ]
