/**
 * The goal ladder, and the one place a goal can be taken out of the plan.
 *
 * **Goals are a ladder, not a list.** `contributes_to` is the rung above, and
 * the indent is the whole argument: "build a company that outlives me" is real
 * and it is not a task, so it sits above "raise a Series A", above "get
 * comfortable speaking to a room", above a Tuesday at 19:00. A flat list of
 * those four would say they are the same kind of thing, which is the mistake
 * every other planner makes.
 *
 * **Roots are whatever nothing sits above, at any horizon.** The seeded world
 * has two `life` roots and a `month` one -- "be at my sister's wedding in
 * Lisbon" needs no decade above it -- so the tree is built from the edges and
 * then ordered by horizon, never assumed.
 *
 * **Freed means freed.** Retiring a goal releases the calendar slots its routes
 * were holding and this screen shows them struck through, with the total. It
 * does not say where that time goes, because at that moment the Scheduler has
 * not run and Second does not know. `GoalStatusChange.note` says when it will,
 * and it is rendered verbatim. A schedule Second did not make is a schedule
 * Second cannot stand behind.
 */

import { useEffect, useMemo, useRef, useState, type RefObject } from 'react'

import { Problem } from '../components/Problem'
import { Section } from '../components/Section'
import { bySlot, clockTime, duration, freedTime, longDate, shortDate } from '../lib/datetime'
import { HORIZON_LABEL, HORIZON_RANK, isSchedulable } from '../lib/horizon'
import { useSecond } from '../store/useSecond'
import type { Goal, GoalStatusChange, Route, Task } from '../types/contract'
import styles from './Goals.module.css'

/** Below this, the Extractor was not sure this is a real, distinct goal, and
 * that is worth a line. Above it, printing the number on every row would turn
 * an honest caveat into a score. */
const CONFIDENCE_WORTH_SAYING = 0.75

interface Rung {
  goal: Goal
  children: Rung[]
  /** Active, above a year, nothing beneath it and no routes. models.py: a wish. */
  stalled: boolean
  /** `contributes_to` names a goal that is not in the graph. A data bug. */
  brokenParent: string | null
}

interface Ladder {
  roots: Rung[]
  /** Goals no root can reach -- a `contributes_to` cycle. Shown flat, not lost. */
  unplaced: Goal[]
}

/** The tabs a person plans from: the week, the month, the year, then everything
 * further out. Long term holds both the generic ambitions and the specific ones.
 * The whole ladder stays one tab away, because that is where a goal's place in
 * the chain is visible. */
type GoalTab = 'week' | 'month' | 'year' | 'long' | 'all'
const TABS: { id: GoalTab; label: string; horizons: Goal['horizon'][] }[] = [
  { id: 'week', label: 'This week', horizons: ['week', 'day'] },
  { id: 'month', label: 'This month', horizons: ['month', 'quarter'] },
  { id: 'year', label: 'This year', horizons: ['year'] },
  { id: 'long', label: 'Long term', horizons: ['three_year', 'decade', 'life'] },
  { id: 'all', label: 'Whole ladder', horizons: [] },
]

export function Goals() {
  const graph = useSecond((state) => state.graph)
  const loading = useSecond((state) => state.loading)
  const errors = useSecond((state) => state.errors)
  const loadGraph = useSecond((state) => state.loadGraph)
  const setGoalStatus = useSecond((state) => state.setGoalStatus)
  const lastStatusChange = useSecond((state) => state.lastStatusChange)
  const [tab, setTab] = useState<GoalTab>('week')

  // Which goal's request is in flight. `loading.status` is one flag for the
  // whole store, so the id is what keeps a pause on one goal from greying out
  // the buttons on every other row.
  const [busyId, setBusyId] = useState<string | null>(null)
  // The goal whose Retire button is armed. At most one, so one ref is enough.
  const [armedId, setArmedId] = useState<string | null>(null)
  const armedRef = useRef<HTMLButtonElement | null>(null)
  // Dismissal lives in the store, not here. It was local state, and App.tsx
  // unmounts this screen on navigation -- so dismissing the band, going to
  // Today and coming back resurrected it for a change made minutes ago.
  const clearStatusChange = useSecond((state) => state.clearStatusChange)

  const ladder = useMemo(() => buildLadder(graph?.goals ?? []), [graph?.goals])

  useEffect(() => {
    if (!armedId) return

    // An armed destructive button that stays armed after the user's attention
    // has moved is a button that retires the wrong goal. Escape and a press
    // anywhere else disarm it; a press on the armed button itself is the
    // confirmation and must survive to its own click handler.
    const disarm = (event: Event) => {
      const target = event.target
      if (target instanceof Node && armedRef.current?.contains(target)) return
      setArmedId(null)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setArmedId(null)
    }

    document.addEventListener('pointerdown', disarm)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', disarm)
      document.removeEventListener('keydown', onKey)
    }
  }, [armedId])

  const apply = async (goalId: string, status: Goal['status']) => {
    setArmedId(null)
    setBusyId(goalId)
    try {
      await setGoalStatus(goalId, status)
    } finally {
      setBusyId(null)
    }
  }

  const controls: Controls = {
    busyId: loading.status ? busyId : null,
    armedId,
    armedRef,
    onPause: (goal) => void apply(goal.id, 'paused'),
    onReactivate: (goal) => void apply(goal.id, 'active'),
    onRetire: (goal) => {
      // Second click confirms. The first only arms, so a mis-aimed click costs
      // nothing and the label says what the next one does.
      if (armedId === goal.id) void apply(goal.id, 'retired')
      else setArmedId(goal.id)
    },
  }

  const change = lastStatusChange
  const stalledCount = countStalled(ladder)

  return (
    <div className={styles.screen}>
      <header className={styles.head}>
        <h1 className={styles.title}>Goals</h1>
        {graph && <p className={`${styles.counts} tabular`}>{tally(graph.goals)}</p>}
      </header>

      {/* The store writes a failed status change to `errors.graph` too, so this
       * one line covers both the read and the write. Retrying re-reads the
       * graph, which is the honest recovery: it says what is actually there. */}
      {errors.graph && <Problem what={errors.graph} onRetry={loadGraph} />}

      <FreedRegion change={change} onDismiss={clearStatusChange} />

      {!graph ? (
        !errors.graph && (
          <p className={styles.absent}>{loading.graph ? 'Reading the graph.' : 'No graph read.'}</p>
        )
      ) : (
        <>
          <div className={styles.tabs} role="tablist" aria-label="Goal horizons">
            {TABS.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={tab === item.id}
                className={styles.tab}
                onClick={() => setTab(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>

          {tab === 'all' ? (
          <Section
            label="Ladder"
            count={graph.goals.length - ladder.unplaced.length}
            aside={
              stalledCount > 0 ? (
                <span className="tabular">
                  {stalledCount} with nothing under {stalledCount === 1 ? 'it' : 'them'}
                </span>
              ) : undefined
            }
          >
            {ladder.roots.length === 0 ? (
              <p className={styles.absent}>No goals in the graph.</p>
            ) : (
              <ul className={styles.ladder}>
                {ladder.roots.map((rung) => (
                  <RungRow key={rung.goal.id} rung={rung} controls={controls} />
                ))}
              </ul>
            )}
          </Section>
          ) : (
            (() => {
              const current = TABS.find((item) => item.id === tab) ?? TABS[0]
              const picked = graph.goals.filter((goal) => current.horizons.includes(goal.horizon))
              return (
                <Section label={current.label} count={picked.length}>
                  {picked.length === 0 ? (
                    <p className={styles.absent}>
                      Nothing set for {current.label.toLowerCase()} yet. Say it on Record, or answer
                      the question on Memory, and it lands here.
                    </p>
                  ) : (
                    <ul className={styles.ladder}>
                      {picked.map((goal) => (
                        <RungRow
                          key={goal.id}
                          rung={{ goal, children: [], stalled: false, brokenParent: null }}
                          controls={controls}
                        />
                      ))}
                    </ul>
                  )}
                </Section>
              )
            })()
          )}

          {ladder.unplaced.length > 0 && (
            <Section label="Not in the ladder" count={ladder.unplaced.length}>
              <p className={styles.absent}>
                contributes_to loops back on itself for these, so no rung can hold them.
              </p>
              <ul className={styles.ladder}>
                {ladder.unplaced.map((goal) => (
                  <RungRow
                    key={goal.id}
                    rung={{ goal, children: [], stalled: false, brokenParent: null }}
                    controls={controls}
                  />
                ))}
              </ul>
            </Section>
          )}
        </>
      )}
    </div>
  )
}

interface Controls {
  busyId: string | null
  armedId: string | null
  armedRef: RefObject<HTMLButtonElement | null>
  onPause: (goal: Goal) => void
  onRetire: (goal: Goal) => void
  onReactivate: (goal: Goal) => void
}

/** One goal, its routes, and the rungs below it. Recursive, because the ladder
 * is: the indent is the only thing on the page saying which serves which. */
function RungRow({ rung, controls }: { rung: Rung; controls: Controls }) {
  const { goal } = rung
  // `data-status` belongs on the rung, not on the goal's own row: `.goalRow` is
  // a sibling of `.routes` and `.children`, so a retired goal's routes and
  // tasks were rendering at exactly an active goal's weight.
  const live = goal.status === 'active'

  return (
    <li className={styles.rung} data-status={goal.status}>
      <div className={styles.goalRow}>
        <div className={styles.goalMain}>
          <span className={styles.goalTitle}>{goal.title}</span>
          <p className={styles.meta}>
            <span>{HORIZON_LABEL[goal.horizon]}</span>
            <span>{goal.status}</span>
            {goal.deadline && <span className="tabular">by {withYear(goal.deadline)}</span>}
            {goal.extraction_confidence < CONFIDENCE_WORTH_SAYING && (
              <span className="tabular">
                heard with {Math.round(goal.extraction_confidence * 100)}% confidence
              </span>
            )}
          </p>
          {rung.stalled && (
            <p className={styles.annotation}>
              Nothing beneath it and no routes, so nothing to work on.
            </p>
          )}
          {rung.brokenParent && (
            <p className={styles.annotation}>
              Serves <span className="evidence">{rung.brokenParent}</span>, which is not in the
              graph.
            </p>
          )}
        </div>
        <GoalControls goal={goal} controls={controls} />
      </div>

      {goal.routes.length > 0 && (
        <ul className={styles.routes}>
          {goal.routes.map((route) => (
            <RouteRow key={route.id} route={route} live={live} />
          ))}
        </ul>
      )}

      {rung.children.length > 0 && (
        <ul className={styles.children}>
          {rung.children.map((child) => (
            <RungRow key={child.goal.id} rung={child} controls={controls} />
          ))}
        </ul>
      )}
    </li>
  )
}

function GoalControls({ goal, controls }: { goal: Goal; controls: Controls }) {
  const busy = controls.busyId === goal.id
  const armed = controls.armedId === goal.id

  if (goal.status !== 'active') {
    return (
      <div className={styles.controls}>
        <button
          type="button"
          className={styles.action}
          disabled={busy}
          onClick={() => controls.onReactivate(goal)}
        >
          Reactivate<span className="visually-hidden"> {goal.title}</span>
        </button>
      </div>
    )
  }

  return (
    <div className={styles.controls}>
      <button
        type="button"
        className={styles.action}
        disabled={busy}
        onClick={() => controls.onPause(goal)}
      >
        Pause<span className="visually-hidden"> {goal.title}</span>
      </button>
      {/* `aria-pressed` because armed is a held state, not a second button: a
       * screen reader has to be able to tell that the next press retires. */}
      <button
        type="button"
        className={styles.action}
        data-armed={armed || undefined}
        aria-pressed={armed}
        disabled={busy}
        ref={armed ? controls.armedRef : undefined}
        onClick={() => controls.onRetire(goal)}
      >
        {armed ? 'Retire · confirm' : 'Retire'}
        <span className="visually-hidden"> {goal.title}</span>
      </button>
    </div>
  )
}

function RouteRow({ route, live }: { route: Route; live: boolean }) {
  return (
    <li className={styles.route}>
      <p className={styles.routeHead}>
        <span className={styles.routeTitle}>{route.title}</span>
        <span className={styles.cadence}>{route.cadence}</span>
        {/* Approved is the norm and printing it on every row is noise. The
         * others change what the row means, so they are said. */}
        {route.status !== 'approved' && <span>{route.status}</span>}
      </p>

      {/* Second explaining why this route suits THIS person, citing something
       * from the person layer. Mono, because it rests on an observed fact. */}
      {route.rationale && <p className={`evidence ${styles.rationale}`}>{route.rationale}</p>}

      {route.tasks.length > 0 && (
        <ul className={styles.tasks}>
          {route.tasks.map((task) => (
            <TaskRow key={task.id} task={task} live={live} />
          ))}
        </ul>
      )}
    </li>
  )
}

/**
 * One task, and the slots it holds.
 *
 * `live` is false when the goal above it is paused or retired, and the slot
 * range is then struck through rather than printed plainly. Without it the
 * screen contradicted itself within three rows: the Freed band said "3 slots,
 * no longer spoken for" while the tasks below went on advertising the same
 * 10-11 September slots as if the calendar still held them. Struck through is
 * the honest rendering -- those occurrences were real, and they are released.
 */
function TaskRow({ task, live }: { task: Task; live: boolean }) {
  return (
    <li className={styles.task}>
      <p className={styles.taskHead}>
        <span className={styles.taskTitle}>{task.title}</span>
        <span className={`${styles.slots} tabular`} data-released={!live}>
          {slotWords(task.scheduled_slots)}
        </span>
        {task.deadline && <span className="tabular">by {withYear(task.deadline)}</span>}
        {task.status !== 'pending' && <span>{task.status}</span>}
        {/* A task can have slipped four times and still be pending, so the slip
         * count is the fact and `status` is not. The one hue tokens.css allows
         * for it, and no adjective. */}
        {task.slip_count > 0 && (
          <span className={`${styles.slips} tabular`}>
            {task.slip_count} {task.slip_count === 1 ? 'slip' : 'slips'}
          </span>
        )}
      </p>
      {task.known_blocker && (
        <p className={styles.blocker}>
          known blocker <span className="evidence">{task.known_blocker}</span>
        </p>
      )}
    </li>
  )
}

/**
 * What the last pause or retire released.
 *
 * The slots are struck through because they are still the same slots -- the
 * calendar had them, and now nothing does. `note` is printed verbatim and
 * nothing here adds to it: the wording is deliberate, the Scheduler has not run
 * at this moment, and no line on this screen may imply the time has already
 * gone somewhere.
 */
/**
 * The live region, mounted always so that it can announce.
 *
 * A `role="status"` inserted together with its own text announces nothing --
 * screen readers need the region in the accessible tree before its contents
 * change. The band was rendered only when a change existed, so the freed time
 * and the note never reached anyone using one. The wrapper is permanent and
 * empty until there is something to say; the inner `role` is gone, because
 * nesting two live regions announces twice or not at all depending on the
 * reader.
 */
function FreedRegion({
  change,
  onDismiss,
}: {
  change: GoalStatusChange | null
  onDismiss: () => void
}) {
  return (
    <div role="status" aria-live="polite">
      {change && <Freed change={change} onDismiss={onDismiss} />}
    </div>
  )
}

function Freed({ change, onDismiss }: { change: GoalStatusChange; onDismiss: () => void }) {
  const held = change.freed.length > 0

  return (
    <Section label={held ? 'Freed' : 'Last status change'}>
      <div className={styles.freedBand}>
        <div className={styles.freedBody}>
          {held && (
            <>
              <ul className={styles.freedList}>
                {change.freed.map((block) => (
                  <li key={`${block.task_id}-${block.start}`}>
                    <p className={styles.freedSlot}>
                      <time className={`${styles.freedWhen} tabular`} dateTime={block.start}>
                        {longDate(block.start)}, {clockTime(block.start)}
                      </time>
                      <span className={`${styles.freedFor} tabular`}>
                        {duration(block.duration_min)}
                      </span>
                      <span className={styles.freedTitle}>{block.title}</span>
                    </p>
                    {/* The ladder the slot was climbing, nearest first: why the
                     * slot existed, and what stops being worked on. */}
                    <p className={styles.serves}>
                      serving {[block.goal_title, ...block.serves].join(' → ')}
                    </p>
                  </li>
                ))}
              </ul>
              <p className={styles.total}>
                <span className="tabular">
                  {freedTime(change.freed.length, change.freed_minutes)}
                </span>
                , no longer spoken for.
              </p>
            </>
          )}

          <p className={styles.note}>{change.note}</p>
        </div>

        <button type="button" className={styles.dismiss} onClick={onDismiss}>
          Dismiss
        </button>
      </div>
    </Section>
  )
}

// ---------------------------------------------------------------------------

/**
 * Build the nesting from `contributes_to`. `graph.goals` is flat.
 *
 * Two failure directions, both resolved the same way -- show the goal somewhere
 * rather than drop it:
 *
 * * A parent that is not in the graph makes its child a root and says so.
 *   models.py calls that a broken link and keeps it apart from a stalled
 *   ambition, because one is a bug and the other is work not yet done.
 * * A cycle cannot be drawn as a tree at all. Nothing in a cycle is reachable
 *   from a root, so it falls out as `unplaced` and is listed flat. A short
 *   chain beats a hung screen.
 */
function buildLadder(goals: Goal[]): Ladder {
  const byId = new Map(goals.map((goal) => [goal.id, goal]))
  const order = new Map(goals.map((goal, index) => [goal.id, index]))
  const childrenOf = new Map<string, Goal[]>()
  const roots: Goal[] = []

  for (const goal of goals) {
    const parentId = goal.contributes_to
    if (!parentId || !byId.has(parentId)) {
      roots.push(goal)
      continue
    }
    const siblings = childrenOf.get(parentId)
    if (siblings) siblings.push(goal)
    else childrenOf.set(parentId, [goal])
  }

  // Furthest horizon first, then the order the graph gave them. Roots sit at
  // different horizons, so without this a `month` root can land above a `life`
  // one and the vertical axis stops meaning "how far out".
  const inLadderOrder = (list: Goal[]): Goal[] =>
    [...list].sort(
      (a, b) =>
        HORIZON_RANK[a.horizon] - HORIZON_RANK[b.horizon] ||
        (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0),
    )

  const seen = new Set<string>()
  const grow = (goal: Goal): Rung => {
    seen.add(goal.id)
    const children = inLadderOrder(childrenOf.get(goal.id) ?? []).filter(
      (child) => !seen.has(child.id),
    )
    const parentId = goal.contributes_to

    return {
      goal,
      children: children.map(grow),
      // `childrenOf` counts children at every status, which is what
      // models.py's `children_of` does: a goal whose only child was retired
      // yesterday is a broken plan, not a wish, and saying otherwise would
      // put the Cascader's label on the wrong row.
      stalled:
        goal.status === 'active' &&
        !isSchedulable(goal.horizon) &&
        !childrenOf.has(goal.id) &&
        goal.routes.length === 0,
      brokenParent: parentId && !byId.has(parentId) ? parentId : null,
    }
  }

  const placed = inLadderOrder(roots).map(grow)

  return { roots: placed, unplaced: goals.filter((goal) => !seen.has(goal.id)) }
}

function countStalled(ladder: Ladder): number {
  const walk = (rungs: Rung[]): number =>
    rungs.reduce((total, rung) => total + (rung.stalled ? 1 : 0) + walk(rung.children), 0)
  return walk(ladder.roots)
}

/** `3 active · 1 paused · 1 retired`. Zero of something is not worth a word. */
function tally(goals: Goal[]): string {
  const counts: Goal['status'][] = ['active', 'paused', 'retired']
  return (
    counts
      .map((status) => ({ status, n: goals.filter((goal) => goal.status === status).length }))
      .filter((part) => part.n > 0)
      .map((part) => `${part.n} ${part.status}`)
      .join(' · ') || 'none'
  )
}

/** `6 Sep 2041`. The year is not optional here: a deadline fifteen years out is
 * the whole point of a `life` goal, and `shortDate` alone would print it as a
 * day in September. Read off the string, never through `Date`. */
function withYear(iso: string): string {
  return `${shortDate(iso)} ${iso.slice(0, 4)}`
}

/**
 * What the calendar holds for this task.
 *
 * A range rather than "next up". `scheduled_slots` are NAIVE wall-clock
 * strings, and deciding which one is next means comparing them against a clock
 * -- the browser's, which is not necessarily the user's. datetime.ts refuses
 * that conversion and so does this: the first and last slot are read off the
 * characters, and nothing can shift an hour.
 */
function slotWords(slots: string[]): string {
  if (slots.length === 0) return 'no slot'

  const ordered = [...slots].sort(bySlot)
  const first = ordered[0]
  const last = ordered[ordered.length - 1]

  if (ordered.length === 1) return `${shortDate(first)} ${clockTime(first)}`
  return `${ordered.length} slots · ${shortDate(first)} – ${shortDate(last)}`
}
