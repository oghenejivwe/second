"""The calendar tools, against recorded Google payloads.

No credentials, no network. Every test drives the real ``googleapiclient`` request
machinery through the real interlock, with only the wire replaced -- so a test
that passes here is evidence about the code that will run, not about a mock of it.

The fixtures are shaped like Google's actual responses, including the awkward
cases the bundled discovery document documents and the happy path does not show:
a cancelled tombstone with nothing but an id, a recurring instance whose
``dateTime`` carries no offset, an all-day marker, and an event organised by
somebody else.
"""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from second.tools import _google, calendar_tools
from second.tools._google import GoogleGuardViolation, recorded_service
from second.tools.calendar_tools import (
    CalendarError,
    create_event,
    find_free_slots,
    get_calendar_events,
    get_calendar_timezone,
    reschedule_event,
)

LONDON = "Europe/London"
EVENTS = "/calendar/v3/calendars/primary/events"
SETTINGS = "/calendar/v3/users/me/settings/timezone"
PRIMARY = "/calendar/v3/calendars/primary"


def _event(event_id, summary, start, end, **extra):
    """A Google event payload, with the keys Google actually sends."""
    payload = {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start, "timeZone": LONDON},
        "end": {"dateTime": end, "timeZone": LONDON},
        "status": "confirmed",
        "organizer": {"email": "jivwewonder@gmail.com", "self": True},
        "creator": {"email": "jivwewonder@gmail.com", "self": True},
    }
    payload.update(extra)
    return payload


def _install(responses):
    """Point the tools at a guarded, fixture-backed calendar client."""
    resource, transport = recorded_service("calendar", responses)
    _google.install_service("calendar", resource)
    return transport


@pytest.fixture(autouse=True)
def _clean():
    _google.reset_services()
    yield
    _google.reset_services()


@pytest.fixture
def timezone_response():
    return {("GET", SETTINGS): {"id": "timezone", "value": LONDON}}


# ---------------------------------------------------------------------------
# Timezone
# ---------------------------------------------------------------------------


def test_timezone_comes_from_the_user_setting(timezone_response):
    _install(timezone_response)
    assert get_calendar_timezone() == LONDON


def test_timezone_falls_back_to_the_primary_calendar():
    """``settings.get`` can return an empty value; the doc neither documents nor
    excludes it, which is exactly why the fall-through exists."""
    _install(
        {
            ("GET", SETTINGS): {"id": "timezone", "value": "   "},
            ("GET", PRIMARY): {"id": "primary", "timeZone": "Africa/Lagos"},
        }
    )
    assert get_calendar_timezone() == "Africa/Lagos"


def test_timezone_returns_none_rather_than_breaking_a_run():
    """``clock.py`` treats ``None`` as "use the machine and mark it untrustworthy".

    A timezone lookup that raised would take down every run that merely wanted to
    know what day it was.
    """
    _install({})  # every route raises FixtureMissing
    assert get_calendar_timezone() is None


def test_an_unknown_timezone_name_does_not_propagate(timezone_response):
    """Google can return a name ``zoneinfo`` does not have. Degrade, do not crash."""
    _install({("GET", SETTINGS): {"value": "Mars/Olympus_Mons"}, ("GET", PRIMARY): {}})
    assert calendar_tools._zone() == ZoneInfo("UTC")


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_events_are_returned_in_the_contract_shape(timezone_response):
    _install(
        {
            **timezone_response,
            ("GET", EVENTS): {
                "items": [
                    _event("clubaaa01", "Speaking club", "2026-09-08T19:00:00+01:00", "2026-09-08T20:30:00+01:00"),
                ]
            },
        }
    )
    (event,) = get_calendar_events("2026-09-08T00:00:00+01:00", "2026-09-09T00:00:00+01:00")

    assert event == {
        "id": "clubaaa01",
        "title": "Speaking club",
        "start": "2026-09-08T19:00:00",
        "end": "2026-09-08T20:30:00",
        "status": "confirmed",
        "is_owner": True,
        "attendees": 1,
        "response": "none",
    }
    assert set(event) == {
        "id", "title", "start", "end", "status", "is_owner", "attendees", "response",
    }, "the key set is the contract AGENTS codes against"


def test_a_utc_event_is_converted_not_truncated(timezone_response):
    """The hour-eating bug this module exists to avoid.

    Google returns an event written in UTC. Truncating the string would emit
    18:00; the user's calendar shows 19:00. Every wall-clock claim downstream --
    "Tuesdays 19:00 is the slot they keep" -- depends on this one conversion.
    """
    _install(
        {
            **timezone_response,
            ("GET", EVENTS): {
                "items": [
                    {
                        "id": "clubaaa01",
                        "summary": "Speaking club",
                        "start": {"dateTime": "2026-09-08T18:00:00Z"},
                        "end": {"dateTime": "2026-09-08T19:30:00Z"},
                        "status": "confirmed",
                        "organizer": {"self": True},
                    }
                ]
            },
        }
    )
    (event,) = get_calendar_events("2026-09-08T00:00:00+01:00", "2026-09-09T00:00:00+01:00")
    assert event["start"] == "2026-09-08T19:00:00", "+00:00 must be converted into Europe/London, not truncated"


def test_an_offsetless_datetime_uses_the_events_own_timezone(timezone_response):
    """``start.dateTime`` is legally offsetless when ``start.timeZone`` is present,
    and ``timeZone`` is mandatory on recurring events -- so every instance of the
    demo's "Eng sync" is this case. ``.astimezone()`` on a naive value would
    assume the machine's zone, which here is not the user's."""
    _install(
        {
            **timezone_response,
            ("GET", EVENTS): {
                "items": [
                    {
                        "id": "engsyn001",
                        "summary": "Eng sync",
                        "start": {"dateTime": "2026-09-08T18:00:00", "timeZone": "America/New_York"},
                        "end": {"dateTime": "2026-09-08T19:00:00", "timeZone": "America/New_York"},
                        "status": "confirmed",
                        "organizer": {"email": "lead@example.com"},
                    }
                ]
            },
        }
    )
    (event,) = get_calendar_events("2026-09-08T00:00:00+01:00", "2026-09-09T00:00:00+01:00")
    # 18:00 New York on 8 Sep 2026 is 23:00 London.
    assert event["start"] == "2026-09-08T23:00:00"
    assert event["is_owner"] is False


def test_cancelled_events_come_back_so_the_drag_is_visible(timezone_response):
    """The demo's second beat: a task dragged across four days is four events,
    three cancelled. If cancelled rows were dropped the story is invisible."""
    _install(
        {
            **timezone_response,
            ("GET", EVENTS): {
                "items": [
                    _event("pitchaa10", "Draft the talk pitch", "2026-08-30T17:00:00+01:00", "2026-08-30T17:45:00+01:00", status="cancelled"),
                    _event("pitchaa11", "Draft the talk pitch", "2026-08-31T17:00:00+01:00", "2026-08-31T17:45:00+01:00", status="cancelled"),
                    _event("pitchaa13", "Draft the talk pitch", "2026-09-02T17:00:00+01:00", "2026-09-02T17:45:00+01:00"),
                ]
            },
        }
    )
    events = get_calendar_events("2026-08-30T00:00:00+01:00", "2026-09-03T00:00:00+01:00")
    assert [e["status"] for e in events] == ["cancelled", "cancelled", "confirmed"]
    assert all(e["title"] == "Draft the talk pitch" for e in events)


def test_a_cancelled_exception_falls_back_to_its_original_start(timezone_response):
    """Google guarantees only ``id``, ``recurringEventId`` and ``originalStartTime``
    on a cancelled exception. Indexing ``start`` would raise and cost the caller
    every other event in the window."""
    _install(
        {
            **timezone_response,
            ("GET", EVENTS): {
                "items": [
                    {
                        "id": "engsyn001_20260908T170000Z",
                        "status": "cancelled",
                        "recurringEventId": "engsyn001",
                        "originalStartTime": {"dateTime": "2026-09-08T18:00:00+01:00", "timeZone": LONDON},
                    }
                ]
            },
        }
    )
    (event,) = get_calendar_events("2026-09-08T00:00:00+01:00", "2026-09-09T00:00:00+01:00")
    assert event["start"] == "2026-09-08T18:00:00"
    assert event["title"] == "(no title)"
    assert event["is_owner"] is False, "a stripped payload must read as not owned"


def test_a_timeless_tombstone_is_skipped_loudly(timezone_response, caplog):
    """A deleted one-off is guaranteed only ``id``. It cannot be placed in a
    window, so it is skipped -- but never silently, because a vanishing row is the
    failure direction this module is written against."""
    _install(
        {
            **timezone_response,
            ("GET", EVENTS): {
                "items": [
                    {"id": "goneaaa01", "status": "cancelled"},
                    _event("clubaaa01", "Speaking club", "2026-09-08T19:00:00+01:00", "2026-09-08T20:30:00+01:00"),
                ]
            },
        }
    )
    with caplog.at_level("WARNING"):
        events = get_calendar_events("2026-09-08T00:00:00+01:00", "2026-09-09T00:00:00+01:00")

    assert [e["id"] for e in events] == ["clubaaa01"]
    assert "goneaaa01" in caplog.text and "skipped" in caplog.text


def test_pagination_follows_the_token_not_the_page_contents(timezone_response):
    """Google documents that a page "may be less than this value, or none at all,
    even if there are more events matching the query". Stopping on an empty page
    truncates the calendar, and a truncated calendar reads as a quiet week."""
    pages = iter(
        [
            {"items": [], "nextPageToken": "p2"},
            {
                "items": [
                    _event("clubaaa01", "Speaking club", "2026-09-08T19:00:00+01:00", "2026-09-08T20:30:00+01:00")
                ]
            },
        ]
    )
    _install({**timezone_response, ("GET", EVENTS): lambda uri, body: next(pages)})

    events = get_calendar_events("2026-09-08T00:00:00+01:00", "2026-09-09T00:00:00+01:00")
    assert [e["id"] for e in events] == ["clubaaa01"], "an empty first page is not the end"


def test_the_list_request_asks_for_cancelled_and_expanded_events(timezone_response):
    """``showDeleted`` and ``singleEvents`` are the two parameters the demo needs,
    and ``orderBy='startTime'`` is a 400 without the second."""
    transport = _install({**timezone_response, ("GET", EVENTS): {"items": []}})
    get_calendar_events("2026-09-08T00:00:00+01:00", "2026-09-09T00:00:00+01:00")

    (_, uri, _) = next(call for call in transport.calls if "/events" in call[1])
    for required in ("showDeleted=true", "singleEvents=true", "orderBy=startTime"):
        assert required in uri, uri


@pytest.mark.parametrize(
    "attendees,expected_response,expected_count",
    [
        (None, "none", 1),
        ([{"self": True, "responseStatus": "accepted"}], "accepted", 1),
        ([{"self": True, "responseStatus": "declined"}], "declined", 1),
        ([{"self": True, "responseStatus": "needsAction"}], "none", 1),
        ([{"self": True, "responseStatus": "tentative"}], "accepted", 1),
        ([{"self": True, "responseStatus": "accepted"}, {"email": "a@b.c"}], "accepted", 2),
        ([{"self": True, "responseStatus": "accepted"}, {"email": "room@b.c", "resource": True}], "accepted", 1),
    ],
)
def test_response_and_attendee_count(timezone_response, attendees, expected_response, expected_count):
    """``needsAction`` is ``"none"``, not ``"declined"``.

    An event nobody responded to, on a slot that was otherwise free, is precisely
    the case where Second must admit it cannot tell -- which is the demo's fourth
    beat and the only one a merely fluent system cannot fake. ``tentative`` goes
    the other way: a maybe is not a refusal.

    Resources (meeting rooms) are not people and must not inflate the count.
    """
    extra = {"attendees": attendees} if attendees is not None else {}
    _install(
        {
            **timezone_response,
            ("GET", EVENTS): {
                "items": [
                    _event("recordaa1", "Record five minutes", "2026-09-08T08:00:00+01:00", "2026-09-08T08:15:00+01:00", **extra)
                ]
            },
        }
    )
    (event,) = get_calendar_events("2026-09-08T00:00:00+01:00", "2026-09-09T00:00:00+01:00")
    assert event["response"] == expected_response
    assert event["attendees"] == expected_count


@pytest.mark.parametrize(
    "payload,owned",
    [
        ({"organizer": {"self": True}}, True),
        ({"organizer": {"email": "lead@example.com"}}, False),
        ({"organizer": {}}, False),
        ({}, False),
        ({"organizer": {"self": True}, "locked": True}, False),
        ({"creator": {"self": True}, "organizer": {"email": "lead@example.com"}}, False),
    ],
)
def test_ownership_fails_toward_not_owned(payload, owned):
    """``organizer.self`` is authoritative and ``locked`` is the second half.

    ``creator.self`` is not authoritative: the creator is never updated and the
    organizer changes when an event is moved. The last case is the dangerous one --
    an event the user created that somebody else now organises.

    Every lookup defaults to falsy, so a stripped payload reads "not owner". Note
    that Google *omits* ``self`` rather than sending ``false``, which is why these
    are truthiness tests and not ``is False``.
    """
    assert calendar_tools._is_owner(payload) is owned


# ---------------------------------------------------------------------------
# Free slots
# ---------------------------------------------------------------------------


def test_free_slots_avoid_real_meetings(timezone_response):
    _install(
        {
            **timezone_response,
            ("GET", EVENTS): {
                "items": [
                    _event("engsyn001", "Eng sync", "2026-09-14T18:00:00+01:00", "2026-09-14T19:00:00+01:00",
                           organizer={"email": "lead@example.com"}, attendees=[{"self": True, "responseStatus": "accepted"}]),
                ]
            },
        }
    )
    slots = find_free_slots("2026-09-14T07:00:00+01:00", "2026-09-14T22:00:00+01:00", 60)
    starts = [s["start"] for s in slots]

    assert "2026-09-14T07:00:00" in starts
    assert "2026-09-14T18:00:00" not in starts, "the Eng sync holds 18:00"
    assert "2026-09-14T17:30:00" not in starts, "17:30-18:30 runs into it"
    assert "2026-09-14T17:00:00" in starts, (
        "17:00-18:00 ends exactly as the meeting starts. Adjacent is not overlapping, "
        "and excluding it would quietly lose the slot most likely to be usable"
    )
    assert "2026-09-14T19:00:00" in starts, "the slot immediately after is free too"
    assert all(s["duration_min"] == 60 for s in slots)


def test_a_declined_block_does_not_hold_its_time(timezone_response):
    """The demo's first beat depends on this.

    The gym blocks were declined four weeks running. If a declined event counted
    as busy, 18:00 would look contended by the gym rather than by the Eng sync that
    actually took it, and the Diagnostician would name the wrong cause.
    """
    _install(
        {
            **timezone_response,
            ("GET", EVENTS): {
                "items": [
                    _event("gymaaa001", "Gym session", "2026-09-14T18:00:00+01:00", "2026-09-14T19:00:00+01:00",
                           attendees=[{"self": True, "responseStatus": "declined"}]),
                ]
            },
        }
    )
    starts = [s["start"] for s in find_free_slots("2026-09-14T07:00:00+01:00", "2026-09-14T22:00:00+01:00", 60)]
    assert "2026-09-14T18:00:00" in starts


@pytest.mark.parametrize(
    "extra,reason",
    [
        ({"status": "cancelled"}, "a cancelled event is not happening"),
        ({"transparency": "transparent"}, "Google's own does-not-block-time flag"),
        ({"eventType": "birthday"}, "a birthday is a label, not a block"),
        ({"eventType": "workingLocation"}, "so is a working-location marker"),
    ],
)
def test_events_that_do_not_hold_their_time(timezone_response, extra, reason):
    _install(
        {
            **timezone_response,
            ("GET", EVENTS): {
                "items": [
                    _event("markeraa1", "Marker", "2026-09-14T10:00:00+01:00", "2026-09-14T11:00:00+01:00", **extra)
                ]
            },
        }
    )
    starts = [s["start"] for s in find_free_slots("2026-09-14T07:00:00+01:00", "2026-09-14T22:00:00+01:00", 60)]
    assert "2026-09-14T10:00:00" in starts, reason


def test_an_all_day_marker_does_not_empty_the_day(timezone_response):
    """A single "Working from home" or birthday entry would otherwise make every
    weekday 100% booked and return ``[]`` -- which reads downstream as "the week is
    full" rather than "I could not tell"."""
    _install(
        {
            **timezone_response,
            ("GET", EVENTS): {
                "items": [
                    {
                        "id": "wfhaaa001",
                        "summary": "Working from home",
                        "start": {"date": "2026-09-14"},
                        "end": {"date": "2026-09-15"},
                        "status": "confirmed",
                        "organizer": {"self": True},
                    }
                ]
            },
        }
    )
    slots = find_free_slots("2026-09-14T07:00:00+01:00", "2026-09-14T22:00:00+01:00", 60)
    assert slots, "an all-day marker must not empty the day"


def test_an_unknown_event_type_still_holds_its_time(timezone_response):
    """Failure direction: refuse to schedule over something we do not recognise.

    ``eventType`` has six values today. If Google adds a seventh, it must default
    to busy rather than to free -- booking the user over their own flight is worse
    than offering one fewer slot. ``fromGmail`` is the live version of this: those
    are the flight and hotel reservations Google creates from confirmation emails,
    and the demo's third beat is booking flights to Lisbon.
    """
    for event_type in ("fromGmail", "somethingGoogleAddsIn2027"):
        _install(
            {
                **timezone_response,
                ("GET", EVENTS): {
                    "items": [
                        _event("flightaa1", "Flight to Lisbon", "2026-09-14T10:00:00+01:00",
                               "2026-09-14T13:00:00+01:00", eventType=event_type)
                    ]
                },
            }
        )
        starts = [s["start"] for s in find_free_slots("2026-09-14T07:00:00+01:00", "2026-09-14T22:00:00+01:00", 60)]
        assert "2026-09-14T10:00:00" not in starts, f"{event_type} must hold its time"
        _google.reset_services()


def test_free_slots_stay_inside_the_working_window(timezone_response):
    _install({**timezone_response, ("GET", EVENTS): {"items": []}})
    slots = find_free_slots("2026-09-14T00:00:00+01:00", "2026-09-15T00:00:00+01:00", 60)
    hours = {datetime.fromisoformat(s["start"]).hour for s in slots}
    assert min(hours) >= calendar_tools.DAY_START.hour
    assert max(hours) + 1 <= calendar_tools.DAY_END.hour


def test_truncation_is_logged_rather_than_silent(timezone_response, caplog):
    """A capped list that looks complete is how a confidently wrong plan gets made."""
    _install({**timezone_response, ("GET", EVENTS): {"items": []}})
    with caplog.at_level("WARNING"):
        slots = find_free_slots("2026-09-14T07:00:00+01:00", "2026-09-28T22:00:00+01:00", 30)

    assert len(slots) == calendar_tools.MAX_SLOTS
    assert "not shown" in caplog.text


def test_a_bad_duration_raises_rather_than_returning_nothing(timezone_response):
    _install(timezone_response)
    for bad in (0, -30):
        with pytest.raises(CalendarError, match="must be positive"):
            find_free_slots("2026-09-14T07:00:00+01:00", "2026-09-14T22:00:00+01:00", bad)


def test_a_bad_datetime_raises(timezone_response):
    _install(timezone_response)
    with pytest.raises(CalendarError, match="ISO 8601"):
        get_calendar_events("next tuesday", "2026-09-14T22:00:00+01:00")


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def test_create_event_writes_a_timed_event_and_notifies_nobody(timezone_response):
    transport = _install(
        {**timezone_response, ("POST", EVENTS): {"id": "createdaa1", "summary": "Gym session"}}
    )
    told = create_event("Gym session", "2026-09-14T07:00:00+01:00", 60)

    assert "createdaa1" in told and "Gym session" in told
    (_, uri, body) = next(call for call in transport.calls if call[0] == "POST")
    assert "sendUpdates=none" in uri, (
        "sendUpdates has no documented default on insert; omitting it risks emailing "
        "real colleagues 21 days of fabricated invites from the demo account"
    )
    sent = json.loads(body)
    assert sent["start"] == {"dateTime": "2026-09-14T07:00:00+01:00", "timeZone": LONDON}
    assert sent["end"] == {"dateTime": "2026-09-14T08:00:00+01:00", "timeZone": LONDON}
    assert "status" not in sent


def test_create_event_rejects_an_empty_title(timezone_response):
    _install(timezone_response)
    with pytest.raises(CalendarError, match="title"):
        create_event("   ", "2026-09-14T07:00:00+01:00", 60)


def test_reschedule_keeps_the_original_duration(timezone_response):
    one_event = _event("gymaaa001", "Gym session", "2026-09-14T18:00:00+01:00", "2026-09-14T19:30:00+01:00")
    transport = _install(
        {
            **timezone_response,
            ("GET", f"{EVENTS}/gymaaa001"): one_event,
            ("PATCH", f"{EVENTS}/gymaaa001"): {"id": "gymaaa001"},
        }
    )
    told = reschedule_event("gymaaa001", "2026-09-15T07:00:00+01:00")

    assert "Gym session" in told and "90 minutes" in told
    (_, uri, body) = next(call for call in transport.calls if call[0] == "PATCH")
    assert "sendUpdates=none" in uri
    sent = json.loads(body)
    assert sent["start"]["dateTime"] == "2026-09-15T07:00:00+01:00"
    assert sent["end"]["dateTime"] == "2026-09-15T08:30:00+01:00", "the 90-minute length must survive the move"
    assert set(sent) == {"start", "end"}, "anything else on this route would be refused by the interlock"


def test_reschedule_refuses_someone_elses_meeting(timezone_response):
    """The rail. **Failure direction: refuse.**

    A refused reschedule is a line in a log; a moved meeting is an apology to eight
    colleagues. The refusal happens in this code, before Google is asked, so the
    cause lands inside the audit trail instead of arriving as a 403 outside it.
    """
    foreign = _event(
        "engsyn001",
        "Eng sync",
        "2026-09-14T18:00:00+01:00",
        "2026-09-14T19:00:00+01:00",
        organizer={"email": "lead@example.com"},
        creator={"email": "lead@example.com"},
        attendees=[{"self": True, "responseStatus": "accepted"}, {"email": "lead@example.com"}],
    )
    transport = _install({**timezone_response, ("GET", f"{EVENTS}/engsyn001"): foreign})

    with pytest.raises(CalendarError, match="organised by lead@example.com"):
        reschedule_event("engsyn001", "2026-09-15T07:00:00+01:00")

    assert not any(call[0] == "PATCH" for call in transport.calls), "nothing may be written"


def test_reschedule_refuses_a_locked_copy(timezone_response):
    """``locked`` can be True while ``organizer.self`` is also True. Without this
    the tool passes its own ownership check and then 403s at Google, which puts the
    refusal outside the audit trail instead of inside it."""
    locked = _event("offsitea1", "Offsite", "2026-09-14T09:00:00+01:00", "2026-09-14T17:00:00+01:00", locked=True)
    _install({**timezone_response, ("GET", f"{EVENTS}/offsitea1"): locked})

    with pytest.raises(CalendarError):
        reschedule_event("offsitea1", "2026-09-15T09:00:00+01:00")


def test_reschedule_cannot_be_talked_into_a_soft_delete(timezone_response):
    """Belt and braces over the interlock.

    ``reschedule_event`` builds its patch body as a literal, so there is no input
    that makes it write ``status``. If somebody later threads a caller-supplied
    dict into it, the interlock refuses -- this test pins that the two layers agree
    about which route is in play.
    """
    one_event = _event("gymaaa001", "Gym session", "2026-09-14T18:00:00+01:00", "2026-09-14T19:00:00+01:00")
    _install({**timezone_response, ("GET", f"{EVENTS}/gymaaa001"): one_event})

    service = _google.service("calendar")
    with pytest.raises(GoogleGuardViolation, match="body sets"):
        service.events().patch(
            calendarId="primary", eventId="gymaaa001", body={"status": "cancelled"}
        ).execute()


def test_there_is_no_delete_tool():
    """The guarantee is the absence of a code path, so this asserts absence."""
    assert not hasattr(calendar_tools, "delete_event")
    assert len(calendar_tools.ALL_CALENDAR_TOOLS) == 4
    assert {t.tool_name for t in calendar_tools.ALL_CALENDAR_TOOLS} == {
        "get_calendar_events",
        "find_free_slots",
        "create_event",
        "reschedule_event",
    }
