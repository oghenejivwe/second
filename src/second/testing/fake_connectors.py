"""Working stand-ins for the seven CONNECTORS tools.

**These exist so nobody waits on credentials.** They carry the same names, the
same signatures and the same safety rails as the real tools, and they read from
:mod:`second.testing.demo_scenario`. An agent built and tested against these runs
unchanged against Google.

Three deliberate properties:

* **The rails are real here too.** ``draft_email`` cannot send, there is no
  delete, and ``reschedule_event`` refuses an event the user does not own. An
  agent developed against permissive fakes learns habits the real tools will
  refuse, and finds out late.
* **They raise rather than returning error dicts**, matching the standing rule.
  A returned error dict leaves ``AfterToolCallEvent.exception`` as ``None`` and
  strips the audit record of its cause.
* **Writes are recorded, not applied.** Everything a fake tool "does" lands in
  ``invocation_state["second"]["fake_effects"]`` so a test can assert that the
  Preparer drafted an email without anything leaving the process.

CONNECTORS: the dict shapes returned here are the contract AGENTS is already
coding against. If a real Google payload makes one of them wrong, say so in a
turn and the CTO will land the change in both places at once.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from strands import ToolContext, tool

from second.settings import NAMESPACE
from second.testing import demo_scenario


class FakeConnectorError(RuntimeError):
    """A fake connector was asked for something the real one would refuse."""


def _scope(tool_context: ToolContext) -> dict[str, Any]:
    return tool_context.invocation_state.setdefault(NAMESPACE, {})


def _record(tool_context: ToolContext, kind: str, **detail: Any) -> None:
    """Log a would-be side effect instead of performing one."""
    _scope(tool_context).setdefault("fake_effects", []).append({"kind": kind, **detail})


def _parse(value: str, field: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as error:
        raise FakeConnectorError(f"{field} must be an ISO 8601 datetime; got {value!r}") from error


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------


@tool(context=True)
def get_calendar_events(start: str, end: str, tool_context: ToolContext) -> list[dict]:
    """List the user's calendar events between two times.

    Includes cancelled events, because a task that was repeatedly rescheduled
    only looks like one if you can see the cancellations it left behind.

    Args:
        start: ISO 8601 datetime, inclusive.
        end: ISO 8601 datetime, exclusive.

    Returns:
        Events oldest first. Each has: id, title, start, end, status
        ("confirmed" or "cancelled"), is_owner, attendees, and response
        ("accepted", "declined" or "none").

    Raises:
        FakeConnectorError: If either bound is not an ISO 8601 datetime.
    """
    lower, upper = _parse(start, "start"), _parse(end, "end")
    # OVERLAP, not start-within. Google's timeMin bounds an event's END and
    # timeMax its START, so an event that began before the window and runs into
    # it comes back -- and those are exactly the events that block time inside
    # the window, which is what the Scheduler most needs to know about. The fake
    # filtered on start and was the one that was wrong. CONNECTORS found it.
    return [
        event
        for event in demo_scenario.calendar_events()
        if datetime.fromisoformat(event["start"]) < upper
        and datetime.fromisoformat(event["end"]) > lower
    ]


@tool(context=True)
def find_free_slots(start: str, end: str, duration_min: int, tool_context: ToolContext) -> list[dict]:
    """Find gaps in the calendar big enough for a given duration.

    Args:
        start: ISO 8601 datetime, the earliest slot to consider.
        end: ISO 8601 datetime, the latest.
        duration_min: How long the slot needs to be, in minutes.

    Returns:
        Free slots, earliest first, each with start, end and duration_min.

    Raises:
        FakeConnectorError: If duration_min is not positive.
    """
    if duration_min <= 0:
        raise FakeConnectorError(f"duration_min must be positive; got {duration_min}")
    lower, upper = _parse(start, "start"), _parse(end, "end")
    return [
        slot
        for slot in demo_scenario.free_slots(duration_min)
        if lower <= datetime.fromisoformat(slot["start"]) < upper
    ]


@tool(context=True)
def create_event(title: str, start: str, duration_min: int, tool_context: ToolContext) -> str:
    """Put a new event in the user's calendar.

    Args:
        title: What the event is called. Use the task's own wording so the user
            recognises it.
        start: ISO 8601 datetime.
        duration_min: Length in minutes.

    Returns:
        A description of what was created, including the new event id.

    Raises:
        FakeConnectorError: If the start is not ISO 8601, or duration is not
            positive.
    """
    when = _parse(start, "start")
    if duration_min <= 0:
        raise FakeConnectorError(f"duration_min must be positive; got {duration_min}")

    event_id = f"created{len(_scope(tool_context).get('fake_effects', [])):03d}"
    _record(tool_context, "create_event", event_id=event_id, title=title, start=start)
    ends = (when + timedelta(minutes=duration_min)).isoformat()
    return f"created {event_id!r}: {title} from {start} to {ends}"


@tool(context=True)
def reschedule_event(event_id: str, new_start: str, tool_context: ToolContext) -> str:
    """Move an event the user owns to a new time.

    Refuses any event the user does not own. **Failure direction: refuse.** A
    refused reschedule is a line in a log; a moved meeting is an apology to eight
    colleagues.

    Args:
        event_id: The event to move.
        new_start: ISO 8601 datetime to move it to.

    Returns:
        A description of the change.

    Raises:
        FakeConnectorError: If the event does not exist, or the user does not own
            it.
    """
    _parse(new_start, "new_start")
    event = next(
        (candidate for candidate in demo_scenario.calendar_events() if candidate["id"] == event_id),
        None,
    )
    if event is None:
        raise FakeConnectorError(f"no event {event_id!r}")
    if not event["is_owner"]:
        raise FakeConnectorError(
            f"{event_id!r} ({event['title']}) belongs to someone else and will not be moved"
        )

    _record(tool_context, "reschedule_event", event_id=event_id, new_start=new_start)
    return f"moved {event['title']!r} from {event['start']} to {new_start}"


# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------


@tool(context=True)
def search_gmail(query: str, tool_context: ToolContext, max_results: int = 10) -> list[dict]:
    """Search the user's mail.

    Matches words in the subject, body and sender. Add "in:sent" to search what
    the user has sent rather than received -- which is how you establish that
    something was never sent at all.

    Args:
        query: Words to look for.
        max_results: How many to return at most.

    Returns:
        Matching messages, each with id, from, to, subject, date, snippet and
        body.
    """
    terms = [word.lower() for word in query.split() if word.lower() != "in:sent"]
    corpus = demo_scenario.sent_items() if "in:sent" in query.lower() else demo_scenario.inbox()

    def matches(message: dict) -> bool:
        haystack = " ".join(
            str(message.get(field, "")) for field in ("subject", "body", "from", "snippet")
        ).lower()
        return all(term in haystack for term in terms) if terms else True

    return [message for message in corpus if matches(message)][:max_results]


@tool(context=True)
def draft_email(to: str, subject: str, body: str, tool_context: ToolContext) -> str:
    """Create a draft email. It is never sent.

    This is the governing principle in one tool: carry the work to the last
    click, and stop. The user opens their drafts, reads it, and presses send --
    or does not.

    Args:
        to: Recipient address.
        subject: Subject line.
        body: Full message body. Write it ready to send, not as a sketch.

    Returns:
        A description of the draft, including its id.

    Raises:
        FakeConnectorError: If the recipient or subject is empty.
    """
    if not to.strip():
        raise FakeConnectorError("a draft needs a recipient")
    if not subject.strip():
        raise FakeConnectorError("a draft needs a subject")

    draft_id = f"draft{len(_scope(tool_context).get('fake_effects', [])):03d}"
    _record(tool_context, "draft_email", draft_id=draft_id, to=to, subject=subject, body=body)
    return f"drafted {draft_id!r} to {to} - {subject!r} ({len(body)} chars). Not sent."


# ---------------------------------------------------------------------------
# Web
# ---------------------------------------------------------------------------


@tool(context=True)
def web_search(query: str, tool_context: ToolContext, max_results: int = 5) -> list[dict]:
    """Search the web for material.

    Args:
        query: What to search for.
        max_results: How many results to return.

    Returns:
        Results, each with title, url, snippet and kind ("video" or "article").
    """
    _record(tool_context, "web_search", query=query)
    catalogue = [
        {
            "title": "How to structure a five-minute talk",
            "url": "https://example.com/five-minute-talk",
            "snippet": "A simple three-beat structure for very short talks.",
            "kind": "video",
        },
        {
            "title": "Vocal delivery: pace, pause, pitch",
            "url": "https://example.com/vocal-delivery",
            "snippet": "Drills for varying pace and using silence deliberately.",
            "kind": "video",
        },
        {
            "title": "Speaking club formats explained",
            "url": "https://example.com/club-formats",
            "snippet": "What to expect from a first visit.",
            "kind": "article",
        },
    ]
    return catalogue[:max_results]


ALL_FAKE_CONNECTORS = (
    get_calendar_events,
    find_free_slots,
    create_event,
    reschedule_event,
    search_gmail,
    draft_email,
    web_search,
)
"""Every fake, ready to hand to a ``ToolRegistry``.

There is no ``delete_event`` here, and there is none in the real connectors
either. The guarantee that Second never deletes a calendar event is that no code
path exists to do it."""
