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

from datetime import date, datetime, timedelta

from second.core.clock import Clock
from second.core.models import (
    BriefJudgement,
    CheckIn,
    CheckInItem,
    DailyBrief,
    ObservationReport,
    LivingGraph,
    PreparedAction,
    Decision,
    Reminder,
    Risk,
    ScheduledBlock,
    Task,
)
from second.graphs.wording import plural, what_is_prepared

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


def blocks_on(graph: LivingGraph, clock: Clock, on: date) -> list[ScheduledBlock]:
    """Every piece of work with a slot on a given day, in time order.

    Paused and retired goals are skipped -- that is what retiring a goal means,
    and it is why retiring one visibly frees time.
    """
    today = on
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


def todays_blocks(graph: LivingGraph, clock: Clock) -> list[ScheduledBlock]:
    """Today's schedule."""
    return blocks_on(graph, clock, clock.today)


def build_check_in(
    graph: LivingGraph,
    clock: Clock,
    observations: ObservationReport | None = None,
    *,
    on: date | None = None,
) -> CheckIn:
    """Ask about yesterday, with the answers already filled in.

    Second knows what was scheduled and has looked for evidence. What it cannot
    know is whether the person actually did the thing -- a calendar shows an
    invite was declined, but nothing anywhere shows whether a five-minute
    recording happened. So it forms a view, shows the evidence, and asks for one
    tap.

    Work already marked done is left out: confirming something the system already
    knows is exactly the busywork this product exists to remove.
    """
    reconciling = on or (clock.today - timedelta(days=1))
    outcomes = {
        observation.task_id: observation
        for observation in (observations.observations if observations else [])
    }

    items: list[CheckInItem] = []
    for block in blocks_on(graph, clock, reconciling):
        task = graph.task_by_id(block.task_id)
        if task is None or task.status == "done":
            continue

        observed = outcomes.get(block.task_id)
        items.append(
            CheckInItem(
                task_id=block.task_id,
                title=block.title,
                goal_title=block.goal_title,
                scheduled_for=block.start,
                inferred=_INFERRED[observed.outcome] if observed else "unknown",
                evidence=observed.evidence if observed else "",
            )
        )

    return CheckIn(on=reconciling, items=items)


_INFERRED = {"honoured": "likely_done", "missed": "likely_missed", "unknown": "unknown"}


def deadline_risks(
    graph: LivingGraph,
    clock: Clock,
    *,
    window_days: int = RISK_WINDOW_DAYS,
    prepared: list[PreparedAction] | None = None,
) -> list[Risk]:
    """Work with a deadline close enough to matter and no plan that reaches it.

    Three ways a task earns a place here, all structural:

    * it is blocked, and its deadline is inside the window;
    * it has a deadline inside the window and no slot booked before it;
    * it has slipped more than twice and still has a deadline coming.

    Nothing here is a judgement about the person. Every item cites the reason it
    qualified.

    Args:
        prepared: Work on the same brief. One that is waiting on the user and names a task by id
            changes that task's reason: "nothing booked before then" beside a draft for it read as
            though nothing had been done. Matched on the id alone, as Memory's fold is.
    """
    today = clock.today
    risks: list[Risk] = []
    waiting: dict[str, PreparedAction] = {}
    for action in prepared or []:
        if action.is_real and action.awaiting.strip() and action.task_id:
            waiting.setdefault(action.task_id, action)

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

                reason = _risk_reason(task, booked_in_time, days_left, graph, waiting.get(task.id))
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
    task: Task,
    booked_in_time: list[datetime],
    days_left: int,
    graph: LivingGraph,
    waiting: PreparedAction | None = None,
) -> str | None:
    """Why this task is at risk, or None if it is fine.

    ``waiting`` is prepared work for this exact task that the user has yet to finish. The deadline
    is still at risk until they do, so the task stays listed, but the reason says what is ready.
    """
    prepared = f" {what_is_prepared(waiting)}" if waiting is not None else ""

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
            return f"Blocked on {names}, and {_due_in(days_left)}.{prepared}"
        return f"Marked blocked, and {_due_in(days_left)}.{prepared}"

    if not booked_in_time:
        if waiting is not None:
            # Still no slot, but "nothing booked before then" beside a finished draft reads as
            # nothing done, which is false. The due date and the waiting work are both true.
            return f"{_due_in(days_left).capitalize()}.{prepared}"
        return f"{_due_in(days_left).capitalize()} with nothing booked before then."

    if task.slip_count > 2:
        return f"Slipped {task.slip_count} times and still {_due_in(days_left)}.{prepared}"

    return None


def _due_in(days_left: int) -> str:
    """"due in 5 days", "due tomorrow", "due today".

    Shown on Today and on Memory as the reason a deadline is at risk, so it reads as a sentence.
    """
    if days_left < 0:
        return f"overdue by {plural(-days_left, 'day')}"
    if days_left == 0:
        return "due today"
    if days_left == 1:
        return "due tomorrow"
    return f"due in {plural(days_left, 'day')}"


NO_EVIDENCE = "Second could not point to anything supporting this."

NO_JUDGEMENT = "No judgement was produced this run; showing the schedule only."
"""The silence reason on a brief the Communicator did not finish. Named so the email source can tell
"the run found nothing" from "the run did not get that far", which are different things to tell a
person."""


def _evidenced(judgement: BriefJudgement) -> tuple[list[Reminder], list[Decision], list[str]]:
    """Apply the product's own rule to the model's output.

    "Every message cites its evidence" was asserted in four places and enforced in
    one. AGENTS found that ``Reminder``, ``Decision``, ``Observation`` and
    ``Deprioritised`` all validate with an empty ``evidence``, so an unsupported
    claim reached the user wearing the same confidence as a supported one.

    The two cases are not symmetric, and treating them the same would be wrong:

    * **A reminder is an assertion about the user's life.** Unsupported, it is a
      nag, and this product does not nag. Dropped.
    * **A decision is a request for help.** Dropping it would be worse than
      showing it -- the user never gets asked, and Second goes quiet on something
      it genuinely could not resolve. Kept, with the missing evidence replaced by
      an explicit admission, because "I need you to choose, and I cannot say why"
      is honest where silence is not.

    Enforced here rather than in a validator, on AGENTS' recommendation and for
    the reason already established on ``Diagnosis``: raising inside a forced
    structured-output call starts a loop whose cheapest escape is a fabricated
    quote.

    Returns:
        The surviving reminders, the decisions, and a note of what was dropped.
    """
    kept_reminders = [r for r in judgement.reminders if (r.evidence or "").strip()]
    dropped = len(judgement.reminders) - len(kept_reminders)

    decisions = [
        d if (d.evidence or "").strip() else d.model_copy(update={"evidence": NO_EVIDENCE})
        for d in judgement.decisions
    ]

    notes: list[str] = []
    if dropped:
        notes.append(f"{dropped} reminder(s) dropped for citing no evidence")
    unsupported = sum(1 for d in decisions if d.evidence == NO_EVIDENCE)
    if unsupported:
        notes.append(f"{unsupported} decision(s) kept but marked unsupported")
    return kept_reminders, decisions, notes


def assemble(
    *,
    graph: LivingGraph,
    clock: Clock,
    judgement: BriefJudgement | None,
    prepared: list[PreparedAction] | None = None,
    observations: ObservationReport | None = None,
    on: date | None = None,
) -> DailyBrief:
    """Build the day from computed facts plus the model's judgement.

    A missing or failed judgement degrades to a factual brief rather than to no
    brief. **Failure direction: still show the day.** The schedule came from the
    graph and is true regardless of whether the Communicator managed to produce a
    typed result -- and a user who opens the app to an error learns not to open
    the app.
    """
    # "nothing" is the Preparer saying there was nothing to carry. It must not
    # count as prepared work, or every autonomous day forces a notification.
    prepared = [item for item in (prepared or []) if item.is_real]
    blocks = todays_blocks(graph, clock)
    risks = deadline_risks(graph, clock, prepared=prepared)
    check_in = build_check_in(graph, clock, observations)

    if judgement is None:
        return DailyBrief(
            on=on or clock.today,
            blocks=blocks,
            prepared=prepared,
            at_risk=risks,
            check_in=check_in if check_in.needs_answer else None,
            notify=bool(prepared),
            silence_reason=NO_JUDGEMENT,
        )

    reminders, decisions, dropped_notes = _evidenced(judgement)
    silence_reason = judgement.silence_reason
    if dropped_notes:
        silence_reason = "; ".join([silence_reason, *dropped_notes]).lstrip("; ")

    return DailyBrief(
        on=on or clock.today,
        blocks=blocks,
        prepared=prepared,
        at_risk=risks,
        reminders=reminders,
        decisions=decisions,
        # The check-in never triggers a notification. It sits inside a brief the
        # user is already looking at, which is what lets it be daily without
        # breaking the promise that Second stays quiet.
        check_in=check_in if check_in.needs_answer else None,
        # A decision or a prepared action always earns a notification, whatever
        # the model concluded. It cannot talk itself out of telling the user
        # about something it is waiting on them for.
        notify=judgement.notify or bool(decisions) or bool(prepared),
        silence_reason=silence_reason,
    )
