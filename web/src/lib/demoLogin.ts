/**
 * The demo sign-in gate.
 *
 * This is a stage prop, not security. The hosted demo is read by judges, and a
 * product that opens straight onto someone's goals does not look like a product
 * anyone would trust with them, so the demo shows a door. The username and
 * password are written into the bundle below and printed on the login screen
 * itself, the check runs in the browser, and the "session" is one flag in
 * sessionStorage that anyone can set from the console. Nothing behind the gate
 * is protected by it, and nothing real should ever be put behind it.
 */

export const DEMO_USERNAME = 'judge'
export const DEMO_PASSWORD = 'second-demo'

/** The one key the gate writes. Namespaced so it cannot collide with anything else on the origin. */
const SIGNED_IN_KEY = 'second.signedIn'

/**
 * True when the pair is the demo pair. The username is trimmed and compared
 * without case, because a stray space or a capital typed on a phone keyboard is
 * not a wrong username; the password is compared exactly, as a password would be.
 */
export function isDemoLogin(username: string, password: string): boolean {
  return username.trim().toLowerCase() === DEMO_USERNAME && password === DEMO_PASSWORD
}

/**
 * Whether this tab has signed in. sessionStorage rather than localStorage, so a
 * fresh tab opens on the login again and every judge sees the door.
 *
 * Reading the storage can throw (a sandboxed frame, a browser set to block site
 * data), and a demo that crashes on its first line is worse than one that asks
 * again, so any failure reads as signed out.
 */
export function readSignedIn(): boolean {
  try {
    return window.sessionStorage.getItem(SIGNED_IN_KEY) === '1'
  } catch {
    return false
  }
}

/**
 * Record signing in or out. A failed write is ignored: App keeps its own state
 * for this tab, so the only cost is being asked again after a reload.
 */
export function writeSignedIn(signedIn: boolean): void {
  try {
    if (signedIn) window.sessionStorage.setItem(SIGNED_IN_KEY, '1')
    else window.sessionStorage.removeItem(SIGNED_IN_KEY)
  } catch {
    // Storage is unavailable; see above.
  }
}
