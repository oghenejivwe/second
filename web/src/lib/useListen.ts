/**
 * Listening for one answer, and nothing after it.
 *
 * `useRecorder` holds a microphone open for a brain dump of any length and
 * restarts the recogniser across every pause. This hook is its opposite: it
 * wants one spoken answer to one question. So it listens continuously while the
 * person is talking, and once words have settled and a short silence follows,
 * it stops by itself and hands back what it heard. The person can also end it
 * early with `stop`, which keeps the words, or `cancel`, which does not.
 *
 * **`start` returns a promise of the final text**, or null when nothing usable
 * was heard: a cancel, an unmount, silence, or an error. The conversation that
 * calls it reads top to bottom as a script, `await listen.start()`, instead of
 * watching `phase` from an effect.
 *
 * The StrictMode defence is `useRecorder`'s. Nothing here starts listening from
 * an effect, so the rehearsal mount has nothing to duplicate; every session
 * carries an `epoch`, and the unmount cleanup bumps it and aborts whatever is
 * running, so a late `result` or `end` from a recogniser nobody holds cannot
 * write to state or resolve a promise into a conversation that has gone.
 *
 * The constructor is looked up when `start` runs (and once for the initial
 * phase), never at module load, so a test can stub it after import. Absence is
 * a phase, `unsupported`, and never an error: Firefox has no recogniser, and the
 * screen offers a text box in its place.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

export type ListenPhase = 'idle' | 'listening' | 'heard' | 'unsupported' | 'error'

export interface Listen {
  phase: ListenPhase
  /** Words not yet settled, as they are spoken. */
  interim: string
  /** Words the engine has settled. The answer once `phase` is `heard`. */
  final: string
  /** Why listening stopped without an answer, when the reason is worth a line. */
  problem: string | null
  /** Whether this browser has a recogniser at all. */
  supported: boolean
  /** Listen for one answer. Resolves with it, or with null when there is none. */
  start: () => Promise<string | null>
  /** Stop listening and keep what was said. */
  stop: () => void
  /** Stop listening and throw away what was said. */
  cancel: () => void
}

/**
 * How long a settled answer is left silent before it is taken as finished.
 * Long enough for a breath mid-sentence, short enough not to feel ignored.
 */
const END_OF_ANSWER_MS = 1600

interface Session {
  readonly epoch: number
  recognition: SpeechRecognition
  resolve: (text: string | null) => void
  promise: Promise<string | null>
  final: string
  interim: string
  silence: number | null
  /** Set by `stop`: the engine is finalising and its words still count. */
  stopping: boolean
  /** Set by an error after which no answer is coming. */
  problem: string | null
}

export function useListen(): Listen {
  const [phase, setPhase] = useState<ListenPhase>(() => (recogniser() ? 'idle' : 'unsupported'))
  const [interim, setInterim] = useState('')
  const [final, setFinal] = useState('')
  const [problem, setProblem] = useState<string | null>(null)

  const sessionRef = useRef<Session | null>(null)
  const epochRef = useRef(0)

  const start = useCallback((): Promise<string | null> => {
    // One answer at a time: a second call joins the first.
    if (sessionRef.current) return sessionRef.current.promise

    const Recogniser = recogniser()
    if (!Recogniser) {
      setPhase('unsupported')
      return Promise.resolve(null)
    }

    const epoch = (epochRef.current += 1)
    let resolve: (text: string | null) => void = () => {}
    const promise = new Promise<string | null>((settle) => (resolve = settle))
    const recognition = new Recogniser()
    const session: Session = {
      epoch,
      recognition,
      resolve,
      promise,
      final: '',
      interim: '',
      silence: null,
      stopping: false,
      problem: null,
    }
    sessionRef.current = session

    recognition.continuous = true
    recognition.interimResults = true
    recognition.maxAlternatives = 1
    // As on Record: the document language is not what the person speaks.
    recognition.lang = navigator.language || 'en-GB'

    const current = () => epochRef.current === epoch

    recognition.onresult = (event) => {
      if (!current()) return
      // Rebuilt from index 0 every time, for the reason `useRecorder` gives:
      // appending would count a result once as interim and again as final.
      let settled = ''
      let moving = ''
      for (let index = 0; index < event.results.length; index += 1) {
        const result = event.results[index]
        if (result.isFinal) settled += result[0].transcript
        else moving += result[0].transcript
      }
      session.final = tidy(settled)
      session.interim = tidy(moving)
      setFinal(session.final)
      setInterim(session.interim)

      if (session.silence !== null) window.clearTimeout(session.silence)
      session.silence = null
      if (session.final && !session.interim && !session.stopping) {
        session.silence = window.setTimeout(() => {
          if (!current() || session.stopping) return
          session.stopping = true
          try {
            recognition.stop()
          } catch {
            /* already ended; `end` follows */
          }
        }, END_OF_ANSWER_MS)
      }
    }

    recognition.onerror = (event) => {
      if (!current()) return
      // `aborted` is a cancel and `no-speech` is silence; `end` says both.
      const said = LISTEN_PROBLEM[event.error]
      if (said) session.problem = said
    }

    recognition.onend = () => {
      if (!current()) return
      // An engine that ended before `stop` finalised everything leaves its
      // last words interim. They were spoken, so they count.
      const text = tidy(session.final || session.interim)
      finish(session)
      if (text && !session.problem) {
        setFinal(text)
        setInterim('')
        setPhase('heard')
        session.resolve(text)
        return
      }
      setInterim('')
      setProblem(session.problem ?? 'Nothing was heard. Say it again, or type it.')
      setPhase('error')
      session.resolve(null)
    }

    setFinal('')
    setInterim('')
    setProblem(null)
    setPhase('listening')

    try {
      recognition.start()
    } catch (cause) {
      finish(session)
      setProblem(
        `Listening did not start: ${cause instanceof Error ? cause.message : String(cause)}. Type the answer instead.`,
      )
      setPhase('error')
      resolve(null)
    }

    return promise

    function finish(ended: Session) {
      if (ended.silence !== null) window.clearTimeout(ended.silence)
      ended.silence = null
      if (sessionRef.current === ended) sessionRef.current = null
      epochRef.current += 1
    }
  }, [])

  const stop = useCallback(() => {
    const session = sessionRef.current
    if (!session || session.stopping) return
    session.stopping = true
    if (session.silence !== null) window.clearTimeout(session.silence)
    session.silence = null
    // `stop`, not `abort`: the engine gets one last pass at the words in
    // flight, and `end` then resolves with them.
    try {
      session.recognition.stop()
    } catch {
      abandon(session, epochRef, sessionRef)
      setPhase('idle')
    }
  }, [])

  const cancel = useCallback(() => {
    const session = sessionRef.current
    if (!session) return
    abandon(session, epochRef, sessionRef)
    setInterim('')
    setFinal('')
    setProblem(null)
    setPhase(recogniser() ? 'idle' : 'unsupported')
  }, [])

  useEffect(
    () => () => {
      // Real unmount and StrictMode's rehearsal take the same path. No state is
      // set and nothing is started, so the second mount begins clean.
      const session = sessionRef.current
      if (session) abandon(session, epochRef, sessionRef)
      epochRef.current += 1
    },
    [],
  )

  return {
    phase,
    interim,
    final,
    problem,
    supported: phase !== 'unsupported',
    start,
    stop,
    cancel,
  }
}

// ---------------------------------------------------------------------------

/** End a session now, discarding its words, and resolve its caller with null. */
function abandon(
  session: Session,
  epochRef: { current: number },
  sessionRef: { current: Session | null },
): void {
  if (sessionRef.current === session) sessionRef.current = null
  epochRef.current += 1
  if (session.silence !== null) window.clearTimeout(session.silence)
  session.silence = null
  const { recognition } = session
  recognition.onresult = null
  recognition.onerror = null
  recognition.onend = null
  try {
    recognition.abort()
  } catch {
    /* already ended */
  }
  session.resolve(null)
}

function recogniser(): { new (): SpeechRecognition } | null {
  if (typeof window === 'undefined') return null
  if (typeof SpeechRecognition !== 'undefined') return SpeechRecognition
  if (typeof webkitSpeechRecognition !== 'undefined') return webkitSpeechRecognition
  return null
}

function tidy(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

/** Only the codes worth a line, each saying what to do instead. */
const LISTEN_PROBLEM: Partial<Record<SpeechRecognitionErrorCode, string>> = {
  'not-allowed':
    'Microphone permission is blocked for this site. Allow it in the browser’s site settings, or type the answer.',
  'service-not-allowed': 'The browser refused its speech service. Type the answer instead.',
  network:
    'Listening lost its network. Chrome sends this audio to a web service to transcribe it. Type the answer instead.',
  'audio-capture': 'No microphone was found. Type the answer instead.',
  'language-not-supported': `Listening does not support ${typeof navigator === 'undefined' ? 'this language' : navigator.language || 'this language'}. Type the answer instead.`,
}
