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
 */
export function BlockRow({ block }: { block: ScheduledBlock }) {
  const chain = [block.goal_title, ...block.serves]

  return (
    <li className={styles.block}>
      <time className={`tabular ${styles.time}`} dateTime={block.start}>
        {clockTime(block.start)}
      </time>

      <div className={styles.middle}>
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

        {block.resource_url && (
          <a className={styles.resource} href={block.resource_url} target="_blank" rel="noreferrer">
            Already attached to the slot
          </a>
        )}
      </div>

      <span className={`tabular ${styles.duration}`}>{duration(block.duration_min)}</span>
    </li>
  )
}
