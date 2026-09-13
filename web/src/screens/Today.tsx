import { useState } from 'react'

import { AuditPanel } from '../components/AuditPanel'
import { BlockRow } from '../components/BlockRow'
import { CheckInList } from '../components/CheckInList'
import { Problem } from '../components/Problem'
import { Section } from '../components/Section'
import { USING_FIXTURES, api, errorLine, type FixtureState } from '../api/client'
import { duration, longDate } from '../lib/datetime'
import { useSecond } from '../store/useSecond'
import type { DailyBrief } from '../types/contract'
import styles from './Today.module.css'

/**
 * The day. It always exists.
 *
 * The old contract was "at most one card, often none". The new one is a brief
 * every day, and the tension with "silence is a feature" is resolved by
 * separating content from interruption: **the brief is a plan, not an
 * interruption.** What stays rare is `notify` and `decisions`.
 *
 * So the quiet state is not an empty screen. It is a fully planned day with one
 * line above it saying nothing needs you -- which is a better thing to look at
 * than an empty state, and a better thing to demonstrate.
 *
 * **Section order comes from the contract, not from urgency**, and models.py is
 * explicit that the field order is the order of value: what you are doing, what
 * has already been done for you, what is slipping, what you forgot, and only
 * then what Second needs from you. A decision sits last on purpose. The line at
 * the top says whether there is one, so nothing is buried; but the day leads,
 * because the day is the product.
 *
 * `silence_reason` is deliberately NOT rendered here. The contract says twice
 * that it is for the audit log and never shown to the user, and an earlier
 * brief addendum that said otherwise was withdrawn. It appears in the audit
 * panel, where it belongs.
 */
export function Today() {
  const brief = useSecond((state) => state.brief)
  const loading = useSecond((state) => state.loading)
  const errors = useSecond((state) => state.errors)
  const loadBrief = useSecond((state) => state.loadBrief)
  const runDaily = useSecond((state) => state.runDaily)
  const showBrief = useSecond((state) => state.showBrief)
  const fixtureState = useSecond((state) => state.fixtureState)

  const [auditOpen, setAuditOpen] = useState(false)

  if (errors.brief && !brief) {
    return (
      <div className={styles.screen}>
        <Problem what={errors.brief} onRetry={loadBrief} />
      </div>
    )
  }

  if (!brief) {
    return (
      <div className={styles.screen}>
        <p className={styles.waiting}>{loading.brief ? 'Reading today.' : 'No day loaded.'}</p>
      </div>
    )
  }

  const quiet = !brief.notify && brief.decisions.length === 0

  return (
    <div className={styles.screen}>
      <header className={styles.head}>
        <div>
          <h1 className={styles.date}>{longDate(brief.on)}</h1>
          <Standing brief={brief} quiet={quiet} />
        </div>

        <div className={styles.actions}>
          <button
            type="button"
            className={styles.run}
            onClick={() => void runDaily()}
            disabled={loading.run}
          >
            {loading.run ? 'Running the day' : 'Run the day'}
          </button>
          <button
            type="button"
            className={styles.ghost}
            aria-pressed={auditOpen}
            onClick={() => setAuditOpen((open) => !open)}
          >
            Audit
          </button>
        </div>
      </header>

      {errors.run && <Problem what={errors.run} onRetry={() => void runDaily()} />}

      {loading.run && (
        <p className={styles.working}>
          Observing yesterday, diagnosing what slipped, adapting the plan. Tens of seconds.
        </p>
      )}

      <div className={styles.body}>
        <Section
          label="Today"
          count={brief.blocks.length}
          aside={brief.blocks.length > 0 ? totalTime(brief) : undefined}
        >
          {brief.blocks.length === 0 ? (
            <p className={styles.nothing}>Nothing is scheduled today.</p>
          ) : (
            <ol className={styles.blocks}>
              {brief.blocks.map((block) => (
                <BlockRow key={`${block.task_id}:${block.start}`} block={block} />
              ))}
            </ol>
          )}
        </Section>

        {brief.prepared.length > 0 && (
          <Section label="Already done for you" count={brief.prepared.length}>
            <ul className={styles.prepared}>
              {brief.prepared.map((action, index) => (
                <li key={`${action.kind}:${index}`} className={styles.preparedItem}>
                  <p className={styles.preparedSummary}>{action.summary}</p>
                  {action.detail && <pre className={`evidence ${styles.draft}`}>{action.detail}</pre>}
                  <p className={styles.awaiting}>
                    <span className="label">Left for you</span>
                    {action.awaiting}
                  </p>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {brief.at_risk.length > 0 && (
          <Section label="At risk" count={brief.at_risk.length}>
            <ul className={styles.risks}>
              {brief.at_risk.map((risk) => (
                <li key={risk.task_id} className={styles.risk}>
                  <span className={styles.riskWhat}>{risk.what}</span>
                  <span className={`tabular ${styles.riskDays}`}>
                    {risk.days_left} {risk.days_left === 1 ? 'day' : 'days'}
                  </span>
                  <p className="evidence">{risk.evidence}</p>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {brief.reminders.length > 0 && (
          <Section label="You committed to this" count={brief.reminders.length}>
            <ul className={styles.reminders}>
              {brief.reminders.map((reminder, index) => (
                <li key={index} className={styles.reminder}>
                  <p>{reminder.what}</p>
                  <p className="evidence">
                    {reminder.source} · {reminder.evidence}
                  </p>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {brief.decisions.length > 0 && (
          <Section label={brief.decisions.length === 1 ? 'One decision' : 'Decisions'}>
            <ul className={styles.decisions}>
              {brief.decisions.map((decision, index) => (
                <li key={index} className={styles.decision}>
                  <p className={styles.question}>{decision.question}</p>
                  <p className="evidence">{decision.evidence}</p>
                  {decision.options.length > 0 && (
                    <ul className={styles.options}>
                      {decision.options.map((option) => (
                        <li key={option}>
                          <Answer text={option} />
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          </Section>
        )}

        {brief.check_in && brief.check_in.items.length > 0 && (
          <CheckInList checkIn={brief.check_in} />
        )}

        {USING_FIXTURES && <BriefSwitcher onPick={showBrief} current={fixtureState} />}
      </div>

      {auditOpen && <AuditPanel onClose={() => setAuditOpen(false)} />}
    </div>
  )
}

/**
 * The line under the date, and the ten seconds of the demo that matter most.
 *
 * On a quiet day it has to read as the system working rather than as a screen
 * that failed to load something -- which is why it says what it says about the
 * day below, and why there is no illustration, no "all caught up", and nothing
 * to dismiss.
 */
function Standing({ brief, quiet }: { brief: DailyBrief; quiet: boolean }) {
  if (quiet) {
    return (
      <div className={styles.standing}>
        <p className={styles.quiet}>Nothing needs you today.</p>
        <p className={styles.quietWhy}>
          The day below is planned. Second speaks when something changes.
        </p>
      </div>
    )
  }

  const count = brief.decisions.length
  return (
    <div className={styles.standing}>
      <p className={styles.loud}>
        {count === 0
          ? 'Something was prepared for you.'
          : count === 1
            ? 'One decision needs you.'
            : `${count} decisions need you.`}
      </p>
    </div>
  )
}

/** One option on a decision, sent back as the user's own words. */
function Answer({ text }: { text: string }) {
  const [sent, setSent] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)

  if (sent) return <span className={styles.answered}>{text} · sent</span>

  return (
    <>
      <button
        type="button"
        className={styles.option}
        onClick={() => {
          setFailed(null)
          api
            .feedback(text)
            .then(() => setSent(true))
            .catch((error: unknown) => setFailed(errorLine(error)))
        }}
      >
        {text}
      </button>
      {failed && <span className={styles.optionFailed}>{failed}</span>}
    </>
  )
}

function totalTime(brief: DailyBrief): string {
  return duration(brief.blocks.reduce((sum, block) => sum + block.duration_min, 0))
}

/**
 * Fixture-mode only: step through the four states Today has.
 *
 * It exists because a live run produces whichever state the day happens to be
 * in, and all four need to be demonstrable on a recording. It is visible only
 * when the fixture flag is on, alongside the rail's marker, so it can never be
 * mistaken for a product feature.
 */
function BriefSwitcher({
  onPick,
  current,
}: {
  onPick: (state: FixtureState) => void
  current: FixtureState
}) {
  // Picking a state switches Schedule and Memory with Today: the store holds the
  // state, and those two screens read the files generated in it.
  const options: [string, FixtureState][] = [
    ['quiet', 'quiet'],
    ['prepared', 'prepared'],
    ['decision', 'decision'],
    ['check-in', 'checkIn'],
  ]

  return (
    <div className={styles.switcher}>
      <span className="label">fixture states</span>
      {options.map(([label, state]) => (
        <button
          key={label}
          type="button"
          className={styles.switch}
          aria-pressed={state === current}
          onClick={() => onPick(state)}
        >
          {label}
        </button>
      ))}
    </div>
  )
}
