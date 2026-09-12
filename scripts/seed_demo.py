"""Build the demo world in a real Google account.

    uv run python scripts/seed_demo.py --zone Europe/London --smoke
    uv run python scripts/seed_demo.py --zone Europe/London --apply
    uv run python scripts/seed_demo.py --zone Europe/London --wipe

Writes exactly what ``second.testing.demo_scenario`` describes: three weeks of
calendar history with four planted beats, and four messages plus one sent item. The
same dataset AGENTS develops against, so the live system sees the world the
Diagnostician was tuned on.

Runs under the **seeder** credential, which is never deployed. ``gmail.insert`` and
``calendar.events``, nothing else. That split is the point: the runtime agent
physically cannot insert mail, so it cannot manufacture the evidence it later cites.

Nine things that each cost an hour to discover
==============================================

1. **Twenty of the thirty-two fixture event ids are illegal.** Google event ids are
   base32hex -- lowercase ``a-v`` and ``0-9``. ``engsync000`` and ``gym000`` both
   contain ``y``, which is outside ``a-v``. So does the brief's own suggested
   ``seedgym001``. Ids here are derived by hashing the fixture id, because hex
   output is legal base32hex by construction and a hash is deterministic, which is
   what makes re-running safe.

2. **``events.insert`` has no ``eventId`` parameter.** The id goes in
   ``body['id']``. Passing ``eventId=`` raises ``TypeError`` before any HTTP call --
   unlike ``patch``/``get``, where it is a path parameter.

3. **Re-inserting an existing id is a 409 ``duplicate``**, and ``num_retries`` will
   not retry it. Caught and turned into a patch, which is the whole idempotency
   story: this script is safe to run five times before the demo, and it will be.

4. **A deleted id is not reusable** -- the 409 persists against the tombstone. So
   ``--wipe`` patches ``status`` to cancelled rather than deleting, which the
   interlock would refuse anyway. Reseeding patches the same ids back to confirmed.

5. **``sendUpdates='none'`` on every write.** The discovery document declares no
   default for it. Omitting it risks emailing twenty-one days of fabricated invites
   to real colleagues from the demo account.

6. **The fifteen "Eng sync" events need ``events.import``.** ``Event.organizer`` is
   read-only *except when importing*, and import is the only way to seed a meeting
   the demo account does not own. Without it every seeded event is owned,
   ``reschedule_event`` never refuses, and the beat where Second declines to move a
   colleague's meeting has nothing real behind it. Import also takes no
   ``sendUpdates`` parameter, so it cannot notify anyone at all.

7. **The three cancelled events are inserted confirmed, then patched.** Whether
   ``events.insert`` accepts ``status='cancelled'`` on creation is documented
   nowhere I could verify, and this is not the place to find out.

8. **Inserted mail with no ``labelIds`` is invisible** -- it lands in All Mail and
   not the inbox. And ``internalDateSource`` defaults to ``receivedTime`` on
   ``insert`` (it defaults to ``dateHeader`` on ``import``, which is the trap), so
   without it every fabricated message is stamped with today's date in front of a
   judge.

9. **Gmail's search index is eventually consistent.** Insert five messages and
   search immediately and you get nothing: the write succeeded and the read hit a
   stale replica. This script waits and then verifies, rather than letting you
   conclude the insert failed.

Why ``--zone`` is required rather than read
==========================================

``get_calendar_timezone`` needs ``calendar``, ``calendar.readonly`` or
``calendar.settings.readonly``. The seeder holds ``calendar.events``, which covers
none of them, so this credential **cannot** read the timezone and asking it would
403 on the first call. Pass it explicitly; the runtime token can tell you what it
is::

    uv run python scripts/authorize_google.py --role runtime --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CALENDAR_ID = "primary"
USER_ID = "me"

SEED_TAG_KEY = "secondSeed"
SEED_TAG_VALUE = "v1"
"""Tags every seeded event so it can be found and retired.

``extendedProperties.private`` keys are limited to 44 characters and a longer one is
**silently dropped** -- after which the find-my-seed-data query returns nothing and
you conclude nothing was written. Short on purpose."""

SEED_ORIGIN_KEY = "secondFrom"
"""The fixture id this event came from, so a seeded calendar can be read back
against ``demo_scenario`` without matching on title strings."""

FOREIGN_ORGANISER = "lead@example.com"
"""The organiser of the Eng sync series. Must not be a real address: ``events.import``
writes it verbatim and a real one would be a stranger's name in the demo account."""

INDEX_WAIT_SECONDS = 20


def legal_event_id(fixture_id: str) -> str:
    """A Google-legal, deterministic event id derived from a fixture id.

    Google event ids are base32hex: lowercase ``a-v`` and ``0-9``, at least 5
    characters. Hex digits are a subset of that, so a hex digest is legal by
    construction -- which avoids slugifying, and avoids discovering at 2am that the
    letter ``y`` is not in ``a-v``.

    Deterministic, so re-running the seeder addresses the same events.
    """
    return "sd" + hashlib.blake2s(fixture_id.encode("utf-8"), digest_size=8).hexdigest()


# ---------------------------------------------------------------------------
# What to write
# ---------------------------------------------------------------------------


def _edge(moment: datetime, zone: ZoneInfo) -> dict[str, str]:
    return {"dateTime": moment.replace(tzinfo=zone).isoformat(), "timeZone": str(zone)}


def planned_events(zone: ZoneInfo) -> list[dict[str, Any]]:
    """Every event to write, from the fixture, in the order to write it."""
    from second.testing import demo_scenario

    planned = []
    for event in demo_scenario.calendar_events():
        fixture_id = event["id"]
        event_id = legal_event_id(fixture_id)
        body: dict[str, Any] = {
            "id": event_id,
            "summary": event["title"],
            "start": _edge(datetime.fromisoformat(event["start"]), zone),
            "end": _edge(datetime.fromisoformat(event["end"]), zone),
            "extendedProperties": {
                "private": {SEED_TAG_KEY: SEED_TAG_VALUE, SEED_ORIGIN_KEY: fixture_id}
            },
        }

        # The user's own RSVP has to be on the event as an attendee entry, or
        # get_calendar_events reads every seeded event as response="none" and the
        # declined-gym beat disappears.
        if event["response"] != "none":
            body["attendees"] = [{"email": demo_scenario.USER_EMAIL, "responseStatus": event["response"]}]

        planned.append(
            {
                "fixture_id": fixture_id,
                "event_id": event_id,
                "body": body,
                "foreign": not event["is_owner"],
                "cancel_after": event["status"] == "cancelled",
                "attendee_count": event["attendees"],
            }
        )
    return planned


def planned_messages(zone: ZoneInfo) -> list[dict[str, Any]]:
    """Every message to insert, with its backdated ``Date`` header."""
    from second.testing import demo_scenario
    from second.tools.gmail_tools import rfc822

    planned = []
    for message, labels in (
        *[(m, ["INBOX", "UNREAD"]) for m in demo_scenario.inbox()],
        # SENT is one of the two labels messages.insert explicitly supports.
        *[(m, ["SENT"]) for m in demo_scenario.sent_items()],
    ):
        sent_at = datetime.fromisoformat(message["date"]).replace(tzinfo=zone)
        planned.append(
            {
                "fixture_id": message["id"],
                "subject": message["subject"],
                "labels": labels,
                "body": {
                    "raw": rfc822(
                        message["to"],
                        message["subject"],
                        message["body"],
                        sent_at=sent_at,
                    ),
                    "labelIds": labels,
                },
                "date": sent_at.isoformat(),
                "from": message["from"],
            }
        )
    return planned


# ---------------------------------------------------------------------------
# Writing it
# ---------------------------------------------------------------------------


def _events():
    from second.tools._google import service

    return service("calendar", "seeder").events()


def _messages():
    from second.tools._google import service

    return service("gmail", "seeder").users().messages()


def _messages_as_runtime():
    """Gmail, read through the RUNTIME credential rather than the seeder's.

    The seeder holds ``gmail.insert`` and ``calendar.events`` and nothing else,
    so ``messages().list`` under it is a guaranteed 403 insufficientPermissions.
    403 is not retryable, so it raised -- uncaught, at the tail of ``verify()``,
    *after* every write had committed. The operator saw a traceback at the end of
    a successful seed and would reasonably re-run the whole thing.

    Reading back as the runtime is also the more honest check: the runtime is
    what has to find this mail on demo day, so proving the runtime can see it
    proves the thing that matters. The seeder proving it could see its own writes
    would have proved nothing.
    """
    from second.tools._google import service

    return service("gmail", "runtime").users().messages()


def _duplicate(error: BaseException) -> bool:
    """Whether this is Google's 409 ``duplicate``, which means "already seeded".

    Walks ``__cause__``: ``_google.call`` wraps every ``HttpError`` in a
    ``GoogleCallFailed`` raised ``from`` it, so the 409 is one link down the chain
    rather than the exception in hand. Checking only the top type is how an
    idempotency path silently never fires -- which is exactly what happened, and
    ``test_a_repeat_run_patches_instead_of_failing`` is why it did not survive.
    """
    from googleapiclient.errors import HttpError

    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, HttpError) and getattr(current.resp, "status", 0) == 409:
            return True
        current = current.__cause__
    return False


def write_event(plan: dict[str, Any], zone: ZoneInfo) -> str:
    """Insert or import one event, patching instead if it is already there."""
    from second.tools._google import call

    body = dict(plan["body"])

    if plan["foreign"]:
        # Only import can write organizer, and only a written organizer makes
        # is_owner False -- which is what reschedule_event refuses on.
        body["organizer"] = {"email": FOREIGN_ORGANISER, "displayName": "Engineering lead"}
        body["iCalUID"] = f"{plan['event_id']}@second.demo"
        body["attendees"] = [
            {"email": FOREIGN_ORGANISER, "organizer": True, "responseStatus": "accepted"},
            {"email": _user_email(), "responseStatus": plan["body"].get("attendees", [{}])[0].get("responseStatus", "accepted")},
            *[
                {"email": f"colleague{n}@example.com", "responseStatus": "accepted"}
                for n in range(1, max(0, plan["attendee_count"] - 2) + 1)
            ],
        ]
        try:
            call(_events().import_(calendarId=CALENDAR_ID, body=body), f"import {plan['fixture_id']}")
            return "imported"
        except Exception as error:  # noqa: BLE001
            if not _duplicate(error):
                raise
            return _repatch(plan, zone, "already imported")

    try:
        # The id goes in the BODY. There is no eventId parameter on insert.
        call(
            _events().insert(calendarId=CALENDAR_ID, sendUpdates="none", body=body),
            f"insert {plan['fixture_id']}",
        )
        return "inserted"
    except Exception as error:  # noqa: BLE001
        if not _duplicate(error):
            raise
        return _repatch(plan, zone, "already present")


def _repatch(plan: dict[str, Any], zone: ZoneInfo, note: str) -> str:
    """Bring an existing seeded event back to its intended time and status.

    This is what makes re-running safe, and what ``--wipe`` is the inverse of. The
    interlock holds the seeder's PATCH body to ``{start, end, status}``, so this
    cannot quietly widen into rewriting attendees.
    """
    from second.tools._google import call

    call(
        _events().patch(
            calendarId=CALENDAR_ID,
            eventId=plan["event_id"],
            sendUpdates="none",
            body={"start": plan["body"]["start"], "end": plan["body"]["end"], "status": "confirmed"},
        ),
        f"re-time {plan['fixture_id']}",
    )
    return note


def cancel_event(plan: dict[str, Any]) -> None:
    """Patch an event to cancelled -- Google's own soft delete.

    The three "Draft the talk pitch" events are created confirmed and then cancelled,
    because a calendar has no move history: a task that was dragged across four days
    only looks like one if it was actually recreated four times, three of them left
    behind as cancellations.
    """
    from second.tools._google import call

    call(
        _events().patch(
            calendarId=CALENDAR_ID,
            eventId=plan["event_id"],
            sendUpdates="none",
            body={"status": "cancelled"},
        ),
        f"cancel {plan['fixture_id']}",
    )


def write_message(plan: dict[str, Any]) -> None:
    """Insert one backdated message."""
    from second.tools._google import call

    call(
        _messages().insert(
            userId=USER_ID,
            # Without this every fabricated message is stamped with today's date.
            # insert defaults to receivedTime; import is the one that defaults to
            # dateHeader, which is why the default here is the wrong way round.
            internalDateSource="dateHeader",
            body=plan["body"],
        ),
        f"insert message {plan['fixture_id']}",
    )


def _user_email() -> str:
    from second.testing import demo_scenario

    return demo_scenario.USER_EMAIL


# ---------------------------------------------------------------------------
# Verifying it
# ---------------------------------------------------------------------------


def verify(zone: ZoneInfo) -> int:
    """Read the seeded world back and check the four beats survived.

    Each of these has failed silently for somebody: cancelled events invisible
    without ``showDeleted``, ownership not written because ``import`` was not used,
    mail stamped with today's date, mail with no label.
    """
    from second.tools._google import call, paged

    problems: list[str] = []

    seeded = list(
        paged(
            _events(),
            "read back the seeded calendar",
            key="items",
            calendarId=CALENDAR_ID,
            showDeleted=True,
            singleEvents=True,
            orderBy="startTime",
            privateExtendedProperty=f"{SEED_TAG_KEY}={SEED_TAG_VALUE}",
            maxResults=250,
        )
    )
    print(f"  calendar: {len(seeded)} tagged events found")

    cancelled = [e for e in seeded if e.get("status") == "cancelled"]
    if len(cancelled) < 3:
        problems.append(
            f"expected at least 3 cancelled events for the dragged-task beat, found "
            f"{len(cancelled)}. Without them the Observer sees one confirmed event and "
            f"no drag history."
        )

    foreign = [e for e in seeded if not (e.get("organizer") or {}).get("self")]
    if not foreign:
        problems.append(
            "no seeded event is organised by somebody else, so reschedule_event will "
            "never refuse anything on real data. events.import did not write organizer "
            "as expected -- fall back to creating the Eng sync series from a second "
            "Google account and inviting this one."
        )
    else:
        print(f"  calendar: {len(foreign)} events owned by somebody else (reschedule_event will refuse these)")

    declined = [
        e
        for e in seeded
        if any(a.get("self") and a.get("responseStatus") == "declined" for a in e.get("attendees") or [])
    ]
    if not declined:
        problems.append(
            "no seeded event carries a declined RSVP, so the recurring-6pm-conflict "
            "beat reads as four honoured sessions."
        )

    print(f"\n  waiting {INDEX_WAIT_SECONDS}s for Gmail's search index (it is eventually consistent)...")
    time.sleep(INDEX_WAIT_SECONDS)

    # Nothing from here on may raise. Every write is already committed, and a
    # traceback at this point reads as "the seed failed" when the seed succeeded
    # -- which invites exactly the re-run that duplicates a world that cannot be
    # deleted. Failures become problems; the caller still exits non-zero.
    try:
        found = call(
            _messages_as_runtime().list(
                userId=USER_ID, q='subject:"travel insurance policy"', maxResults=5
            ),
            "search for the seeded policy email",
        )
    except Exception as error:  # noqa: BLE001 - see the comment above
        problems.append(
            f"could not read the mail back as the runtime: {type(error).__name__}: {error}. "
            f"THE WRITES ABOVE ALL SUCCEEDED -- do not re-run --apply. Authorise the "
            f"runtime role if you have not, then re-run this with --verify."
        )
    else:
        if not (found.get("messages") or []):
            problems.append(
                "the policy email is not searchable yet. The insert may still have "
                "succeeded -- Gmail's index lags. Check the inbox by eye before concluding "
                "anything, and re-run this verification rather than re-inserting."
            )
        else:
            print(f"  gmail: the policy email is searchable ({len(found['messages'])} hit)")

    if problems:
        print("\nPROBLEMS:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nAll four beats verified.")
    return 0


def wipe(zone: ZoneInfo) -> int:
    """Retire every seeded event by patching it to cancelled.

    Not deleting: the interlock forbids DELETE, and a deleted id cannot be reused
    anyway -- a later insert with the same id still returns 409 against the
    tombstone. Patching to cancelled leaves the ids reusable, so reseeding works.
    """
    from second.tools._google import paged

    seeded = list(
        paged(
            _events(),
            "find seed events to retire",
            key="items",
            calendarId=CALENDAR_ID,
            showDeleted=True,
            singleEvents=True,
            privateExtendedProperty=f"{SEED_TAG_KEY}={SEED_TAG_VALUE}",
            maxResults=250,
        )
    )
    live = [e for e in seeded if e.get("status") != "cancelled"]
    print(f"retiring {len(live)} of {len(seeded)} seeded events (cancelling, not deleting)")

    for event in live:
        cancel_event({"event_id": event["id"], "fixture_id": event["id"]})
    print("done. Re-run with --apply to bring them back; the ids are deterministic.")
    print("Seeded MAIL is not touched -- there is no route to remove it and no scope for one.")
    return 0


# ---------------------------------------------------------------------------


def run(zone: ZoneInfo, *, smoke: bool, apply: bool) -> int:
    events = planned_events(zone)
    messages = planned_messages(zone)

    if smoke:
        # One event and one message before twenty of each. A bad id, a bad body or a
        # missing scope fails identically on the first and on the thirty-second, and
        # finding out on the first is twenty minutes cheaper.
        events = [next(e for e in events if e["foreign"])][:1] + [
            next(e for e in events if e["cancel_after"])
        ][:1]
        messages = messages[:1]
        print("SMOKE TEST: one imported event, one cancelled event, one message.\n")

    if not apply:
        print(f"DRY RUN. Would write {len(events)} events and {len(messages)} messages.\n")
        for plan in events[:5]:
            kind = "import" if plan["foreign"] else "insert"
            print(f"  {kind:7} {plan['event_id']}  {plan['body']['summary']:24} "
                  f"{plan['body']['start']['dateTime']}"
                  f"{'  then cancel' if plan['cancel_after'] else ''}")
        if len(events) > 5:
            print(f"  ... and {len(events) - 5} more")
        for plan in messages:
            print(f"  message {plan['labels']} {plan['date'][:10]}  {plan['subject'][:50]}")
        print("\nRe-run with --apply to write it.")
        return 0

    print(f"Writing {len(events)} events...")
    outcomes: dict[str, int] = {}
    for plan in events:
        outcome = write_event(plan, zone)
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        if plan["cancel_after"]:
            cancel_event(plan)
            outcomes["cancelled"] = outcomes.get("cancelled", 0) + 1
    print(f"  {', '.join(f'{count} {name}' for name, count in sorted(outcomes.items()))}")

    print(f"\nWriting {len(messages)} messages...")
    for plan in messages:
        write_message(plan)
        print(f"  {plan['labels']} {plan['date'][:10]}  {plan['subject'][:50]}")

    print("\nVerifying...")
    return verify(zone)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--zone",
        required=True,
        help="IANA timezone, e.g. Europe/London. Required: the seeder's calendar.events "
        "scope cannot read it (settings.get needs calendar or calendar.readonly).",
    )
    parser.add_argument("--apply", action="store_true", help="actually write; default is a dry run")
    parser.add_argument("--smoke", action="store_true", help="one event and one message only")
    parser.add_argument("--wipe", action="store_true", help="cancel every seeded event")
    parser.add_argument("--verify", action="store_true", help="read the seeded world back and check the beats")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(ROOT / "src"))
    try:
        zone = ZoneInfo(args.zone)
    except Exception:  # noqa: BLE001
        print(f"unknown timezone {args.zone!r}")
        return 1

    from second.testing import demo_scenario

    print(f"Seeding against anchor date {demo_scenario.TODAY} in {zone}.")
    print("The Living Graph uses the same anchor; shifting one without the other")
    print("desynchronises the plan from the calendar.\n")

    if args.wipe:
        return wipe(zone)
    if args.verify:
        return verify(zone)
    return run(zone, smoke=args.smoke, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
