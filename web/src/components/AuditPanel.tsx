import { useEffect, useMemo } from 'react'

import { Problem } from './Problem'
import { useSecond } from '../store/useSecond'
import type { AuditEntry } from '../types/contract'
import styles from './AuditPanel.module.css'

/**
 * Every write the system made, in the order it made them.
 *
 * This is the demo's primary evidence that Second is doing what it claims, and
 * a judge is pointed at it. It does not need to be beautiful; it needs to be
 * readable at a glance on a recording.
 *
 * Three decisions worth stating:
 *
 * **Grouped by `run_id`, oldest first inside the group.** `/api/audit` returns
 * newest first, which is right for a feed and wrong for reading a run: a run is
 * a sequence, and observer → diagnostician → adapter → preparer → communicator
 * only tells its story forwards.
 *
 * **There are no spans.** The brief asked for node spans; `AuditEntry` carries
 * no duration, so there are none to show and none are invented. What it does
 * carry is a clock time, a node or tool name, whether the entry was a write, and
 * whether it failed -- which is enough to see the shape of a run.
 *
 * **Writes and failures are marked; reads are not.** A read is the common case
 * and marking it would make the two things worth noticing harder to find. The
 * one failure in the seeded demo -- the Adapter refusing to move a meeting the
 * user does not own -- is the single most important row in this panel.
 */
export function AuditPanel({ onClose }: { onClose: () => void }) {
  const audit = useSecond((state) => state.audit)
  const loading = useSecond((state) => state.loading.audit)
  const error = useSecond((state) => state.errors.audit)
  const loadAudit = useSecond((state) => state.loadAudit)

  useEffect(() => {
    if (audit.length === 0) void loadAudit()
  }, [audit.length, loadAudit])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const runs = useMemo(() => groupByRun(audit), [audit])

  return (
    <aside className={styles.panel} aria-label="Audit log">
      <header className={styles.head}>
        <h2 className="label">Audit</h2>
        <p className={styles.count}>
          {audit.length} {audit.length === 1 ? 'entry' : 'entries'}
          {runs.length > 0 && ` · ${runs.length} ${runs.length === 1 ? 'run' : 'runs'}`}
        </p>
        <button type="button" className={styles.close} onClick={onClose}>
          Close
        </button>
      </header>

      <div className={styles.body}>
        {error && <Problem what={error} onRetry={() => void loadAudit()} />}

        {!error && audit.length === 0 && (
          <p className={styles.nothing}>
            {loading ? 'Reading the audit.' : 'Nothing has run yet, so nothing has been written.'}
          </p>
        )}

        {runs.map((run) => (
          <section key={run.id} className={styles.run}>
            <h3 className={styles.runId}>
              <span className={styles.runLabel}>run</span>
              {run.id.slice(0, 8)}
              <span className={styles.runMeta}>
                {run.writes} {run.writes === 1 ? 'write' : 'writes'}
                {run.failures > 0 && ` · ${run.failures} refused`}
              </span>
            </h3>

            <ol className={styles.entries}>
              {run.entries.map((entry, index) => (
                <li
                  key={`${entry.at}:${index}`}
                  className={styles.entry}
                  data-kind={entry.kind}
                  data-write={entry.is_write}
                  data-failed={entry.failed}
                >
                  <time className={`tabular ${styles.at}`} dateTime={entry.at}>
                    {entry.at.slice(11, 19)}
                  </time>
                  <span className={styles.actor}>{entry.actor}</span>
                  <span className={styles.action}>{entry.action}</span>
                  <span className={styles.mark}>
                    {entry.failed ? 'refused' : entry.is_write ? 'wrote' : ''}
                  </span>
                  {Object.keys(entry.payload).length > 0 && (
                    <dl className={`evidence ${styles.payload}`}>
                      {Object.entries(entry.payload).map(([key, value]) => (
                        <div key={key} className={styles.pair}>
                          <dt>{key}</dt>
                          <dd>{value}</dd>
                        </div>
                      ))}
                    </dl>
                  )}
                </li>
              ))}
            </ol>
          </section>
        ))}
      </div>
    </aside>
  )
}

interface Run {
  id: string
  entries: AuditEntry[]
  writes: number
  failures: number
}

/** Newest run first; oldest entry first within a run. */
function groupByRun(entries: AuditEntry[]): Run[] {
  const runs = new Map<string, AuditEntry[]>()
  for (const entry of entries) {
    const existing = runs.get(entry.run_id)
    if (existing) existing.push(entry)
    else runs.set(entry.run_id, [entry])
  }

  return [...runs.entries()].map(([id, list]) => {
    const ordered = [...list].sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : 0))
    return {
      id,
      entries: ordered,
      writes: ordered.filter((entry) => entry.is_write).length,
      failures: ordered.filter((entry) => entry.failed).length,
    }
  })
}
