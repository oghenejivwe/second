/**
 * Turn a `LivingGraph` into something `@xyflow/react` can draw.
 *
 * Every render decision the Living Graph screen makes lives here rather than in
 * the components, because they are claims about the data and claims are worth
 * testing:
 *
 * * **Rows come from the horizon, not from graph depth.** A ladder can be four
 *   rungs deep ("speak to a room" under "raise a Series A" under "build a
 *   company that outlives me") or one rung ("be at my sister's wedding in
 *   Lagos"), so depth alone would put a life-shaped ambition and a month-shaped
 *   one on different rows for no reason a reader could see. Banding by horizon
 *   makes the vertical axis mean something: how far out this is.
 *
 * * **A child is always below its parent**, even when the data disagrees with
 *   its own horizons. `row = max(horizonRow, parentRow + 1)` -- because
 *   `contributes_to` is model-written and a goal pointing at a parent of the
 *   same horizon would otherwise draw a horizontal edge that reads as a
 *   sibling link.
 *
 * * **Slipped is `slip_count > 0`**, not a status. Nothing in the contract
 *   marks a task red; `status` is pending/done/blocked and a task can have
 *   slipped four times and still be pending. The slips are the fact.
 *
 * * **A dependency edge is highlighted when the upstream task is not done.**
 *   That is the blocking edge: `t-flights` cannot happen until `t-leave` does,
 *   and `t-leave` has no slot at all. Computed here, once, rather than inside
 *   the edge component, so the edge component stays a renderer.
 *
 * * **Person-layer facts sit at the edges of the graph as annotations on the
 *   node they are about.** They are context, not content, per the brief -- so
 *   they are not nodes competing for the reader's attention.
 */

import type { Goal, Link, LivingGraph, Route, Task } from '../types/contract'
import {
  HORIZON_LABEL,
  HORIZON_ROW,
  isSchedulable,
  type Horizon,
} from './horizon'
import { layoutForest, type TreeInput } from './layout'

export { HORIZON_LABEL, HORIZON_ROW }
export type { Horizon }

export type NodeKind = 'goal' | 'route' | 'task'

/** Set by the screen after a run, from the graph diff. Not read off the graph:
 * it is a fact about two graphs, so it cannot be derived from one. */
type Changeable = { changed?: boolean }

/** A person-layer fact, hung on the node it is about. */
export interface Annotation {
  kind: Link['kind']
  text: string
  note: string
  /** Whether this records something that held or something that was abandoned. */
  tone: 'held' | 'slipped' | 'neutral'
}

export type GoalNodeData = Changeable & {
  kind: 'goal'
  goal: Goal
  horizon: Horizon
  schedulable: boolean
  /** An active long-horizon goal with no children and no routes is a wish. */
  stalled: boolean
  /** Points at a parent that is not in the graph. A data bug, shown as one. */
  broken: boolean
  annotations: Annotation[]
}

export type RouteNodeData = Changeable & {
  kind: 'route'
  route: Route
  annotations: Annotation[]
}

export type TaskNodeData = Changeable & {
  kind: 'task'
  task: Task
  slipped: boolean
  /** The ids of unfinished tasks this one waits on. */
  blockedBy: string[]
  annotations: Annotation[]
}

export type SecondNodeData = GoalNodeData | RouteNodeData | TaskNodeData

export interface FlowNode {
  id: string
  type: NodeKind
  data: SecondNodeData
  position: { x: number; y: number }
}

export interface FlowEdge {
  id: string
  source: string
  target: string
  type: 'containment' | 'dependency'
  data: { blocked: boolean; label: string }
}

export interface FlowModel {
  nodes: FlowNode[]
  edges: FlowEdge[]
  /** Ids present in the graph but never placed -- a `contributes_to` cycle. */
  unplaced: string[]
}

const NODE_WIDTH: Record<NodeKind, number> = { goal: 248, route: 216, task: 208 }
const ROW_HEIGHT = 132

const ANNOTATION_GUTTER = 178
/** Space reserved to the right of a node that carries person-layer facts.

 * The annotations are absolutely positioned outside the node box, so the
 * browser does not measure them and the layout has no idea they are there.
 * Caught by looking at the screen: "Tue 19:00, attended every week" was
 * printed across the top of the task in the next column. Reserving the gutter
 * in the layout input is the fix -- 170px of annotation plus its 8px gap --
 * because the alternative, moving the facts inside the node, would make them
 * content, and the brief is right that they are context.
 */

const TONE: Partial<Record<Link['kind'], Annotation['tone']>> = {
  slot_honoured_for_task: 'held',
  slot_abandoned_for_task: 'slipped',
  blocker_recurs_for_goal: 'slipped',
}

/** A route is drawn when it is still in play. Rejected and dropped ones are not
 * deleted from the graph -- that is deliberate, the record of a rejected route
 * is useful -- but they are not part of the plan and do not belong in the tree. */
const LIVE_ROUTE_STATUSES: Route['status'][] = ['proposed', 'approved']

export function buildFlowModel(graph: LivingGraph): FlowModel {
  const goalIds = new Set(graph.goals.map((goal) => goal.id))
  const tasks = new Map<string, Task>()
  for (const goal of graph.goals) {
    for (const route of goal.routes) {
      for (const task of route.tasks) tasks.set(task.id, task)
    }
  }

  const annotations = annotationsByTarget(graph.links)
  const inputs: TreeInput<SecondNodeData>[] = []
  const horizonRow = new Map<string, number>()

  // Reserved width per node, which is the node plus its annotation gutter. The
  // layout centres nodes inside their reserved box, so positioning has to use
  // the same number or an annotated node drifts right by half a gutter.
  const reserved = new Map<string, number>()

  const reserve = (id: string, kind: NodeKind, facts: Annotation[]): number => {
    const width = NODE_WIDTH[kind] + (facts.length > 0 ? ANNOTATION_GUTTER : 0)
    reserved.set(id, width)
    return width
  }

  // Goals, deepest-horizon-last so a parent's row is known before its child's.
  for (const goal of sortedByLadder(graph.goals)) {
    const parentRow = goal.contributes_to ? horizonRow.get(goal.contributes_to) : undefined
    const row = Math.max(HORIZON_ROW[goal.horizon], parentRow === undefined ? 0 : parentRow + 1)
    horizonRow.set(goal.id, row)

    const schedulable = isSchedulable(goal.horizon)
    const goalFacts = annotations.get(goal.id) ?? []
    inputs.push({
      id: goal.id,
      parent: goal.contributes_to && goalIds.has(goal.contributes_to) ? goal.contributes_to : null,
      width: reserve(goal.id, 'goal', goalFacts),
      payload: {
        kind: 'goal',
        goal,
        horizon: goal.horizon,
        schedulable,
        stalled:
          goal.status === 'active' &&
          !schedulable &&
          !graph.goals.some((other) => other.contributes_to === goal.id) &&
          goal.routes.length === 0,
        broken: Boolean(goal.contributes_to) && !goalIds.has(goal.contributes_to as string),
        annotations: goalFacts,
      },
    })
  }

  const deepestGoalRow = Math.max(0, ...horizonRow.values())

  for (const goal of graph.goals) {
    for (const route of goal.routes) {
      if (!LIVE_ROUTE_STATUSES.includes(route.status)) continue
      const routeFacts = annotations.get(route.id) ?? []
      inputs.push({
        id: route.id,
        parent: goal.id,
        width: reserve(route.id, 'route', routeFacts),
        payload: { kind: 'route', route, annotations: routeFacts },
      })

      for (const task of route.tasks) {
        const blockedBy = task.depends_on.filter((id) => {
          const upstream = tasks.get(id)
          return !upstream || upstream.status !== 'done'
        })
        const taskFacts = annotations.get(task.id) ?? []
        inputs.push({
          id: task.id,
          parent: route.id,
          width: reserve(task.id, 'task', taskFacts),
          payload: {
            kind: 'task',
            task,
            slipped: task.slip_count > 0,
            blockedBy,
            annotations: taskFacts,
          },
        })
      }
    }
  }

  const { placed } = layoutForest(inputs, { rowHeight: ROW_HEIGHT, columnGap: 28 })
  const placedIds = new Set(placed.map((node) => node.id))

  const nodes: FlowNode[] = placed.map((node) => {
    // Goals keep their horizon band; routes and tasks hang below every goal, so
    // the two layers never interleave however deep a particular ladder went.
    const row =
      node.payload.kind === 'goal'
        ? (horizonRow.get(node.id) ?? 0)
        : deepestGoalRow + (node.payload.kind === 'route' ? 1 : 2)

    return {
      id: node.id,
      type: node.payload.kind,
      data: node.payload,
      // Left edge of the reserved box, so the gutter lands to the node's right
      // -- exactly where the annotations are drawn.
      position: { x: node.x - (reserved.get(node.id) ?? NODE_WIDTH[node.payload.kind]) / 2, y: row * ROW_HEIGHT },
    }
  })

  const edges: FlowEdge[] = []
  for (const goal of graph.goals) {
    if (goal.contributes_to && placedIds.has(goal.contributes_to) && placedIds.has(goal.id)) {
      edges.push(containment(goal.contributes_to, goal.id))
    }
    for (const route of goal.routes) {
      if (!placedIds.has(route.id)) continue
      edges.push(containment(goal.id, route.id))
      for (const task of route.tasks) {
        if (!placedIds.has(task.id)) continue
        edges.push(containment(route.id, task.id))

        for (const upstreamId of task.depends_on) {
          if (!placedIds.has(upstreamId)) continue
          const upstream = tasks.get(upstreamId)
          const blocked = !upstream || upstream.status !== 'done'
          edges.push({
            id: `dep:${upstreamId}->${task.id}`,
            source: upstreamId,
            target: task.id,
            type: 'dependency',
            data: {
              blocked,
              label: blocked ? 'waiting on this' : 'done',
            },
          })
        }
      }
    }
  }

  return {
    nodes,
    edges,
    unplaced: inputs.filter((node) => !placedIds.has(node.id)).map((node) => node.id),
  }
}

function containment(source: string, target: string): FlowEdge {
  return {
    id: `has:${source}->${target}`,
    source,
    target,
    type: 'containment',
    data: { blocked: false, label: '' },
  }
}

/** Goals ordered so that every parent precedes its children. */
function sortedByLadder(goals: Goal[]): Goal[] {
  const byId = new Map(goals.map((goal) => [goal.id, goal]))
  const depth = (goal: Goal): number => {
    let steps = 0
    let current: Goal | undefined = goal
    const seen = new Set<string>()
    while (current?.contributes_to && !seen.has(current.id)) {
      seen.add(current.id)
      current = byId.get(current.contributes_to)
      steps += 1
      if (steps > goals.length) break
    }
    return steps
  }
  return [...goals].sort((a, b) => depth(a) - depth(b))
}

function annotationsByTarget(links: Link[]): Map<string, Annotation[]> {
  const out = new Map<string, Annotation[]>()
  for (const link of links) {
    const annotation: Annotation = {
      kind: link.kind,
      text: link.to_ref,
      note: link.note,
      tone: TONE[link.kind] ?? 'neutral',
    }
    const existing = out.get(link.from_id)
    if (existing) existing.push(annotation)
    else out.set(link.from_id, [annotation])
  }
  return out
}
