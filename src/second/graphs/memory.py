"""What to remember today, gathered from every source Second can read.

The founder asked for "a memory tab that reminds them every important thing for that day", pulling
from the calendar "and from any other sources we tie in later". So this module is a seam first and
three sources second.

Adding a source
---------------

A source is one class with a ``name`` and a ``collect(context)`` method returning
:class:`Collected`. Register it in :func:`default_sources`, which is the only list of sources in the
system, and add its name to ``MemorySourceName`` in ``core/models.py`` so the browser's generated
types know how to label its items. That is the whole change: a Slack source reads Slack inside
``collect``, and nothing else here or in the service moves.

Every source inherits three rules from the code around it rather than from its own care:

* **Every item carries evidence.** ``MemoryItem`` refuses to be built without it. These items are
  made in Python, never by a forced tool call, so a raise fails a test instead of starting a model
  loop -- the opposite trade from ``Diagnosis``, for the opposite reason.
* **A source that cannot be read says so.** Raise :class:`SourceUnavailable` with a sentence, or let
  the error escape. Either way the source is listed as not connected with the reason, and the other
  sources still run. An empty list from a broken calendar reads as "nothing to remember", which is
  the most confident wrong answer this tab could give. The reverse holds too: a source that was
  read and simply has nothing yet is connected, with a note saying why it is empty.
* **Reading is all a source does.** ``GET /api/memory`` is a read. A source never writes, never runs
  the daily graph and never calls a model; the email source reads what the morning run already
  concluded rather than asking a model again on every page view.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from second.core.clock import Clock
from second.core.models import (
    DailyBrief,
    HorizonQuestion,
    LivingGraph,
    Memory,
    MemoryItem,
    MemorySourceStatus,
    ScheduledBlock,
)
from second.graphs.brief import NO_JUDGEMENT, blocks_on, deadline_risks
from second.graphs.wording import day_label, plural, quoted, what_is_prepared

logger = logging.getLogger(__name__)

CalendarReader = Callable[[str, str], list[dict[str, Any]]]
"""``get_calendar_events`` as a plain call: ISO start and end in, the connector's event dicts out."""


class SourceUnavailable(RuntimeError):
    """A source could not be read. The message is what the user is shown as the reason."""


@dataclass(frozen=True)
class MemoryContext:
    """Everything a source may read, loaded once so two sources never see two different graphs."""

    user_id: str
    graph: LivingGraph
    clock: Clock
    brief: DailyBrief | None = None
    """Today's cached brief, or None when the morning run has not happened. Never computed here."""


@dataclass
class Collected:
    """What one source found, and a line about how it found it."""

    items: list[MemoryItem] = field(default_factory=list)
    note: str = ""
    """Shown beside the source. Say what was read and what was left out, so that zero items reads
    as a result rather than as a failure."""


class MemorySource(Protocol):
    """One place memory items come from. See the module docstring for how to add one."""

    name: str

    def collect(self, context: MemoryContext) -> Collected: ...


# ---------------------------------------------------------------------------
# The sources
# ---------------------------------------------------------------------------


class GraphSource:
    """What the Living Graph already knows matters today.

    Today's placed blocks come first, as events. Memory said "On today 0" while Today and Schedule
    each showed three blocks, because only the calendar fed that group and the demo calendar is
    empty today. The plan is a fact the graph holds, so the graph says it.
    """

    name = "graph"

    def collect(self, context: MemoryContext) -> Collected:
        graph, clock = context.graph, context.clock
        # Every item the graph owns carries the goal and task ids it came from, so a screen can take
        # it off when that goal is paused or retired without matching on a title.
        items: list[MemoryItem] = [
            MemoryItem(
                what=block.title,
                evidence=_in_the_plan(block),
                source="graph",
                kind="event",
                at=block.start,
                goal_id=block.goal_id,
                task_id=block.task_id,
            )
            for block in blocks_on(graph, clock, clock.today)
        ]

        waiting = [
            action
            for action in (context.brief.prepared if context.brief is not None else [])
            # Only work actually waiting on a click. "nothing" is the Preparer saying there was
            # nothing to carry, and an action with no awaiting step is not the user's to finish.
            if action.is_real and action.awaiting.strip()
        ]
        folded: set[int] = set()

        for risk in deadline_risks(graph, clock):
            # One thing, one item. The leave request was listed twice, once as "nothing booked"
            # and once as "a draft is waiting", and the two read as a contradiction. Folded only on
            # the task id the prepared action names, never on similar wording: two titles that
            # look alike are a guess.
            action = next(
                (candidate for candidate in waiting if candidate.task_id == risk.task_id and id(candidate) not in folded),
                None,
            )
            if action is None:
                items.append(
                    MemoryItem(
                        what=f"{risk.what}, due {day_label(risk.deadline)}",
                        evidence=risk.evidence,
                        source="graph",
                        kind="deadline",
                        due=risk.deadline,
                        goal_id=risk.goal_id,
                        task_id=risk.task_id,
                    )
                )
                continue
            folded.add(id(action))
            items.append(
                MemoryItem(
                    what=f"{risk.what}, due {day_label(risk.deadline)}",
                    evidence=f"Due {day_label(risk.deadline)}. {what_is_prepared(action)}",
                    source="graph",
                    kind="waiting_on_you",
                    due=risk.deadline,
                    goal_id=risk.goal_id,
                    task_id=risk.task_id,
                )
            )

        for action in waiting:
            if id(action) in folded:
                continue
            task_id, goal_id = _owner_of(graph, action.task_id)
            items.append(
                MemoryItem(
                    what=action.summary,
                    evidence=f"On today's brief. {what_is_prepared(action)}",
                    source="graph",
                    kind="waiting_on_you",
                    goal_id=goal_id,
                    task_id=task_id,
                )
            )

        for goal in graph.active_goals():
            for route in goal.routes:
                if route.status not in ("approved", "proposed"):
                    continue
                for task in route.tasks:
                    blocker = (task.known_blocker or "").strip()
                    if task.status == "done" or not blocker:
                        continue
                    items.append(
                        MemoryItem(
                            what=f"{task.title}: {blocker}",
                            evidence=f"What you told Second about {quoted(task.title)}: {quoted(blocker)}",
                            source="graph",
                            kind="told_second",
                            goal_id=goal.id,
                            task_id=task.id,
                        )
                    )

        for constraint in graph.person.constraints:
            if constraint.strip():
                items.append(
                    MemoryItem(
                        what=constraint.strip(),
                        evidence=f"A standing rule Second plans around: {quoted(constraint.strip())}",
                        source="graph",
                        kind="constraint",
                    )
                )

        note = "Today's plan, deadlines at risk, what you told Second, and your standing rules."
        if context.brief is None:
            note += " The morning run has not happened yet today, so nothing it prepared is listed."
        return Collected(items=items, note=note)


class CalendarSource:
    """Today's calendar events that are not already in today's plan.

    Second's own task blocks are calendar events too, created with the task's own title, and the
    graph source already lists them as events. Showing "Gym session 07:00" twice is noise, so an
    event whose title and start both match a block placed today is left to the graph source. That
    match is reliable for the events Second creates. It would also fold in an event the user made by
    hand with exactly a task's title at exactly its time, which costs nothing, because the block
    is already listed at that time.

    Cancelled and declined events are not things the user is doing today, so they are counted in
    the note rather than listed.
    """

    name = "calendar"

    def __init__(self, read_events: CalendarReader | None = None) -> None:
        self._read_events = read_events

    def collect(self, context: MemoryContext) -> Collected:
        clock = context.clock
        # The live reader is looked up at call time rather than bound at construction, so a test
        # can replace it for a whole request without reaching into an instance.
        read = self._read_events or live_calendar
        start, end = clock.window()
        events = read(start, end)

        own = {
            (block.title.casefold(), block.start)
            for block in blocks_on(context.graph, clock, clock.today)
        }

        items: list[MemoryItem] = []
        cancelled = declined = in_plan = 0
        for event in events:
            if event.get("status") == "cancelled":
                cancelled += 1
                continue
            if event.get("response") == "declined":
                declined += 1
                continue

            title = str(event.get("title") or "(no title)")
            begins = clock.local(datetime.fromisoformat(event["start"]))
            ends = clock.local(datetime.fromisoformat(event["end"]))
            if (title.casefold(), begins) in own:
                in_plan += 1
                continue

            items.append(
                MemoryItem(
                    what=title,
                    evidence=_quote_event(event, title, begins, ends),
                    source="calendar",
                    kind="event",
                    at=begins,
                )
            )

        return Collected(items=items, note=_calendar_note(len(events), in_plan, cancelled, declined))


class EmailSource:
    """Commitments made in email, as this morning's run found them.

    Reads the reminders on today's cached brief and nothing else. Spotting a forgotten promise in
    an inbox is judgement, which is why the Communicator does it during the daily run; doing it
    again here would call a model on a GET.

    No brief yet is not a broken inbox. The morning run simply has not happened, so the source is
    connected with nothing in it and says so. It is listed as not connected only when a run did
    happen and could not finish reading, because then an empty list really would mislead.
    """

    name = "email"

    def collect(self, context: MemoryContext) -> Collected:
        brief = context.brief
        if brief is None:
            return Collected(note="The morning run has not read your email yet today.")
        if brief.silence_reason == NO_JUDGEMENT and not brief.reminders:
            raise SourceUnavailable(
                "The morning run could not finish reading your email today, so nothing from it is listed."
            )

        items: list[MemoryItem] = []
        unsupported = 0
        for reminder in brief.reminders:
            if reminder.source != "email":
                continue  # a calendar or graph reminder stays on the brief, where it came from
            if not (reminder.evidence or "").strip():
                # Counted and said out loud, rather than dropped quietly or allowed to take the
                # supported reminders down with it.
                unsupported += 1
                continue
            items.append(
                MemoryItem(what=reminder.what, evidence=reminder.evidence, source="email", kind="reminder")
            )

        if items or unsupported:
            note = "From the morning run's read of your email today."
        else:
            note = "The morning run read your email today and found nothing to remind you of."
        if unsupported:
            verb = "is" if unsupported == 1 else "are"
            note += f" {plural(unsupported, 'reminder')} cited no evidence and {verb} not shown."
        return Collected(items=items, note=note)


def live_calendar(start: str, end: str) -> list[dict[str, Any]]:
    """The real Google Calendar read.

    Imported late so importing this module needs no Google client, and so a missing credential
    surfaces as this source's reason rather than as an import error for the whole API.
    """
    from second.tools.calendar_tools import get_calendar_events

    return get_calendar_events(start, end)


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def default_sources(calendar: CalendarReader | None = None) -> list[MemorySource]:
    """Every source memory reads, in the order their items are listed.

    **This is the one place a source is registered.** A new one is a new class and a new line here.

    Args:
        calendar: Replaces the live Google Calendar read. Tests and the fixture generator pass
            ``second.testing.fake_connectors.read_fake_calendar``.
    """
    return [GraphSource(), CalendarSource(calendar), EmailSource()]


def collect_memory(
    context: MemoryContext,
    sources: list[MemorySource],
    *,
    questions: list[HorizonQuestion] | None = None,
) -> Memory:
    """Ask every source, and report on each one whether or not it answered.

    **Failure direction: lose one source, keep the tab.** A calendar that cannot be reached must not
    hide a deadline the graph already knows about, so each source runs on its own and a failure
    becomes that source's reason.
    """
    items: list[MemoryItem] = []
    statuses: list[MemorySourceStatus] = []

    for source in sources:
        try:
            collected = source.collect(context)
        except SourceUnavailable as error:
            statuses.append(MemorySourceStatus(name=source.name, connected=False, reason=str(error)))
            continue
        except Exception as error:  # noqa: BLE001 - one broken source must not blank the others
            logger.warning("memory source %s could not be read", source.name, exc_info=True)
            statuses.append(
                MemorySourceStatus(
                    name=source.name,
                    connected=False,
                    reason=f"Could not be read: {type(error).__name__}: {error}",
                )
            )
            continue

        items.extend(collected.items)
        statuses.append(
            MemorySourceStatus(
                name=source.name,
                connected=True,
                reason=collected.note or f"Read {plural(len(collected.items), 'item')}.",
                items=len(collected.items),
            )
        )

    return Memory(on=context.clock.today, items=items, sources=statuses, questions=questions or [])


# ---------------------------------------------------------------------------


def _owner_of(graph: LivingGraph, task_id: str | None) -> tuple[str | None, str | None]:
    """The task id and the id of the goal that owns it, or neither.

    Prepared work names its task in a model's words. An id the graph does not hold is not passed on,
    because a screen that withdraws by it would be acting on a made-up id.
    """
    if not task_id:
        return None, None
    for goal in graph.goals:
        for route in goal.routes:
            if any(task.id == task_id for task in route.tasks):
                return task_id, route.goal_id
    return None, None


def _in_the_plan(block: ScheduledBlock) -> str:
    """The block, as the plan holds it: when, what, and the goal it is for."""
    ends = block.start + timedelta(minutes=block.duration_min)
    return (
        f"In today's plan from {block.start:%H:%M} to {ends:%H:%M}: {quoted(block.title)}, "
        f"towards {quoted(block.goal_title)}."
    )


def _quote_event(event: dict[str, Any], title: str, begins: datetime, ends: datetime) -> str:
    """The calendar entry, quoted closely enough to find it again."""
    parts = [f"Calendar: {quoted(title)}, {begins:%H:%M} to {ends:%H:%M}"]
    attendees = int(event.get("attendees") or 1)
    if attendees > 1:
        parts.append(f"{attendees} attendees")
    if event.get("is_owner") is False:
        parts.append("organised by someone else")
    if event.get("response") == "none" and attendees > 1:
        parts.append("not answered yet")
    return ", ".join(parts) + "."


def _calendar_note(read: int, in_plan: int, cancelled: int, declined: int) -> str:
    if read == 0:
        return "Read today's calendar: nothing in it."
    left_out = [
        f"{count} {label}"
        for count, label in (
            (in_plan, "already listed from today's plan"),
            (cancelled, "cancelled"),
            (declined, "declined"),
        )
        if count
    ]
    note = f"Read {plural(read, 'event')} today."
    if left_out:
        note += " Not repeated here: " + "; ".join(left_out) + "."
    return note

