"""What time it is for this person, and where.

Second reasons in local time constantly and never says so out loud. "6pm loses
to meetings", "Tuesdays 19:00 is the slot they actually keep", "no work before
10am" -- every one of those is a wall-clock claim, and every one of them is wrong
by an hour or by a day if the timezone is wrong.

**Nobody is asked what timezone they are in.** The calendar already knows, and
asking would go stale the moment they travelled. Resolution order:

1. An explicit override, for tests and for a scenario that must reproduce.
2. **The user's Google Calendar timezone.** This is the authority: it is the
   timezone their events are actually written in, set by them, and it follows
   them.
3. The machine's local timezone, for local development before Google is wired up.
4. UTC, which is always wrong for a person but never crashes.

Only the first two are trustworthy in production. Levels 3 and 4 are recorded in
:attr:`Clock.source` so a run can say how it decided, rather than quietly
producing a plan an hour out.

DST is the reason this uses IANA names rather than fixed offsets. The demo spans
three weeks of history; a fixed offset silently misplaces every event on the far
side of a clock change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

TimezoneSource = Literal["explicit", "calendar", "system", "utc"]

WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _load(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("unknown timezone %r", name)
        return None


def _system_timezone() -> tuple[ZoneInfo | None, TimezoneSource]:
    try:
        from tzlocal import get_localzone

        zone = get_localzone()
        return _load(str(zone)), "system"
    except Exception:  # noqa: BLE001 - never let clock detection break a run
        logger.debug("could not resolve the system timezone", exc_info=True)
        return None, "system"


def resolve_timezone(
    explicit: str | None = None,
    calendar_timezone: str | None = None,
) -> tuple[ZoneInfo, TimezoneSource]:
    """Work out which timezone this person lives in.

    Args:
        explicit: An override. Wins over everything.
        calendar_timezone: The IANA name from the user's Google Calendar, e.g.
            ``"Europe/London"``. This is the authority in production.

    Returns:
        The zone, and which rung of the ladder produced it.
    """
    if explicit and (zone := _load(explicit)):
        return zone, "explicit"
    if calendar_timezone and (zone := _load(calendar_timezone)):
        return zone, "calendar"
    zone, _ = _system_timezone()
    if zone:
        return zone, "system"
    return ZoneInfo("UTC"), "utc"


@dataclass(frozen=True)
class Clock:
    """The current moment, in the user's own timezone.

    Time is injected rather than read from the system clock at the point of use,
    so a seeded scenario reproduces. A test that passes on Tuesday and fails on
    Wednesday is worse than no test.
    """

    zone: ZoneInfo
    now: datetime
    source: TimezoneSource = "explicit"

    @classmethod
    def detect(
        cls,
        *,
        explicit: str | None = None,
        calendar_timezone: str | None = None,
        now: datetime | None = None,
    ) -> Clock:
        """Build a clock, discovering the timezone rather than being told it."""
        zone, source = resolve_timezone(explicit, calendar_timezone)
        moment = (now or datetime.now(timezone.utc)).astimezone(zone)
        if source in ("system", "utc"):
            logger.warning(
                "timezone came from %s, not the user's calendar; wall-clock reasoning may be off",
                source,
            )
        return cls(zone=zone, now=moment, source=source)

    @classmethod
    def fixed(cls, on: date, zone_name: str = "UTC", at: time = time(9, 0)) -> Clock:
        """A clock pinned to a specific moment, for scenarios and tests."""
        zone = _load(zone_name) or ZoneInfo("UTC")
        return cls(zone=zone, now=datetime.combine(on, at, tzinfo=zone), source="explicit")

    # -- reading --------------------------------------------------------

    @property
    def today(self) -> date:
        """The user's today, which is not necessarily UTC's."""
        return self.now.date()

    @property
    def name(self) -> str:
        """The IANA name, for prompts and for the audit log."""
        return str(self.zone)

    @property
    def is_trustworthy(self) -> bool:
        """Whether the timezone came from a source that actually knows.

        False means it was guessed from the machine or fell back to UTC. The
        Scheduler should say so rather than place a 7am block with confidence.
        """
        return self.source in ("explicit", "calendar")

    # -- converting -----------------------------------------------------

    def local(self, moment: datetime) -> datetime:
        """Move a datetime into the user's timezone.

        A naive datetime is assumed to already be local -- which is what the
        Living Graph stores, because a plan is written in the wall-clock time the
        person reads off their own calendar.
        """
        if moment.tzinfo is None:
            return moment.replace(tzinfo=self.zone)
        return moment.astimezone(self.zone)

    def slot_label(self, moment: datetime) -> str:
        """Render a slot the way the Person layer stores it: ``"Tue 19:00"``.

        This must be computed in local time. The same instant is "Tue 19:00" in
        London and "Tue 11:00" in Los Angeles, and the Person layer's whole claim
        is that it knows which slots this person keeps.
        """
        moment = self.local(moment)
        return f"{WEEKDAY_LABELS[moment.weekday()]} {moment:%H:%M}"

    def window(self, *, days_back: int = 0, days_forward: int = 0) -> tuple[str, str]:
        """An ISO 8601 range around today, for calendar and inbox queries.

        Returns:
            ``(start, end)`` as ISO strings, spanning whole local days -- start of
            the day ``days_back`` ago to the end of the day ``days_forward``
            ahead.
        """
        start = datetime.combine(self.today - timedelta(days=days_back), time.min, tzinfo=self.zone)
        end = datetime.combine(
            self.today + timedelta(days=days_forward), time.min, tzinfo=self.zone
        ) + timedelta(days=1)
        return start.isoformat(), end.isoformat()

    def describe(self) -> str:
        """One line for a system prompt, so an agent reasons in the right frame.

        Uses no platform-specific strftime codes -- ``%-d`` is glibc-only and
        this build is developed on Windows and deployed on Linux.
        """
        confidence = "" if self.is_trustworthy else " (guessed - do not rely on precise times)"
        return (
            f"Today is {self.today.strftime('%A')} {self.today.day} "
            f"{self.today.strftime('%B %Y')}, and the local time is "
            f"{self.now.strftime('%H:%M')} in {self.name}{confidence}."
        )
