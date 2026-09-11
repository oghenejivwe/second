"""The demo seeder, driven against recorded Google payloads.

Every write here goes through the **seeder** allowlist, which is wider than the
runtime's by three routes and no more. The tests that matter most are the ones
checking that the widening stops where it was argued to stop.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from second.testing import demo_scenario
from second.tools import _google
from second.tools._google import GoogleGuardViolation, recorded_service

ROOT = Path(__file__).resolve().parents[2]
EVENTS = "/calendar/v3/calendars/primary/events"
MESSAGES = "/gmail/v1/users/me/messages"
LONDON = ZoneInfo("Europe/London")

BASE32HEX = re.compile(r"^[a-v0-9]{5,1024}$")


def _load(name: str):
    """Import a script by path -- ``scripts/`` is not a package."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def seed():
    return _load("seed_demo")


@pytest.fixture(autouse=True)
def _clean():
    _google.reset_services()
    yield
    _google.reset_services()


def _install(responses):
    calendar, cal_transport = recorded_service("calendar", responses, "seeder")
    gmail, gmail_transport = recorded_service("gmail", responses, "seeder")
    _google.install_service("calendar", calendar, "seeder")
    _google.install_service("gmail", gmail, "seeder")
    return cal_transport, gmail_transport


# ---------------------------------------------------------------------------
# Event ids
# ---------------------------------------------------------------------------


def test_every_fixture_id_becomes_a_legal_google_id(seed):
    """Twenty of the thirty-two fixture ids are illegal as Google event ids.

    Google event ids are base32hex: lowercase ``a-v`` and ``0-9``. ``engsync000``
    and ``gym000`` both contain ``y``, which is outside ``a-v`` -- and so does the
    brief's own suggested replacement ``seedgym001``. The seeder hard-fails 400 on
    its first insert with "Invalid resource id value", which reads like a
    ``calendarId`` problem.
    """
    fixture_ids = [event["id"] for event in demo_scenario.calendar_events()]
    illegal = [i for i in fixture_ids if not BASE32HEX.match(i)]
    assert len(illegal) == 20, "the fixture changed; re-check the id derivation"
    assert not BASE32HEX.match("seedgym001"), "the brief's example is illegal too ('y')"

    derived = [seed.legal_event_id(i) for i in fixture_ids]
    assert all(BASE32HEX.match(d) for d in derived)
    assert all(len(d) >= 5 for d in derived)


def test_derived_ids_are_deterministic_and_unique(seed):
    """Deterministic is what makes re-running safe: the second run addresses the same
    events instead of creating thirty-two more."""
    fixture_ids = [event["id"] for event in demo_scenario.calendar_events()]
    once = [seed.legal_event_id(i) for i in fixture_ids]
    twice = [seed.legal_event_id(i) for i in fixture_ids]

    assert once == twice
    assert len(set(once)) == len(set(fixture_ids)), "a collision would silently merge two events"


# ---------------------------------------------------------------------------
# What gets written
# ---------------------------------------------------------------------------


def test_the_plan_covers_the_whole_fixture(seed):
    planned = seed.planned_events(LONDON)
    assert len(planned) == len(demo_scenario.calendar_events())

    assert sum(1 for p in planned if p["foreign"]) == 15, "the Eng sync series"
    assert sum(1 for p in planned if p["cancel_after"]) == 3, "the dragged task"


def test_every_event_is_tagged_so_it_can_be_found_again(seed):
    """``extendedProperties.private`` keys are limited to 44 characters and a longer
    one is **silently dropped** -- after which the find-my-seed-data query returns
    nothing and you conclude nothing was written."""
    for plan in seed.planned_events(LONDON):
        private = plan["body"]["extendedProperties"]["private"]
        assert private[seed.SEED_TAG_KEY] == seed.SEED_TAG_VALUE
        assert private[seed.SEED_ORIGIN_KEY] == plan["fixture_id"]
        assert all(len(key) <= 44 for key in private), "a longer key is dropped without a word"


def test_an_owned_event_is_inserted_with_its_id_in_the_body(seed):
    """``events.insert`` has no ``eventId`` parameter -- it raises ``TypeError``
    before any HTTP call. The id goes in ``body['id']``."""
    cal, _ = _install({("POST", EVENTS): {"id": "x"}})
    plan = next(p for p in seed.planned_events(LONDON) if not p["foreign"])

    assert seed.write_event(plan, LONDON) == "inserted"
    (_, uri, body) = cal.calls[0]
    assert "sendUpdates=none" in uri, (
        "the discovery doc declares no default; omitting it risks emailing 21 days of "
        "fabricated invites to real colleagues"
    )
    assert json.loads(body)["id"] == plan["event_id"]


def test_a_foreign_event_is_imported_because_only_import_writes_the_organiser(seed):
    """``Event.organizer`` is read-only *except when importing*.

    Without this the fifteen Eng sync events are owned by the demo account,
    ``reschedule_event`` never refuses anything, and the beat where Second declines
    to move a colleague's meeting has nothing real behind it.
    """
    cal, _ = _install({("POST", f"{EVENTS}/import"): {"id": "x"}})
    plan = next(p for p in seed.planned_events(LONDON) if p["foreign"])

    assert seed.write_event(plan, LONDON) == "imported"
    (verb, uri, body) = cal.calls[0]
    assert verb == "POST" and uri.endswith("/events/import?alt=json")

    sent = json.loads(body)
    assert sent["organizer"]["email"] == seed.FOREIGN_ORGANISER
    assert sent["iCalUID"], "events.import requires iCalUID"
    assert "sendUpdates" not in uri, "import has no sendUpdates parameter, so it cannot notify anyone"
    assert "@example.com" in seed.FOREIGN_ORGANISER, (
        "import writes organizer verbatim; a real address puts a stranger in the demo account"
    )


def test_a_repeat_run_patches_instead_of_failing(seed):
    """Re-inserting an existing id is a 409 ``duplicate`` and ``num_retries`` will not
    retry it. This script will be run five times before the demo."""
    cal, _ = _install(
        {
            ("POST", EVENTS): (409, {"error": {"errors": [{"reason": "duplicate"}], "message": "The requested identifier already exists."}}),
            ("PATCH", lambda: None): None,  # placeholder, replaced below
        }
    )
    plan = next(p for p in seed.planned_events(LONDON) if not p["foreign"])
    cal, _ = _install(
        {
            ("POST", EVENTS): (409, {"error": {"errors": [{"reason": "duplicate"}], "message": "exists"}}),
            ("PATCH", f"{EVENTS}/{plan['event_id']}"): {"id": plan["event_id"]},
        }
    )

    assert seed.write_event(plan, LONDON) == "already present"
    patches = [c for c in cal.calls if c[0] == "PATCH"]
    assert len(patches) == 1
    assert set(json.loads(patches[0][2])) == {"start", "end", "status"}


def test_a_cancelled_event_is_created_then_patched(seed):
    """Whether ``events.insert`` accepts ``status='cancelled'`` on creation is
    documented nowhere verifiable, so it is created confirmed and then cancelled.

    A calendar has no move history: a task dragged across four days only looks like
    one if it was recreated four times with three cancellations left behind.
    """
    plan = next(p for p in seed.planned_events(LONDON) if p["cancel_after"])
    cal, _ = _install(
        {
            ("POST", EVENTS): {"id": plan["event_id"]},
            ("PATCH", f"{EVENTS}/{plan['event_id']}"): {"id": plan["event_id"], "status": "cancelled"},
        }
    )

    seed.write_event(plan, LONDON)
    assert "status" not in json.loads(cal.calls[0][2]), "created confirmed"

    seed.cancel_event(plan)
    assert json.loads(cal.calls[-1][2]) == {"status": "cancelled"}


def test_the_rsvp_is_written_so_the_declined_beat_survives(seed):
    """Without an attendee entry carrying the user's own RSVP, every seeded event
    reads ``response="none"`` and the recurring-6pm-conflict beat becomes four
    honoured gym sessions."""
    declined = [
        p for p in seed.planned_events(LONDON)
        if any(a.get("responseStatus") == "declined" for a in p["body"].get("attendees") or [])
    ]
    assert len(declined) == 4, "four of five gym sessions were declined"
    assert all(a["email"] == demo_scenario.USER_EMAIL for p in declined for a in p["body"]["attendees"])


# ---------------------------------------------------------------------------
# Mail
# ---------------------------------------------------------------------------


def test_messages_are_backdated_and_labelled(seed):
    """Two silent failures in one call.

    ``internalDateSource`` defaults to ``receivedTime`` on **insert** (it defaults to
    ``dateHeader`` on import, which is the trap), so without it every fabricated
    message is stamped with today's date in front of a judge. And mail inserted with
    no ``labelIds`` lands in All Mail and not the inbox, so it is invisible.
    """
    _, gmail = _install({("POST", MESSAGES): {"id": "m1"}})
    plan = seed.planned_messages(LONDON)[0]

    seed.write_message(plan)
    (verb, uri, body) = gmail.calls[0]

    assert verb == "POST"
    assert "internalDateSource=dateHeader" in uri, uri
    assert json.loads(body)["labelIds"] == ["INBOX", "UNREAD"]


def test_the_sent_item_is_labelled_sent(seed):
    """``SENT`` and ``DRAFT`` are the two labels ``messages.insert`` documents support
    for. The empty-of-leave-requests sent folder is what makes the flight booking
    genuinely blocked rather than merely late."""
    plans = seed.planned_messages(LONDON)
    sent = [p for p in plans if p["labels"] == ["SENT"]]

    assert len(sent) == 1
    assert "leave" not in sent[0]["subject"].lower(), (
        "the sent folder must contain no leave request -- its absence is the evidence"
    )


def test_the_backdated_header_is_a_real_rfc822_date(seed):
    """Parsed with the stdlib, so the test is about the message rather than about my
    own formatter agreeing with itself."""
    import base64
    from email import message_from_bytes
    from email.policy import SMTP
    from email.utils import parsedate_to_datetime

    plan = seed.planned_messages(LONDON)[0]
    parsed = message_from_bytes(base64.urlsafe_b64decode(plan["body"]["raw"]), policy=SMTP)
    when = parsedate_to_datetime(parsed["Date"])

    assert when.tzinfo is not None, "a naive Date header gets misplaced by a later conversion"
    assert when.year == 2026 and when.month == 3, "the policy email is five months before the demo"


# ---------------------------------------------------------------------------
# The rails still hold for the seeder
# ---------------------------------------------------------------------------


def test_the_seeder_still_cannot_send_or_delete():
    """Wider is not unbounded. The seeder writes to the same real mailbox and the
    same real calendar, so it keeps the two promises."""
    calendar, _ = recorded_service("calendar", {}, "seeder")
    gmail, _ = recorded_service("gmail", {}, "seeder")

    with pytest.raises(GoogleGuardViolation):
        calendar.events().delete(calendarId="primary", eventId="sdabc12345").execute()
    with pytest.raises(GoogleGuardViolation):
        calendar.calendars().clear(calendarId="primary").execute()
    with pytest.raises(GoogleGuardViolation):
        gmail.users().messages().send(userId="me", body={}).execute()
    with pytest.raises(GoogleGuardViolation):
        gmail.users().drafts().send(userId="me", body={"id": "r1"}).execute()
    with pytest.raises(GoogleGuardViolation):
        gmail.users().messages().batchDelete(userId="me", body={"ids": ["m1"]}).execute()


def test_the_runtime_cannot_do_any_of_what_the_seeder_does():
    """The split is the claim that the agent cannot fabricate its own evidence.

    If the runtime could insert mail or import an event, the Preparer could write the
    message it later cites, and every citation in the product would be worth nothing.
    """
    calendar, _ = recorded_service("calendar", {}, "runtime")
    gmail, _ = recorded_service("gmail", {}, "runtime")

    with pytest.raises(GoogleGuardViolation):
        gmail.users().messages().insert(userId="me", body={"raw": "eA=="}).execute()
    with pytest.raises(GoogleGuardViolation):
        calendar.events().import_(calendarId="primary", body={"iCalUID": "x@y"}).execute()
    with pytest.raises(GoogleGuardViolation, match="body sets"):
        calendar.events().patch(
            calendarId="primary", eventId="sdabc12345", body={"status": "cancelled"}
        ).execute()


def test_the_seeder_does_not_read_the_timezone_itself(seed):
    """``settings.get`` needs ``calendar``, ``calendar.readonly`` or
    ``calendar.settings.readonly``. The seeder holds ``calendar.events``, which covers
    none of them -- so reading the zone would 403 on the first call. It is a required
    argument instead.
    """
    source = (ROOT / "scripts" / "seed_demo.py").read_text(encoding="utf-8")
    assert "get_calendar_timezone" not in source.split('"""', 2)[-1], (
        "the seeder credential cannot read the calendar timezone"
    )

    with pytest.raises(SystemExit):
        seed.main([])  # --zone is required
