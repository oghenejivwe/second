import styles from './Problem.module.css'

/**
 * What failed, in one line, with a way to try again.
 *
 * The message is the server's own wherever there is one. That is the whole
 * point: `second.agents.observer does not exist yet (owned by AGENTS)` tells the
 * reader what to do next, and "Something went wrong" tells them to give up. The
 * product cites its evidence when it is working and it does not stop when it is
 * broken.
 */
export function Problem({ what, onRetry }: { what: string; onRetry?: () => void }) {
  return (
    <div className={styles.problem} role="alert">
      <p className={styles.what}>{what}</p>
      {onRetry && (
        <button type="button" className={styles.retry} onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}
