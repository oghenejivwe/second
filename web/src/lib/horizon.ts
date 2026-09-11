/**
 * How a horizon reads, ranks and behaves. One copy, because two screens show it.
 *
 * This started as duplicated tables in `livingGraph.ts` and `screens/Goals.tsx`,
 * with different words in each -- "a lifetime" in one place and "life" in the
 * other for the same rung. Harmless-looking and wrong: a reader flipping between
 * Goals and the Living Graph has to be able to tell that they are looking at the
 * same thing, and two spellings of one concept quietly says they are not.
 *
 * Short phrasings win because the Living Graph puts them on a 248px node, and
 * the wording that survives that constraint reads perfectly well in a list.
 */

import type { Goal } from '../types/contract'

export type Horizon = Goal['horizon']

/** In words. `year` is a field name; "this year" is what a person says. */
export const HORIZON_LABEL: Record<Horizon, string> = {
  life: 'life',
  decade: 'decade',
  three_year: 'three years',
  year: 'this year',
  quarter: 'this quarter',
  month: 'this month',
  week: 'this week',
  day: 'today',
}

/** Furthest out first. Orders roots, which may sit at any horizon. */
export const HORIZON_RANK: Record<Horizon, number> = {
  life: 0,
  decade: 1,
  three_year: 2,
  year: 3,
  quarter: 4,
  month: 5,
  week: 6,
  day: 7,
}

/**
 * Which band a goal is drawn in on the Living Graph.
 *
 * Coarser than the rank on purpose: eight rows for eight horizons would be
 * mostly empty space, and what the vertical axis has to communicate is "how far
 * out is this", not which of eight enum members was chosen.
 */
export const HORIZON_ROW: Record<Horizon, number> = {
  life: 0,
  decade: 1,
  three_year: 1,
  year: 2,
  quarter: 3,
  month: 3,
  week: 3,
  day: 3,
}

/**
 * Near enough to hold routes and tasks that go in a calendar.
 *
 * A year is the boundary, and `models.py` says why: "get comfortable speaking to
 * a room this year, at the club every Tuesday" needs no further decomposition to
 * be workable, while "build a billion-dollar company" cannot go in Tuesday's 9am
 * slot and a system that pretends otherwise produces a plan nobody believes.
 *
 * Mirrors `SCHEDULABLE_HORIZONS` in the contract. If that set moves, this is the
 * one place here that has to move with it.
 */
export const SCHEDULABLE_HORIZONS: ReadonlySet<Horizon> = new Set<Horizon>([
  'year',
  'quarter',
  'month',
  'week',
  'day',
])

export function isSchedulable(horizon: Horizon): boolean {
  return SCHEDULABLE_HORIZONS.has(horizon)
}
