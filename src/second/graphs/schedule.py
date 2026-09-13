"""Every day has a schedule: what is already placed, and what the routes' own rhythm implies.

The founder asked for "what I want to do tomorrow, automatically, based on what it knows". Two
things answer that, and a screen must never confuse them:

* **Placed** blocks are facts. A task holds that slot in the Living Graph, and
  :func:`second.graphs.brief.blocks_on` already reads them. This module calls it and adds nothing.
* **Proposed** blocks are a projection. A route that says "Tuesdays 19:00" and has nothing placed
  next Tuesday implies a Tuesday 19:00 block. That is arithmetic on the user's own words, so it is
  computed here, and it is never written anywhere. The Scheduler decides what is booked; this only
  shows what the week looks like if the routes carry on as written.

No model is involved, on purpose. A GET that asks a model to imagine next week will eventually
imagine a meeting.

The refusals are the point of the module. Each is recorded with its reason rather than silently
omitted, because an empty Monday reads as "nothing to do" when the truth is "Second chose not to
put the gym back where it keeps failing":

* a cadence Second cannot read is not guessed at;
* a slot the person layer records as abandoned is not proposed again;
* nothing is proposed after the task's deadline or the goal's;
* nothing is proposed on top of something already there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from second.core.clock import WEEKDAY_LABELS, Clock
from second.core.models import (
    LivingGraph,
    Route,
    Schedule,
    ScheduleDay,
    ScheduledBlock,
    SkippedProposal,
    Task,
)
from second.graphs.brief import _blocks_for, blocks_on
from second.graphs.wording import day_label, quoted
from second.settings import SCHEDULE_DAYS

ALL_DAYS = frozenset(range(7))
WEEKDAYS = frozenset(range(5))
WEEKEND = frozenset({5, 6})

_DAY_TOKEN = re.compile(
    r"\b(?:(?P<full>monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?"
    r"|(?P<short>mon|tues?|weds?|thu(?:rs?)?|fri|sat|sun)s?)\b"
)
"""A weekday, spelled out or abbreviated. Word-bounded, so "month" is never Monday.

A spelled-out name always counts. An abbreviation counts only where it is plainly a day (see
``_counts_as_day``), because "sun", "sat" and "wed" are also ordinary English words, and "before sun
up" is not a Sunday."""

_DAY_INDEX = {"mo": 0, "tu": 1, "we": 2, "th": 3, "fr": 4, "sa": 5, "su": 6}
"""The first two letters of every spelling above are unique to one day."""

_EVERY_DAY = re.compile(r"\b(?:daily|every\s+day|each\s+day)\b")
_WEEKDAYS = re.compile(r"\bweekdays?\b")
_WEEKENDS = re.compile(r"\bweekends?\b")
_ONE_OFF = re.compile(r"\bone[-\s]?off\b")

_EXCEPTION = re.compile(
    r"\b(?:except|excluding|exclude|apart\s+from|other\s+than|save\s+for|unless|skip(?:s|ping)?"
    r"|not|no|never|without)\b"
)
"""Anything that takes days away: "except", "not in August", "not on bank holidays", "no Fridays".

A negation is refused wholesale rather than parsed, because reading "Weekdays, not Fridays" without
it gives Friday back, the exact day the user ruled out."""

_FREQUENCY = re.compile(
    r"\b(?:twice|thrice)\b"
    r"|\b(?:\d+|one|two|three|four|five|six|seven|several|few|many)\s*(?:x|times?)\b"
)
"""A count per period: "twice a week", "3 times a week", "3x a week". It says how many, not which
days, and choosing the days is the Scheduler's decision, not arithmetic."""

_RELATIVE_TIME = re.compile(
    r"\b(?:before|after|around|about|roughly|approximately|earliest|latest)\b"
)
"""A time given relative to something: "before sun up", "after work", "around 7". Reading the
number alone would put the block on the wrong side of the thing the user named."""

_LONGER_PERIOD = re.compile(
    r"\b(?:monthly|quarterly|yearly|annually|(?:a|per|each|every)\s+(?:month|quarter|year)"
    r"|of\s+(?:the|each|every)\s+month)\b"
)
"""A rhythm longer than a fortnight. "Once a month on Tuesday" read as weekly is four blocks for
one promise."""

_EVERY_OTHER_WEEKDAY = re.compile(
    r"\b(?:every\s+(?:other|second|2nd)|alternate)\s+"
    r"(?=(?:mon|tue|wed|thu|fri|sat|sun))"
)
_FORTNIGHT = re.compile(
    r"\b(?:fortnight(?:ly)?|every\s+(?:other|second|2nd|two|2)\s+weeks?|alternate\s+weeks?)\b"
)
_OTHER_INTERVAL = re.compile(
    r"\b(?:every\s+(?:other|second|2nd|third|3rd|fourth|4th|\d+|two|three|four|five|six)\s+days?"
    r"|alternate\s+days|every\s+(?:third|3rd|fourth|4th|\d+|three|four|five|six)\s+(?:weeks?|mon|tue|wed|thu|fri|sat|sun)"
    r"|bi-?weekly)"
)
"""Every other day, every three weeks, every third Tuesday, and "biweekly", which means twice a week
to some people and every two weeks to others. None of them is a weekly rhythm with a skipped week."""

_MERIDIEM_TIME = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*([ap])\.?m\b\.?")
_CLOCK_TIME = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b")
_NAMED_TIME = {"noon": time(12, 0), "midday": time(12, 0), "midnight": time(0, 0)}
_TIME_LIKE = re.compile(r"\b\d{1,2}[:.]\d{2}\b")
_BARE_NUMBER = re.compile(r"\b\d+\b")


class CadenceUnreadable(ValueError):
    """A route's cadence is not a shape Second reads. The message is the reason, for the user."""


@dataclass(frozen=True)
class Cadence:
    """The part of a route's cadence that can be put on a calendar."""

    weekdays: frozenset[int]
    at: time | None
    fortnightly: bool = False


def parse_cadence(text: str) -> Cadence:
    """Read a cadence written in plain words, or refuse.

    Reads named weekdays ("Tuesdays", "Mon/Wed/Fri"), day ranges ("Mon-Fri", "Monday to Friday"),
    "weekdays", "weekends", "daily" or "every day", and "every other <weekday>" or "fortnightly on
    <weekday>", each with an optional time ("19:00", "7pm", "7:30 pm", "noon"). Anything else
    raises rather than being fitted to the nearest shape: a proposal built on a misread cadence puts
    a block on a day the user never chose, and they learn to ignore the rest of the week.

    Args:
        text: ``Route.cadence``, as the Route Planner or the Adapter wrote it.

    Returns:
        The days, the time if one was named, and whether it alternates weeks.

    Raises:
        CadenceUnreadable: With a sentence saying what could not be read.
    """
    said = text.strip()
    lowered = said.lower()
    if not said:
        raise CadenceUnreadable("The route has no cadence written down.")
    shown = quoted(said)

    if _ONE_OFF.search(lowered):
        raise CadenceUnreadable(f"{shown} is a one-off, not a rhythm, so there is no day to project it onto.")
    if _EXCEPTION.search(lowered):
        raise CadenceUnreadable(
            f"{shown} leaves some days or times out, and Second does not read exceptions, so nothing is "
            "proposed rather than a block on a day you ruled out."
        )
    if _FREQUENCY.search(lowered):
        raise CadenceUnreadable(
            f"{shown} says how many times, not which days, so there is no day to put a block on."
        )
    if _RELATIVE_TIME.search(lowered):
        raise CadenceUnreadable(
            f"{shown} gives a time relative to something else, and Second will not turn that into a clock time."
        )
    if _LONGER_PERIOD.search(lowered):
        raise CadenceUnreadable(f"{shown} repeats less often than every two weeks, and Second only reads weekly and fortnightly rhythms.")
    if _OTHER_INTERVAL.search(lowered):
        raise CadenceUnreadable(
            f"{shown} does not repeat weekly or every other week, so it cannot be laid over a week."
        )

    fortnightly = bool(_EVERY_OTHER_WEEKDAY.search(lowered) or _FORTNIGHT.search(lowered))
    at, rest = _read_time(lowered, shown)
    named = _read_days(rest, shown)

    grouped: frozenset[int] = frozenset()
    if _EVERY_DAY.search(lowered):
        grouped |= ALL_DAYS
    if _WEEKDAYS.search(lowered):
        grouped |= WEEKDAYS
    if _WEEKENDS.search(lowered):
        grouped |= WEEKEND

    if fortnightly and (grouped or not named):
        # "Fortnightly" on its own, or "every other weekday", has no single weekday to count the
        # fortnight on, and reading it as one would put a block on the wrong half of the days.
        raise CadenceUnreadable(
            f"{shown} alternates weeks, but not on a named weekday, so there is no fortnight to count."
        )

    days = named | grouped
    if not days:
        raise CadenceUnreadable(
            f"{shown} names no day Second can read, so nothing is proposed rather than a guess."
        )

    return Cadence(weekdays=days, at=at, fortnightly=fortnightly)


def _read_time(lowered: str, shown: str) -> tuple[time | None, str]:
    """The one time a cadence names, and the text with it removed so its digits are not reread.

    am and pm are read before 24-hour times, because "7:30 pm" also contains "7:30", and reading
    that half alone is the block twelve hours early.
    """
    found: set[time] = set()

    def meridiem(match: re.Match[str]) -> str:
        hour, minute = int(match.group(1)), int(match.group(2) or 0)
        if not 1 <= hour <= 12 or minute > 59:
            raise CadenceUnreadable(f"{shown} names {match.group(0).strip()}, which is not a time on a 12-hour clock.")
        # 12am is midnight and 12pm is noon; every other hour gains twelve in the afternoon.
        hour = hour % 12 + (12 if match.group(3) == "p" else 0)
        found.add(time(hour, minute))
        return " "

    rest = _MERIDIEM_TIME.sub(meridiem, lowered)

    def clock(match: re.Match[str]) -> str:
        found.add(time(int(match.group(1)), int(match.group(2))))
        return " "

    rest = _CLOCK_TIME.sub(clock, rest)
    for word, value in _NAMED_TIME.items():
        if re.search(rf"\b{word}\b", rest):
            found.add(value)
            rest = re.sub(rf"\b{word}\b", " ", rest)

    if _TIME_LIKE.search(rest):
        raise CadenceUnreadable(f"{shown} names a time that is not on a 24-hour clock.")
    # The fortnight phrases are the only place a number may stand for something other than a time.
    if _BARE_NUMBER.search(_FORTNIGHT.sub(" ", rest)):
        raise CadenceUnreadable(
            f"{shown} has a number Second cannot read as a time. Write it as 19:00 or 7pm."
        )
    if len(found) > 1:
        raise CadenceUnreadable(f"{shown} names more than one time, and Second will not pick one.")
    return (found.pop() if found else None), rest


def _read_days(lowered: str, shown: str) -> frozenset[int]:
    """Every weekday a cadence names, with ranges filled in.

    "Mon-Fri" is five days, not two. A range that does not run forwards through the week ("Fri-Mon")
    is refused rather than wrapped, because whether it means the weekend or the working week is
    exactly the guess this module will not make.
    """
    tokens = list(_DAY_TOKEN.finditer(lowered))
    joins = [_join(lowered, tokens[index], tokens[index + 1]) for index in range(len(tokens) - 1)]

    days: set[int] = set()
    for index, token in enumerate(tokens):
        joined = (index > 0 and joins[index - 1] is not None) or (index < len(joins) and joins[index] is not None)
        if _counts_as_day(lowered, token, joined):
            days.add(_DAY_INDEX[token.group(0)[:2]])

    for index, join in enumerate(joins):
        if join == "or":
            raise CadenceUnreadable(f"{shown} offers a choice of days, and Second will not pick one.")
        if join != "range":
            continue
        if index > 0 and joins[index - 1] == "range":
            raise CadenceUnreadable(f"{shown} chains one range into another, and Second will not guess where it ends.")
        start, end = _DAY_INDEX[tokens[index].group(0)[:2]], _DAY_INDEX[tokens[index + 1].group(0)[:2]]
        if end <= start:
            raise CadenceUnreadable(
                f"{shown} runs from {WEEKDAY_LABELS[start]} to {WEEKDAY_LABELS[end]}, which does not go "
                "forwards through the week, so Second will not guess which days it covers."
            )
        days.update(range(start, end + 1))

    return frozenset(days)


_RANGE_JOIN = re.compile(r"-|–|—|to|through|thru|until|till")
_LIST_JOIN = re.compile(r"/|,|&|\+|and|,\s*and|,\s*&")
_CHOICE_JOIN = re.compile(r"or|,\s*or|/\s*or")


def _join(lowered: str, first: re.Match[str], second: re.Match[str]) -> str | None:
    """How two neighbouring day names are joined: a range, a list, a choice, or not at all."""
    between = lowered[first.end() : second.start()].strip()
    if _RANGE_JOIN.fullmatch(between):
        return "range"
    if _LIST_JOIN.fullmatch(between):
        # "between Monday and Friday" is a range said with "and".
        return "range" if re.search(r"\bbetween\s+$", lowered[: first.start()]) else "list"
    if _CHOICE_JOIN.fullmatch(between):
        return "or"
    return None


def _counts_as_day(lowered: str, token: re.Match[str], joined: bool) -> bool:
    """Whether a day name is being used as a day.

    A spelled-out name always is. An abbreviation is when it is joined to another day ("Mon/Wed"),
    stands alone as the whole cadence, follows "on" or "every", or is followed by a time or a part
    of the day ("Sun 09:00", "Sat mornings"). Otherwise "sun" is the sun.
    """
    if token.group("full") or joined:
        return True
    before, after = lowered[: token.start()], lowered[token.end() :]
    if not before.strip(" ,.") and not after.strip(" ,."):
        return True
    if re.search(r"\b(?:on|every|each|next|this)\s+$", before):
        return True
    if re.match(r"\s*,?\s*(?:at\s+)?\d", after):
        return True
    return bool(re.match(r"\s+(?:morning|afternoon|evening|night)s?\b", after))


@dataclass
class _Projection:
    """The days being built, shared by every route so proposals can see each other."""

    graph: LivingGraph
    clock: Clock
    span: list[date]
    placed: dict[date, list[ScheduledBlock]]
    proposed: dict[date, list[ScheduledBlock]] = field(default_factory=dict)
    refused: dict[date, list[SkippedProposal]] = field(default_factory=dict)
    unplaceable: list[SkippedProposal] = field(default_factory=list)


def build_schedule(graph: LivingGraph, clock: Clock, *, days: int = SCHEDULE_DAYS) -> Schedule:
    """Today and the days after it, each with what is placed and what the routes imply.

    Pure: reads the graph, writes nothing, calls no model.

    Args:
        graph: The Living Graph. Read, never modified.
        clock: Whose today, in their own zone.
        days: How many days, today included.

    Returns:
        One ``ScheduleDay`` per day in the span, empty days included.

    Raises:
        ValueError: If ``days`` is less than one.
    """
    if days < 1:
        raise ValueError(f"a schedule needs at least one day; got {days}")

    span = [clock.today + timedelta(days=offset) for offset in range(days)]
    projection = _Projection(
        graph=graph,
        clock=clock,
        span=span,
        placed={day: blocks_on(graph, clock, day) for day in span},
        proposed={day: [] for day in span},
        refused={day: [] for day in span},
    )

    for goal in graph.active_goals():
        for route in goal.routes:
            # Only what the user approved. A proposed route is still Second's suggestion, and
            # projecting it forward would present it as a plan they agreed to.
            if route.status == "approved":
                _project(projection, route)

    return Schedule(
        start=clock.today,
        days=[
            ScheduleDay(
                on=day,
                blocks=sorted(
                    projection.placed[day] + projection.proposed[day], key=lambda block: block.start
                ),
                skipped=projection.refused[day],
            )
            for day in span
        ],
        skipped=projection.unplaceable,
    )


def _project(projection: _Projection, route: Route) -> None:
    """Lay one route's cadence over the span."""
    graph, clock = projection.graph, projection.clock
    remaining = [task for task in route.tasks if task.status != "done"]
    if not remaining:
        return  # finished, and nothing finished is ever proposed

    def unplaceable(reason: str, task_id: str | None) -> None:
        projection.unplaceable.append(
            SkippedProposal(
                route_id=route.id,
                route_title=route.title,
                task_id=task_id,
                on=None,
                wanted=route.cadence,
                reason=reason,
            )
        )

    # A route's cadence belongs to the route, but a block needs a task. The first pending task
    # whose dependencies are done is the one the next session would actually be spent on.
    task = next(
        (candidate for candidate in remaining if candidate.status == "pending" and _ready(graph, candidate)),
        None,
    )
    if task is None:
        unplaceable("Every task left on this route is blocked or waiting on another task.", None)
        return

    try:
        cadence = parse_cadence(route.cadence)
    except CadenceUnreadable as error:
        unplaceable(str(error), task.id)
        return

    last = _latest_slot(task, clock)
    at, borrowed = cadence.at, cadence.at is None
    if at is None:
        if last is None:
            unplaceable(
                f"{quoted(route.cadence)} names no time, and {quoted(task.title)} has never had a slot "
                "to take one from.",
                task.id,
            )
            return
        at = last.time()
    if cadence.fortnightly and last is None:
        unplaceable(
            f"{quoted(route.cadence)} alternates weeks, and {quoted(task.title)} has no earlier slot to "
            "count the fortnight from.",
            task.id,
        )
        return

    route_task_ids = {candidate.id for candidate in route.tasks}
    for day in projection.span:
        if day.weekday() not in cadence.weekdays:
            continue
        if cadence.fortnightly and last is not None and not _same_fortnight(last.date(), day):
            continue
        if any(block.task_id in route_task_ids for block in projection.placed[day]):
            continue  # the route already has this day, and a placed block beats a projection
        _propose(projection, route, task, day, at, borrowed)


def _propose(
    projection: _Projection, route: Route, task: Task, day: date, at: time, borrowed: bool
) -> None:
    """Propose one block, or record exactly why not."""
    graph, clock = projection.graph, projection.clock
    slot = datetime.combine(day, at)
    label = clock.slot_label(slot)

    def refuse(reason: str) -> None:
        projection.refused[day].append(
            SkippedProposal(
                route_id=route.id,
                route_title=route.title,
                task_id=task.id,
                on=day,
                wanted=label,
                reason=reason,
            )
        )

    if clock.local(slot) <= clock.now:
        refuse(f"{label} today has already passed.")
        return
    if task.deadline is not None and day > task.deadline:
        refuse(f"{quoted(task.title)} is due {day_label(task.deadline)}, and this day is after it.")
        return
    # The goal's deadline binds too. A task with no date of its own under a wedding that happens on
    # the 25th is still pointless on the 26th.
    goal = graph.goal_by_id(route.goal_id)
    if goal is not None and goal.deadline is not None and day > goal.deadline:
        refuse(
            f"{quoted(goal.title)}, the goal this serves, has a deadline of {day_label(goal.deadline)}, "
            "and this day is after it."
        )
        return
    # Compared on the Person layer's own label, built by the same Clock.slot_label that wrote it,
    # so "Mon 18:00" here and "Mon 18:00" there cannot disagree about zone or format.
    if label in graph.person.abandoned_slots:
        refuse(
            f"{label} is recorded as an abandoned slot: scheduled and repeatedly missed. "
            "Second will not propose it again."
        )
        return

    block = _blocks_for(graph, task, slot, clock)
    if block is None:
        refuse(f"{quoted(task.title)} could not be traced up to the goal it serves.")
        return

    clash = next(
        (other for other in projection.placed[day] + projection.proposed[day] if _overlaps(block, other)),
        None,
    )
    if clash is not None:
        held = "already placed" if clash.status == "placed" else "proposed first"
        refuse(f"Would overlap {quoted(clash.title)} at {clash.start:%H:%M}, which is {held}.")
        return

    # model_validate rather than model_copy: model_copy skips validators, and the one that refuses
    # a proposal with no reason is the point.
    projection.proposed[day].append(
        ScheduledBlock.model_validate(
            {
                **block.model_dump(),
                "status": "proposed",
                "why": _why(graph, route, day, label, at, borrowed),
            }
        )
    )


def _why(graph: LivingGraph, route: Route, day: date, label: str, at: time, borrowed: bool) -> str:
    """The cadence, the empty day, and the person-layer facts behind the proposal."""
    parts = [
        f"{route.title} runs {quoted(route.cadence)}, and nothing is placed for it on "
        f"{WEEKDAY_LABELS[day.weekday()]} {day.day} {day:%b}."
    ]
    if borrowed:
        parts.append(f"The cadence names no time, so this uses {at:%H:%M}, when its last slot was.")
    if label in graph.person.honoured_slots:
        parts.append(f"{label} is a slot you keep.")
    if route.rationale.strip():
        parts.append(route.rationale.strip())
    return " ".join(parts)


def _ready(graph: LivingGraph, task: Task) -> bool:
    """Whether every dependency is done. A dependency missing from the graph counts as not done."""
    return all(
        (dependency := graph.task_by_id(task_id)) is not None and dependency.status == "done"
        for task_id in task.depends_on
    )


def _latest_slot(task: Task, clock: Clock) -> datetime | None:
    """The task's most recent slot, local and aware, or None if it never had one."""
    if not task.scheduled_slots:
        return None
    return max(clock.local(slot) for slot in task.scheduled_slots)


def _same_fortnight(anchor: date, day: date) -> bool:
    """Whether ``day`` falls in an on-week, counting whole weeks from the anchor's week."""
    anchor_week = anchor - timedelta(days=anchor.weekday())
    week = day - timedelta(days=day.weekday())
    return ((week - anchor_week).days // 7) % 2 == 0


def _overlaps(first: ScheduledBlock, second: ScheduledBlock) -> bool:
    return first.start < second.start + timedelta(minutes=second.duration_min) and second.start < (
        first.start + timedelta(minutes=first.duration_min)
    )
