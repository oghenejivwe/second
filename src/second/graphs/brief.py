"""Assembling the daily brief: facts in Python, judgement from the model.

The split here is deliberate and it is a correctness decision, not a style one.

**Today's schedule is a fact.** It is already in the Living Graph: which tasks
have a slot today, which goal each serves, how that goal ladders up. Asking a
model to list it invites it to invent a block, and a plan with one imaginary
meeting in it is worse than no plan -- the user stops trusting the other five.
So blocks and deadline risk are computed here, deterministically, from data.

**What needs a model is what a model is actually good at**: noticing that
somebody promised a reply three weeks ago and never sent it, and judging whether
any of today is worth interrupting them for. That is ``BriefJudgement``.

The brief is assembled from both. It exists every day. Existing is not
interrupting -- ``notify`` is the separate, rarer decision.
"""

from __future__ import annotations

from datetime import date, datetime

from second.core.clock import Clock
from second.core.models import (
    BriefJudgement,
    DailyBrief,
    LivingGraph,
    PreparedAction,
    Risk,
    ScheduledBlock,
    Task,
)

RISK_WINDOW_DAYS = 14
"""How far ahead a deadline has to be before it stops being today's problem."""


def _blocks_for(graph: LivingGraph, task: Task, slot: datetime, clock: Clock) -> ScheduledBlock | None:
    """Build one block, resolving the ladder of goals it serves."""
    route = next(
        (r for goal in graph.goals for r in goal.routes if r.id == task.route_id),
        None,
    )
    if route is None:
        return None

    chain = graph.ladder(route.goal_id)
    if not chain:
        return None
    owner, ancestors = chain[0], chain[1:]

    return ScheduledBlock(
        task_id=task.id,
        goal_id=owner.id,
        goal_title=owner.title,
        horizon=owner.horizon,
        serves=[goal.title for goal in ancestors],
        title=task.title,
        start=clock.local(slot),
        duration_min=60,
        resource_url=task.resource_url,
    )


def todays_blocks(graph: LivingGraph, clock: Clock) -> list[ScheduledBlock]:
    """Every piece of work with a slot today, in time order.

    Paused and retired goals are skipped -- that is what retiring a goal means,
    and it is why retiring one visibly frees time.
    """
    today = clock.today
    blocks: list[ScheduledBlock] = []

    for goal in graph.active_goals():
        for route in goal.routes:
            if route.status not in ("approved", "proposed"):
                continue
            for task in route.tasks:
                if task.status == "done":
                    continue
                for slot in task.scheduled_slots:
                    if clock.local(slot).date() != today:
                        continue
                    block = _blocks_for(graph, task, slot, clock)
                    if block:
                        blocks.append(block)

    return sorted(blocks, key=lambda block: block.start)


def deadline_risks(graph: LivingGraph, clock: Clock, *, window_days: int = RISK_WINDOW_DAYS) -> list[Risk]:
    """Work with a deadline close enough to matter and no plan that reaches it.

    Three ways a task earns a place here, all structural:

    * it is blocked, and its deadline is inside the window;
    * it has a deadline inside the window and no slot booked before it;
    * it has slipped more than twice and still has a deadline coming.

    Nothing here is a judgement about the person. Every item cites the reason it
    qualified.
    """
    today = clock.today
    risks: list[Risk] = []

    for goal in graph.active_goals():
        for route in goal.routes:
            for task in route.tasks:
                if task.status == "done" or task.deadline is None:
                    continue

                days_left = (task.deadline - today).days
                if days_left > window_days:
                    continue

                booked_in_time = [
                    slot
                    for slot in task.scheduled_slots
                    if today <= clock.local(slot).date() <= task.deadline
                ]

                reason = _risk_reason(task, booked_in_time, days_left, graph)
                if reason is None:
                    continue

                risks.append(
                    Risk(
                        task_id=task.id,
                        goal_id=goal.id,
                        what=task.title,
                        deadline=task.deadline,
                        days_left=days_left,
                        evidence=reason,
                    )
                )

    return sorted(risks, key=lambda risk: risk.days_left)


def _risk_reason(
    task: Task, booked_in_time: list[datetime], days_left: int, graph: LivingGraph
) -> str | None:
    """Why this task is at risk, or None if it is fine."""
    if task.status == "blocked":
        blockers = [
            blocker
            for blocker in task.depends_on
            if (dep := graph.task_by_id(blocker)) and dep.status != "done"
        ]
        if blockers:
            names = ", ".join(
                dep.title for blocker in blockers if (dep := graph.task_by_id(blocker))
            )
            return f"Blocked on {names}, and due in {days_left} day(s)."
        return f"Marked blocked, and due in {days_left} day(s)."

    if not booked_in_time:
        return f"Due in {days_left} day(s) with nothing booked before then."

    if task.slip_count > 2:
        return f"Slipped {task.slip_count} times and still due in {days_left} day(s)."

    return None


def assemble(
    *,
    graph: LivingGraph,
    clock: Clock,
    judgement: BriefJudgement | None,
    prepared: list[PreparedAction] | None = None,
    on: date | None = None,
) -> DailyBrief:
    """Build the day from computed facts plus the model's judgement.

    A missing or failed judgement degrades to a factual brief rather than to no
    brief. **Failure direction: still show the day.** The schedule came from the
    graph and is true regardless of whether the Communicator managed to produce a
    typed result -- and a user who opens the app to an error learns not to open
    the app.
    """
    prepared = prepared or []
    blocks = todays_blocks(graph, clock)
    risks = deadline_risks(graph, clock)

    if judgement is None:
        return DailyBrief(
            on=on or clock.today,
            blocks=blocks,
            prepared=prepared,
            at_risk=risks,
            notify=bool(prepared),
            silence_reason="No judgement was produced this run; showing the schedule only.",
        )

    return DailyBrief(
        on=on or clock.today,
        blocks=blocks,
        prepared=prepared,
        at_risk=risks,
        reminders=judgement.reminders,
        decisions=judgement.decisions,
        # A decision or a prepared action always earns a notification, whatever
        # the model concluded. It cannot talk itself out of telling the user
        # about something it is waiting on them for.
        notify=judgement.notify or bool(judgement.decisions) or bool(prepared),
        silence_reason=judgement.silence_reason,
    )
