"""Google Calendar, as four tools and one plain function.

Every call here goes through the interlock in :mod:`second.tools._google`, which
is the only thing standing between Second and a deleted event. There is no
``delete_event`` in this file and there never will be.

The shapes returned here match :mod:`second.testing.fake_connectors` exactly,
because AGENTS is already coding against those. Two places where the real API
cannot match the fake are documented at :func:`get_calendar_events` and
:func:`find_free_slots`, and both are raised in the log rather than papered over.

Datetimes across this boundary
------------------------------

**In: offset-aware ISO 8601** -- ``second.core.clock.Clock.window()`` produces
``'2026-08-20T00:00:00+01:00'``. **Out: naive local wall-clock ISO** --
``'2026-08-20T18:00:00'``, which is what the Living Graph stores and what the
person reads off their own calendar.

The conversion runs through the calendar's IANA timezone and never through string
truncation. Google returns ``start.dateTime`` with whatever offset the event was
written in; truncating a ``+00:00`` event for a ``Europe/London`` user puts it an
hour early, every event, silently, with nothing crashing. That is the bug
:func:`get_calendar_timezone` and ``core/clock.py`` exist to prevent, so this
module must not reintroduce it one layer down.

Note also that ``start.dateTime`` is legally offsetless when ``start.timeZone`` is
present -- and ``timeZone`` is mandatory on recurring events, so every instance of
the demo's "Eng sync" is a candidate. ``.astimezone()`` on a naive datetime
assumes the *server's* zone, which on this machine is ``Africa/Lagos``. Every
parse here attaches a zone explicitly before converting.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from strands import tool

from second.tools._google import call, paged, service

logger = logging.getLogger(__name__)

CALENDAR_ID = "primary"

DAY_START = time(7, 0)
DAY_END = time(22, 0)
"""The window :func:`find_free_slots` will propose inside, in the user's local time.

A fixed threshold is not a control, so: stepping outside it costs the user a
suggestion at 06:00 or 23:00, which they would decline. Stepping *inside* it
costs nothing, because the caller's own ``start``/``end`` bound the search
further. If the Scheduler ever needs a 06:00 slot this becomes a parameter; until
something asks, a narrower window is the one that produces suggestions a person
would actually keep."""

SLOT_STEP_MINUTES = 30
MAX_SLOTS = 60
"""Cap on slots returned, because an agent reading 300 candidate slots spends its
attention on nothing. **Truncation is logged, never silent** -- a capped list that
looks complete is how a confidently wrong plan gets made."""

FREE_EVENT_TYPES = frozenset({"birthday", "workingLocation"})
"""Event types that never occupy time.

Written as an exclusion rather than a list of busy types on purpose: Google's
``eventType`` enum has six values today (``birthday``, ``default``, ``focusTime``,
``fromGmail``, ``outOfOffice``, ``workingLocation``) and a seventh added later
must default to **busy**. Failure direction: refuse to schedule over something we
do not recognise, rather than book the user over their own flight.

``fromGmail`` is the one that matters here -- those are the flight and hotel
reservations Google creates from confirmation emails, and the demo's third beat is
booking flights to Lisbon."""


class CalendarError(RuntimeError):
    """A calendar call could not be completed. Raised, never returned.

    The ``@tool`` decorator attaches a raised exception to
    ``AfterToolCallEvent.exception``; a returned error dict arrives with
    ``exception=None`` and the audit record loses its cause.
    """


# ---------------------------------------------------------------------------
# Timezone -- not a tool, because no agent calls it
# ---------------------------------------------------------------------------


def get_calendar_timezone() -> str | None:
    """The user's IANA timezone, read from their own calendar rather than asked.

    Asking would go stale the moment they travelled. ``core/clock.py`` calls this
    first and falls back to the machine, then to UTC, recording which -- so an
    agent can decline to be precise about a time it guessed.

    Two rungs, because the two API calls need disjoint scopes and only the broad
    ``calendar`` scope covers both: ``settings.get`` accepts ``calendar``,
    ``calendar.readonly`` or ``calendar.settings.readonly``; ``calendars.get``
    accepts ``calendar``, ``calendar.calendars`` and others. Neither is covered by
    ``calendar.events``.

    Returns:
        An IANA name such as ``"Europe/London"``, or ``None`` if the calendar
        could not say -- which is a fall-through, not an error. ``clock.py``
        already treats ``None`` as "use the machine's zone and mark it
        untrustworthy", and a timezone lookup must never be the thing that breaks
        a run.
    """
    for describe, read in (
        ("user setting", _timezone_from_settings),
        ("primary calendar", _timezone_from_calendar),
    ):
        try:
            name = read()
        except Exception:  # noqa: BLE001 - a clock lookup never breaks a run
            logger.warning("could not read the timezone from the %s", describe, exc_info=True)
            continue
        if name and name.strip():
            logger.info("calendar timezone %r, from the %s", name, describe)
            return name.strip()
    logger.warning("the calendar did not report a timezone; falling back to the machine")
    return None


def _timezone_from_settings() -> str | None:
    request = service("calendar").settings().get(setting="timezone")
    return (call(request, "read the calendar timezone setting") or {}).get("value")


def _timezone_from_calendar() -> str | None:
    request = service("calendar").calendars().get(calendarId=CALENDAR_ID)
    return (call(request, "read the primary calendar") or {}).get("timeZone")


def _zone() -> ZoneInfo:
    """The zone to render wall-clock times in. UTC only as a last resort."""
    name = get_calendar_timezone()
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning("the calendar reported an unknown timezone %r", name)
    return ZoneInfo("UTC")


# ---------------------------------------------------------------------------
# Parsing Google's datetimes
# ---------------------------------------------------------------------------


def _aware(value: str, zone: ZoneInfo, field: str) -> datetime:
    """Parse an ISO 8601 string into an aware datetime, attaching ``zone`` if naive.

    Never calls ``.astimezone()`` on a naive value: CPython would assume the
    server's zone, and on this machine that is ``Africa/Lagos``.
    """
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise CalendarError(f"{field} is not an ISO 8601 datetime: {value!r}") from error
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=zone)


def _event_edge(edge: dict[str, Any] | None, zone: ZoneInfo) -> datetime | None:
    """One end of an event, as an aware datetime, or ``None`` if it has no time.

    Handles both shapes Google uses: ``{'dateTime': ..., 'timeZone': ...}`` for a
    timed event and ``{'date': 'YYYY-MM-DD'}`` for an all-day one. The event's own
    ``timeZone`` wins over the calendar's, because a recurring instance carries the
    zone it recurs in -- but an unparseable name falls back rather than raising,
    since one bad zone string must not cost the caller every other event.
    """
    if not edge:
        return None
    if stamp := edge.get("dateTime"):
        zone_name = edge.get("timeZone")
        local = zone
        if zone_name:
            try:
                local = ZoneInfo(zone_name)
            except (ZoneInfoNotFoundError, ValueError):
                logger.warning("event carried an unknown timeZone %r; using %s", zone_name, zone)
        return _aware(stamp, local, "event time")
    if day := edge.get("date"):
        return datetime.combine(date.fromisoformat(day), time.min, tzinfo=zone)
    return None


def _local_iso(moment: datetime, zone: ZoneInfo) -> str:
    """A naive local wall-clock ISO string -- the shape this contract returns."""
    return moment.astimezone(zone).replace(tzinfo=None).isoformat()


# ---------------------------------------------------------------------------
# Normalising an event
# ---------------------------------------------------------------------------


def _is_owner(event: dict[str, Any]) -> bool:
    """Whether the user may move this event.

    ``organizer.self`` is authoritative: Google's own model is that "events have a
    single organizer which is the calendar containing the main copy of the event".
    ``creator.self`` is not -- the creator is never updated, and the organizer
    changes when an event is moved.

    ``locked`` is the second half. A locked copy refuses changes to ``start`` and
    ``end`` even when ``organizer.self`` is true; without this check
    ``reschedule_event`` passes its own test and then 403s at Google, which puts
    the refusal outside the audit trail instead of inside it.

    Failure direction: every lookup defaults to falsy, so a stripped payload -- a
    cancelled tombstone has no ``organizer`` at all -- reads **not owner**. Note
    the truthiness tests: Google omits ``self`` rather than sending ``false``, so
    ``is False`` would never fire.
    """
    organised = bool((event.get("organizer") or {}).get("self"))
    return organised and not event.get("locked")


def _response(event: dict[str, Any]) -> str:
    """The user's own RSVP, as ``"accepted" | "declined" | "none"``.

    ``"none"`` is meaningful and is not ``"declined"``: an event nobody responded
    to, in a slot that was otherwise free, is exactly the case where Second must
    admit it cannot tell. The demo's fourth beat depends on this distinction.

    ``tentative`` maps to ``accepted`` -- a maybe is not a refusal. (For
    *busy-ness* it maps the other way; see :func:`_occupies`.)

    A solo block has no ``attendees`` at all and reads ``"none"``, matching the
    fixture. Two cases silently read ``"none"`` when the user did in fact accept:
    an event with more than 200 guests, where Google documents that response
    status is not propagated, and one with ``attendeesOmitted``. Both are
    recorded in the log rather than guessed at.
    """
    if event.get("attendeesOmitted"):
        logger.info("event %s has attendeesOmitted; its response may read as none", event.get("id"))
    mine = next((a for a in event.get("attendees") or [] if a.get("self")), None)
    if mine is None:
        return "none"
    return {
        "accepted": "accepted",
        "tentative": "accepted",
        "declined": "declined",
        "needsAction": "none",
    }.get(mine.get("responseStatus", ""), "none")


def _attendee_count(event: dict[str, Any]) -> int:
    """How many people are on this event. ``1`` for a solo block, matching the fixture."""
    attendees = event.get("attendees") or []
    if event.get("attendeesOmitted"):
        logger.info("event %s omitted attendees; the count is a lower bound", event.get("id"))
    return len([a for a in attendees if not a.get("resource")]) or 1


def _normalise(event: dict[str, Any], zone: ZoneInfo) -> dict[str, Any] | None:
    """One Google event as the small dict this contract returns, or ``None``.

    ``None`` means the event carried no time at all, which happens for a deleted
    one-off: Google guarantees only ``id`` on those. A cancelled *exception* of a
    recurring series guarantees ``id``, ``recurringEventId`` and
    ``originalStartTime``, so the start falls back to ``originalStartTime`` before
    giving up -- which is what keeps the demo's dragged-task beat visible.

    A dropped row is logged. Silently discarding an event is the failure direction
    this whole module is written against.
    """
    start = _event_edge(event.get("start"), zone) or _event_edge(event.get("originalStartTime"), zone)
    if start is None:
        logger.warning(
            "calendar event %s has no start and was skipped (status=%s)",
            event.get("id"),
            event.get("status"),
        )
        return None

    end = _event_edge(event.get("end"), zone) or start
    return {
        "id": event.get("id", ""),
        "title": event.get("summary") or "(no title)",
        "start": _local_iso(start, zone),
        "end": _local_iso(end, zone),
        "status": event.get("status", "confirmed"),
        "is_owner": _is_owner(event),
        "attendees": _attendee_count(event),
        "response": _response(event),
    }


def _fetch_raw(start: str, end: str, zone: ZoneInfo) -> list[dict[str, Any]]:
    """Google's own event payloads for a window.

    ``showDeleted=True`` is load-bearing: ``events.list`` returns cancelled events
    only with this flag (or on an incremental sync), and the demo's dragged-task
    beat is three cancelled events. ``singleEvents=True`` expands recurrences to
    one row per occurrence -- without it the three-week "Eng sync" series arrives
    as a single row carrying an RRULE and the recurring 6pm conflict is invisible.
    ``orderBy='startTime'`` is a 400 unless ``singleEvents`` is true.

    Pagination loops on ``nextPageToken`` and not on a page being non-empty:
    Google documents that a page "may be less than this value, or none at all,
    even if there are more events matching the query", so stopping at the first
    empty page truncates the calendar -- and a truncated calendar looks exactly
    like a quiet week.

    Note this is an **overlap** filter, not a start filter: ``timeMin`` bounds an
    event's end and ``timeMax`` bounds its start. An event that began before the
    window and runs into it is returned. See :func:`get_calendar_events`.
    """
    return list(
        paged(
            service("calendar").events(),
            "list calendar events",
            key="items",
            calendarId=CALENDAR_ID,
            timeMin=_aware(start, zone, "start").isoformat(),
            timeMax=_aware(end, zone, "end").isoformat(),
            showDeleted=True,
            singleEvents=True,
            orderBy="startTime",
            maxResults=250,
        )
    )


def _fetch(start: str, end: str, zone: ZoneInfo) -> list[dict[str, Any]]:
    """Every event overlapping a window, oldest first, cancellations included."""
    events = [
        normalised
        for event in _fetch_raw(start, end, zone)
        if (normalised := _normalise(event, zone))
    ]
    return sorted(events, key=lambda event: event["start"])


# ---------------------------------------------------------------------------
# The tools
# ---------------------------------------------------------------------------


@tool
def get_calendar_events(start: str, end: str) -> list[dict]:
    """List the user's calendar events between two times.

    Includes cancelled events, because a task that was repeatedly rescheduled only
    looks like one if you can see the cancellations it left behind.

    Args:
        start: ISO 8601 datetime, the beginning of the window.
        end: ISO 8601 datetime, the end of the window.

    Returns:
        Events oldest first. Each has: id, title, start, end, status
        ("confirmed", "tentative" or "cancelled"), is_owner, attendees and
        response ("accepted", "declined" or "none"). Times are local wall-clock.

    Raises:
        CalendarError: If a bound is not ISO 8601.
        GoogleCallFailed: If Google could not be reached. Never an empty list --
            an empty list is indistinguishable from "nothing found" and would
            produce a confident diagnosis of the wrong thing.

    Note:
        **This returns the overlap set, where the fake returns the start set.**
        ``events.list``'s ``timeMin`` bounds an event's *end* and ``timeMax``
        bounds its *start*, so an event that began before ``start`` and runs into
        the window is included. ``fake_connectors`` filters ``lower <= start <
        upper`` and excludes it.

        Google cannot be asked for start-only filtering, and post-filtering for it
        would discard exactly the events that block time inside the window -- which
        is the information the Scheduler most needs. So the real tool keeps the
        overlap and the divergence is raised in the log for the CTO to settle in
        both places. It changes nothing in the demo, where no event straddles a
        window boundary.
    """
    return _fetch(start, end, _zone())


@tool
def find_free_slots(start: str, end: str, duration_min: int) -> list[dict]:
    """Find times in the calendar big enough for a given duration.

    Args:
        start: ISO 8601 datetime, the earliest slot to consider.
        end: ISO 8601 datetime, the latest.
        duration_min: How long the slot needs to be, in minutes.

    Returns:
        Free slots, earliest first, each with start, end and duration_min. Only
        between 07:00 and 22:00 local, on a half-hour grid.

    Raises:
        CalendarError: If duration_min is not positive, or a bound is not ISO 8601.

    Note:
        **The fake returns a hardcoded fixture; this computes real gaps.** The
        shape is identical (start, end, duration_min) so nothing downstream
        changes, but the values cannot match: ``fake_connectors`` emits 07:00 and
        12:00 on each weekday of a fixed week regardless of what is in the
        calendar, because it has no events to read.

        One behavioural difference worth knowing: this emits **every** fitting
        half-hour start inside a free gap, not one per gap. One slot per gap would
        make the demo's gym adaptation a foregone conclusion rather than a choice
        among candidates.
    """
    if duration_min <= 0:
        raise CalendarError(f"duration_min must be positive; got {duration_min}")

    zone = _zone()
    lower = _aware(start, zone, "start").astimezone(zone)
    upper = _aware(end, zone, "end").astimezone(zone)
    busy = _busy_spans(_fetch_raw(start, end, zone), zone)

    slots: list[dict[str, Any]] = []
    dropped = 0
    length = timedelta(minutes=duration_min)
    step = timedelta(minutes=SLOT_STEP_MINUTES)

    for day in _days(lower.date(), upper.date()):
        cursor = datetime.combine(day, DAY_START, tzinfo=zone)
        closes = datetime.combine(day, DAY_END, tzinfo=zone)
        while cursor + length <= closes:
            if cursor < lower or cursor + length > upper:
                cursor += step
                continue
            if not any(cursor < span_end and cursor + length > span_start for span_start, span_end in busy):
                if len(slots) < MAX_SLOTS:
                    slots.append(
                        {
                            "start": _local_iso(cursor, zone),
                            "end": _local_iso(cursor + length, zone),
                            "duration_min": duration_min,
                        }
                    )
                else:
                    dropped += 1
            cursor += step

    if dropped:
        logger.warning(
            "found %d free slots and returned the first %d; %d not shown",
            len(slots) + dropped,
            MAX_SLOTS,
            dropped,
        )
    return slots


@tool
def create_event(title: str, start: str, duration_min: int) -> str:
    """Put a new event in the user's calendar.

    Args:
        title: What the event is called. Use the task's own wording so the user
            recognises it.
        start: ISO 8601 datetime.
        duration_min: Length in minutes.

    Returns:
        A description of what was created, including the new event id.

    Raises:
        CalendarError: If the start is not ISO 8601, the duration is not positive,
            or the title is empty.
    """
    if not title.strip():
        raise CalendarError("an event needs a title the user will recognise")
    if duration_min <= 0:
        raise CalendarError(f"duration_min must be positive; got {duration_min}")

    zone = _zone()
    when = _aware(start, zone, "start")
    ends = when + timedelta(minutes=duration_min)

    created = call(
        service("calendar")
        .events()
        .insert(
            calendarId=CALENDAR_ID,
            sendUpdates="none",
            body={
                "summary": title.strip(),
                "start": _edge_body(when, zone),
                "end": _edge_body(ends, zone),
            },
        ),
        f"create {title.strip()!r}",
    )

    event_id = created.get("id", "?")
    return (
        f"created {event_id!r}: {title.strip()} from {_local_iso(when, zone)} "
        f"to {_local_iso(ends, zone)} ({zone})"
    )


@tool
def reschedule_event(event_id: str, new_start: str) -> str:
    """Move an event the user owns to a new time, keeping its length.

    Refuses any event the user does not organise, and any locked copy.
    **Failure direction: refuse.** A refused reschedule is a line in a log; a
    moved meeting is an apology to eight colleagues.

    Args:
        event_id: The event to move.
        new_start: ISO 8601 datetime to move it to.

    Returns:
        A description of the change.

    Raises:
        CalendarError: If the event does not exist, the user does not own it, or
            new_start is not ISO 8601.
    """
    zone = _zone()
    when = _aware(new_start, zone, "new_start")

    existing = call(
        service("calendar").events().get(calendarId=CALENDAR_ID, eventId=event_id),
        f"read event {event_id!r}",
    )
    if not existing:
        raise CalendarError(f"no event {event_id!r}")

    title = existing.get("summary") or "(no title)"
    if not _is_owner(existing):
        organiser = (existing.get("organizer") or {}).get("email", "someone else")
        raise CalendarError(
            f"{event_id!r} ({title}) is organised by {organiser} and will not be moved. "
            f"Second does not move events the user does not own."
        )

    was_start = _event_edge(existing.get("start"), zone)
    was_end = _event_edge(existing.get("end"), zone)
    if was_start is None or was_end is None:
        raise CalendarError(f"{event_id!r} ({title}) has no start or end and cannot be moved")
    length = was_end - was_start

    # The body is a literal, never caller-supplied, and the interlock holds this
    # route to {start, end} -- writing status here would be a soft delete.
    call(
        service("calendar")
        .events()
        .patch(
            calendarId=CALENDAR_ID,
            eventId=event_id,
            sendUpdates="none",
            body={"start": _edge_body(when, zone), "end": _edge_body(when + length, zone)},
        ),
        f"move event {event_id!r}",
    )

    return (
        f"moved {title!r} from {_local_iso(was_start, zone)} to "
        f"{_local_iso(when, zone)} ({zone}), keeping its {int(length.total_seconds() // 60)} minutes"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _edge_body(moment: datetime, zone: ZoneInfo) -> dict[str, str]:
    """One end of an event, as Google wants it written."""
    return {"dateTime": moment.astimezone(zone).isoformat(), "timeZone": str(zone)}


def _days(first: date, last: date) -> list[date]:
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def _occupies(event: dict[str, Any], raw: dict[str, Any]) -> bool:
    """Whether an event actually blocks its time.

    Four reasons it might not, each one a way ``find_free_slots`` would otherwise
    return ``[]`` and have that read as "the week is full":

    * **cancelled** -- it is not happening.
    * **declined** -- the demo's gym blocks were declined four weeks running. If a
      declined block counted as busy, 18:00 would look contended by the gym rather
      than by the Eng sync that actually took it, and the diagnosis would be wrong.
    * **transparent** -- Google's own "does not block time" flag.
    * **all-day** -- a birthday, a working-location marker, a travel day. Almost
      always a label rather than a block, and treating one as busy empties the
      entire day. ``birthday`` and ``workingLocation`` event types never occupy
      time at all; every other type does, so an unfamiliar seventh value Google
      adds later fails toward busy.

    ``tentative`` counts as **busy** -- the user is holding that time, even if they
    have not committed. That is the opposite of how ``_response`` maps it, and both
    are deliberate.
    """
    if event["status"] == "cancelled" or event["response"] == "declined":
        return False
    if raw.get("transparency") == "transparent":
        return False
    if raw.get("eventType", "default") in FREE_EVENT_TYPES:
        return False
    if (raw.get("start") or {}).get("date"):
        return False
    return True


def _busy_spans(raw_events: list[dict[str, Any]], zone: ZoneInfo) -> list[tuple[datetime, datetime]]:
    """The times that are genuinely taken, as aware datetimes.

    Takes the raw payloads rather than normalised ones because three of the four
    reasons an event does not occupy its time (``transparency``, ``eventType``,
    all-day) are keys the small contract dict deliberately drops.
    """
    spans: list[tuple[datetime, datetime]] = []
    for raw in raw_events:
        normalised = _normalise(raw, zone)
        if normalised is None or not _occupies(normalised, raw):
            continue
        spans.append(
            (
                _aware(normalised["start"], zone, "start").astimezone(zone),
                _aware(normalised["end"], zone, "end").astimezone(zone),
            )
        )
    return spans


ALL_CALENDAR_TOOLS = (get_calendar_events, find_free_slots, create_event, reschedule_event)
"""The four calendar tools. There is no fifth, and the missing one is ``delete``."""
