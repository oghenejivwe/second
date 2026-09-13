import { useEffect, useRef, useState } from 'react'

import { errorLine, isFixtureAcknowledgement, USING_FIXTURES } from '../api/client'
import { FIXTURE_WEEK_ANSWER } from '../api/weekAnswer'
import { cancelSpeech, isSpeechSupported, speak } from '../lib/speech'
import {
  spokenAnswerReply,
  spokenBrief,
  spokenQuestion,
  spokenReadBack,
  spokenSkipReply,
} from '../lib/spokenBrief'
import { useListen } from '../lib/useListen'
import { withdrawQuestions } from '../lib/withdrawn'
import { questionKey, useSecond, type SettledQuestion } from '../store/useSecond'
import type { DailyBrief, HorizonQuestion } from '../types/contract'
import { Problem } from './Problem'
import styles from './TalkItThrough.module.css'

/**
 * Today, said out loud, and the question Memory is due to ask, answered by voice.
 *
 * The conversation is a script, read top to bottom in `begin`: say the brief;
 * find a due question, reading Memory first if nothing has; ask it; listen as
 * soon as the asking ends; read back what was heard; and let the person choose
 * to plan it, say it again or skip. Planning and skipping go through the
 * store's own `answerQuestion` and `skipQuestion`, so an answer given here
 * settles the question on Memory exactly as the text box there would, and the
 * reply that is read out is the one the store recorded, told from the fields
 * Memory's `Outcome` shows.
 *
 * **Every spoken line is a caption first.** Each one is added to the list on
 * screen before the voice starts, and that list is an `aria-live` region, so
 * the conversation reads the same muted, on a screen recording, and to a
 * screen reader. What the browser cannot do is a state of the panel, said in
 * one line: without a recogniser the question gets a text box, and without a
 * voice the captions are the whole conversation.
 *
 * **The conversation starts from an effect, and that is safe here** where it is
 * not for `useRecorder`'s microphone. The panel exists only after a click, so
 * the browser's activation rule for speech is already met; the first step waits
 * one microtask, and StrictMode's rehearsal aborts before that microtask runs,
 * so the rehearsal says nothing and captions nothing. Listening is started only
 * from the script after a spoken line has ended, never from the effect itself.
 * Closing the panel unmounts it: the effect aborts the voice and `useListen`
 * aborts the recogniser.
 *
 * Today's decision cards answer through `api.feedback` inside Today, and the
 * store has no action for them, so a decision is read out as part of the brief
 * and answered with its own buttons, not by voice.
 */
export function TalkItThrough({ brief, onClose }: { brief: DailyBrief; onClose: () => void }) {
  const listen = useListen()
  const speaks = isSpeechSupported()
  const autoListen = speaks && listen.supported

  const [lines, setLines] = useState<Line[]>([])
  const [step, setStep] = useState<Step>({ kind: 'brief' })
  const [speaking, setSpeaking] = useState(false)
  const [typed, setTyped] = useState('')

  const controllerRef = useRef<AbortController | null>(null)
  const lineId = useRef(0)
  /** Which `say` last started, so an earlier one ending does not clear the indicator. */
  const sayCount = useRef(0)

  const add = (who: Line['who'], text: string) => {
    const id = (lineId.current += 1)
    setLines((previous) => [...previous, { id, who, text }])
  }

  /** Caption the line, then speak it. Resolves when it has been said, or at once without a voice. */
  const say = async (text: string, signal: AbortSignal) => {
    if (signal.aborted) return
    add('second', text)
    const mine = (sayCount.current += 1)
    setSpeaking(true)
    await speak(text, { signal })
    if (sayCount.current === mine) setSpeaking(false)
  }

  const begin = async (signal: AbortSignal) => {
    // StrictMode's rehearsal aborts before this microtask runs.
    await Promise.resolve()
    if (signal.aborted) return

    setStep({ kind: 'brief' })
    await say(spokenBrief(brief), signal)
    if (signal.aborted) return

    setStep({ kind: 'reading' })
    const questions = await dueQuestions(signal)
    if (signal.aborted) return

    if (questions === null) {
      const what = useSecond.getState().errors.memory
      setStep({ kind: 'finished', problem: what ?? 'Memory could not be read.' })
      await say('I could not read Memory, so I have no question to ask.', signal)
      return
    }
    if (questions.length === 0) {
      setStep({ kind: 'finished', problem: null })
      await say('No question is due.', signal)
      return
    }
    await ask(questions[0], signal)
  }

  const ask = async (question: HorizonQuestion, signal: AbortSignal, again = false) => {
    setTyped('')
    setStep({ kind: 'asking', question })
    // Asked again after Second asked back: the clarifying questions were just
    // said, so the question is not repeated before listening.
    if (!again) await say(spokenQuestion(question), signal)
    if (signal.aborted) return
    if (autoListen) await hear(question, signal)
  }

  const hear = async (question: HorizonQuestion, signal: AbortSignal) => {
    setStep({ kind: 'asking', question })
    const text = await listen.start()
    // Null is a cancel, silence or an error; `listen.phase` says which, and
    // the asking step then offers to listen again or to type.
    if (signal.aborted || text === null) return
    add('you', text)
    setStep({ kind: 'heard', question, text })
    await say(spokenReadBack(text), signal)
  }

  const plan = async (question: HorizonQuestion, text: string) => {
    const signal = controllerRef.current?.signal
    if (!signal || signal.aborted) return
    setStep({ kind: 'sending', question, text, action: 'plan' })
    try {
      await useSecond.getState().answerQuestion(question, text)
    } catch (error) {
      if (!signal.aborted) setStep({ kind: 'failed', question, text, action: 'plan', what: errorLine(error) })
      return
    }
    if (signal.aborted) return

    const settled = useSecond.getState().settled[questionKey(question)]
    if (settled?.how !== 'answered') {
      await changedUnderfoot(signal)
      return
    }
    await say(
      spokenAnswerReply(settled.reply, settled.text, USING_FIXTURES ? FIXTURE_WEEK_ANSWER : null, brief.on),
      signal,
    )
    if (signal.aborted) return
    if (stillOpen(settled)) await ask(question, signal, true)
    else await moveOn(question, signal)
  }

  const skip = async (question: HorizonQuestion) => {
    const signal = controllerRef.current?.signal
    if (!signal || signal.aborted) return
    listen.cancel()
    cancelSpeech()
    setStep({ kind: 'sending', question, text: null, action: 'skip' })
    try {
      await useSecond.getState().skipQuestion(question)
    } catch (error) {
      if (!signal.aborted) setStep({ kind: 'failed', question, text: null, action: 'skip', what: errorLine(error) })
      return
    }
    if (signal.aborted) return

    const settled = useSecond.getState().settled[questionKey(question)]
    if (settled?.how !== 'skipped') {
      await changedUnderfoot(signal)
      return
    }
    await say(spokenSkipReply(settled.reply, question.horizon), signal)
    if (!signal.aborted) await moveOn(question, signal)
  }

  /** Fixture mode only: the store drops a reply for a morning no longer on screen. */
  const changedUnderfoot = async (signal: AbortSignal) => {
    setStep({ kind: 'finished', problem: null })
    await say('The morning on screen changed while I was sending that, so nothing was recorded.', signal)
  }

  /** The next due question, if another horizon has one, or the end. */
  const moveOn = async (settledOne: HorizonQuestion, signal: AbortSignal) => {
    const { memory, settled, graph } = useSecond.getState()
    const next = memory
      ? openQuestions(memory.questions, settled, graph).find(
          (question) => questionKey(question) !== questionKey(settledOne),
        )
      : undefined
    if (next) {
      await ask(next, signal)
      return
    }
    setStep({ kind: 'finished', problem: null })
    await say('No other question is due.', signal)
  }

  const sayAgain = (question: HorizonQuestion) => {
    const signal = controllerRef.current?.signal
    if (!signal || signal.aborted) return
    // The read-back may still be playing, and a recogniser started under it
    // would transcribe Second instead of the person.
    cancelSpeech()
    void hear(question, signal)
  }

  const sendTyped = (question: HorizonQuestion) => {
    const text = typed.trim()
    if (!text) return
    listen.cancel()
    add('you', text)
    void plan(question, text)
  }

  const stop = () => {
    controllerRef.current?.abort()
    listen.cancel()
    setSpeaking(false)
    setStep({ kind: 'stopped' })
  }

  const restart = () => {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    setLines([])
    void begin(controller.signal)
  }

  useEffect(() => {
    const controller = new AbortController()
    controllerRef.current = controller
    void begin(controller.signal)
    return () => controller.abort()
    // Once per mount, on purpose: the conversation is about the brief as it was
    // when the panel opened, and Today remounts the panel when the fixture
    // state changes.
  }, [])

  const over = step.kind === 'finished' || step.kind === 'stopped'
  const listening = listen.phase === 'listening'

  return (
    <section className={styles.panel} aria-label="Talk it through">
      <header className={styles.head}>
        <p className={styles.title}>
          <MicGlyph />
          Talk it through
          {(speaking || listening) && !over && (
            <span className={styles.state}>
              {listening ? <Waveform /> : null}
              {listening ? 'Listening' : 'Speaking'}
            </span>
          )}
        </p>
        <div className={styles.controls}>
          <button type="button" className={styles.pill} onClick={stop} disabled={over}>
            Stop
          </button>
          <button type="button" className={styles.quiet} onClick={onClose}>
            Close
          </button>
        </div>
      </header>

      {!speaks && !listen.supported ? (
        <p className={styles.support}>This browser cannot speak or listen, so the conversation is shown as text.</p>
      ) : !listen.supported ? (
        <p className={styles.support}>This browser cannot listen, so type your answer.</p>
      ) : !speaks ? (
        <p className={styles.support}>This browser cannot speak, so Second’s lines are shown as text.</p>
      ) : null}

      <ol className={styles.captions} aria-live="polite" aria-relevant="additions">
        {lines.map((line) => (
          <li key={line.id} className={styles.line} data-who={line.who}>
            <span className={styles.who}>{line.who === 'second' ? 'Second' : 'You'}</span>
            <p className={styles.said}>{line.text}</p>
          </li>
        ))}
      </ol>

      {brief.decisions.length > 0 && step.kind !== 'brief' && (
        <p className={styles.note}>
          The decision is answered with its own buttons below. It is read out here, not taken by voice.
        </p>
      )}

      {step.kind === 'reading' && <p className={styles.status}>Reading Memory for a due question.</p>}

      {step.kind === 'asking' && (
        <>
          {listening && (
            <div className={styles.live}>
              <Waveform />
              <p className={styles.transcript}>
                {listen.final || listen.interim ? (
                  <>
                    {listen.final}
                    {listen.final && listen.interim ? ' ' : ''}
                    <span className={styles.interim}>{listen.interim}</span>
                  </>
                ) : (
                  <span className={styles.interim}>Listening for your answer.</span>
                )}
              </p>
              <button type="button" className={styles.pill} onClick={listen.stop}>
                Done
              </button>
            </div>
          )}

          {!listening && listen.phase === 'error' && listen.problem && <Problem what={listen.problem} />}

          {!listening && (listen.phase === 'error' || !autoListen) && (
            <div className={styles.typed}>
              <label htmlFor="talk-answer" className={styles.boxLabel}>
                Type your answer. Second plans it the way it plans anything you record.
              </label>
              <textarea
                id="talk-answer"
                className={styles.box}
                rows={3}
                value={typed}
                onChange={(event) => setTyped(event.target.value)}
              />
              <div className={styles.actions}>
                <button
                  type="button"
                  className={styles.filled}
                  disabled={!typed.trim()}
                  onClick={() => sendTyped(step.question)}
                >
                  Plan it
                </button>
                {listen.supported && (
                  <button type="button" className={styles.pill} onClick={() => sayAgain(step.question)}>
                    {listen.phase === 'error' ? 'Say it again' : 'Answer aloud'}
                  </button>
                )}
                <button type="button" className={styles.pill} onClick={() => void skip(step.question)}>
                  Skip
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {step.kind === 'heard' && (
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.filled}
            onClick={() => {
              cancelSpeech()
              void plan(step.question, step.text)
            }}
          >
            Plan it
          </button>
          <button type="button" className={styles.pill} onClick={() => sayAgain(step.question)}>
            Say it again
          </button>
          <button type="button" className={styles.pill} onClick={() => void skip(step.question)}>
            Skip
          </button>
        </div>
      )}

      {step.kind === 'sending' && (
        <p className={styles.status}>
          {step.action === 'skip'
            ? 'Skipping.'
            : USING_FIXTURES
              ? 'Planning your answer.'
              : 'Planning your answer. This takes tens of seconds.'}
        </p>
      )}

      {step.kind === 'failed' && (
        <Problem
          what={step.what}
          onRetry={() =>
            step.action === 'plan' && step.text !== null
              ? void plan(step.question, step.text)
              : void skip(step.question)
          }
        />
      )}

      {step.kind === 'finished' && step.problem && <Problem what={step.problem} />}

      {step.kind === 'stopped' && (
        <div className={styles.actions}>
          <p className={styles.status}>Stopped.</p>
          <button type="button" className={styles.pill} onClick={restart}>
            Start again
          </button>
        </div>
      )}
    </section>
  )
}

/** The ghost pill in Today's header that opens the panel. */
export function TalkPill({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button type="button" className={styles.pill} aria-expanded={open} onClick={onToggle}>
      <MicGlyph />
      Talk it through
    </button>
  )
}

/** A microphone, stroked in the one instrument blue. Decorative: the words beside it carry the meaning. */
export function MicGlyph() {
  return (
    <svg className={styles.mic} viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5.5 11a6.5 6.5 0 0 0 13 0" />
      <path d="M12 17.5V21" />
    </svg>
  )
}

/** Five bars that move while the recogniser is open. Motion only, so hidden from assistive technology. */
export function Waveform() {
  return (
    <span className={styles.wave} aria-hidden="true">
      <span />
      <span />
      <span />
      <span />
      <span />
    </span>
  )
}

// ---------------------------------------------------------------------------

interface Line {
  id: number
  who: 'second' | 'you'
  text: string
}

type Step =
  | { kind: 'brief' }
  | { kind: 'reading' }
  | { kind: 'asking'; question: HorizonQuestion }
  | { kind: 'heard'; question: HorizonQuestion; text: string }
  | { kind: 'sending'; question: HorizonQuestion; text: string | null; action: 'plan' | 'skip' }
  | {
      kind: 'failed'
      question: HorizonQuestion
      text: string | null
      action: 'plan' | 'skip'
      what: string
    }
  | { kind: 'finished'; problem: string | null }
  | { kind: 'stopped' }

const HORIZON_ORDER: Record<HorizonQuestion['horizon'], number> = { week: 0, month: 1 }

/**
 * The questions still wanting an answer, week first, as Memory lists them.
 *
 * A question settled this session is left out unless Second asked back about
 * the answer, which Memory also keeps open. Fixture mode takes off a question
 * anchored to a goal paused or retired this session, by Memory's own rule.
 */
function openQuestions(
  due: HorizonQuestion[],
  settled: Record<string, SettledQuestion>,
  graph: Parameters<typeof withdrawQuestions>[1],
): HorizonQuestion[] {
  const open = due.filter((question) => {
    const entry = settled[questionKey(question)]
    return entry === undefined || stillOpen(entry)
  })
  const shown = USING_FIXTURES ? withdrawQuestions(open, graph).questions : open
  return [...shown].sort((a, b) => HORIZON_ORDER[a.horizon] - HORIZON_ORDER[b.horizon])
}

/** MemoryScreen's rule: an answer Second asked back about has settled nothing. */
function stillOpen(settled: SettledQuestion): boolean {
  return (
    settled.how === 'answered' &&
    !isFixtureAcknowledgement(settled.reply) &&
    settled.reply.clarifying_questions.length > 0
  )
}

/**
 * Memory's due questions, reading Memory first when no screen has.
 *
 * `loadMemory` returns at once when a read is already in flight, so in that
 * case this waits for the store to say the read has finished. Null when Memory
 * could not be read.
 */
async function dueQuestions(signal: AbortSignal): Promise<HorizonQuestion[] | null> {
  if (!useSecond.getState().memory) {
    await useSecond.getState().loadMemory()
    if (!useSecond.getState().memory && useSecond.getState().loading.memory) {
      await memoryRead(signal)
    }
  }
  const { memory, settled, graph } = useSecond.getState()
  if (!memory) return null
  return openQuestions(memory.questions, settled, graph)
}

function memoryRead(signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const done = () => {
      unsubscribe()
      signal.removeEventListener('abort', done)
      resolve()
    }
    const unsubscribe = useSecond.subscribe((state) => {
      if (!state.loading.memory) done()
    })
    signal.addEventListener('abort', done, { once: true })
    if (!useSecond.getState().loading.memory) done()
  })
}
