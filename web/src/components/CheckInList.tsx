import { useState } from 'react'

import { api, errorLine } from '../api/client'
import { clockTime, longDate } from '../lib/datetime'
import { Section } from './Section'
import type { CheckIn, CheckInItem } from '../types/contract'
import styles from './CheckInList.module.css'

/**
 * Yesterday, reconciled. Confirmation, not data entry.
 *
 * Second can infer a great deal from a calendar and an inbox. It cannot infer
 * whether somebody actually did a five-minute recording, because nothing
 * anywhere records that -- and without asking, the picture drifts: slips get
 * invented and honoured slots get filed as abandoned.
 *
 * So it asks. But it does not ask blind: every row arrives with Second's own
 * guess and the evidence behind it, and the user's job is one tap to confirm or
 * correct rather than to remember and report.
 *
 * **The `unknown` row is the honest one and it looks different.** An empty
 * `evidence` is the contract saying Second genuinely has nothing -- not a
 * missing field. Dressing that row up to match the others would be the system
 * implying a view it does not hold.
 *
 * **This never notifies.** It rides inside a brief the user already opened,
 * which is exactly what lets it be daily without breaking the promise that
 * Second stays quiet.
 */
export function CheckInList({ checkIn }: { checkIn: CheckIn }) {
  const unknowns = checkIn.items.filter((item) => item.inferred === 'unknown').length
  const held = checkIn.items.length - unknowns

  return (
    <Section
      label="Yesterday"
      count={checkIn.items.length}
      aside={
        <>
          {longDate(checkIn.on)}
          {held > 0 && ` · a view on ${held} of ${checkIn.items.length}`}
        </>
      }
    >
      <ul className={styles.list}>
        {checkIn.items.map((item) => (
          <Row key={item.task_id} item={item} on={checkIn.on} />
        ))}
      </ul>
    </Section>
  )
}

const GUESS: Record<CheckInItem['inferred'], string> = {
  likely_done: 'likely done',
  likely_missed: 'likely missed',
  unknown: 'could not tell',
}

function Row({ item, on }: { item: CheckInItem; on: string }) {
  const [answer, setAnswer] = useState<boolean | null>(null)
  const [sending, setSending] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)

  /**
   * Answers go back through `/api/feedback` as text -- there is no typed
   * check-in route, by ruling. The task id is included in the sentence on
   * purpose: the Interpreter has to turn this into a typed `CompletionReport`
   * with a `task_id`, and giving it the id outright beats making it match on a
   * title that two goals could share.
   */
  const send = (didIt: boolean) => {
    setSending(true)
    setFailed(null)
    api
      .feedback(
        `Check-in for ${on}: "${item.title}" (${item.task_id}) — ` +
          (didIt ? 'yes, I did it.' : 'no, I did not do it.'),
      )
      .then(() => setAnswer(didIt))
      .catch((error: unknown) => setFailed(errorLine(error)))
      .finally(() => setSending(false))
  }

  const unknown = item.inferred === 'unknown'

  return (
    <li className={styles.row} data-answered={answer !== null} data-unknown={unknown}>
      <div className={styles.what}>
        <p className={styles.title}>{item.title}</p>
        <p className={styles.goal}>
          <time className="tabular" dateTime={item.scheduled_for}>
            {clockTime(item.scheduled_for)}
          </time>
          <span className={styles.dot}>·</span>
          {item.goal_title}
        </p>
      </div>

      <div className={styles.guess}>
        <span className={styles.guessLabel} data-inferred={item.inferred}>
          {GUESS[item.inferred]}
        </span>
        {item.evidence ? (
          <p className="evidence">{item.evidence}</p>
        ) : (
          <p className={styles.noEvidence}>No evidence either way.</p>
        )}
      </div>

      {answer === null ? (
        <div className={styles.answers}>
          <button
            type="button"
            className={styles.did}
            disabled={sending}
            onClick={() => send(true)}
            aria-label={`I did ${item.title}`}
          >
            did it
          </button>
          <button
            type="button"
            className={styles.didnt}
            disabled={sending}
            onClick={() => send(false)}
            aria-label={`I did not do ${item.title}`}
          >
            did not
          </button>
        </div>
      ) : (
        /* No tick, no colour change, no animation. The row records the answer
         * and stops asking. Confirming something is not an achievement. */
        <p className={styles.recorded}>{answer ? 'did it' : 'did not'}</p>
      )}

      {failed && <p className={styles.failed}>{failed}</p>}
    </li>
  )
}
