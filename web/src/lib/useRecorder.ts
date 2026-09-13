/**
 * One microphone, three things hanging off it, and a teardown that can be
 * trusted.
 *
 * The three consumers of the same `MediaStream`:
 *
 * 1. **`MediaRecorder`** captures the bytes. They go to `api.startVoice`, which
 *    puts them in front of Amazon Transcribe -- the accurate transcript, late.
 * 2. **`SpeechRecognition`** paints words as they are spoken -- the inaccurate
 *    transcript, instant. Perceived latency is zero because the user reads
 *    their own sentence forming while the real transcription has not started.
 * 3. **`AnalyserNode`** feeds the waveform, so the page shows that sound is
 *    arriving rather than asserting it.
 *
 * **Nothing here starts the microphone from an effect.** Capture begins only in
 * `start`, which runs from a click, and click handlers are not double-invoked.
 * That is the whole defence against React 19 StrictMode's mount/unmount/mount
 * in development producing two live `MediaRecorder`s. The remaining hole is
 * that `getUserMedia` is asynchronous: it can resolve *after* the component
 * unmounted or after the user pressed stop, and a stream nobody holds still
 * lights the tab's recording indicator. So every session carries an `epoch`,
 * the epoch is bumped by teardown, and a resolution that finds the epoch moved
 * stops its own tracks and returns. The unmount cleanup bumps the epoch and
 * releases whatever is already running; it starts nothing, so StrictMode's
 * second pass has nothing to duplicate.
 *
 * Feature absence is a state, never a failure. Firefox has no
 * `SpeechRecognition` and Safari has no WebM `MediaRecorder`; in both cases the
 * screen still records or still transcribes, and says in one line which half is
 * missing.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Bare `audio/webm`, no `;codecs=opus`.
 *
 * This has cost this project a day once already. The upload lands in S3 through
 * a presigned PUT, and the signature covers the content type *exactly*.
 * `MediaRecorder.mimeType` reports `audio/webm;codecs=opus`, so a blob built
 * from `recorder.mimeType` uploads with a Content-Type the signature does not
 * cover, and S3 answers an opaque 403 that reads like a CORS failure. The
 * chunks are therefore re-wrapped into a blob typed bare. Do not "fix" this
 * back to `recorder.mimeType`.
 */
const AUDIO_TYPE = 'audio/webm'

/** 2048 samples across the canvas: enough shape to read, cheap enough to animate. */
const FFT_SIZE = 2048

export type RecorderPhase = 'idle' | 'asking' | 'recording' | 'stopped'

export interface Recorder {
  phase: RecorderPhase
  /** Words as they were spoken. Always `''` when `liveSupported` is false. */
  live: string
  /** Whether this browser has the Web Speech API at all. */
  liveSupported: boolean
  /** Why the live transcript stopped, when the reason is worth a line. */
  liveProblem: string | null
  /** The captured audio, re-wrapped bare. Null until a recording finished. */
  audio: Blob | null
  /** Whether this browser records the WebM the upload route is signed for. */
  captureSupported: boolean
  /** What stopped the microphone, in the browser's own words where it has any. */
  problem: string | null
  /** Whole seconds of the current or last recording. */
  seconds: number
  /** Live signal for the waveform. Null whenever nothing is being captured. */
  analyser: AnalyserNode | null
  start: () => void
  stop: () => void
}

/** Everything one recording holds open, so teardown has a single argument. */
interface Session {
  readonly epoch: number
  stream: MediaStream | null
  recorder: MediaRecorder | null
  context: AudioContext | null
  recognition: SpeechRecognition | null
  chunks: Blob[]
  timer: number | null
  /** True once the user pressed stop, so the recogniser does not restart. */
  stopping: boolean
  /** False when stop arrived while the permission prompt was still open. */
  began: boolean
  /**
   * True once this session may no longer write to the transcript.
   *
   * Separate from `stopping` because a graceful stop deliberately leaves the
   * recogniser running long enough to deliver the words already in flight --
   * `stopping` means "do not restart", this means "do not speak".
   */
  abandoned: boolean
}

const LIVE_CONSTRUCTOR = speechConstructor()
const RECORDING_TYPE = recordingType()

export function useRecorder(): Recorder {
  const [phase, setPhase] = useState<RecorderPhase>('idle')
  const [live, setLive] = useState('')
  const [liveProblem, setLiveProblem] = useState<string | null>(null)
  const [audio, setAudio] = useState<Blob | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [seconds, setSeconds] = useState(0)
  const [analyser, setAnalyser] = useState<AnalyserNode | null>(null)

  const sessionRef = useRef<Session | null>(null)
  /** The finished session, still allowed to deliver its last words. */
  const lastRef = useRef<Session | null>(null)
  const epochRef = useRef(0)

  /** The end of a recording, whether it produced audio or not. */
  const finish = useCallback((session: Session, blob: Blob | null) => {
    if (epochRef.current !== session.epoch) return
    epochRef.current += 1
    sessionRef.current = null
    lastRef.current = session

    // A recording can end without the user pressing stop -- a `MediaRecorder`
    // error takes this path too. `stop` tells the recogniser to finish and
    // leaves it to deliver its last words; anything else has to kill it, since
    // `SpeechRecognition` opens its own capture and stopping our tracks does
    // not touch it.
    if (!session.stopping) {
      session.stopping = true
      session.abandoned = true
      killRecognition(session)
    }

    release(session)
    setAnalyser(null)
    if (blob && blob.size > 0) setAudio(blob)
    setPhase(session.began ? 'stopped' : 'idle')
  }, [])

  const startedRef = useRef(0)

  const start = useCallback(() => {
    // A second click on a button already asking, and nothing else: StrictMode
    // cannot reach here, because no effect calls this.
    if (sessionRef.current) return
    startedRef.current = Date.now()

    // The previous recogniser may still be finalising. It has had its chance;
    // from here its words would land in a transcript that belongs to a
    // different recording.
    if (lastRef.current) {
      lastRef.current.abandoned = true
      killRecognition(lastRef.current)
      lastRef.current = null
    }

    if (!navigator.mediaDevices?.getUserMedia) {
      setProblem(
        'This page has no microphone to ask for. getUserMedia needs a secure context: https, or localhost. Type the brain dump below instead.',
      )
      return
    }

    const epoch = (epochRef.current += 1)
    const session: Session = {
      epoch,
      stream: null,
      recorder: null,
      context: null,
      recognition: null,
      chunks: [],
      timer: null,
      stopping: false,
      began: false,
      abandoned: false,
    }
    sessionRef.current = session

    setPhase('asking')
    setProblem(null)
    setLiveProblem(null)
    setLive('')
    setAudio(null)
    setSeconds(0)

    navigator.mediaDevices
      .getUserMedia({ audio: true })
      .then((stream) => {
        // The permission prompt is answered on the user's own schedule, which
        // may be after this component went away. Stopping the tracks here is
        // the only thing that turns the tab's recording indicator back off.
        if (epochRef.current !== epoch) {
          for (const track of stream.getTracks()) track.stop()
          return
        }

        session.stream = stream
        session.began = true

        // The analyser is deliberately NOT connected onward to
        // `context.destination`: routing the microphone to the speakers is
        // feedback, not a visualisation.
        const context = new AudioContext()
        session.context = context
        void context.resume()
        const node = context.createAnalyser()
        node.fftSize = FFT_SIZE
        context.createMediaStreamSource(stream).connect(node)
        setAnalyser(node)

        if (RECORDING_TYPE) {
          attachRecorder(session, stream, RECORDING_TYPE, finish, setProblem, epochRef)
        }
        if (LIVE_CONSTRUCTOR) attachRecognition(session, setLive, setLiveProblem)

        // Counted from the press, not from here, and read off the clock rather
        // than incremented, so a slow permission prompt or a throttled tab
        // cannot make the seconds lag.
        const tick = () => setSeconds(Math.floor((Date.now() - startedRef.current) / 1000))
        tick()
        session.timer = window.setInterval(() => {
          if (epochRef.current !== epoch) return
          tick()
        }, 250)

        setPhase('recording')
      })
      .catch((cause: unknown) => {
        if (epochRef.current !== epoch) return
        epochRef.current += 1
        sessionRef.current = null
        setPhase('idle')
        setProblem(microphoneProblem(cause))
      })
  }, [finish])

  const stop = useCallback(() => {
    const session = sessionRef.current
    if (!session || session.stopping) return
    session.stopping = true

    if (session.timer !== null) {
      window.clearInterval(session.timer)
      session.timer = null
    }

    // `stop`, not `abort`: the engine gets one last pass at the words already
    // in flight, and the words matter more than the two hundred milliseconds.
    // `onend` is left wired but reads `stopping`, so it will not restart.
    if (session.recognition) {
      try {
        session.recognition.stop()
      } catch {
        /* already ended */
      }
    }

    if (session.recorder && session.recorder.state !== 'inactive') {
      // The blob is assembled in `onstop`, which fires after the final
      // `dataavailable`. Assembling it here would drop the last timeslice.
      session.recorder.stop()
      return
    }

    finish(session, null)
  }, [finish])

  useEffect(
    () => () => {
      // Real unmount and StrictMode's rehearsal of one take the same path.
      // Bumping the epoch is what makes an in-flight `getUserMedia` stop its
      // own tracks when it lands; `release` deals with anything already open.
      // No state is set here and nothing is started, so the second mount
      // begins from a clean slate with nothing duplicated.
      epochRef.current += 1
      for (const ref of [sessionRef, lastRef]) {
        const session = ref.current
        ref.current = null
        if (!session) continue
        session.stopping = true
        session.abandoned = true
        killRecognition(session)
        release(session)
      }
    },
    [],
  )

  return {
    phase,
    live,
    liveSupported: LIVE_CONSTRUCTOR !== null,
    liveProblem,
    audio,
    captureSupported: RECORDING_TYPE !== null,
    problem,
    seconds,
    analyser,
    start,
    stop,
  }
}

// ---------------------------------------------------------------------------

function attachRecorder(
  session: Session,
  stream: MediaStream,
  type: string,
  finish: (session: Session, blob: Blob | null) => void,
  setProblem: (what: string) => void,
  epochRef: { current: number },
): void {
  const recorder = new MediaRecorder(stream, { mimeType: type })
  session.recorder = recorder

  recorder.ondataavailable = (event) => {
    if (event.data.size > 0) session.chunks.push(event.data)
  }

  recorder.onstop = () => {
    finish(session, new Blob(session.chunks, { type: AUDIO_TYPE }))
  }

  recorder.onerror = (event) => {
    if (epochRef.current !== session.epoch) return
    const cause: unknown = event.error
    setProblem(
      cause instanceof DOMException
        ? `The recording stopped: ${cause.name}: ${cause.message}`
        : event.message || 'The recording stopped and the browser gave no reason.',
    )
    finish(session, session.chunks.length > 0 ? new Blob(session.chunks, { type: AUDIO_TYPE }) : null)
  }

  // A timeslice, so chunks exist on disk-ish rather than only in one final
  // blob: a tab that dies mid-sentence then still has most of the audio.
  recorder.start(1000)
}

function attachRecognition(
  session: Session,
  setLive: (text: string) => void,
  setLiveProblem: (what: string | null) => void,
): void {
  if (!LIVE_CONSTRUCTOR) return

  const recognition = new LIVE_CONSTRUCTOR()
  session.recognition = recognition
  recognition.continuous = true
  recognition.interimResults = true
  recognition.maxAlternatives = 1
  // The engine's own default is the document language, which is not what the
  // person speaks. If the service does not have it, `language-not-supported`
  // says so on screen rather than silently transcribing into the wrong one.
  recognition.lang = navigator.language || 'en-US'

  /** Text from recognition sessions that have already ended. */
  let carried = ''
  /** Text settled inside the current session, rebuilt on every event. */
  let settled = ''
  let fatal = false

  recognition.onresult = (event) => {
    // Not the epoch: a session that has been stopped gracefully is still the
    // rightful owner of the transcript until a new recording begins.
    if (session.abandoned) return

    // `results` holds the whole current session, so it is rebuilt from index 0
    // rather than appended to. Appending would count a result twice: once while
    // interim, again once `isFinal` flipped.
    let final = ''
    let interim = ''
    for (let index = 0; index < event.results.length; index += 1) {
      const result = event.results[index]
      if (result.isFinal) final += result[0].transcript
      else interim += result[0].transcript
    }
    settled = final
    setLive([carried, final, interim].filter(Boolean).join(' ').replace(/\s+/g, ' ').trim())
  }

  recognition.onerror = (event) => {
    if (session.abandoned) return
    if (SPEECH_FATAL.has(event.error)) fatal = true
    // `no-speech` and `aborted` are the ordinary end of a quiet stretch and of
    // a stop. Reporting them would be noise about nothing being wrong.
    const said = SPEECH_PROBLEM[event.error]
    if (said) setLiveProblem(said)
  }

  recognition.onend = () => {
    // Chrome ends a recognition after a stretch of silence even with
    // `continuous` set, and the next one starts with `results` empty. What has
    // already settled is carried forward by hand, or a pause mid-brain-dump
    // erases everything said before it.
    if (session.abandoned || session.stopping || fatal) return
    carried = [carried, settled].filter(Boolean).join(' ')
    settled = ''
    try {
      recognition.start()
    } catch {
      /* already running; the next `end` will try again */
    }
  }

  try {
    recognition.start()
  } catch (cause) {
    setLiveProblem(
      `Live transcription did not start: ${cause instanceof Error ? cause.message : String(cause)}. The accurate transcript still arrives when the upload finishes.`,
    )
  }
}

/** Let go of the microphone. Idempotent, and safe on a half-built session. */
function release(session: Session): void {
  if (session.timer !== null) window.clearInterval(session.timer)
  session.timer = null

  if (session.recorder) {
    session.recorder.ondataavailable = null
    session.recorder.onstop = null
    session.recorder.onerror = null
    if (session.recorder.state !== 'inactive') {
      try {
        session.recorder.stop()
      } catch {
        /* already inactive */
      }
    }
    session.recorder = null
  }

  // Every track, by hand. Dropping the reference is not enough: the tab keeps
  // its recording indicator until the tracks themselves are stopped, and a user
  // who sees that after pressing stop is right not to trust the screen.
  for (const track of session.stream?.getTracks() ?? []) track.stop()
  session.stream = null

  if (session.context && session.context.state !== 'closed') void session.context.close()
  session.context = null
}

/** Only for teardown that is not waiting on a final result. */
function killRecognition(session: Session): void {
  const recognition = session.recognition
  if (!recognition) return
  session.recognition = null
  recognition.onresult = null
  recognition.onerror = null
  recognition.onend = null
  try {
    recognition.abort()
  } catch {
    /* already ended */
  }
}

function speechConstructor(): { new (): SpeechRecognition } | null {
  if (typeof SpeechRecognition !== 'undefined') return SpeechRecognition
  if (typeof webkitSpeechRecognition !== 'undefined') return webkitSpeechRecognition
  return null
}

/**
 * The most specific WebM the browser will record, or null.
 *
 * Null means Safari, which records `audio/mp4`. Re-wrapping mp4 bytes as
 * `audio/webm` would upload a file whose type is a lie, and the lie would be
 * believed: `start_transcription` passes `MediaFormat` to Transcribe
 * explicitly, so the job would be told to read WebM out of an mp4 container and
 * would fail asynchronously with a reason nobody is looking for. The screen
 * says no accurate transcript is coming instead of sending it.
 */
function recordingType(): string | null {
  if (typeof MediaRecorder === 'undefined') return null
  for (const candidate of ['audio/webm;codecs=opus', AUDIO_TYPE]) {
    if (MediaRecorder.isTypeSupported(candidate)) return candidate
  }
  return null
}

/** What stopped the microphone. The browser's own name for it, always. */
function microphoneProblem(cause: unknown): string {
  if (cause instanceof DOMException) {
    switch (cause.name) {
      case 'NotAllowedError':
      case 'SecurityError':
        return 'Microphone permission is blocked for this site. Allow it in the browser’s site settings and record again, or type the brain dump below.'
      case 'NotFoundError':
      case 'OverconstrainedError':
        return 'No microphone was found. Type the brain dump below instead.'
      case 'NotReadableError':
        return 'The microphone is held by another application. Close it and record again, or type the brain dump below.'
      case 'AbortError':
        return 'The microphone stopped before it started. Record again, or type the brain dump below.'
      default:
        return `${cause.name}: ${cause.message}`
    }
  }
  if (cause instanceof Error) return cause.message
  return String(cause)
}

/** Codes after which restarting the recogniser only reproduces the error. */
const SPEECH_FATAL = new Set<SpeechRecognitionErrorCode>([
  'not-allowed',
  'service-not-allowed',
  'audio-capture',
  'language-not-supported',
  'bad-grammar',
  'phrases-not-supported',
])

/**
 * Only the codes worth a line on screen.
 *
 * Each one says what was lost and what still holds, because the two transcripts
 * fail independently: losing the live one costs latency, not the transcript.
 */
const SPEECH_PROBLEM: Partial<Record<SpeechRecognitionErrorCode, string>> = {
  'not-allowed':
    'The browser refused live transcription. The accurate transcript still arrives when the upload finishes.',
  'service-not-allowed':
    'The browser refused its speech service. The accurate transcript still arrives when the upload finishes.',
  network:
    'Live transcription lost its network. Chrome sends this audio to a web service; the upload and the accurate transcript are separate and unaffected.',
  'audio-capture': 'Live transcription lost the microphone.',
  'language-not-supported': `Live transcription does not support ${navigator.language || 'this language'}. The accurate transcript still arrives when the upload finishes.`,
}
