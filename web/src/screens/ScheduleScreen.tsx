/**
 * The days ahead, today first, and the difference between a plan and a guess.
 *
 * Every day carries two kinds of block. A placed block holds a slot in the
 * Living Graph. A proposed block is Python laying a route's own cadence --
 * "Tuesdays 19:00" -- over a day where nothing is placed for it, and nothing
 * books it. `BlockRow` draws that difference on the row, so this screen lists
 * the day's blocks in time order and does not sort the two apart: a suggestion
 * at 08:00 belongs before a meeting at 19:00, whatever it is.
 *
 * **What Second refused is on the page.** An empty Monday reads as "nothing to
 * do" when the truth is that the gym keeps failing at 18:00 and Second will not
 * put it back there. So each day lists the slots it did not suggest, with the
 * server's reason verbatim, and a route that could not be laid over any day at
 * all is listed once, at the end.
 *
 * **An empty day says only what the payload guarantees**, which is that nothing
 * is placed on it and nothing is suggested for it. It does not say why. A paused
 * goal's routes are left out of the payload without a word, and a route listed
 * at the end is one that could not be laid over any day, not necessarily one
 * whose cadence Second failed to read. So the sentence names no cause, and
 * points at a refusal on the day or the routes at the end when there are some.
 *
 * **Fixture mode takes a paused or retired goal's work off.** Live, pausing or
 * retiring drops the schedule and the server's next answer leaves that goal
 * out. The checked-in schedule cannot be asked again, so `withdrawFromSchedule`
 * removes that goal's blocks and refusals against the graph in the store, and
 * one sentence under the header says what came off and why.
 */

import { useEffect } from 'react'

import { BlockRow } from '../components/BlockRow'
import { Problem } from '../components/Problem'
import { Section } from '../components/Section'
import { USING_FIXTURES } from '../api/client'
import { dayMonth, longDate, weekday } from '../lib/datetime'
import { plural, takenOffLine, withdrawFromSchedule, type ScheduleWithdrawal } from '../lib/withdrawn'
import { useSecond } from '../store/useSecond'
import type { Schedule, ScheduleDay, SkippedProposal } from '../types/contract'
import styles from './ScheduleScreen.module.css'

type Relative = 'today' | 'tomorrow' | null

export function ScheduleScreen() {
  const loaded = useSecond((state) => state.schedule)
  const graph = useSecond((state) => state.graph)
  const error = useSecond((state) => state.errors.schedule)
  const loadSchedule = useSecond((state) => state.loadSchedule)

  // Read on arrival rather than at startup. Nulled by any write that moves the
  // graph, so coming back after a Daily run reads the days again.
  useEffect(() => {
    if (!loaded) void loadSchedule()
  }, [loaded, loadSchedule])

  if (error && !loaded) {
    return (
      <div className={styles.screen}>
        <Problem what={error} onRetry={() => void loadSchedule()} />
      </div>
    )
  }

  if (!loaded) {
    return (
      <div className={styles.screen}>
        <p className={styles.waiting}>Reading the days ahead.</p>
      </div>
    )
  }

  const withdrawn = USING_FIXTURES ? withdrawFromSchedule(loaded, graph) : null
  const schedule = withdrawn?.schedule ?? loaded
  const withdrawnSentence = withdrawn ? withdrawnLine(withdrawn) : null

  // Today is the schedule's own start, not the browser's clock: the fixture is
  // pinned to 2026-09-10, and the user's day is in the user's zone.
  const startsToday = schedule.days[0]?.on === schedule.start
  const relative = (index: number): Relative =>
    !startsToday ? null : index === 0 ? 'today' : index === 1 ? 'tomorrow' : null

  return (
    <div className={styles.screen}>
      <header className={styles.head}>
        <h1 className={styles.title}>Schedule</h1>
        <p className={styles.what}>
          {span(schedule)} Placed blocks hold a slot in your plan. Suggested blocks carry a route's
          own rhythm onto a day with nothing placed for it: they are not in your calendar, and
          nothing has booked them.
        </p>
        <p className={`tabular ${styles.tally}`}>{tally(schedule)}</p>
        {withdrawnSentence && <p className={styles.withdrawn}>{withdrawnSentence}</p>}
      </header>

      {error && <Problem what={error} onRetry={() => void loadSchedule()} />}

      <div className={styles.body}>
        {schedule.days.map((day, index) => (
          <Day
            key={day.on}
            day={day}
            relative={relative(index)}
            emptied={withdrawn?.emptied.has(day.on) ?? false}
            unlaid={schedule.skipped.length}
          />
        ))}

        {schedule.skipped.length > 0 && <Unlaid skipped={schedule.skipped} />}
      </div>
    </div>
  )
}

function Day({
  day,
  relative,
  emptied,
  unlaid,
}: {
  day: ScheduleDay
  relative: Relative
  emptied: boolean
  unlaid: number
}) {
  const placed = day.blocks.filter((block) => block.status === 'placed').length
  const suggested = day.blocks.length - placed

  const label = relative === 'today' ? 'Today' : relative === 'tomorrow' ? 'Tomorrow' : weekday(day.on)
  const date = relative ? longDate(day.on) : dayMonth(day.on)
  const split = [
    placed > 0 ? `${placed} placed` : null,
    suggested > 0 ? `${suggested} suggested` : null,
  ].filter(Boolean)

  return (
    <Section
      label={label}
      count={day.blocks.length}
      aside={split.length > 0 ? `${date} · ${split.join(' · ')}` : date}
    >
      {day.blocks.length > 0 ? (
        <ol className={styles.blocks}>
          {day.blocks.map((block) => (
            <BlockRow key={`${block.task_id}:${block.start}:${block.status}`} block={block} />
          ))}
        </ol>
      ) : (
        <p className={styles.nothing}>{emptyDay(day, relative, emptied, unlaid)}</p>
      )}

      {day.skipped.length > 0 && <Refused skipped={day.skipped} />}
    </Section>
  )
}

/** Why a day is empty, in words the payload guarantees. Never a cause the server did not send. */
function emptyDay(day: ScheduleDay, relative: Relative, emptied: boolean, unlaid: number): string {
  const when = relative ?? `on ${weekday(day.on)}`

  // Fixture mode only: this day held blocks, and every one was for a goal the
  // graph in the store now has paused or retired.
  if (emptied) {
    return `Nothing is left ${when}: every block here was for a goal that is now paused or retired.`
  }

  if (day.skipped.length > 0) {
    return `Nothing is placed ${when} and nothing is suggested. What a route wanted here, and why Second did not suggest it, is below.`
  }

  const end = unlaid > 0 ? ' The routes listed at the end are not on any day.' : ''
  return `Nothing is placed ${when}, and Second suggested nothing for it.${end}`
}

/** Slots a route's cadence asked for on this day, and why Second did not suggest them. */
function Refused({ skipped }: { skipped: SkippedProposal[] }) {
  return (
    <div className={styles.refused}>
      <p className="label">Not suggested</p>
      <ul className={styles.refusals}>
        {skipped.map((item, index) => (
          <li key={`${item.route_id}:${item.wanted}:${index}`} className={styles.refusal}>
            <span className={`tabular ${styles.wanted}`}>{item.wanted}</span>
            <span className={styles.route}>{item.route_title}</span>
            <p className={`evidence ${styles.reason}`}>{item.reason}</p>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Routes with no day to put a suggestion on: an unreadable cadence, a one-off, every task blocked. */
function Unlaid({ skipped }: { skipped: SkippedProposal[] }) {
  return (
    <Section label="Not laid over any day" count={skipped.length}>
      <p className={styles.nothing}>
        {skipped.length === 1 ? 'This route appears' : 'These routes appear'} on none of the days
        above. Second's reason is under each one.
      </p>
      <ul className={styles.refusals}>
        {skipped.map((item, index) => (
          <li key={`${item.route_id}:${index}`} className={styles.unlaid}>
            <p className={styles.route}>{item.route_title}</p>
            <p className={styles.cadence}>
              <span className="label">cadence</span>
              <span className="evidence">{item.wanted}</span>
            </p>
            <p className="evidence">{item.reason}</p>
          </li>
        ))}
      </ul>
    </Section>
  )
}

/** `Thursday 10 September and the 6 days after it.` */
function span(schedule: Schedule): string {
  const after = schedule.days.length - 1
  const first = longDate(schedule.start)
  if (after <= 0) return `${first}.`
  return `${first} and the ${after === 1 ? 'day' : `${after} days`} after it.`
}

/** Counts of what the payload holds. Arithmetic on the list, never on the calendar. */
function tally(schedule: Schedule): string {
  const blocks = schedule.days.flatMap((day) => day.blocks)
  const placed = blocks.filter((block) => block.status === 'placed').length
  const refused = schedule.days.reduce((sum, day) => sum + day.skipped.length, 0)

  const parts = [`${placed} placed`, `${blocks.length - placed} suggested`]
  if (refused > 0) parts.push(`${refused} not suggested`)
  if (schedule.skipped.length > 0) parts.push(`${schedule.skipped.length} not laid over any day`)
  return parts.join(' · ')
}

/** `8 blocks were taken off the schedule because “X” is retired.` Null when nothing came off. */
function withdrawnLine(withdrawn: ScheduleWithdrawal): string | null {
  const { blocks, refused, unlaid, goals } = withdrawn

  const parts = [
    blocks > 0 ? plural(blocks, 'block', 'blocks') : null,
    refused > 0 ? plural(refused, 'slot not suggested', 'slots not suggested') : null,
    unlaid > 0 ? plural(unlaid, 'route not laid over any day', 'routes not laid over any day') : null,
  ].filter((part): part is string => part !== null)

  return takenOffLine(parts, blocks + refused + unlaid, 'the schedule', goals)
}
