"""The shared contract. Every domain imports this; PLATFORM lands changes to it.

These types are the seam between the three instances. AGENTS emits them, PLATFORM
persists them, SURFACES renders them, CONNECTORS fills them with real calendar and
inbox data. Widening one to solve a local problem breaks the other three, so
propose changes in your log turn rather than editing this file.

Four of these are structured-output models -- ``ExtractionResult``,
``ScheduleDecision``, ``Diagnosis``, ``FeedbackUpdate``. They are handed to
``Agent(structured_output_model=...)``, which registers their JSON schema as a
tool the model must call. Two consequences worth knowing before you edit them:

  * Every field needs a description the model can act on. The schema IS the
    prompt for that field.
  * Deep nesting costs tokens and accuracy. ``Goal.routes`` defaults to empty
    because the Extractor emits shallow goals and the Route Planner fills them
    in afterwards -- one model never has to produce the whole tree at once.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

TaskStatus = Literal["pending", "done", "blocked"]
RouteStatus = Literal["proposed", "approved", "rejected", "dropped"]
GoalStatus = Literal["active", "paused", "retired"]

Horizon = Literal["life", "decade", "three_year", "year", "quarter", "month", "week", "day"]
"""How far out a goal sits.

Goals ladder down: a life-shaped ambition becomes a decade, a decade becomes
three years, three years becomes this year, and eventually something lands in
Tuesday morning. ``contributes_to`` is the rung above.

The horizon is the *rung*; ``deadline`` is the *date*. "In fifteen years" is a
``life`` goal with a deadline fifteen years out -- the enum stays short so a
model can reason about it reliably, and precision lives in the date."""

HORIZON_ORDER: tuple[Horizon, ...] = (
    "life",
    "decade",
    "three_year",
    "year",
    "quarter",
    "month",
    "week",
    "day",
)

SCHEDULABLE_HORIZONS: frozenset[str] = frozenset({"year", "quarter", "month", "week", "day"})
"""Goals near enough to hold routes and tasks that go in a calendar.

A year is the boundary because a yearly goal with a weekly cadence is a perfectly
ordinary thing -- "get comfortable speaking to a room this year, at the club every
Tuesday" needs no further decomposition to be workable.

Above a year it stops being true. You cannot put "build a billion-dollar company"
in Tuesday's 9am slot, and a system that pretends otherwise produces a plan
nobody believes. Those get walked down by the Cascader first."""
BlockerType = Literal[
    "MISSING_INFORMATION",
    "UNDEFINED_SCOPE",
    "UNMET_DEPENDENCY",
    "CALENDAR_CONFLICT",
    "UNKNOWN",
]


# ---------------------------------------------------------------------------
# Goals layer
# ---------------------------------------------------------------------------


class Slip(BaseModel):
    """One occasion on which a task did not happen as planned."""

    on: date
    scheduled_for: datetime | None = None
    noticed_by: str = Field(default="observer", description="Which agent recorded this slip.")
    note: str = ""


class Task(BaseModel):
    """A single concrete action inside a route."""

    id: str
    route_id: str
    title: str
    depends_on: list[str] = Field(
        default_factory=list,
        description="Task ids that must be done first. An UNMET_DEPENDENCY diagnosis reads this.",
    )
    deadline: date | None = None
    scheduled_slots: list[datetime] = Field(default_factory=list)
    slip_count: int = 0
    slips: list[Slip] = Field(default_factory=list)
    status: TaskStatus = "pending"
    known_blocker: str | None = Field(
        default=None,
        description="Written from the user's own answer. Once set, never ask about this task again.",
    )
    resource_url: str | None = Field(
        default=None,
        description="Material attached to this task's slot, so it is already there at 7am.",
    )


class Route(BaseModel):
    """One concrete way of reaching a goal. Proposed by Second, approved by the user."""

    id: str
    goal_id: str
    title: str
    cadence: str = Field(description="How often, in plain words. 'Weekly, Tuesday evenings'.")
    rationale: str = Field(description="Why this route suits THIS person, citing a person-layer fact.")
    status: RouteStatus = "proposed"
    tasks: list[Task] = Field(default_factory=list)


class Goal(BaseModel):
    """Something the user said they want, at some distance from today.

    Goals form a ladder rather than a list. "A billion-dollar company in fifteen
    years" is a real goal and it is not a task; it becomes a three-year goal,
    which becomes this year's, which becomes something that occupies Tuesday
    morning. ``contributes_to`` is that ladder, and it is what lets Second answer
    the only question that matters on a Tuesday morning: *why this, today?*
    """

    id: str
    title: str
    horizon: Horizon = "year"
    contributes_to: str | None = Field(
        default=None,
        description="The id of the longer-horizon goal this serves. None for a top-level ambition.",
    )
    deadline: date | None = None
    status: GoalStatus = "active"
    routes: list[Route] = Field(default_factory=list)
    extraction_confidence: float = Field(
        default=1.0,
        description="How sure the Extractor was that this is a real, distinct goal.",
    )

    @property
    def is_schedulable(self) -> bool:
        """Whether this goal is near enough to hold calendar-bound work."""
        return self.horizon in SCHEDULABLE_HORIZONS


# ---------------------------------------------------------------------------
# Person layer -- what makes Second feel like it knows you
# ---------------------------------------------------------------------------


class PersonModel(BaseModel):
    """Observed facts about how this person actually operates.

    Structural only. Every field here is something the system watched happen, or
    something the user said outright. Nothing in this model is an inference about
    motivation, discipline or mood, and no agent may write one.
    """

    preferences: dict[str, str] = Field(
        default_factory=dict,
        description='Stated or demonstrated, e.g. {"learning_mode": "video"}.',
    )
    constraints: list[str] = Field(
        default_factory=list,
        description='Hard rules the Scheduler must honour, e.g. "no work before 10am".',
    )
    honoured_slots: list[str] = Field(
        default_factory=list,
        description='Time slots this person actually keeps, e.g. "Tue 07:00".',
    )
    abandoned_slots: list[str] = Field(
        default_factory=list,
        description="Slots repeatedly scheduled and repeatedly missed.",
    )
    recurring_blockers: list[str] = Field(default_factory=list)
    resources_served: list[str] = Field(
        default_factory=list,
        description="Already shown to the user. The Resource Finder never repeats one.",
    )


# ---------------------------------------------------------------------------
# Connective layer
# ---------------------------------------------------------------------------


LinkKind = Literal[
    "route_suits_preference",
    "resource_served_for_goal",
    "slot_honoured_for_task",
    "slot_abandoned_for_task",
    "blocker_recurs_for_goal",
]


class Link(BaseModel):
    """An edge between the goals layer and the person layer."""

    kind: LinkKind
    from_id: str = Field(description="Goals-layer id: a goal, route or task.")
    to_ref: str = Field(description="Person-layer reference: a preference key, slot or constraint.")
    note: str = ""


# ---------------------------------------------------------------------------
# The Living Graph
# ---------------------------------------------------------------------------


class LivingGraph(BaseModel):
    """One persistent structure per user. Written by every agent, read by every agent.

    ``version`` backs the conditional write that stops two nodes in the same run
    clobbering each other. Read it, send it back with your update, and expect the
    write to be rejected if it moved underneath you.
    """

    user_id: str
    goals: list[Goal] = Field(default_factory=list)
    person: PersonModel = Field(default_factory=PersonModel)
    links: list[Link] = Field(default_factory=list)
    version: int = 0
    updated_at: datetime | None = None

    def task_by_id(self, task_id: str) -> Task | None:
        """Find a task anywhere in the tree."""
        for goal in self.goals:
            for route in goal.routes:
                for task in route.tasks:
                    if task.id == task_id:
                        return task
        return None

    def active_goals(self) -> list[Goal]:
        """Goals still competing for the user's time."""
        return [goal for goal in self.goals if goal.status == "active"]

    def goal_by_id(self, goal_id: str) -> Goal | None:
        """Find a goal by id."""
        return next((goal for goal in self.goals if goal.id == goal_id), None)

    def children_of(self, goal_id: str) -> list[Goal]:
        """The shorter-horizon goals that serve this one."""
        return [goal for goal in self.goals if goal.contributes_to == goal_id]

    def ladder(self, goal_id: str) -> list[Goal]:
        """Walk up from a goal to the ambition it ultimately serves.

        Returns the chain nearest-first, so ``ladder("t-week-goal")`` reads as
        "this week, serving this quarter, serving this year, serving the decade".
        This is what turns a line on a Tuesday into a reason.

        Cycles are survivable rather than fatal: a malformed ``contributes_to``
        stops the walk instead of hanging the daily run. **Failure direction:
        return a short chain, not no day.**
        """
        chain: list[Goal] = []
        seen: set[str] = set()
        current = self.goal_by_id(goal_id)
        while current and current.id not in seen:
            chain.append(current)
            seen.add(current.id)
            current = self.goal_by_id(current.contributes_to) if current.contributes_to else None
        return chain

    def roots(self) -> list[Goal]:
        """Top-level ambitions -- the goals nothing else sits above."""
        return [goal for goal in self.goals if goal.contributes_to is None]

    def schedulable_goals(self) -> list[Goal]:
        """Active goals near enough to hold work that goes in a calendar."""
        return [goal for goal in self.active_goals() if goal.is_schedulable]

    def stalled_ambitions(self) -> list[Goal]:
        """Long-horizon goals that have never been cashed into anything doable.

        An ambition with no children and no routes is a wish. This is the
        Cascader's work queue, and a non-empty list here on the day of a demo
        means a goal the user stated is doing nothing.
        """
        return [
            goal
            for goal in self.active_goals()
            if not goal.is_schedulable
            and not self.children_of(goal.id)
            and not goal.routes
        ]

    def broken_links(self) -> list[Goal]:
        """Goals pointing at a parent that is not in the graph.

        A data-integrity problem rather than a planning one, kept separate
        because the two want different responses: this one is a bug, a stalled
        ambition is just work not yet done.
        """
        ids = {goal.id for goal in self.goals}
        return [goal for goal in self.goals if goal.contributes_to and goal.contributes_to not in ids]


# ---------------------------------------------------------------------------
# Structured outputs -- these route the graphs
# ---------------------------------------------------------------------------


class ExtractionResult(BaseModel):
    """What the Extractor heard in a spoken brain dump."""

    goals: list[Goal] = Field(description="One per distinct thing the user wants. Shallow: no routes yet.")
    clarifying_questions: list[str] = Field(
        default_factory=list,
        description="Ask rather than guess. Empty when everything was clear.",
    )


class Placement(BaseModel):
    """One task placed into a real calendar slot."""

    task_id: str
    start: datetime
    duration_min: int
    calendar_event_id: str | None = None


class Deprioritised(BaseModel):
    """Something that lost the competition for a slot, and why it lost."""

    task_id: str
    wanted: str = Field(description="The slot it wanted.")
    lost_to: str = Field(description="What took the slot instead.")
    reason: str = Field(description="Deadline pressure, a person-layer constraint, or an honoured-slot record.")


class ScheduleDecision(BaseModel):
    """The Scheduler's verdict across ALL active goals at once.

    ``deprioritised`` is not optional output. A scheduler that only reports what
    it placed is hiding the decision it actually made.
    """

    placed: list[Placement] = Field(default_factory=list)
    deprioritised: list[Deprioritised] = Field(default_factory=list)
    rationale: str = Field(description="How competition between goals was resolved.")


class Diagnosis(BaseModel):
    """Why a task slipped, and whether Second can act on it alone.

    ``requires_user_decision`` routes the Daily Graph. It is a typed field read by
    a conditional edge, not a prompt hoping for the best.

    **``evidence`` is nullable, and that is load-bearing.** Strands produces
    structured output by *forcing* a tool call: if the model declines, it is
    re-asked with the choice forced, and on that pass it cannot refuse. A required
    non-nullable ``evidence`` field would therefore compel the model to write
    *something* in it even when nothing in the calendar or inbox supports a cause
    -- which is how a real quote ends up attached to a conclusion it does not
    support. The rule this model is meant to encode, *no evidence no diagnosis*,
    is precisely the rule forced tool choice removes. So the schema has to give
    the model somewhere honest to land.
    """

    task_id: str
    blocker_type: BlockerType
    evidence: str | None = Field(
        default=None,
        description=(
            "Quote the calendar entry or the email this rests on. "
            "Leave null if nothing in the evidence supports a structural cause. "
            "Never invent or paraphrase a quote to fill this field."
        ),
    )
    confidence: float = Field(ge=0.0, le=1.0)
    proposed_action: str
    requires_user_decision: bool = Field(
        description="True when Second genuinely cannot resolve this without the user."
    )

    @model_validator(mode="after")
    def _no_evidence_means_unknown(self) -> "Diagnosis":
        """A diagnosis with no evidence is downgraded, not rejected.

        Coerced rather than raised, deliberately. A ``ValidationError`` goes back
        to the model as an error tool result with **no attempt cap**, and the
        cheapest way for a model to escape that loop is to invent a quote. Raising
        here would actively manufacture the failure it is trying to prevent.

        So instead: no evidence, no claim. The blocker becomes ``UNKNOWN``,
        confidence is capped low, and the conditional edge routes to the
        Communicator, which asks the user honestly. That is the behaviour the
        product promises, enforced by the type rather than by a prompt.
        """
        if not (self.evidence or "").strip():
            self.blocker_type = "UNKNOWN"
            self.confidence = min(self.confidence, 0.3)
            self.requires_user_decision = True
        return self


class FeedbackUpdate(BaseModel):
    """One typed change derived from something the user said back."""

    target: Literal["route", "task", "person_model"]
    target_id: str | None = None
    change: str = Field(description="What to change, in terms the Adapter can act on.")
    person_model_patch: dict[str, str] = Field(
        default_factory=dict,
        description="Merged into PersonModel.preferences. This is how Second learns.",
    )


class FeedbackResult(BaseModel):
    """Everything the Interpreter took from one thing the user said.

    Covers both directions of the daily loop: ``completions`` is the user
    reporting backwards on what actually happened, ``updates`` is everything else
    -- a preference, a time that does not work, a route that is too much.
    """

    completions: list[CompletionReport] = Field(
        default_factory=list,
        description="Answers to the check-in. Ground truth; overrides what was inferred.",
    )
    updates: list[FeedbackUpdate] = Field(default_factory=list)
    intentions: list[str] = Field(
        default_factory=list,
        description="Things the user says they want to do today that are not yet in the plan.",
    )
    acknowledgement: str = Field(default="", description="At most one line back to the user. Often empty.")


# ---------------------------------------------------------------------------
# What reaches the user
# ---------------------------------------------------------------------------


class PreparedAction(BaseModel):
    """Work carried up to the last click, and stopped there.

    Second never completes the irreversible step. A draft is created, never sent.
    Options are assembled, never booked.
    """

    kind: Literal["email_draft", "options", "retrieved_fact", "calendar_change"]
    summary: str = Field(description="What was prepared, in one line.")
    detail: str = Field(default="", description="The draft body, the compared options, the retrieved value.")
    external_ref: str | None = Field(default=None, description="Gmail draft id, calendar event id.")
    awaiting: str = Field(description="The single thing left for the user to do.")


class ScheduledBlock(BaseModel):
    """One piece of work occupying a real slot today, and what it is for.

    ``goal_title`` and ``serves`` are denormalised onto the block on purpose. The
    day has to answer *why this, today?* without the reader following a chain of
    ids, and "Draft the pitch — 45 min — serves: speak well → this year → the
    decade" is the whole product in one line.
    """

    task_id: str
    goal_id: str
    goal_title: str
    horizon: Horizon
    serves: list[str] = Field(
        default_factory=list,
        description="Titles of the longer-horizon goals above this one, nearest first.",
    )
    title: str
    start: datetime = Field(
        description=(
            "Timezone-AWARE, in the user's own zone. Note the asymmetry, which is "
            "deliberate: Task.scheduled_slots are stored NAIVE because the Living "
            "Graph holds wall-clock time -- a plan is what the person reads off "
            "their own calendar, and storing it as UTC would move the plan when "
            "they travel. Anything crossing the API boundary is made aware by "
            "Clock.local() so a browser cannot guess wrong. Never compare a raw "
            "scheduled_slot against one of these without passing it through the "
            "clock first."
        )
    )
    duration_min: int
    resource_url: str | None = Field(
        default=None,
        description="Material attached to the slot, so the thing to watch is already there.",
    )


class GoalStatusChange(BaseModel):
    """What pausing or retiring a goal actually did.

    ``freed`` is the point. Retiring a goal releases the calendar time its routes
    were holding, and the Goals screen has to be able to show that concretely --
    these slots, this many hours, no longer spoken for.

    It says *freed*, not *redistributed*, deliberately. The Scheduler has not run
    again yet, so nothing has been reallocated. Claiming otherwise would have
    Second describing a plan it has not made, which is the one thing this product
    must never do. ``note`` says when the reallocation actually happens.
    """

    graph: "LivingGraph"
    freed: list["ScheduledBlock"] = Field(
        default_factory=list,
        description="Upcoming slots the goal was holding, now released. Empty when it held none.",
    )
    freed_minutes: int = 0
    note: str = Field(
        default="",
        description="What becomes of the freed time, in plain words.",
    )


class Risk(BaseModel):
    """Something with a deadline that will not be met on the current plan."""

    task_id: str
    goal_id: str
    what: str
    deadline: date
    days_left: int
    evidence: str = Field(description="Why this is at risk. Cite the calendar or the graph.")


class Reminder(BaseModel):
    """Something the user cares about and has probably forgotten.

    Not a nag and not a nudge. This exists because commitments get made in email
    and then never reach a plan -- a reply promised, a form nobody filled in, a
    booking that closes. Every one cites where it came from, and a reminder with
    no evidence is a defect.
    """

    what: str
    evidence: str
    source: Literal["email", "calendar", "graph"]


class Decision(BaseModel):
    """The one kind of thing that is allowed to interrupt.

    Second reaches here only when it genuinely cannot proceed alone. Options are
    included because a question with three researched answers costs five seconds
    and a bare question costs a round trip.
    """

    question: str
    task_id: str | None = None
    evidence: str
    options: list[str] = Field(default_factory=list)


class DailyBrief(BaseModel):
    """What Second has for you today. The product's face.

    Assembled every day, whether or not anything needs you. **Existing is not
    interrupting** -- ``notify`` is the separate, rarer decision about whether to
    push. Silence means ``notify`` is false and ``decisions`` is empty, not that
    the brief is missing.

    The order of the fields is the order of value: what you are doing, what has
    already been done for you, what is slipping, what you forgot, and only then
    what Second needs from you.
    """

    on: date
    blocks: list[ScheduledBlock] = Field(
        default_factory=list, description="Today's schedule, in time order."
    )
    prepared: list[PreparedAction] = Field(
        default_factory=list,
        description="Work carried to the last click while the user was elsewhere.",
    )
    at_risk: list[Risk] = Field(default_factory=list)
    reminders: list[Reminder] = Field(default_factory=list)
    decisions: list[Decision] = Field(
        default_factory=list,
        description="Usually empty. Each one costs the user attention, so earn it.",
    )
    check_in: CheckIn | None = Field(
        default=None,
        description="Yesterday, pre-filled, awaiting confirmation. Does not trigger a notification.",
    )
    notify: bool = Field(
        default=False,
        description="Push this at the user. True only when a decision is needed or something was prepared.",
    )
    silence_reason: str = Field(
        default="",
        description="When notify is false, why. Recorded for the audit, never shown to the user.",
    )

    @property
    def is_quiet(self) -> bool:
        """Nothing here needs the user's attention today."""
        return not self.notify and not self.decisions


class IntakeResult(BaseModel):
    """What one spoken brain dump produced.

    ``clarifying_questions`` being non-empty means the Intake graph stopped after
    the Extractor on purpose: it was not clear enough what the user wanted to
    justify putting anything in their calendar. ``schedule`` is ``None`` in that
    case, and the caller asks rather than shows a plan.
    """

    graph: LivingGraph
    clarifying_questions: list[str] = Field(default_factory=list)
    schedule: "ScheduleDecision | None" = Field(
        default=None,
        description="What the Scheduler placed and what it deprioritised, when it ran.",
    )


class Observation(BaseModel):
    """What the Observer could work out about one scheduled slot.

    Inference only. The calendar can show an invite was declined and the inbox
    can show a mail was never sent, but **nothing in either can tell you whether
    somebody actually did the five-minute recording.** That is what the check-in
    is for, and it is why ``outcome`` is allowed to be ``"unknown"`` rather than
    being forced into a guess.
    """

    task_id: str
    scheduled_for: datetime
    outcome: Literal["honoured", "missed", "unknown"]
    evidence: str = Field(description="Quote the calendar entry or the email. No evidence, no claim.")
    source: Literal["calendar", "email", "none"]


class ObservationReport(BaseModel):
    """The Observer's sanitised bundle. The only thing the Diagnostician sees.

    This is the context-isolation boundary made concrete: the Observer reads raw
    calendar entries and raw email, and hands on **this** -- task ids, outcomes
    and quoted evidence. Not inbox contents. The Diagnostician cannot reach
    Gmail or Calendar itself, so this report is the whole of its world.
    """

    observations: list[Observation] = Field(default_factory=list)
    notes: str = Field(
        default="",
        description="Structural context not tied to one task, e.g. a standing meeting that moved.",
    )


class CheckInItem(BaseModel):
    """One thing to confirm, arriving with the answer already filled in.

    Second does everything it can before asking. It knows what was scheduled, it
    has looked for evidence, and it has formed a view. The user's job is one tap
    to confirm or correct -- not to remember and report.
    """

    task_id: str
    title: str
    goal_title: str
    scheduled_for: datetime
    inferred: Literal["likely_done", "likely_missed", "unknown"]
    evidence: str = Field(
        default="",
        description="Why Second thinks so. Empty when it genuinely has nothing and is simply asking.",
    )


class CheckIn(BaseModel):
    """The daily reconciliation. What actually happened, from the only source that knows.

    **This is not a notification.** It sits inside the brief the user is already
    looking at, so it costs them nothing extra -- which is why it can be daily
    without breaking the promise that Second stays quiet.

    Without it the system's picture drifts: slips get inferred that never
    happened, honoured slots get recorded as abandoned, and every diagnosis
    downstream is built on a guess.
    """

    on: date = Field(description="The day being reconciled, usually yesterday.")
    items: list[CheckInItem] = Field(default_factory=list)

    @property
    def needs_answer(self) -> bool:
        """Whether there is anything to confirm at all."""
        return bool(self.items)

    @property
    def uncertain(self) -> list[CheckInItem]:
        """The items Second genuinely could not work out. These matter most."""
        return [item for item in self.items if item.inferred == "unknown"]


class CompletionReport(BaseModel):
    """The user's own answer about one task. Beats every inference.

    When this disagrees with the Observer, this wins and the inference is
    discarded -- not averaged, not weighed. The person was there.
    """

    task_id: str
    did_it: bool
    note: str = Field(default="", description="Anything they said about why, in their words.")


class BriefJudgement(BaseModel):
    """The part of the daily brief that requires judgement rather than arithmetic.

    Today's schedule and what is at risk are **facts already in the Living
    Graph**, so PLATFORM computes them in Python: deterministic, free, testable,
    and impossible to hallucinate a meeting into. A model asked to list your day
    will eventually invent a block, and a plan you cannot trust is worse than no
    plan.

    What genuinely needs a model is this: what did the user commit to and forget,
    and is any of it worth interrupting them for.
    """

    reminders: list[Reminder] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    notify: bool = Field(
        description="True only when a decision is needed or something was prepared for them."
    )
    silence_reason: str = Field(
        default="",
        description="When notify is false, why. For the audit log, never shown to the user.",
    )


class RoutePlan(BaseModel):
    """Concrete routes proposed for goals that are near enough to work on.

    Shallow on purpose. The alternative was to carry whole ``Goal`` objects here,
    which means a Goal->Route->Task schema at every hop and nothing persisted at
    all if the Scheduler fails downstream. Instead the Cascader writes the goal
    ladder to the graph as it goes, and this carries only what is new -- so a
    scheduling failure costs the routes, not the ladder.
    """

    routes: list[Route] = Field(description="Proposed routes, each already bound to a goal_id.")
    rationale: str = Field(description="Why these routes suit THIS person, citing a person-layer fact.")
    clarifying_questions: list[str] = Field(
        default_factory=list,
        description="Ask rather than invent a cadence the user will abandon in week two.",
    )


class CascadeResult(BaseModel):
    """A long-horizon ambition, cashed into goals that can actually be worked.

    "A billion-dollar company in fifteen years" is not a task and pretending
    otherwise produces a plan nobody believes. The Cascader walks it down one
    rung at a time until something lands at a horizon that can hold a calendar
    slot, and says honestly when it cannot.
    """

    goals: list[Goal] = Field(
        description="New goals, each with contributes_to set to the rung above it."
    )
    rationale: str = Field(description="Why this decomposition and not another.")
    clarifying_questions: list[str] = Field(
        default_factory=list,
        description="Ask rather than invent a plausible-sounding ladder. Empty when it was clear.",
    )


class AuditEntry(BaseModel):
    """One thing the system did. Written by the audit hook, never by an agent."""

    at: datetime
    run_id: str
    kind: Literal["node", "tool"]
    actor: str = Field(description="Node id or agent name.")
    action: str = Field(description="Tool name, or the node's phase.")
    payload: dict[str, str] = Field(default_factory=dict)
    is_write: bool = False
    failed: bool = False
