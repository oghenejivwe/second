import { useEffect, useId, useRef, useState, type FormEvent } from 'react'

import { DEMO_PASSWORD, DEMO_USERNAME, isDemoLogin, writeSignedIn } from '../lib/demoLogin'
import styles from './Login.module.css'

/**
 * The door to the demo. A stage prop, not security: see lib/demoLogin.ts.
 *
 * Both fields open already filled and the pair is printed under the form, so a
 * judge's whole job here is one press. That is why the Sign in button, and not
 * the first field, takes focus on mount: Enter or a click is all that is left.
 * The fields stay real and editable, so the screen still behaves like a login
 * when someone does type into it, including saying so when the pair is wrong.
 */
export function Login({ onSignedIn }: { onSignedIn: () => void }) {
  const [username, setUsername] = useState(DEMO_USERNAME)
  const [password, setPassword] = useState(DEMO_PASSWORD)
  const [wrong, setWrong] = useState(false)

  const submit = useRef<HTMLButtonElement>(null)
  const id = useId()
  const usernameId = `${id}-username`
  const passwordId = `${id}-password`
  const errorId = `${id}-error`

  useEffect(() => {
    submit.current?.focus()
  }, [])

  function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!isDemoLogin(username, password)) {
      setWrong(true)
      return
    }
    writeSignedIn(true)
    onSignedIn()
  }

  return (
    <main className={styles.band}>
      <div className={styles.column}>
        <h1 className={styles.title}>Second</h1>
        <p className={styles.tagline}>Say your goals out loud. Second plans the rest.</p>

        <form className={styles.card} onSubmit={signIn} noValidate>
          <div className={styles.field}>
            <label className={styles.fieldLabel} htmlFor={usernameId}>
              Username
            </label>
            <input
              id={usernameId}
              className={styles.input}
              name="username"
              type="text"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              value={username}
              aria-invalid={wrong || undefined}
              aria-describedby={wrong ? errorId : undefined}
              onChange={(event) => {
                setUsername(event.target.value)
                setWrong(false)
              }}
            />
          </div>

          <div className={styles.field}>
            <label className={styles.fieldLabel} htmlFor={passwordId}>
              Password
            </label>
            <input
              id={passwordId}
              className={styles.input}
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              aria-invalid={wrong || undefined}
              aria-describedby={wrong ? errorId : undefined}
              onChange={(event) => {
                setPassword(event.target.value)
                setWrong(false)
              }}
            />
          </div>

          {/* Inline and in the slip hue, never a toast: the message belongs
           * beside the fields it is about, and it stays until they change. */}
          {wrong && (
            <p id={errorId} className={styles.error} role="alert">
              Those details do not match the demo login shown below.
            </p>
          )}

          <button ref={submit} type="submit" className={styles.submit}>
            Sign in
          </button>

          <p className={styles.preset}>
            Demo login: both fields are filled in{' '}
            <span className={styles.pair}>
              ({DEMO_USERNAME} / {DEMO_PASSWORD})
            </span>
            . Press Sign in.
          </p>
        </form>
      </div>
    </main>
  )
}
