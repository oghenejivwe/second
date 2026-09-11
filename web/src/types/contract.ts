/* eslint-disable */
/**
 * GENERATED. Do not edit.
 *
 * Source: src/second/core/models.py, via pydantic's serialization-mode JSON
 * Schema. Regenerate with:
 *
 *   python web/scripts/make_fixtures.py && node web/scripts/gen-types.mjs
 *
 * Datetimes arrive as ISO 8601 strings. Two shapes, and the difference matters:
 * ScheduledBlock.start carries an offset, Task.scheduled_slots do not. See
 * src/lib/datetime.ts -- never compare one against the other directly.
 */

/**
 * One thing the system did. Written by the audit hook, never by an agent.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "AuditEntry".
 */
export interface AuditEntry {
  at: string
  run_id: string
  kind: 'node' | 'tool'
  /**
   * Node id or agent name.
   */
  actor: string
  /**
   * Tool name, or the node's phase.
   */
  action: string
  payload: {
    [k: string]: string
  }
  is_write: boolean
  failed: boolean
}
/**
 * A long-horizon ambition, cashed into goals that can actually be worked.
 *
 * "A billion-dollar company in fifteen years" is not a task and pretending
 * otherwise produces a plan nobody believes. The Cascader walks it down one
 * rung at a time until something lands at a horizon that can hold a calendar
 * slot, and says honestly when it cannot.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "CascadeResult".
 */
export interface CascadeResult {
  /**
   * New goals, each with contributes_to set to the rung above it.
   */
  goals: Goal[]
  /**
   * Why this decomposition and not another.
   */
  rationale: string
  /**
   * Ask rather than invent a plausible-sounding ladder. Empty when it was clear.
   */
  clarifying_questions: string[]
}
/**
 * Something the user said they want, at some distance from today.
 *
 * Goals form a ladder rather than a list. "A billion-dollar company in fifteen
 * years" is a real goal and it is not a task; it becomes a three-year goal,
 * which becomes this year's, which becomes something that occupies Tuesday
 * morning. ``contributes_to`` is that ladder, and it is what lets Second answer
 * the only question that matters on a Tuesday morning: *why this, today?*
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "Goal".
 */
export interface Goal {
  id: string
  title: string
  horizon: 'life' | 'decade' | 'three_year' | 'year' | 'quarter' | 'month' | 'week' | 'day'
  /**
   * The id of the longer-horizon goal this serves. None for a top-level ambition.
   */
  contributes_to: string | null
  deadline: string | null
  status: 'active' | 'paused' | 'retired'
  routes: Route[]
  /**
   * How sure the Extractor was that this is a real, distinct goal.
   */
  extraction_confidence: number
}
/**
 * One concrete way of reaching a goal. Proposed by Second, approved by the user.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "Route".
 */
export interface Route {
  id: string
  goal_id: string
  title: string
  /**
   * How often, in plain words. 'Weekly, Tuesday evenings'.
   */
  cadence: string
  /**
   * Why this route suits THIS person, citing a person-layer fact.
   */
  rationale: string
  status: 'proposed' | 'approved' | 'rejected' | 'dropped'
  tasks: Task[]
}
/**
 * A single concrete action inside a route.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "Task".
 */
export interface Task {
  id: string
  route_id: string
  title: string
  /**
   * Task ids that must be done first. An UNMET_DEPENDENCY diagnosis reads this.
   */
  depends_on: string[]
  deadline: string | null
  scheduled_slots: string[]
  slip_count: number
  slips: Slip[]
  status: 'pending' | 'done' | 'blocked'
  /**
   * Written from the user's own answer. Once set, never ask about this task again.
   */
  known_blocker: string | null
  /**
   * Material attached to this task's slot, so it is already there at 7am.
   */
  resource_url: string | null
}
/**
 * One occasion on which a task did not happen as planned.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "Slip".
 */
export interface Slip {
  on: string
  scheduled_for: string | null
  /**
   * Which agent recorded this slip.
   */
  noticed_by: string
  note: string
}
/**
 * The daily reconciliation. What actually happened, from the only source that knows.
 *
 * **This is not a notification.** It sits inside the brief the user is already
 * looking at, so it costs them nothing extra -- which is why it can be daily
 * without breaking the promise that Second stays quiet.
 *
 * Without it the system's picture drifts: slips get inferred that never
 * happened, honoured slots get recorded as abandoned, and every diagnosis
 * downstream is built on a guess.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "CheckIn".
 */
export interface CheckIn {
  /**
   * The day being reconciled, usually yesterday.
   */
  on: string
  items: CheckInItem[]
}
/**
 * One thing to confirm, arriving with the answer already filled in.
 *
 * Second does everything it can before asking. It knows what was scheduled, it
 * has looked for evidence, and it has formed a view. The user's job is one tap
 * to confirm or correct -- not to remember and report.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "CheckInItem".
 */
export interface CheckInItem {
  task_id: string
  title: string
  goal_title: string
  scheduled_for: string
  inferred: 'likely_done' | 'likely_missed' | 'unknown'
  /**
   * Why Second thinks so. Empty when it genuinely has nothing and is simply asking.
   */
  evidence: string
}
/**
 * The user's own answer about one task. Beats every inference.
 *
 * When this disagrees with the Observer, this wins and the inference is
 * discarded -- not averaged, not weighed. The person was there.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "CompletionReport".
 */
export interface CompletionReport {
  task_id: string
  did_it: boolean
  /**
   * Anything they said about why, in their words.
   */
  note: string
}
/**
 * What Second has for you today. The product's face.
 *
 * Assembled every day, whether or not anything needs you. **Existing is not
 * interrupting** -- ``notify`` is the separate, rarer decision about whether to
 * push. Silence means ``notify`` is false and ``decisions`` is empty, not that
 * the brief is missing.
 *
 * The order of the fields is the order of value: what you are doing, what has
 * already been done for you, what is slipping, what you forgot, and only then
 * what Second needs from you.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "DailyBrief".
 */
export interface DailyBrief {
  on: string
  /**
   * Today's schedule, in time order.
   */
  blocks: ScheduledBlock[]
  /**
   * Work carried to the last click while the user was elsewhere.
   */
  prepared: PreparedAction[]
  at_risk: Risk[]
  reminders: Reminder[]
  /**
   * Usually empty. Each one costs the user attention, so earn it.
   */
  decisions: Decision[]
  /**
   * Yesterday, pre-filled, awaiting confirmation. Does not trigger a notification.
   */
  check_in: CheckIn | null
  /**
   * Push this at the user. True only when a decision is needed or something was prepared.
   */
  notify: boolean
  /**
   * When notify is false, why. Recorded for the audit, never shown to the user.
   */
  silence_reason: string
}
/**
 * One piece of work occupying a real slot today, and what it is for.
 *
 * ``goal_title`` and ``serves`` are denormalised onto the block on purpose. The
 * day has to answer *why this, today?* without the reader following a chain of
 * ids, and "Draft the pitch — 45 min — serves: speak well → this year → the
 * decade" is the whole product in one line.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "ScheduledBlock".
 */
export interface ScheduledBlock {
  task_id: string
  goal_id: string
  goal_title: string
  horizon: 'life' | 'decade' | 'three_year' | 'year' | 'quarter' | 'month' | 'week' | 'day'
  /**
   * Titles of the longer-horizon goals above this one, nearest first.
   */
  serves: string[]
  title: string
  /**
   * Timezone-AWARE, in the user's own zone. Note the asymmetry, which is deliberate: Task.scheduled_slots are stored NAIVE because the Living Graph holds wall-clock time -- a plan is what the person reads off their own calendar, and storing it as UTC would move the plan when they travel. Anything crossing the API boundary is made aware by Clock.local() so a browser cannot guess wrong. Never compare a raw scheduled_slot against one of these without passing it through the clock first.
   */
  start: string
  duration_min: number
  /**
   * Material attached to the slot, so the thing to watch is already there.
   */
  resource_url: string | null
}
/**
 * Work carried up to the last click, and stopped there.
 *
 * Second never completes the irreversible step. A draft is created, never sent.
 * Options are assembled, never booked.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "PreparedAction".
 */
export interface PreparedAction {
  kind: 'email_draft' | 'options' | 'retrieved_fact' | 'calendar_change' | 'nothing'
  /**
   * What was prepared, in one line.
   */
  summary: string
  /**
   * The draft body, the compared options, the retrieved value.
   */
  detail: string
  /**
   * Gmail draft id, calendar event id.
   */
  external_ref: string | null
  /**
   * The single thing left for the user to do.
   */
  awaiting: string
}
/**
 * Something with a deadline that will not be met on the current plan.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "Risk".
 */
export interface Risk {
  task_id: string
  goal_id: string
  what: string
  deadline: string
  days_left: number
  /**
   * Why this is at risk. Cite the calendar or the graph.
   */
  evidence: string
}
/**
 * Something the user cares about and has probably forgotten.
 *
 * Not a nag and not a nudge. This exists because commitments get made in email
 * and then never reach a plan -- a reply promised, a form nobody filled in, a
 * booking that closes. Every one cites where it came from, and a reminder with
 * no evidence is a defect.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "Reminder".
 */
export interface Reminder {
  what: string
  evidence: string
  source: 'email' | 'calendar' | 'graph'
}
/**
 * The one kind of thing that is allowed to interrupt.
 *
 * Second reaches here only when it genuinely cannot proceed alone. Options are
 * included because a question with three researched answers costs five seconds
 * and a bare question costs a round trip.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "Decision".
 */
export interface Decision {
  question: string
  task_id: string | null
  evidence: string
  options: string[]
}
/**
 * Something that lost the competition for a slot, and why it lost.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "Deprioritised".
 */
export interface Deprioritised {
  task_id: string
  /**
   * The slot it wanted.
   */
  wanted: string
  /**
   * What took the slot instead.
   */
  lost_to: string
  /**
   * Deadline pressure, a person-layer constraint, or an honoured-slot record.
   */
  reason: string
}
/**
 * Why a task slipped, and whether Second can act on it alone.
 *
 * ``requires_user_decision`` routes the Daily Graph. It is a typed field read by
 * a conditional edge, not a prompt hoping for the best.
 *
 * **``evidence`` is nullable, and that is load-bearing.** Strands produces
 * structured output by *forcing* a tool call: if the model declines, it is
 * re-asked with the choice forced, and on that pass it cannot refuse. A required
 * non-nullable ``evidence`` field would therefore compel the model to write
 * *something* in it even when nothing in the calendar or inbox supports a cause
 * -- which is how a real quote ends up attached to a conclusion it does not
 * support. The rule this model is meant to encode, *no evidence no diagnosis*,
 * is precisely the rule forced tool choice removes. So the schema has to give
 * the model somewhere honest to land.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "Diagnosis".
 */
export interface Diagnosis {
  task_id: string
  blocker_type:
    | 'MISSING_INFORMATION'
    | 'UNDEFINED_SCOPE'
    | 'UNMET_DEPENDENCY'
    | 'CALENDAR_CONFLICT'
    | 'UNKNOWN'
  /**
   * Quote the calendar entry or the email this rests on. Leave null if nothing in the evidence supports a structural cause. Never invent or paraphrase a quote to fill this field.
   */
  evidence: string | null
  confidence: number
  proposed_action: string
  /**
   * True when Second genuinely cannot resolve this without the user.
   */
  requires_user_decision: boolean
}
/**
 * What the Extractor heard in a spoken brain dump.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "ExtractionResult".
 */
export interface ExtractionResult {
  /**
   * One per distinct thing the user wants. Shallow: no routes yet.
   */
  goals: Goal[]
  /**
   * Ask rather than guess. Empty when everything was clear.
   */
  clarifying_questions: string[]
}
/**
 * Everything the Interpreter took from one thing the user said.
 *
 * Covers both directions of the daily loop: ``completions`` is the user
 * reporting backwards on what actually happened, ``updates`` is everything else
 * -- a preference, a time that does not work, a route that is too much.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "FeedbackResult".
 */
export interface FeedbackResult {
  /**
   * Answers to the check-in. Ground truth; overrides what was inferred.
   */
  completions: CompletionReport[]
  updates: FeedbackUpdate[]
  /**
   * Things the user says they want to do today that are not yet in the plan.
   */
  intentions: string[]
  /**
   * At most one line back to the user. Often empty.
   */
  acknowledgement: string
}
/**
 * One typed change derived from something the user said back.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "FeedbackUpdate".
 */
export interface FeedbackUpdate {
  target: 'route' | 'task' | 'person_model'
  target_id: string | null
  /**
   * What to change, in terms the Adapter can act on.
   */
  change: string
  /**
   * Merged into PersonModel.preferences. This is how Second learns.
   */
  person_model_patch: {
    [k: string]: string
  }
}
/**
 * What pausing or retiring a goal actually did.
 *
 * ``freed`` is the point. Retiring a goal releases the calendar time its routes
 * were holding, and the Goals screen has to be able to show that concretely --
 * these slots, this many hours, no longer spoken for.
 *
 * It says *freed*, not *redistributed*, deliberately. The Scheduler has not run
 * again yet, so nothing has been reallocated. Claiming otherwise would have
 * Second describing a plan it has not made, which is the one thing this product
 * must never do. ``note`` says when the reallocation actually happens.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "GoalStatusChange".
 */
export interface GoalStatusChange {
  graph: LivingGraph
  /**
   * Upcoming slots the goal was holding, now released. Empty when it held none.
   */
  freed: ScheduledBlock[]
  freed_minutes: number
  /**
   * What becomes of the freed time, in plain words.
   */
  note: string
}
/**
 * One persistent structure per user. Written by every agent, read by every agent.
 *
 * ``version`` backs the conditional write that stops two nodes in the same run
 * clobbering each other. Read it, send it back with your update, and expect the
 * write to be rejected if it moved underneath you.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "LivingGraph".
 */
export interface LivingGraph {
  user_id: string
  goals: Goal[]
  person: PersonModel
  links: Link[]
  version: number
  updated_at: string | null
}
/**
 * Observed facts about how this person actually operates.
 *
 * Structural only. Every field here is something the system watched happen, or
 * something the user said outright. Nothing in this model is an inference about
 * motivation, discipline or mood, and no agent may write one.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "PersonModel".
 */
export interface PersonModel {
  /**
   * Stated or demonstrated, e.g. {"learning_mode": "video"}.
   */
  preferences: {
    [k: string]: string
  }
  /**
   * Hard rules the Scheduler must honour, e.g. "no work before 10am".
   */
  constraints: string[]
  /**
   * Time slots this person actually keeps, e.g. "Tue 07:00".
   */
  honoured_slots: string[]
  /**
   * Slots repeatedly scheduled and repeatedly missed.
   */
  abandoned_slots: string[]
  recurring_blockers: string[]
  /**
   * Already shown to the user. The Resource Finder never repeats one.
   */
  resources_served: string[]
}
/**
 * An edge between the goals layer and the person layer.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "Link".
 */
export interface Link {
  kind:
    | 'route_suits_preference'
    | 'resource_served_for_goal'
    | 'slot_honoured_for_task'
    | 'slot_abandoned_for_task'
    | 'blocker_recurs_for_goal'
  /**
   * Goals-layer id: a goal, route or task.
   */
  from_id: string
  /**
   * Person-layer reference: a preference key, slot or constraint.
   */
  to_ref: string
  note: string
}
/**
 * What one spoken brain dump produced.
 *
 * ``clarifying_questions`` being non-empty means the Intake graph stopped after
 * the Extractor on purpose: it was not clear enough what the user wanted to
 * justify putting anything in their calendar. ``schedule`` is ``None`` in that
 * case, and the caller asks rather than shows a plan.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "IntakeResult".
 */
export interface IntakeResult {
  graph: LivingGraph
  clarifying_questions: string[]
  /**
   * What the Scheduler placed and what it deprioritised, when it ran.
   */
  schedule: ScheduleDecision | null
}
/**
 * The Scheduler's verdict across ALL active goals at once.
 *
 * ``deprioritised`` is not optional output. A scheduler that only reports what
 * it placed is hiding the decision it actually made.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "ScheduleDecision".
 */
export interface ScheduleDecision {
  placed: Placement[]
  deprioritised: Deprioritised[]
  /**
   * How competition between goals was resolved.
   */
  rationale: string
}
/**
 * One task placed into a real calendar slot.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "Placement".
 */
export interface Placement {
  task_id: string
  start: string
  duration_min: number
  calendar_event_id: string | null
}
/**
 * What the Observer could work out about one scheduled slot.
 *
 * Inference only. The calendar can show an invite was declined and the inbox
 * can show a mail was never sent, but **nothing in either can tell you whether
 * somebody actually did the five-minute recording.** That is what the check-in
 * is for, and it is why ``outcome`` is allowed to be ``"unknown"`` rather than
 * being forced into a guess.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "Observation".
 */
export interface Observation {
  task_id: string
  scheduled_for: string
  outcome: 'honoured' | 'missed' | 'unknown'
  /**
   * Quote the calendar entry or the email. No evidence, no claim.
   */
  evidence: string
  source: 'calendar' | 'email' | 'none'
}
/**
 * The Observer's sanitised bundle. The only thing the Diagnostician sees.
 *
 * This is the context-isolation boundary made concrete: the Observer reads raw
 * calendar entries and raw email, and hands on **this** -- task ids, outcomes
 * and quoted evidence. Not inbox contents. The Diagnostician cannot reach
 * Gmail or Calendar itself, so this report is the whole of its world.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "ObservationReport".
 */
export interface ObservationReport {
  observations: Observation[]
  /**
   * Structural context not tied to one task, e.g. a standing meeting that moved.
   */
  notes: string
}
/**
 * Concrete routes proposed for goals that are near enough to work on.
 *
 * Shallow on purpose. The alternative was to carry whole ``Goal`` objects here,
 * which means a Goal->Route->Task schema at every hop and nothing persisted at
 * all if the Scheduler fails downstream. Instead the Cascader writes the goal
 * ladder to the graph as it goes, and this carries only what is new -- so a
 * scheduling failure costs the routes, not the ladder.
 *
 * This interface was referenced by `SecondContract`'s JSON-Schema
 * via the `definition` "RoutePlan".
 */
export interface RoutePlan {
  /**
   * Proposed routes, each already bound to a goal_id.
   */
  routes: Route[]
  /**
   * Why these routes suit THIS person, citing a person-layer fact.
   */
  rationale: string
  /**
   * Ask rather than invent a cadence the user will abandon in week two.
   */
  clarifying_questions: string[]
}
