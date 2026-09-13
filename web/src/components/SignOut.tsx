import { writeSignedIn } from '../lib/demoLogin'
import styles from './SignOut.module.css'

/**
 * Leave the demo and go back to the login. Part of the stage prop in
 * lib/demoLogin.ts: it clears the one flag and hands control back to App, which
 * owns whether the gate is shown. Nothing else is reset, so signing in again
 * lands on the screen that was open.
 */
export function SignOut({ onSignedOut }: { onSignedOut: () => void }) {
  return (
    <button
      type="button"
      className={styles.signOut}
      onClick={() => {
        writeSignedIn(false)
        onSignedOut()
      }}
    >
      Sign out
    </button>
  )
}
