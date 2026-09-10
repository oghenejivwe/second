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

from pydantic import BaseModel, Field

TaskStatus = Literal["pending", "done", "blocked"]
RouteStatus = Literal["proposed", "approved", "rejected", "dropped"]
GoalStatus = Literal["active", "paused", "retired"]
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
    """Something the user said they want."""

    id: str
    title: str
    deadline: date | None = None
    status: GoalStatus = "active"
    routes: list[Route] = Field(default_factory=list)
    extraction_confidence: float = Field(
        default=1.0,
        description="How sure the Extractor was that this is a real, distinct goal.",
    )


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
    """

    task_id: str
    blocker_type: BlockerType
    evidence: str = Field(description="Quote the calendar entry or the email. No evidence, no diagnosis.")
    confidence: float = Field(ge=0.0, le=1.0)
    proposed_action: str
    requires_user_decision: bool = Field(
        description="True when Second genuinely cannot resolve this without the user."
    )


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
    """Everything the Interpreter took from one piece of feedback."""

    updates: list[FeedbackUpdate] = Field(default_factory=list)
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


class TodayCard(BaseModel):
    """At most one of these per day. Often there is none, and that is correct."""

    task_id: str | None = None
    headline: str
    evidence: str = Field(description="Why Second is saying anything at all.")
    question: str | None = Field(default=None, description="Set only when a decision is genuinely needed.")
    prepared: PreparedAction | None = None


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
