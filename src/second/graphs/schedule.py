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
    r"|\b(?:\d+|one|two|three|four|five|six|seven)\s+(?:days?|mornings?|afternoons?|evenings?|nights?|sessions?)"
    r"\s+(?:a|per|each|every)\s+(?:week|fortnight|month)\b"
)
"""A count per period: "twice a week", "3 times a week", "3x a week", "3 mornings a week". It says
how many, not which days, and choosing the days is the Scheduler's decision, not arithmetic.

"3 mornings a week" has no "times", and its 3 used to reach the bare-number rule, which told the
user to write a clock time. The cadence was refused, but for the wrong thing."""

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

_ALTERNATE_GROUP = re.compile(
    r"\b(?:every\s+(?:other|second|2nd|two|2)|alternate)\s+(?:weekdays?|weekends?)\b"
)
""""Every other weekday" was read as every weekday, doubling the rhythm. Which weekdays it leaves
is not arithmetic (Mon/Wed/Fri this week and Tue/Thu the next, or something else), so it is refused
by name rather than left for the fortnight rule, which only looks for a named weekday."""

_EVERY_OTHER_WEEKDAY = re.compile(
    r"\b(?:every\s+(?:other|second|2nd|two|2)|alternate)\s+"
    r"(?=(?:mon|tue|wed|thu|fri|sat|sun))"
)
_FORTNIGHT = re.compile(
    r"\b(?:(?:(?:once\s+)?(?:a|every|each|per)\s+)?fortnight(?:ly)?"
    r"|every\s+(?:other|second|2nd|two|2)\s+weeks?|alternate\s+weeks?)\b"
)
_OTHER_INTERVAL = re.compile(
    r"\b(?:every\s+(?:other|second|2nd|third|3rd|fourth|4th|\d+|two|three|four|five|six)\s+days?\b"
    r"|alternate\s+days\b"
    r"|every\s+(?:third|3rd|fourth|4th|three|four|five|six|[3-9]|[1-9]\d+)\s+(?:weeks?\b|mon|tue|wed|thu|fri|sat|sun)"
    r"|bi-?weekly)"
)
"""Every other day, every three weeks, every third Tuesday, and "biweekly", which means twice a week
to some people and every two weeks to others. None of them is a weekly rhythm with a skipped week.

"every 2 weeks" is not in here: it was, through a bare ``\\d+``, and was refused as not fortnightly
while "every two weeks" read as fortnightly. Two is the one count that is a fortnight."""

_COUNT_WORDS = (
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty"
    r"|forty[-\s]five|forty|fifty|sixty|ninety"
)
_MINUTES = r"(?:minutes?|mins?|m)"
_HOURS = (
    rf"(?:(?:\d(?:\.\d+)?|{_COUNT_WORDS})\s*-?\s*(?:hours?|hrs?)"
    r"|[1-3](?:\.\d+)?\s*-?\s*h)"
)
"""A count of hours. One digit before "hours", and only 1 to 3 before a bare "h", because "19h" and
"7h" are how some people write 19:00 and 07:00: read as lengths, they left "Tuesdays 19h" with no
time at all. A digit too big to be a session is left for the bare-number rule, which refuses it."""
_DURATION = re.compile(
    r"\b(?:for\s+)?(?:(?:about|around|roughly|approximately)\s+)?"
    r"(?:half\s+an\s+hour"
    r"|(?:an|one)\s+hour\s+and\s+a\s+half"
    r"|(?:an|one)\s+and\s+a\s+half\s+hours"
    r"|an\s+hour"
    rf"|{_HOURS}"
    rf"(?:\s*(?:and\s+)?(?:\d{{1,2}}|{_COUNT_WORDS})\s*-?\s*{_MINUTES}|\s*\d{{2}}(?!\s*[:.]))?"
    rf"|(?:\d{{1,3}}|{_COUNT_WORDS})\s*-?\s*{_MINUTES}"
    r")\b"
)
"""How long a session is: "15 minutes", "for 90 mins", "1h30", "an hour", "about half an hour".

It says nothing about which day or when, so it is set aside before anything else is read. "Weekday
mornings, 15 minutes" is the Route Planner prompt's own example, and its 15 was being refused as a
number that is not a time, so every route written as instructed got no proposals. "about" goes with
the length it qualifies, because a rough length does not move the block the way "about 7" does.
Three digits at most for minutes, so "1900m" is not a length."""

_MERIDIEM_TIME = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*([ap])\.?m\b\.?")
_CLOCK_TIME = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b")
_NAMED_TIME = {"noon": time(12, 0), "midday": time(12, 0), "midnight": time(0, 0)}
_TIME_LIKE = re.compile(r"\b\d{1,2}[:.]\d{2}\b")
_BARE_NUMBER = re.compile(r"\b\d+\b")

_TIME_MARK = "T"
"""Left where a time was read. Upper case, because the cadence is lower-cased before reading, so
nothing the user wrote can be mistaken for it. Without a mark the text after "Sun 09:00" was blank,
and "an abbreviated day followed by a time counts" could never fire."""

_DAY_PART = re.compile(r"\b(?:in\s+the\s+)?(?P<part>morning|afternoon|evening|night)s?\b")
_DAY_PART_HOURS: dict[str, tuple[tuple[time, time], ...]] = {
    "morning": ((time(4, 0), time(12, 0)),),
    "afternoon": ((time(12, 0), time(18, 0)),),
    "evening": ((time(17, 0), time.max),),
    "night": ((time(18, 0), time.max), (time(0, 0), time(5, 0))),
}
"""Wide on purpose. These only catch a plain contradiction, "Tuesday mornings 19:00", where either
word could be the mistake; they are not a definition of when a morning ends."""

_NIGHT_ENDS = time(5, 0)
"""A night's time before this is after midnight. "Friday nights 1am" is 01:00 on Saturday, a day the
cadence never names, so it is refused rather than put on Friday or quietly moved to Saturday."""

_WEEKLY = re.compile(r"\b(?:weekly|(?:every|each|per)\s+week)\b")
_FILLER = re.compile(r"\b(?:on|at|every|each|and)\b")
_WORD = re.compile(r"[a-z0-9]+")


class CadenceUnreadable(ValueError):
    """A route's cadence is not a shape Second reads. The message is the reason, for the user."""


@dataclass(frozen=True)
class Cadence:
    """The part of a route's cadence that can be put on a calendar."""

    weekdays: frozenset[int]
    at: time | None
    fortnightly: bool = False
    part: str | None = None
    """"morning", "evening" and so on, when the cadence names one. A borrowed time must fall in it."""


def parse_cadence(text: str) -> Cadence:
    """Read a cadence written in plain words, or refuse.

    Reads named weekdays ("Tuesdays", "Mon/Wed/Fri"), day ranges ("Mon-Fri", "Monday to Friday"),
    "weekdays", "weekends", "daily" or "every day", and "every other <weekday>" or "fortnightly on
    <weekday>", each with an optional time ("19:00", "7pm", "7:30 pm", "noon"), an optional part of
    the day ("mornings") and an optional length ("15 minutes"), which is set aside.

    Every other word refuses the cadence, and the reason names it. The parser used to refuse only
    the qualifiers on a list, so a word nobody thought to list ("during term time", "if it is dry")
    was dropped without a trace and the rhythm it limited was proposed in full. A proposal built on
    a misread cadence puts a block on a day the user never chose, and they learn to ignore the rest
    of the week.

    Args:
        text: ``Route.cadence``, as the Route Planner or the Adapter wrote it.

    Returns:
        The days, the time if one was named, whether it alternates weeks, and the part of the day.

    Raises:
        CadenceUnreadable: With a sentence saying what could not be read.
    """
    said = text.strip()
    lowered = said.lower()
    if not said:
        raise CadenceUnreadable("The route has no cadence written down.")
    shown = quoted(said)

    # Every step below blanks what it read with spaces of the same length, so a position found in
    # one version of the text is the same position in every other, including the original.
    mask = _blank(_DURATION, lowered)

    if _ONE_OFF.search(mask):
        raise CadenceUnreadable(f"{shown} is a one-off, not a rhythm, so there is no day to project it onto.")
    if _EXCEPTION.search(mask):
        raise CadenceUnreadable(
            f"{shown} leaves some days or times out, and Second does not read exceptions, so nothing is "
            "proposed rather than a block on a day you ruled out."
        )
    if _FREQUENCY.search(mask):
        raise CadenceUnreadable(
            f"{shown} says how many times, not which days, so there is no day to put a block on."
        )
    if _RELATIVE_TIME.search(mask):
        raise CadenceUnreadable(
            f"{shown} gives a time relative to something else, and Second will not turn that into a clock time."
        )
    if _LONGER_PERIOD.search(mask):
        raise CadenceUnreadable(f"{shown} repeats less often than every two weeks, and Second only reads weekly and fortnightly rhythms.")
    if _ALTERNATE_GROUP.search(mask):
        raise CadenceUnreadable(
            f"{shown} alternates over a group of days rather than one named day, so which days it means "
            "is a guess Second will not make."
        )
    if _OTHER_INTERVAL.search(mask):
        raise CadenceUnreadable(
            f"{shown} does not repeat weekly or every other week, so it cannot be laid over a week."
        )

    fortnightly = bool(_EVERY_OTHER_WEEKDAY.search(mask) or _FORTNIGHT.search(mask))
    mask = _blank(_FORTNIGHT, _blank(_EVERY_OTHER_WEEKDAY, mask))
    marks, mask = _read_time(mask, shown)
    named, day_starts, mask = _read_days(lowered, mask, shown)
    day_starts += [match.start() for pattern in (_EVERY_DAY, _WEEKDAYS, _WEEKENDS) for match in pattern.finditer(mask)]

    grouped: frozenset[int] = frozenset()
    if _EVERY_DAY.search(mask):
        grouped |= ALL_DAYS
    if _WEEKDAYS.search(mask):
        grouped |= WEEKDAYS
    if _WEEKENDS.search(mask):
        grouped |= WEEKEND
    mask = _blank(_WEEKENDS, _blank(_WEEKDAYS, _blank(_EVERY_DAY, mask)))

    parts = list(dict.fromkeys(match.group("part") for match in _DAY_PART.finditer(mask)))
    mask = _blank(_FILLER, _blank(_WEEKLY, _blank(_DAY_PART, mask)))

    leftover = list(dict.fromkeys(_WORD.findall(mask)))
    if leftover:
        raise CadenceUnreadable(
            f"{shown} includes {_the_words(leftover)}, which Second does not read as a day, a time or a "
            "length. A word it skipped could be the one that limits the rhythm, so nothing is proposed."
        )

    at = _one_time(marks, day_starts, shown)

    if len(parts) > 1:
        raise CadenceUnreadable(f"{shown} names more than one part of the day, and Second will not pick one.")
    part = parts[0] if parts else None
    if at is not None and part is not None and not in_day_part(at, part):
        raise CadenceUnreadable(
            f"{shown} names {at:%H:%M}, which is not in the {part}, and Second will not choose which of "
            "the two you meant."
        )
    if at is not None and part == "night" and at < _NIGHT_ENDS:
        raise CadenceUnreadable(
            f"{shown} names {at:%H:%M}, which is {'midnight' if at == time(0, 0) else 'after midnight'}, "
            "so it falls on the next day, and the "
            "cadence does not name that day. Second will not guess which day you meant."
        )

    if fortnightly and (grouped or not named):
        # "Fortnightly" on its own has no single weekday to count the fortnight on, and reading it as
        # one would put a block on the wrong half of the days.
        raise CadenceUnreadable(
            f"{shown} alternates weeks, but not on a named weekday, so there is no fortnight to count."
        )
    if fortnightly and len(named) > 1:
        # "Every other Tuesday and Thursday" could alternate both days, or only Tuesday with Thursday
        # weekly. Both readings are common, and the wrong one halves or doubles a day's rhythm.
        raise CadenceUnreadable(
            f"{shown} alternates weeks on more than one day, and Second cannot tell which of the days "
            "alternate, so nothing is proposed."
        )

    days = named | grouped
    if not days:
        raise CadenceUnreadable(
            f"{shown} names no day Second can read, so nothing is proposed rather than a guess."
        )

    return Cadence(weekdays=days, at=at, fortnightly=fortnightly, part=part)


def in_day_part(at: time, part: str) -> bool:
    """Whether a time falls in a named part of the day, on the wide windows above."""
    return any(start <= at < end for start, end in _DAY_PART_HOURS[part])


def _blank(pattern: re.Pattern[str], text: str) -> str:
    """Remove what a pattern matched without moving anything after it."""
    return pattern.sub(lambda match: " " * len(match.group(0)), text)


def _the_words(words: list[str]) -> str:
    """"the word “gym”", "the words “during”, “term” and “time”"."""
    shown = [quoted(word) for word in words]
    if len(shown) == 1:
        return f"the word {shown[0]}"
    return f"the words {', '.join(shown[:-1])} and {shown[-1]}"


def _read_time(mask: str, shown: str) -> tuple[list[tuple[int, time]], str]:
    """Every time a cadence names, where it was written, and the text with each replaced by a mark.

    am and pm are read before 24-hour times, because "7:30 pm" also contains "7:30", and reading
    that half alone is the block twelve hours early. Whether the times add up to one is decided in
    :func:`_one_time`, once the days are known, because where a time sits among the days matters.
    """
    found: list[tuple[int, time]] = []

    def marked(match: re.Match[str], value: time) -> str:
        found.append((match.start(), value))
        return _TIME_MARK + " " * (len(match.group(0)) - 1)

    def meridiem(match: re.Match[str]) -> str:
        hour, minute = int(match.group(1)), int(match.group(2) or 0)
        if not 1 <= hour <= 12 or minute > 59:
            raise CadenceUnreadable(f"{shown} names {match.group(0).strip()}, which is not a time on a 12-hour clock.")
        # 12am is midnight and 12pm is noon; every other hour gains twelve in the afternoon.
        return marked(match, time(hour % 12 + (12 if match.group(3) == "p" else 0), minute))

    rest = _MERIDIEM_TIME.sub(meridiem, mask)
    rest = _CLOCK_TIME.sub(lambda match: marked(match, time(int(match.group(1)), int(match.group(2)))), rest)
    for word, value in _NAMED_TIME.items():
        rest = re.sub(rf"\b{word}\b", lambda match, value=value: marked(match, value), rest)

    if _TIME_LIKE.search(rest):
        raise CadenceUnreadable(f"{shown} names a time that is not on a 24-hour clock.")
    # Lengths and fortnights were set aside before this, so any number left is a time that failed.
    if _BARE_NUMBER.search(rest):
        raise CadenceUnreadable(
            f"{shown} has a number Second cannot read as a time. Write it as 19:00 or 7pm."
        )
    return found, rest


def _one_time(marks: list[tuple[int, time]], day_starts: list[int], shown: str) -> time | None:
    """The one time a cadence names, if its days all share it, or refuse.

    Days and times are read in the order they were written. A time that follows all the days ("Mon/
    Wed 19:00") or comes before them all ("7pm Tuesdays") belongs to every day, and so does one
    written after each group of days ("Wed 7pm and Sun 7pm"). A time with days on both sides of it
    ("Mon 7pm and Wed") was put on Wednesday too, a time the user only ever wrote beside Monday.

    Args:
        marks: Where each time was written, and the time.
        day_starts: Where each counted day, or group of days, was written.
        shown: The cadence as the reason quotes it.
    """
    if not marks:
        return None
    runs: list[list[time | None]] = []
    for _, value in sorted([(start, None) for start in day_starts] + marks, key=lambda item: item[0]):
        if runs and (runs[-1][0] is None) == (value is None):
            runs[-1].append(value)
        else:
            runs.append([value])
    shape = "".join("D" if run[0] is None else "T" for run in runs)
    each_group_timed = len(runs) >= 4 and re.fullmatch(r"(?:DT)+", shape) is not None

    times = {value for _, value in marks}
    if len(times) > 1:
        if each_group_timed:
            raise CadenceUnreadable(
                f"{shown} gives its days different times, and two different times are not one cadence, "
                "so Second will not pick one."
            )
        raise CadenceUnreadable(f"{shown} names more than one time, and Second will not pick one.")
    if shape.find("T") > 0 and "D" in shape[shape.find("T") :] and not each_group_timed:
        raise CadenceUnreadable(
            f"{shown} puts a time after only some of its days, and Second will not guess whether the days "
            "after it share that time."
        )
    return times.pop()


def _read_days(lowered: str, mask: str, shown: str) -> tuple[frozenset[int], list[int], str]:
    """Every weekday a cadence names, with ranges filled in, where each counted day was written, and
    the text with them blanked.

    "Mon-Fri" is five days, not two. A range that does not run forwards through the week ("Fri-Mon")
    is refused rather than wrapped, because whether it means the weekend or the working week is
    exactly the guess this module will not make. A day name that does not count as a day is left
    in the text, so the leftover rule refuses it by name rather than dropping it.
    """
    tokens = list(_DAY_TOKEN.finditer(mask))
    joins = [_join(mask, tokens[index], tokens[index + 1]) for index in range(len(tokens) - 1)]
    _refuse_spaced_abbreviations(mask, tokens, shown)

    days: set[int] = set()
    starts: list[int] = []
    read: list[tuple[int, int]] = []
    for index, token in enumerate(tokens):
        joined = (index > 0 and joins[index - 1] is not None) or (index < len(joins) and joins[index] is not None)
        if _counts_as_day(lowered, mask, token, joined):
            days.add(_DAY_INDEX[token.group(0)[:2]])
            starts.append(token.start())
            read.append(token.span())

    for index, join in enumerate(joins):
        if join is None:
            continue
        first, second = tokens[index], tokens[index + 1]
        read.append((first.end(), second.start()))
        if join == "or":
            raise CadenceUnreadable(f"{shown} offers a choice of days, and Second will not pick one.")
        if join != "range":
            continue
        if index > 0 and joins[index - 1] == "range":
            raise CadenceUnreadable(f"{shown} chains one range into another, and Second will not guess where it ends.")
        start, end = _DAY_INDEX[first.group(0)[:2]], _DAY_INDEX[second.group(0)[:2]]
        if end <= start:
            raise CadenceUnreadable(
                f"{shown} runs from {WEEKDAY_LABELS[start]} to {WEEKDAY_LABELS[end]}, which does not go "
                "forwards through the week, so Second will not guess which days it covers."
            )
        opener = re.search(r"\b(?:between|from)\s+$", mask[: first.start()])
        if opener is not None:
            read.append(opener.span())
        days.update(range(start, end + 1))

    for begin, end in read:
        mask = mask[:begin] + " " * (end - begin) + mask[end:]
    return frozenset(days), starts, mask


def _refuse_spaced_abbreviations(mask: str, tokens: list[re.Match[str]], shown: str) -> None:
    """Refuse "mon wed fri 07:00", saying how to write it, rather than naming "mon" as a stray word.

    Abbreviations with only spaces between them are not joined, so they do not count as days, and
    the leftover rule used to refuse them as words Second does not read: true, and no help. The
    reason now shows the user's own days written the way that reads.
    """
    run: list[re.Match[str]] = []
    for token in tokens:
        spaced = run and not mask[run[-1].end() : token.start()].strip()
        if spaced and (token.group("short") or run[-1].group("short")):
            run.append(token)
            continue
        if len(run) > 1:
            break
        run = [token]
    if len(run) > 1:
        written = "/".join(token.group(0).capitalize() for token in run)
        raise CadenceUnreadable(
            f"{shown} lists days with only spaces between them, so Second cannot tell they are a list. "
            f"Write them as {written}."
        )


_RANGE_JOIN = re.compile(r"-|–|—|to|through|thru|until|till")
_LIST_JOIN = re.compile(r"/|,|&|\+|and|,\s*and|,\s*&")
_CHOICE_JOIN = re.compile(r"or|,\s*or|/\s*or")


def _join(text: str, first: re.Match[str], second: re.Match[str]) -> str | None:
    """How two neighbouring day names are joined: a range, a list, a choice, or not at all."""
    between = text[first.end() : second.start()].strip()
    if _RANGE_JOIN.fullmatch(between):
        return "range"
    if _LIST_JOIN.fullmatch(between):
        # "between Monday and Friday" is a range said with "and".
        return "range" if re.search(r"\bbetween\s+$", text[: first.start()]) else "list"
    if _CHOICE_JOIN.fullmatch(between):
        return "or"
    return None


def _counts_as_day(lowered: str, mask: str, token: re.Match[str], joined: bool) -> bool:
    """Whether a day name is being used as a day.

    A spelled-out name always is. An abbreviation is when it is joined to another day ("Mon/Wed"),
    stands alone as the whole cadence, follows "on", "every" or a list word ("Mon 7pm and Wed"), or
    is followed by a time or a part of the day ("Sun 09:00", "Sat mornings"). Otherwise "sun" is
    the sun.

    "and Wed" counts so that "Mon 7pm and Wed" is refused for what it is, a time beside only some of
    its days, the same as "Monday 7pm and Wednesday", instead of for the word "wed".

    What follows is read from ``mask``, where a time is a mark; what comes before is read from the
    original, where "every other" is still there to see.
    """
    if token.group("full") or joined:
        return True
    before, after = mask[: token.start()], mask[token.end() :]
    if not before.strip(" ,.") and not after.strip(" ,."):
        return True
    if re.search(
        r"\b(?:on|every|each|next|this|alternate|every\s+(?:other|second|2nd|two|2))\s+$",
        lowered[: token.start()],
    ):
        return True
    if re.search(r"(?:,|&|\+|\band)\s*$", mask[: token.start()]):
        return True
    if re.match(rf"\s*,?\s*(?:at\s+)?{_TIME_MARK}\b", after):
        return True
    return bool(re.match(r"\s+(?:in\s+the\s+)?(?:morning|afternoon|evening|night)s?\b", after))


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
        # The last slot's time is borrowed on trust that the rhythm has not moved. A route that now
        # says "mornings" and last ran at 18:00 has moved, and borrowing 18:00 would contradict it.
        if cadence.part is not None and not in_day_part(at, cadence.part):
            unplaceable(
                f"{quoted(route.cadence)} names no time, and the last slot {quoted(task.title)} had, "
                f"{at:%H:%M}, is not in the {cadence.part}, so Second will not borrow it.",
                task.id,
            )
            return
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
