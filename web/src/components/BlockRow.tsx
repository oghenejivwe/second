import { clockTime, duration } from '../lib/datetime'
import type { ScheduledBlock } from '../types/contract'
import styles from './BlockRow.module.css'

/**
 * One piece of work on the day, and what it is for.
 *
 * The `serves` line is the product in one row. A to-do list says "Record five
 * minutes". This says "Record five minutes, serving: speak to a room → raise a
 * Series A → build a company that outlives me" -- which answers *why this,
 * today?*, and no calendar app answers that.
 *
 * `goal_title` is the goal that owns the task; `serves` is the ladder above it,
 * nearest first. Together they are the whole chain, so the row builds it as
 * `[goal_title, ...serves]` rather than showing the two separately.
 *
 * The time is read off the string rather than parsed, via `clockTime`. These
 * are timezone-aware, so `Date` would work -- but it would render in the
 * *browser's* zone, and the browser is not necessarily where the user is.
 *
 * **A proposed block says so on the row itself.** `status: "proposed"` is
 * Python laying a route's own cadence over a day where nothing is placed for
 * it, and the contract says a proposal is never written anywhere. So the row
 * names it as Second's suggestion in words, sits on a dashed edge where a
 * placed block has none, and prints its `why` as evidence under the ladder. The
 * mark lives here rather than on the Schedule screen so that any screen reusing
 * the row cannot show a suggestion as booked by forgetting to.
 */
export function BlockRow({ block }: { block: ScheduledBlock }) {
  const chain = [block.goal_title, ...block.serves]
  const proposed = block.status === 'proposed'

  return (
    <li className={styles.block} data-status={block.status}>
      <time className={`tabular ${styles.time}`} dateTime={block.start}>
        {clockTime(block.start)}
      </time>

      <div className={styles.middle}>
        {proposed && <p className={styles.suggested}>Second's suggestion · not in your calendar</p>}

        <p className={styles.title}>{block.title}</p>

        <p className={styles.serves}>
          <span className={styles.servesLabel}>serving</span>
          {chain.map((title, index) => (
            <span key={`${title}:${index}`} className={styles.link}>
              {index > 0 && <span className={styles.arrow}>→</span>}
              {title}
            </span>
          ))}
        </p>

        {proposed && <p className={`evidence ${styles.why}`}>{block.why}</p>}

        {/* A proposal holds no slot, so "attached to the slot" would be false
          * on one. The material is the task's either way. */}
        {block.resource_url && (
          <a className={styles.resource} href={block.resource_url} target="_blank" rel="noreferrer">
            {proposed ? 'Material for this task' : 'Already attached to the slot'}
          </a>
        )}
      </div>

      {/* Only a placed block has a length worth printing. A proposal carries
        * the same fixed `duration_min` whatever the task is, so a five-minute
        * recording read "1h", and a number on the row is taken as a fact. */}
      {!proposed && (
        <span className={`tabular ${styles.duration}`}>{duration(block.duration_min)}</span>
      )}
    </li>
  )
}
