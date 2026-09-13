/**
 * Fixture mode only: take a paused or retired goal's work off a checked-in read.
 *
 * Live, pausing or retiring a goal drops `schedule` and `memory` from the store,
 * and the server answers the next read from a graph where that goal is no longer
 * active: `schedule.py` projects `graph.active_goals()` only, and `questions.py`
 * anchors a question only to an active goal. A checked-in schedule.json cannot
 * answer again, so without this the Schedule screen went on suggesting sessions
 * for a goal retired a moment earlier.
 *
 * What comes off is decided by one fact, the goal's status in the graph the store
 * holds, which the pause and retire fixtures wrote. The same rule the server
 * uses: a goal is out when its own status is not `active`. Nothing is matched on
 * titles, and anything whose goal cannot be found in the graph stays, because
 * removing it would be a guess.
 *
 * Every function returns what was removed alongside what was kept, so a screen
 * can say why its list is shorter instead of shortening it silently.
 */

import type {
  DailyBrief,
  Goal,
  HorizonQuestion,
  LivingGraph,
  MemoryItem,
  Schedule,
} from '../types/contract'

/** Goals in the graph whose status is not active, by id. Empty with no graph. */
function inactiveGoals(graph: LivingGraph | null): Map<string, Goal> {
  const out = new Map<string, Goal>()
  for (const goal of graph?.goals ?? []) if (goal.status !== 'active') out.set(goal.id, goal)
  return out
}

/** Route id to the id of the goal that owns it. A skipped proposal names a route, not a goal. */
function routeOwners(graph: LivingGraph | null): Map<string, string> {
  const out = new Map<string, string>()
  for (const goal of graph?.goals ?? []) for (const route of goal.routes) out.set(route.id, goal.id)
  return out
}

export interface ScheduleWithdrawal {
  schedule: Schedule
  /** The inactive goals something was taken off for, in graph order. */
  goals: Goal[]
  blocks: number
  /** Refusals on a day ("not suggested"). */
  refused: number
  /** Routes the schedule could not lay over any day. */
  unlaid: number
  /** Days that held blocks before and hold none now. */
  emptied: Set<string>
}

export function withdrawFromSchedule(schedule: Schedule, graph: LivingGraph | null): ScheduleWithdrawal {
  const inactive = inactiveGoals(graph)
  const owners = routeOwners(graph)
  const hit = new Set<string>()

  const out = (goalId: string | undefined): boolean => {
    if (goalId === undefined || !inactive.has(goalId)) return false
    hit.add(goalId)
    return true
  }

  let blocks = 0
  let refused = 0
  const emptied = new Set<string>()

  const days = schedule.days.map((day) => {
    const keptBlocks = day.blocks.filter((block) => !out(block.goal_id))
    const keptSkips = day.skipped.filter((item) => !out(owners.get(item.route_id)))
    blocks += day.blocks.length - keptBlocks.length
    refused += day.skipped.length - keptSkips.length
    if (day.blocks.length > 0 && keptBlocks.length === 0) emptied.add(day.on)
    return { ...day, blocks: keptBlocks, skipped: keptSkips }
  })

  const skipped = schedule.skipped.filter((item) => !out(owners.get(item.route_id)))

  return {
    schedule: { ...schedule, days, skipped },
    goals: (graph?.goals ?? []).filter((goal) => hit.has(goal.id)),
    blocks,
    refused,
    unlaid: schedule.skipped.length - skipped.length,
    emptied,
  }
}

/** Task id to the id of the goal that owns it, for an item that names a task and no goal. */
function taskOwners(graph: LivingGraph | null): Map<string, string> {
  const out = new Map<string, string>()
  for (const goal of graph?.goals ?? []) {
    for (const route of goal.routes) for (const task of route.tasks) out.set(task.id, goal.id)
  }
  return out
}

export interface MemoryWithdrawal {
  items: MemoryItem[]
  removed: MemoryItem[]
  /** The inactive goals those items belonged to, in graph order. */
  goals: Goal[]
}

/**
 * The graph source stamps `goal_id` and `task_id` on what it owns. An item is
 * out when its goal is inactive, or, with no goal id, when the task it names
 * sits under an inactive goal. A constraint or an email reminder carries
 * neither, belongs to no goal, and stays.
 */
export function withdrawFromMemory(items: MemoryItem[], graph: LivingGraph | null): MemoryWithdrawal {
  const inactive = inactiveGoals(graph)
  const owners = taskOwners(graph)

  const ownerOf = (item: MemoryItem): string | undefined =>
    item.goal_id ?? (item.task_id ? owners.get(item.task_id) : undefined)
  const isOut = (item: MemoryItem) => {
    const goalId = ownerOf(item)
    return goalId !== undefined && inactive.has(goalId)
  }

  const removed = items.filter(isOut)
  const hit = new Set(removed.map(ownerOf))

  return {
    items: items.filter((item) => !isOut(item)),
    removed,
    goals: (graph?.goals ?? []).filter((goal) => hit.has(goal.id)),
  }
}

export interface BriefWithdrawal {
  brief: DailyBrief
  /** The inactive goals something was taken off for, in graph order. */
  goals: Goal[]
  blocks: number
  atRisk: number
  prepared: number
  decisions: number
  /** Today held blocks before and holds none now. */
  emptied: boolean
}

/**
 * Today, by the same rule. A block and an item at risk carry their goal's id. A prepared action and
 * a decision carry at most a task id, so they go when that task sits under an inactive goal, and
 * stay when they name no task. A reminder names neither and stays, and so does the check-in, which
 * is a record of what was scheduled yesterday, when the goal was still active.
 *
 * `notify` is true only when a decision is needed or something was prepared, so it is worked out
 * again when either list gets shorter. Otherwise the line under the date would go on saying
 * something was prepared after the draft itself came off.
 */
export function withdrawFromBrief(brief: DailyBrief, graph: LivingGraph | null): BriefWithdrawal {
  const inactive = inactiveGoals(graph)
  const owners = taskOwners(graph)
  const hit = new Set<string>()

  const out = (goalId: string | undefined): boolean => {
    if (goalId === undefined || !inactive.has(goalId)) return false
    hit.add(goalId)
    return true
  }
  const ownerOf = (taskId: string | null): string | undefined =>
    taskId === null ? undefined : owners.get(taskId)

  const blocks = brief.blocks.filter((block) => !out(block.goal_id))
  const atRisk = brief.at_risk.filter((risk) => !out(risk.goal_id))
  const prepared = brief.prepared.filter((action) => !out(ownerOf(action.task_id)))
  const decisions = brief.decisions.filter((decision) => !out(ownerOf(decision.task_id)))

  const cut = {
    blocks: brief.blocks.length - blocks.length,
    atRisk: brief.at_risk.length - atRisk.length,
    prepared: brief.prepared.length - prepared.length,
    decisions: brief.decisions.length - decisions.length,
  }
  const promptsCut = cut.prepared > 0 || cut.decisions > 0

  return {
    brief: {
      ...brief,
      blocks,
      at_risk: atRisk,
      prepared,
      decisions,
      notify: promptsCut ? brief.notify && (prepared.length > 0 || decisions.length > 0) : brief.notify,
    },
    goals: (graph?.goals ?? []).filter((goal) => hit.has(goal.id)),
    ...cut,
    emptied: brief.blocks.length > 0 && blocks.length === 0,
  }
}

export interface QuestionWithdrawal {
  questions: HorizonQuestion[]
  removed: HorizonQuestion[]
  /** The inactive goals those questions were anchored to, in graph order. */
  goals: Goal[]
}

/** A general question has no anchor goal, so it always stays. */
export function withdrawQuestions(
  questions: HorizonQuestion[],
  graph: LivingGraph | null,
): QuestionWithdrawal {
  const inactive = inactiveGoals(graph)
  const isOut = (question: HorizonQuestion) =>
    question.anchor_goal_id !== null && inactive.has(question.anchor_goal_id)

  const removed = questions.filter(isOut)
  const anchors = new Set(removed.map((question) => question.anchor_goal_id))

  return {
    questions: questions.filter((question) => !isOut(question)),
    removed,
    goals: (graph?.goals ?? []).filter((goal) => anchors.has(goal.id)),
  }
}

/** `“A” is retired`, `“A” and “B” are paused`, `“A” is retired and “B” is paused`. */
export function whyWithdrawn(goals: Goal[]): string {
  const clauses = (['retired', 'paused'] as const)
    .map((status) => goals.filter((goal) => goal.status === status).map((goal) => `“${goal.title}”`))
    .map((titles, index) => {
      if (titles.length === 0) return null
      const status = index === 0 ? 'retired' : 'paused'
      return `${andList(titles)} ${titles.length === 1 ? 'is' : 'are'} ${status}`
    })
    .filter((clause): clause is string => clause !== null)
  return andList(clauses)
}

/**
 * `2 blocks and 1 decision were taken off Today because “A” is retired.` Null when nothing came off.
 *
 * One sentence for Today, Schedule and Memory, so the same retire cannot be worded three ways on
 * three screens. `parts` are the counted things, in the order the screen lists them.
 */
export function takenOffLine(parts: string[], total: number, from: string, goals: Goal[]): string | null {
  if (total === 0 || parts.length === 0) return null
  const counted = andList(parts)
  return `${counted.charAt(0).toUpperCase()}${counted.slice(1)} ${total === 1 ? 'was' : 'were'} taken off ${from} because ${whyWithdrawn(goals)}.`
}

/** `1 block`, `3 blocks`. */
export function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`
}

/** `a`, `a and b`, `a, b and c`. */
export function andList(items: string[]): string {
  if (items.length <= 1) return items.join('')
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}
