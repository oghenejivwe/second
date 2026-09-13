"""The recurring question: what do you want to do this week, this month, and by when?

The founder asked for a feedback mechanism that asks "every one, two or three days". Two rules keep
it a question rather than a nag, and both are facts computed here rather than judgement:

* **It is asked on a cadence**, per horizon, from ``settings.QUESTION_CADENCE_DAYS``. Answering or
  skipping records the day in ``PersonModel.asked_on``, and the question stays quiet until that
  many days have passed.
* **It is anchored to a real gap.** The question names the goal with nothing set at that horizon --
  a year goal with no month goal under it -- so the user answers about something they already
  said they wanted, and the evidence says why it was asked today.

At most one question per horizon. Two questions about this week is a form.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from second.core.models import Goal, HorizonQuestion, LivingGraph
from second.graphs.wording import plural, quoted
from second.settings import QUESTION_CADENCE_DAYS

ANCHOR_RUNGS: dict[str, tuple[str, ...]] = {
    "month": ("quarter", "year"),
    "week": ("month", "quarter", "year"),
}
"""Which goals a question at each horizon may be anchored to, nearest rung first.

Nearest first because the closest rung is the one that horizon most directly serves: a month goal
due in six weeks needs something this week more than a year goal does. Keys must cover
``QUESTION_CADENCE_DAYS``; a test holds them together."""


def cadence_days(horizon: str) -> int:
    """How often a horizon is asked about.

    Raises:
        ValueError: If Second does not ask about that horizon at all.
    """
    try:
        return QUESTION_CADENCE_DAYS[horizon]
    except KeyError:
        raise ValueError(
            f"Second does not ask about the {horizon!r} horizon; it asks about {sorted(QUESTION_CADENCE_DAYS)}"
        ) from None


def is_due(graph: LivingGraph, horizon: str, today: date) -> bool:
    """Never asked, or asked at least a full cadence ago."""
    every = cadence_days(horizon)
    last = graph.person.asked_on.get(horizon)
    return last is None or (today - last).days >= every


def next_due(horizon: str, asked: date) -> date:
    """The first day the question comes back after being asked on ``asked``."""
    return asked + timedelta(days=cadence_days(horizon))


def anchor_for(graph: LivingGraph, horizon: str) -> Goal | None:
    """The most relevant active goal above ``horizon`` with no active child at ``horizon``.

    Ordered by nearest rung, then by the earliest deadline (a goal with no deadline comes last),
    then by the order the goals sit in the graph -- so the same graph always anchors the same way.
    A paused or retired child does not count as filling the rung: it is not being worked.
    """
    rungs = ANCHOR_RUNGS.get(horizon, ())
    candidates = [
        goal
        for goal in graph.active_goals()
        if goal.horizon in rungs
        and not any(
            child.status == "active" and child.horizon == horizon for child in graph.children_of(goal.id)
        )
    ]
    ranked = sorted(
        candidates,
        key=lambda goal: (rungs.index(goal.horizon), goal.deadline is None, goal.deadline or date.max),
    )
    return ranked[0] if ranked else None


def question_for(graph: LivingGraph, horizon: str, today: date) -> HorizonQuestion:
    """The one question for a horizon, whether or not it is due.

    Used on its own when the user answers, so the question the answer is filed under is the one
    they were shown.
    """
    every = cadence_days(horizon)
    last = graph.person.asked_on.get(horizon)
    anchor = anchor_for(graph, horizon)

    if anchor is None:
        text = f"What do you want to do this {horizon}, and by when?"
        gap = _general_gap(graph, horizon)
    else:
        text = f"What do you want to do this {horizon} towards {quoted(anchor.title)}, and by when?"
        gap = _anchor_gap(graph, anchor, horizon, today)

    if last is None:
        when = "Never asked before."
    else:
        elapsed = (today - last).days
        ago = "today" if elapsed == 0 else f"{plural(elapsed, 'day')} ago"
        when = f"Last asked {ago}, on {last.isoformat()}."

    return HorizonQuestion(
        horizon=horizon,
        question=text,
        evidence=f"{gap} {when}",
        anchor_goal_id=anchor.id if anchor else None,
        anchor_goal_title=anchor.title if anchor else None,
        last_asked=last,
        every_days=every,
    )


def due_questions(graph: LivingGraph, today: date) -> list[HorizonQuestion]:
    """Every horizon whose cadence has elapsed, one question each, shortest horizon first."""
    return [
        question_for(graph, horizon, today)
        for horizon in QUESTION_CADENCE_DAYS
        if is_due(graph, horizon, today)
    ]


def mark_asked(graph: LivingGraph, horizon: str, on: date) -> None:
    """Record that a horizon was put to the user. For ``store.mutate``, so safe to run twice."""
    cadence_days(horizon)
    graph.person.asked_on[horizon] = on


# ---------------------------------------------------------------------------


def _anchor_gap(graph: LivingGraph, anchor: Goal, horizon: str, today: date) -> str:
    """Why this goal was chosen, in words that stay true whatever the graph holds.

    The anchor is chosen for having no goal set at this horizon, which is not the same as having
    nothing planned: "Get comfortable speaking to a room" has no month goal and three sessions
    placed this month. Saying "nothing is planned" there would be false, so the sessions are counted
    and the sentence follows the count.
    """
    placed = _sessions_under(graph, anchor, today, _end_of(horizon, today))
    if placed == 0:
        return f"Nothing is planned for this {horizon} under {quoted(anchor.title)}."
    return (
        f"{quoted(anchor.title)} has {plural(placed, 'session')} placed this {horizon} "
        f"but no goal set for the {horizon}."
    )


def _general_gap(graph: LivingGraph, horizon: str) -> str:
    """Why the question names no goal: none to name, or every one already has this horizon set."""
    rungs = ANCHOR_RUNGS.get(horizon, ())
    names = [rung.replace("_", " ") for rung in rungs]
    listed = ", ".join(names[:-1]) + (" or " if len(names) > 1 else "") + names[-1] if names else "longer"
    if not any(goal.horizon in rungs for goal in graph.active_goals()):
        return f"You have no {listed} goal to ask about, so this is asked in general."
    both = listed.replace(" or ", " and ")
    return f"Every {both} goal already has a goal set for this {horizon}, so this is asked in general."


def _end_of(horizon: str, today: date) -> date:
    """The last day of this week (Sunday) or this month."""
    if horizon == "week":
        return today + timedelta(days=6 - today.weekday())
    return today.replace(day=calendar.monthrange(today.year, today.month)[1])


def _sessions_under(graph: LivingGraph, anchor: Goal, start: date, end: date) -> int:
    """Slots from ``start`` to ``end`` on unfinished tasks under a goal or any goal beneath it.

    Read as the naive wall-clock dates the Living Graph stores, the same way the Scheduler writes
    them; routes the way ``blocks_on`` counts them, approved or proposed.
    """
    goals, seen, frontier = [], {anchor.id}, [anchor]
    while frontier:
        goal = frontier.pop()
        goals.append(goal)
        for child in graph.children_of(goal.id):
            if child.status == "active" and child.id not in seen:
                seen.add(child.id)
                frontier.append(child)

    return sum(
        1
        for goal in goals
        for route in goal.routes
        if route.status in ("approved", "proposed")
        for task in route.tasks
        if task.status != "done"
        for slot in task.scheduled_slots
        if start <= slot.date() <= end
    )
