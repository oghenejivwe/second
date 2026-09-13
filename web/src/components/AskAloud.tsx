import { useEffect, useRef, useState } from 'react'

import { isSpeechSupported, speak } from '../lib/speech'
import { spokenQuestion } from '../lib/spokenBrief'
import { useListen } from '../lib/useListen'
import type { HorizonQuestion } from '../types/contract'
import { MicGlyph, Waveform } from './TalkItThrough'
import styles from './AskAloud.module.css'

/**
 * Memory's question, asked out loud, with the spoken answer poured into the box.
 *
 * It asks, listens, and hands the words to `onHeard`, which is the card's own
 * `setText`. It sends nothing: the person reads what was heard in the box they
 * would have typed into, and presses the card's own send. A transcript is a
 * guess at what was said, and a plan made from a guess nobody checked is the
 * wrong way round.
 *
 * Everything starts from the click. Unmounting aborts the voice through the
 * signal and `useListen` aborts the recogniser, so leaving Memory mid-question
 * leaves nothing talking or listening.
 */
export function AskAloud({
  question,
  disabled,
  onHeard,
}: {
  question: HorizonQuestion
  disabled: boolean
  onHeard: (text: string) => void
}) {
  const listen = useListen()
  const speaks = isSpeechSupported()
  const [asking, setAsking] = useState(false)
  const controllerRef = useRef<AbortController | null>(null)

  useEffect(() => () => controllerRef.current?.abort(), [])

  if (!speaks && !listen.supported) return null

  const ask = async () => {
    controllerRef.current?.abort()
    listen.cancel()
    const controller = new AbortController()
    controllerRef.current = controller

    setAsking(true)
    await speak(spokenQuestion(question), { signal: controller.signal })
    if (controller.signal.aborted) return
    setAsking(false)

    if (!listen.supported) return
    const text = await listen.start()
    if (controller.signal.aborted || text === null) return
    onHeard(text)
  }

  /** While asking, stop the voice and listen to nothing. While listening, keep what was said. */
  const stop = () => {
    if (asking) {
      controllerRef.current?.abort()
      setAsking(false)
      return
    }
    listen.stop()
  }

  const busy = asking || listen.phase === 'listening'

  return (
    <div className={styles.aloud}>
      <div className={styles.row}>
        <button
          type="button"
          className={styles.pill}
          disabled={disabled}
          onClick={busy ? stop : () => void ask()}
        >
          <MicGlyph />
          {busy ? 'Stop' : 'Ask me aloud'}
        </button>
        {listen.phase === 'listening' && <Waveform />}
      </div>

      {/* The state is announced; the words forming are not, because a screen
       * reader re-reading every interim guess would talk over the person. */}
      <p className={styles.status} aria-live="polite">
        {statusLine(asking, speaks, listen)}
      </p>
      {listen.phase === 'listening' && (listen.final || listen.interim) && (
        <p className={styles.heard}>
          {[listen.final, listen.interim].filter(Boolean).join(' ')}
        </p>
      )}
    </div>
  )
}

function statusLine(asking: boolean, speaks: boolean, listen: ReturnType<typeof useListen>): string {
  if (asking) return speaks ? 'Asking.' : ''
  switch (listen.phase) {
    case 'listening':
      return 'Listening for your answer.'
    case 'heard':
      return 'Heard. The words are in the box below; send them when they are right.'
    case 'error':
      return listen.problem ?? ''
    case 'unsupported':
      return 'This browser cannot listen, so type the answer below.'
    default:
      return ''
  }
}
