/**
 * What a run changed, so the Living Graph can show it.
 *
 * The product's central claim is that Second notices things and adapts the plan
 * on its own. A judge watching a recording can only believe that if the graph
 * visibly differs after a run -- so the screen diffs the graph it had against
 * the graph it just fetched and marks what moved.
 *
 * Compared by value rather than by version, deliberately. `LivingGraph.version`
 * increments on every write including ones that changed nothing, and a graph
 * that pulses all over after a no-op run teaches the viewer that the highlight
 * means nothing.
 */

import type { LivingGraph } from '../types/contract'

export interface GraphDiff {
  /** Goal, route and task ids whose own fields changed. */
  changed: Set<string>
  /** Ids that were not in the previous graph at all. */
  added: Set<string>
  /** Person-layer refs that gained a fact. */
  personFacts: string[]
  get any(): boolean
}

export function diffGraphs(before: LivingGraph | null, after: LivingGraph): GraphDiff {
  const changed = new Set<string>()
  const added = new Set<string>()

  const previous = before ? flatten(before) : new Map<string, string>()
  const current = flatten(after)

  for (const [id, signature] of current) {
    const was = previous.get(id)
    if (was === undefined) added.add(id)
    else if (was !== signature) changed.add(id)
  }

  const personFacts = before ? newPersonFacts(before, after) : []

  return {
    changed,
    added,
    personFacts,
    get any() {
      return changed.size > 0 || added.size > 0 || personFacts.length > 0
    },
  }
}

/** One comparable signature per entity. Only the fields a screen renders. */
function flatten(graph: LivingGraph): Map<string, string> {
  const out = new Map<string, string>()

  for (const goal of graph.goals) {
    out.set(goal.id, [goal.title, goal.horizon, goal.status, goal.contributes_to, goal.deadline].join('|'))

    for (const route of goal.routes) {
      out.set(route.id, [route.title, route.cadence, route.status].join('|'))

      for (const task of route.tasks) {
        out.set(
          task.id,
          [
            task.title,
            task.status,
            task.slip_count,
            task.known_blocker,
            task.resource_url,
            task.deadline,
            task.depends_on.join(','),
            task.scheduled_slots.join(','),
          ].join('|'),
        )
      }
    }
  }

  return out
}

function newPersonFacts(before: LivingGraph, after: LivingGraph): string[] {
  const facts: string[] = []
  const lists = ['honoured_slots', 'abandoned_slots', 'recurring_blockers', 'constraints'] as const

  for (const key of lists) {
    const was = new Set(before.person[key])
    for (const value of after.person[key]) if (!was.has(value)) facts.push(value)
  }

  for (const [key, value] of Object.entries(after.person.preferences)) {
    if (before.person.preferences[key] !== value) facts.push(`${key}: ${value}`)
  }

  const wasLinks = new Set(before.links.map(linkKey))
  for (const link of after.links) {
    if (!wasLinks.has(linkKey(link))) facts.push(link.note || link.to_ref)
  }

  return facts
}

function linkKey(link: LivingGraph['links'][number]): string {
  return `${link.kind}|${link.from_id}|${link.to_ref}`
}
