import { useEffect, useMemo, useRef, useState } from 'react'

import { Problem } from '../components/Problem'
import { Section } from '../components/Section'
import { api, errorLine } from '../api/client'
import { clockTime, duration, shortDate } from '../lib/datetime'
import { diffGraphs, type GraphDiff } from '../lib/diff'
import { HORIZON_LABEL } from '../lib/horizon'
import { useRecorder, type Recorder, type RecorderPhase } from '../lib/useRecorder'
import { useSecond } from '../store/useSecond'
import type {
  FeedbackResult,
  Goal,
  IntakeResult,
  LivingGraph,
  ScheduleDecision,
} from '../types/contract'
import styles from './Record.module.css'

/**
 * The way things get into Second: one button, one brain dump.
 *
 * Two transcripts run off the same microphone and the screen is honest about
 * both. The Web Speech API paints words as they are spoken, so there is
 * something true to read from the first second. `MediaRecorder` captures the
 * audio, `api.startVoice` puts it in front of Transcribe, and when the accurate
 * transcript lands it replaces the live one -- with a line saying so, because a
 * user who watches text change under them without explanation has learnt not to
 * trust the screen.
 *
 * **Intake is never sent automatically.** The upload starts on its own, because
 * that is a transcription job with no consequences; the brain dump reaches the
 * Intake graph only when the user presses the button. What Intake writes lands
 * in the Living Graph and on the calendar, and Second does not do that on the
 * strength of a microphone having gone quiet.
 *
 * **Questions are not a failure.** `clarifying_questions` non-empty usually
 * means the Intake graph stopped after the Extractor on purpose: it was not
 * clear enough what the user wanted to justify putting anything in their
 * calendar. That screen asks; it does not apologise. A plan shows placements
 * and deprioritisations at the same weight, per models.py: a scheduler that
 * only reports what it placed is hiding the decision it made.
 *
 * The two are typed independently -- only the `IntakeResult` docstring couples
 * them -- so `Outcome` reads both fields and can render both. A screen that
 * branched on the questions alone would tell the user nothing reached their
 * calendar without having looked at `schedule`.
 */
/** Below this the Extractor was not sure it heard a real, distinct goal, and
 * that is worth one line. Above it the number is a score nobody asked for.
 * Matches the threshold the Goals screen uses. */
const CONFIDENCE_WORTH_SAYING = 0.75

/** `1 route`, `2 routes`. Second counts things constantly; it should not say
 * "1 routes" while doing it. */
function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`
}

export function Record() {
  const recorder = useRecorder()
  const graph = useSecond((state) => state.graph)
  const loadGraph = useSecond((state) => state.loadGraph)

  /** The text that will be sent. Mirrors the live transcript until touched. */
  const [draft, setDraft] = useState('')
  const [edited, setEdited] = useState(false)

  const [job, setJob] = useState<Job>(IDLE_JOB)
  const [accurate, setAccurate] = useState<string | null>(null)
  const [swap, setSwap] = useState<Swap>('none')

  const [sending, setSending] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [result, setResult] = useState<IntakeResult | null>(null)
  const [written, setWritten] = useState<Written | null>(null)
  const [intakeProblem, setIntakeProblem] = useState<string | null>(null)

  const uploaded = useRef<Blob | null>(null)

  // The live transcript owns the box until the user types in it or the accurate
  // one takes over. No phase test: the last words settle a beat after stop, and
  // they belong in the box too.
  useEffect(() => {
    if (!recorder.liveSupported || edited || swap !== 'none') return
    setDraft(recorder.live)
  }, [recorder.live, recorder.liveSupported, edited, swap])

  // Upload, once per blob. StrictMode runs this effect twice in development and
  // a second `startVoice` would create a second Transcribe job, so the blob that
  // has already gone is remembered. The job id lands in state, which survives
  // StrictMode's remount, so the poll below picks it up either way.
  useEffect(() => {
    const audio = recorder.audio
    if (!audio || uploaded.current === audio) return
    uploaded.current = audio

    setJob({ state: 'uploading', problem: null })
    api
      .startVoice(audio)
      .then((id) => setJob({ state: 'running', id, problem: null }))
      .catch((error: unknown) => setJob({ state: 'failed', problem: errorLine(error) }))
  }, [recorder.audio])

  // Poll until Transcribe is done or has failed. Re-running this effect costs
  // one extra GET, which is why the cancel flag is all the cleanup it needs.
  useEffect(() => {
    if (job.state !== 'running' || !job.id) return
    const id = job.id
    let cancelled = false
    let attempts = 0
    let timer = 0

    const ask = () => {
      api
        .voiceJob(id)
        .then((next) => {
          if (cancelled) return
          if (next.status === 'done') {
            // Fixture mode answers `done` with a null transcript, and live the
            // field is nullable too. A done job with nothing in it must leave
            // the live transcript alone rather than blanking the box.
            if (next.transcript && next.transcript.trim()) setAccurate(next.transcript.trim())
            setJob({ state: 'done', problem: null })
            return
          }
          if (next.status === 'failed') {
            // The reason is Amazon Transcribe's own, carried through by the API
            // because the seam raises rather than returning a status. Quote it:
            // "the media format is not supported" is worth reading, and saying
            // there is no reason when there is one is the error message this
            // product exists not to write. `fullStop` adds the boundary the quote
            // does not carry, so the two sentences do not run together.
            const reason = next.detail?.trim()
            setJob({
              state: 'failed',
              problem: reason
                ? `Transcribing the audio failed: ${fullStop(reason)} The live transcript is what you have.`
                : 'Transcribing the audio failed, and the API gave no reason. The live transcript is what you have.',
            })
            return
          }
          attempts += 1
          if (attempts >= MAX_POLLS) {
            setJob({
              state: 'failed',
              problem: `Transcribing the audio is still running after ${Math.round((MAX_POLLS * POLL_MS) / 1000)} seconds. This screen stopped asking. The live transcript is what you have.`,
            })
            return
          }
          timer = window.setTimeout(ask, POLL_MS)
        })
        .catch((error: unknown) => {
          if (!cancelled) setJob({ state: 'failed', problem: errorLine(error) })
        })
    }

    timer = window.setTimeout(ask, POLL_MS)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [job.state, job.id])

  // The swap, decided in one place. Replacing text the user typed, or text that
  // has already been sent, would destroy work without asking -- so those two
  // cases are offered instead of taken.
  //
  // The comparison comes first because everything downstream of here describes
  // a change. Transcribe returning the words already in the box is a real case
  // -- it is the same speech -- and there is then nothing to offer and nothing
  // to announce: the offer would say the transcript "differs from the text in
  // the box" about identical text, and the replaced note would describe a
  // replacement the user did not see happen.
  useEffect(() => {
    if (accurate === null || swap !== 'none') return
    if (accurate.trim() === draft.trim()) {
      setSwap('unchanged')
      return
    }
    if (edited || sending || result !== null) {
      setSwap('offered')
      return
    }
    setDraft(accurate)
    setSwap('replaced')
  }, [accurate, swap, draft, edited, sending, result])

  // Seconds, because the brief forbids a spinner and a number is true.
  useEffect(() => {
    if (!sending) return
    setElapsed(0)
    const timer = window.setInterval(() => setElapsed((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [sending])

  /**
   * Pressing Record starts a new brain dump, so it clears the last one.
   *
   * Including anything typed into the box. The box is the fallback for a broken
   * microphone; somebody who typed their brain dump has no reason to then press
   * Record, and carrying stale text into a fresh recording would mean sending a
   * transcript that is half spoken and half left over.
   */
  const begin = () => {
    setDraft('')
    setEdited(false)
    setJob(IDLE_JOB)
    setAccurate(null)
    setSwap('none')
    setResult(null)
    setWritten(null)
    setIntakeProblem(null)
    uploaded.current = null
    recorder.start()
  }

  const send = () => {
    const transcript = draft.trim()
    if (!transcript) return

    // Captured at click time: this is the graph as it stood before Intake wrote
    // to it, which is the only thing that can say what the brain dump added.
    const before = graph

    setSending(true)
    setIntakeProblem(null)
    api
      .intake(transcript)
      .then((next) => {
        setResult(next)
        // With no before-graph there is no diff, and marking everything as new
        // would be a lie. `null` means the section is not shown at all.
        //
        // The whole diff is kept, not just `.added`. An intake that edits an
        // existing goal adds no id, and a screen holding only the additions
        // cannot tell that apart from an intake that wrote nothing. The version
        // is kept for the same reason: it is a fact about two graphs, and read
        // off the after-graph alone it can only be restated, never checked.
        setWritten(
          before ? { diff: diffGraphs(before, next.graph), version: before.version } : null,
        )
        // Intake wrote to the graph. The Living Graph screen reads the store,
        // so it would otherwise show a plan one brain dump out of date.
        void loadGraph()
      })
      .catch((error: unknown) => setIntakeProblem(errorLine(error)))
      .finally(() => setSending(false))
  }

  const words = draft.trim() ? draft.trim().split(/\s+/).length : 0
  const recording = recorder.phase === 'recording'

  return (
    <div className={styles.screen}>
      <header className={styles.head}>
        <h1 className={styles.title}>Record</h1>
        <p className={styles.what}>
          Say what you want. The Extractor takes the goals out of it, the Cascader walks the long
          ones down to a horizon that can hold a calendar slot, and the Scheduler fits what is left
          against the calendar it can see. It stops and asks instead when what you said was not
          clear enough to plan on.
        </p>
      </header>

      <div className={styles.capture}>
        {/* No `aria-pressed`: Record and Stop are two actions, not one held
          * state, so there is nothing for it to be the value of. Goals.tsx uses
          * it where there genuinely is one. The phase itself is announced by
          * `notes` pushing a line into the live region below -- which the
          * waveform cannot do, being `aria-hidden`, and the clock cannot do,
          * being a bare number. */}
        <button
          type="button"
          className={styles.trigger}
          disabled={recorder.phase === 'asking'}
          onClick={() => (recording ? recorder.stop() : begin())}
        >
          {TRIGGER[recorder.phase]}
        </button>
        <Waveform analyser={recorder.analyser} active={recording} />
        <span className={`tabular ${styles.clock}`}>{mmss(recorder.seconds)}</span>
      </div>

      {recorder.problem && <Problem what={recorder.problem} onRetry={begin} />}

      <div className={styles.notes} role="status" aria-live="polite">
        {notes(recorder, job, swap).map((note) => (
          <p key={note} className={styles.note}>
            {note}
          </p>
        ))}
      </div>

      <Section label="Transcript" aside={<span className="tabular">{plural(words, 'word')}</span>}>
        <label htmlFor="transcript" className={styles.boxLabel}>
          {recording
            ? 'Painted as you speak, and editable once you stop.'
            : 'Editable. Type here if the microphone is not available.'}
        </label>
        <textarea
          id="transcript"
          className={styles.box}
          value={draft}
          readOnly={recording || sending}
          spellCheck={false}
          rows={8}
          placeholder={recording ? '' : 'Nothing recorded yet.'}
          onChange={(event) => {
            setEdited(true)
            setDraft(event.target.value)
          }}
        />

        <div className={styles.send}>
          <button
            type="button"
            className={styles.primary}
            disabled={!draft.trim() || recording || sending}
            onClick={send}
          >
            {sending ? 'Intake is running' : result ? 'Send again' : 'Send to Second'}
          </button>

          {swap === 'offered' && accurate && (
            <p className={styles.offer}>
              The transcript from the upload is ready and differs from the text in the box.
              <button
                type="button"
                className={styles.link}
                onClick={() => {
                  setDraft(accurate)
                  setEdited(false)
                  setSwap('replaced')
                }}
              >
                Use it
              </button>
            </p>
          )}
        </div>
      </Section>

      {intakeProblem && <Problem what={intakeProblem} onRetry={send} />}

      {sending && (
        <p className={styles.working}>
          Extracting the goals, cascading the long ones to a horizon that can hold a slot, designing
          routes, then scheduling across every active goal at once.{' '}
          <span className="tabular">{elapsed}s</span> so far; tens of seconds is normal.
        </p>
      )}

      {result && (
        <div className={styles.results}>
          <Outcome result={result} />
          {written && <Added graph={result.graph} written={written} />}
        </div>
      )}
    </div>
  )
}

/* Written as a mapped type rather than `Record<...>`, because the component in
 * this file is also called Record and the two side by side read as one thing. */
const TRIGGER: { [phase in RecorderPhase]: string } = {
  idle: 'Record',
  asking: 'Asking for the microphone',
  recording: 'Stop',
  stopped: 'Record again',
}

/* The live region's half of the same state. `idle` says nothing: there is
 * nothing to announce about a microphone nobody has pressed yet. */
const PHASE_NOTE: { [phase in RecorderPhase]: string | null } = {
  idle: null,
  asking: 'Asking this browser for the microphone.',
  recording: 'Recording.',
  stopped: 'Recording stopped.',
}

const POLL_MS = 1500
const MAX_POLLS = 80

/**
 * What became of the accurate transcript.
 *
 * `unchanged` is the fourth state because the first three all describe a
 * change: it means Transcribe returned the words already in the box, so the
 * box is settled -- the live transcript no longer writes to it -- and there is
 * nothing to say about it.
 */
type Swap = 'none' | 'replaced' | 'offered' | 'unchanged'

interface Job {
  state: 'idle' | 'uploading' | 'running' | 'done' | 'failed'
  id?: string
  problem: string | null
}

const IDLE_JOB: Job = { state: 'idle', problem: null }

/** What one intake did to the graph, against the graph it was sent from. */
interface Written {
  diff: GraphDiff
  /** The version the graph carried BEFORE the intake, so it can be compared. */
  version: number
}

/**
 * What the page says about itself, in order, and only when it is true.
 *
 * Everything here is a fact about this browser, this microphone or this job.
 * The two transcripts fail independently and the line says which one is
 * affected, because "live transcription is unavailable" and "no transcript is
 * coming" are different news and a reader has to be able to tell them apart --
 * but the two halves are composed into one line rather than pushed as two,
 * because a browser missing both got both lines and they disagreed.
 *
 * This is also the screen's only announcement channel: it is the `role=status`
 * region, so the phase goes through here too.
 */
function notes(recorder: Recorder, job: Job, swap: Swap): string[] {
  const lines: string[] = []

  // One line composed from the two support booleans rather than two pushed
  // independently. Pushed independently they contradicted each other whenever
  // this browser had neither half: "the accurate transcript will arrive when
  // the upload finishes" and "no accurate transcript can be produced from it"
  // were both on the screen at once. The arrival is only stated while a job is
  // actually running -- before that there is nothing in flight to promise.
  if (!recorder.liveSupported && !recorder.captureSupported) {
    lines.push(
      'This browser has neither live transcription nor WebM recording, so no transcript can be made from the microphone. What you type in the box is all there is.',
    )
  } else if (!recorder.liveSupported) {
    lines.push(
      job.state === 'running'
        ? 'Live transcription is unavailable in this browser. The accurate transcript is on its way from the audio.'
        : 'Live transcription is unavailable in this browser. An accurate transcript is made from the audio once you stop recording.',
    )
  } else if (!recorder.captureSupported) {
    lines.push(
      'This browser does not record WebM audio, so no accurate transcript can be produced from it. What ends up in the box is all there is.',
    )
  }

  if (recorder.liveProblem) lines.push(recorder.liveProblem)

  // The phase, because nothing else announces it: the trigger carries no
  // `aria-pressed` to read back, the waveform is `aria-hidden` and the clock is
  // an unlabelled number.
  const phase = PHASE_NOTE[recorder.phase]
  if (phase) lines.push(phase)

  if (job.state === 'uploading') lines.push('Uploading the audio.')
  if (job.state === 'running') {
    lines.push(
      recorder.liveSupported
        ? 'Transcribing the audio. The accurate transcript will replace the live one.'
        : 'Transcribing the audio. There is no live transcript for it to replace.',
    )
  }
  if (job.state === 'failed' && job.problem) lines.push(job.problem)
  // `unchanged` says nothing on purpose: no text moved, so there is nothing to
  // explain. And with no live transcript there was nothing painted to be
  // replaced, which is the other half of the same claim.
  if (swap === 'replaced') {
    lines.push(
      recorder.liveSupported
        ? 'Transcript replaced. The text before this was painted as you spoke; this one was transcribed from the audio.'
        : 'The box now holds the transcript made from the audio.',
    )
  }

  return lines
}

/**
 * A quote given the sentence boundary it does not carry.
 *
 * `read_job` in src/second/api/voice.py passes Amazon Transcribe's
 * `FailureReason` through verbatim, and it ends without punctuation -- so
 * quoting it mid-line ran two sentences together: "...failed: the media format
 * is not supported The live transcript is what you have." The reason's own
 * words are untouched; only the boundary is added.
 */
function fullStop(quote: string): string {
  return /[.?!]$/.test(quote) ? quote : `${quote}.`
}

/** `2:07`. Minutes and seconds of a recording, which `duration` does not do. */
function mmss(total: number): string {
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

// ---------------------------------------------------------------------------

/**
 * A 1px line of the actual signal.
 *
 * `getByteTimeDomainData`, so this is a waveform. Frequency bars were the other
 * option and they read as a music visualiser, which tells the viewer the wrong
 * thing about what the page is for.
 *
 * The canvas is sized in device pixels and drawn in them, or it is soft on a
 * retina screen and on the recording. When nothing is being captured the same
 * element holds a flat line at rest rather than disappearing: the control is
 * still there, it just has no signal.
 */
function Waveform({ analyser, active }: { analyser: AnalyserNode | null; active: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const context = canvas.getContext('2d')
    if (!context) return

    const samples = new Uint8Array(analyser ? analyser.fftSize : 0)
    let frame = 0
    // Read off the element, never written here: the only colours this app has
    // live in tokens.css, and a canvas has no cascade of its own to inherit.
    let stroke = window.getComputedStyle(canvas).color
    let weight = 1

    const paint = () => {
      const { width, height } = canvas
      context.clearRect(0, 0, width, height)
      context.lineWidth = weight
      context.strokeStyle = stroke
      context.beginPath()

      if (analyser && active) {
        analyser.getByteTimeDomainData(samples)
        const middle = height / 2
        const reach = middle - weight
        for (let index = 0; index < samples.length; index += 1) {
          const x = (index / (samples.length - 1)) * width
          // 128 is silence, so the line rests in the middle on its own.
          const y = middle + ((samples[index] - 128) / 128) * reach
          if (index === 0) context.moveTo(x, y)
          else context.lineTo(x, y)
        }
      } else {
        context.moveTo(0, height / 2)
        context.lineTo(width, height / 2)
      }

      context.stroke()
      if (active) frame = requestAnimationFrame(paint)
    }

    const resize = () => {
      const ratio = window.devicePixelRatio || 1
      const box = canvas.getBoundingClientRect()
      // Setting width or height clears the context's state, which is why the
      // stroke and the line weight are re-applied inside `paint`.
      canvas.width = Math.max(1, Math.round(box.width * ratio))
      canvas.height = Math.max(1, Math.round(box.height * ratio))
      weight = ratio
      stroke = window.getComputedStyle(canvas).color || stroke
      if (!active) paint()
    }

    const observer = new ResizeObserver(resize)
    observer.observe(canvas)
    resize()
    if (active) frame = requestAnimationFrame(paint)

    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [analyser, active])

  return <canvas ref={canvasRef} className={styles.wave} aria-hidden="true" />
}

// ---------------------------------------------------------------------------

/**
 * Both fields, read together.
 *
 * `clarifying_questions` and `schedule` are typed independently and only the
 * `IntakeResult` docstring couples them, so a run carrying both is a shape the
 * contract permits. Returning on the questions alone had `Asked` telling the
 * user nothing was put in their calendar without anything on this path having
 * read `schedule` -- so when both arrive, both are shown, questions first
 * because they are the half that needs the user.
 */
function Outcome({ result }: { result: IntakeResult }) {
  if (result.clarifying_questions.length > 0) {
    return (
      <>
        <Asked questions={result.clarifying_questions} scheduled={result.schedule !== null} />
        {result.schedule && <Planned schedule={result.schedule} graph={result.graph} />}
      </>
    )
  }
  if (result.schedule) return <Planned schedule={result.schedule} graph={result.graph} />
  return (
    <p className={styles.nothing}>
      Intake returned no questions and no schedule. Nothing was placed and nothing was asked.
    </p>
  )
}

/**
 * Second asking back, which is the system working.
 *
 * Usually the Intake graph stopped after the Extractor because it was not clear
 * enough what the user wanted to justify putting anything in their calendar. So
 * the questions get the room a plan would have had, and there is no apology
 * anywhere on this path: a confident wrong plan is the worse outcome and this
 * is the screen that avoided it.
 *
 * `scheduled` is the one thing this component cannot work out for itself. The
 * sentence about the calendar is a claim about `schedule`, so it is only made
 * when the caller has read that field and found it null.
 */
function Asked({ questions, scheduled }: { questions: string[]; scheduled: boolean }) {
  const one = questions.length === 1

  return (
    <Section
      label={one ? 'One question back' : 'Questions back'}
      count={questions.length > 1 ? questions.length : undefined}
    >
      <p className={styles.stopped}>
        {scheduled ? (
          <>
            Intake asked and scheduled in the same run, so the plan below is not the whole answer.
            {one ? ' This question is' : ' These questions are'} still open.
          </>
        ) : (
          <>
            Intake stopped after the Extractor, so nothing was scheduled and nothing was put in the
            calendar. {one ? 'This is' : 'These are'} what it needs first.
          </>
        )}
      </p>

      <ol className={styles.questions}>
        {questions.map((question) => (
          <li key={question} className={styles.question}>
            {question}
          </li>
        ))}
      </ol>

      <Answer />
    </Section>
  )
}

/** The answer, sent as the user's own words to the Interpreter. */
function Answer() {
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const [reply, setReply] = useState<FeedbackResult | null>(null)
  const [failed, setFailed] = useState<string | null>(null)

  const send = () => {
    const answer = text.trim()
    if (!answer) return
    setSending(true)
    setFailed(null)
    api
      .feedback(answer)
      .then((next) => {
        setReply(next)
        setText('')
      })
      .catch((error: unknown) => setFailed(errorLine(error)))
      .finally(() => setSending(false))
  }

  return (
    <div className={styles.answer}>
      <label htmlFor="answer" className={styles.boxLabel}>
        Answer in your own words. It goes to the Interpreter, which turns it into typed changes.
      </label>
      <textarea
        id="answer"
        className={styles.box}
        value={text}
        rows={3}
        readOnly={sending}
        onChange={(event) => setText(event.target.value)}
      />

      <div className={styles.send}>
        <button
          type="button"
          className={styles.primary}
          disabled={!text.trim() || sending}
          onClick={send}
        >
          {sending ? 'Sending' : 'Send the answer'}
        </button>
      </div>

      {failed && <Problem what={failed} onRetry={send} />}

      {reply && (
        <div className={styles.reply}>
          {/* "At most one line back to the user. Often empty" is the contract's
            * own description of this field, so empty is an answer and not a gap
            * to fill. Substituting "Recorded." wrote a line the API did not
            * send, and asserted a write the response does not evidence. */}
          {reply.acknowledgement.trim().length > 0 && (
            <p className={styles.replyLine}>{reply.acknowledgement}</p>
          )}
          {/* Ground truth about a task, which beats every inference -- so it is
            * the one part of the reply that must not be dropped. All three
            * fields are shown: `did_it` as the label, the id as evidence, and
            * the user's own note when they gave one. */}
          {reply.completions.length > 0 && (
            <ul className={styles.updates}>
              {reply.completions.map((completion, index) => (
                <li key={`${completion.task_id}:${index}`} className={styles.update}>
                  <span className={styles.updateTarget}>
                    {completion.did_it ? 'done' : 'not done'}
                  </span>
                  <span className="evidence">{completion.task_id}</span>
                  {completion.note && (
                    <span className={styles.completionNote}>{completion.note}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {reply.updates.length > 0 && (
            <ul className={styles.updates}>
              {reply.updates.map((update, index) => (
                <li key={`${update.target}:${index}`} className={styles.update}>
                  <span className={styles.updateTarget}>{update.target}</span>
                  {update.change}
                </li>
              ))}
            </ul>
          )}
          {reply.intentions.length > 0 && (
            <ul className={styles.updates}>
              {reply.intentions.map((intention) => (
                <li key={intention} className={styles.update}>
                  <span className={styles.updateTarget}>today</span>
                  {intention}
                </li>
              ))}
            </ul>
          )}
          {/* Four empty fields is a real answer rather than a render that went
            * missing, and with the acknowledgement no longer invented there is
            * nothing else on the page to say so. */}
          {reply.acknowledgement.trim().length === 0 &&
            reply.completions.length === 0 &&
            reply.updates.length === 0 &&
            reply.intentions.length === 0 && (
              <p className={styles.nothing}>
                The Interpreter typed nothing from that answer: no changes, no completions, no
                intentions, and no line back.
              </p>
            )}
        </div>
      )}
    </div>
  )
}

/**
 * What the Scheduler decided, both halves of it.
 *
 * models.py is blunt about this: a scheduler that only reports what it placed is
 * hiding the decision it actually made. So the deprioritised list is the same
 * type size, in the same kind of section, with the same amount of room as the
 * placements -- and it says plainly when nothing lost, rather than vanishing
 * and leaving the reader to assume nothing did.
 *
 * `Placement` carries a `task_id` and no title, so titles are resolved against
 * the graph this same result carried. When an id is not in it, the id is shown
 * as it stands: inventing a title for a task Second cannot find is exactly the
 * kind of plausible-looking fiction this product must not produce.
 *
 * Exported for the Memory screen, which shows what an answer to its week or
 * month question planned. That answer is planned by the same graph as a brain
 * dump and returns the same `ScheduleDecision`, so it is drawn the same way.
 */
export function Planned({ schedule, graph }: { schedule: ScheduleDecision; graph: LivingGraph }) {
  const named = useMemo(() => taskIndex(graph), [graph])

  return (
    <>
      <Section
        label="Placed"
        count={schedule.placed.length}
        aside={
          schedule.placed.length > 0 ? (
            <span className="tabular">
              {duration(schedule.placed.reduce((sum, one) => sum + one.duration_min, 0))}
            </span>
          ) : undefined
        }
      >
        {schedule.placed.length === 0 ? (
          <p className={styles.nothing}>Nothing was placed.</p>
        ) : (
          <ul className={styles.decided}>
            {schedule.placed.map((placement) => {
              const task = named.get(placement.task_id)
              return (
                <li key={`${placement.task_id}:${placement.start}`} className={styles.held}>
                  <p className={styles.decidedTitle}>
                    {task ? task.title : <span className="evidence">{placement.task_id}</span>}
                  </p>
                  <p className={`tabular ${styles.when}`}>
                    <time dateTime={placement.start}>
                      {shortDate(placement.start)} {clockTime(placement.start)}
                    </time>
                    <span className={styles.dot}>·</span>
                    {duration(placement.duration_min)}
                  </p>
                  {task ? (
                    <Serving chain={task.serves} />
                  ) : (
                    <p className={styles.serves}>
                      This id is not in the graph this result carried.
                    </p>
                  )}
                  <p className={styles.ref}>
                    {placement.calendar_event_id ? (
                      <span className="evidence">
                        calendar event {placement.calendar_event_id}
                      </span>
                    ) : (
                      'Not written to the calendar.'
                    )}
                  </p>
                </li>
              )
            })}
          </ul>
        )}
      </Section>

      <Section label="Deprioritised" count={schedule.deprioritised.length}>
        {schedule.deprioritised.length === 0 ? (
          <p className={styles.nothing}>Nothing lost a slot to this plan.</p>
        ) : (
          <ul className={styles.decided}>
            {schedule.deprioritised.map((loss) => {
              const task = named.get(loss.task_id)
              return (
                <li key={`${loss.task_id}:${loss.wanted}`} className={styles.slipped}>
                  <p className={styles.decidedTitle}>
                    {task ? task.title : <span className="evidence">{loss.task_id}</span>}
                  </p>
                  <p className={`tabular ${styles.when}`}>wanted {loss.wanted}</p>
                  <p className={styles.lostTo}>lost to {loss.lost_to}</p>
                  {task ? (
                    <Serving chain={task.serves} />
                  ) : (
                    <p className={styles.serves}>
                      This id is not in the graph this result carried.
                    </p>
                  )}
                  <p className={`evidence ${styles.reason}`}>{loss.reason}</p>
                </li>
              )
            })}
          </ul>
        )}
      </Section>

      <Section label="How the competition was resolved">
        <p className={styles.rationale}>{schedule.rationale}</p>
      </Section>
    </>
  )
}

/**
 * What this brain dump put in the graph.
 *
 * A fact about two graphs, which is why it is diffed rather than read off one:
 * nothing in `IntakeResult` marks a goal as new. `extraction_confidence` is
 * shown as the number it is -- how sure the Extractor was that this is a real,
 * distinct goal -- because a goal recorded at 0.61 is worth a second look and an
 * adjective would hide that.
 *
 * The version is a fact about two graphs for the same reason, so it is
 * compared and not merely printed. An intake that edited an existing goal
 * rather than adding one adds no id at all: it lands in the empty state below
 * with the version already moved, and "still at version N" would then be the
 * screen contradicting the number beside it.
 */
function Added({ graph, written }: { graph: LivingGraph; written: Written }) {
  const { diff } = written
  const goals = graph.goals.filter((goal) => diff.added.has(goal.id))

  let routes = 0
  let tasks = 0
  for (const goal of graph.goals) {
    for (const route of goal.routes) {
      if (diff.added.has(route.id)) routes += 1
      for (const task of route.tasks) if (diff.added.has(task.id)) tasks += 1
    }
  }

  const changed = diff.changed.size
  const facts = diff.personFacts.length
  const moved = written.version !== graph.version

  if (goals.length === 0 && routes === 0 && tasks === 0) {
    return (
      <p className={styles.nothing}>
        Nothing new reached the graph.{' '}
        {!moved ? (
          <>
            It is still at version <span className="tabular">{graph.version}</span>.
          </>
        ) : (
          <>
            The version moved from <span className="tabular">{written.version}</span> to{' '}
            <span className="tabular">{graph.version}</span>:{' '}
            {changed > 0
              ? `${changed} existing ${changed === 1 ? 'entry' : 'entries'} changed.`
              : facts > 0
                ? `the person layer gained ${facts} ${facts === 1 ? 'fact' : 'facts'}.`
                : 'nothing this screen compares moved with it.'}
          </>
        )}
      </p>
    )
  }

  return (
    <Section
      label="New in the graph"
      count={goals.length}
      aside={
        <span className="tabular">
          {plural(routes, 'route')} · {plural(tasks, 'task')}
          {changed > 0 && ` · ${changed} changed`} · version {graph.version}
        </span>
      }
    >
      {goals.length === 0 ? (
        <p className={styles.nothing}>No new goals. The routes and tasks hang off existing ones.</p>
      ) : (
        <ul className={styles.goals}>
          {goals.map((goal) => (
            <li key={goal.id} className={styles.goal}>
              <span className={styles.goalTitle}>{goal.title}</span>
              <span className={styles.horizon}>{HORIZON_LABEL[goal.horizon]}</span>
              {/* Only when the Extractor was unsure. Printed on every row it
                * reads as a score being kept on the user; printed on the one
                * row that earned it, it is Second saying it may have misheard.
                * Same threshold as the Goals screen. */}
              {goal.extraction_confidence < CONFIDENCE_WORTH_SAYING && (
                <span className={`tabular ${styles.confidence}`}>
                  heard with {Math.round(goal.extraction_confidence * 100)}% confidence
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}

/**
 * The ladder above a task, in the shape Today already uses for it.
 *
 * `components/BlockRow.tsx` renders this same relationship in this same row
 * position, as a labelled arrow chain built from `goal_title` + `serves`. Two
 * screens describing the same relationship two different ways teaches the
 * reader that neither means anything in particular, so this is that component's
 * markup, against the chain `Named.serves` carries.
 */
function Serving({ chain }: { chain: string[] }) {
  return (
    <p className={styles.serves}>
      <span className={styles.servesLabel}>serving</span>
      {chain.map((title, index) => (
        <span key={`${title}:${index}`} className={styles.rung}>
          {index > 0 && <span className={styles.arrow}>→</span>}
          {title}
        </span>
      ))}
    </p>
  )
}

/** A task's own title and the goal ladder above it, both from the graph. */
interface Named {
  title: string
  /** The owning goal, then every rung above it, nearest first. */
  serves: string[]
}

/** task_id to the title and the ladder above it, from the graph in hand. */
function taskIndex(graph: LivingGraph): Map<string, Named> {
  const byId = new Map<string, Goal>()
  for (const goal of graph.goals) byId.set(goal.id, goal)

  const out = new Map<string, Named>()
  for (const goal of graph.goals) {
    // One walk per goal rather than one per task: every task under a goal hangs
    // off the same ladder.
    const chain = ladder(goal, byId)
    for (const route of goal.routes) {
      for (const task of route.tasks) out.set(task.id, { title: task.title, serves: chain })
    }
  }
  return out
}

/**
 * The owning goal and every rung above it, nearest first.
 *
 * `ScheduledBlock` arrives with this chain denormalised onto it; `IntakeResult`
 * denormalises nothing, so it is walked up `contributes_to` here. The route is
 * deliberately not on it: a route is one way of reaching the nearest goal, not a
 * rung on the ladder of goals above it, and putting it in the chain would have
 * the arrows claim a relationship the graph does not hold.
 *
 * Bounded by a seen-set. `contributes_to` is a plain id the schema does not
 * constrain, so a cycle in it is possible and would otherwise hang the render.
 */
function ladder(goal: Goal, byId: Map<string, Goal>): string[] {
  const titles = [goal.title]
  const seen = new Set([goal.id])

  let above = goal.contributes_to
  while (above !== null && !seen.has(above)) {
    seen.add(above)
    const rung = byId.get(above)
    // A `contributes_to` pointing outside the graph in hand stops the chain
    // rather than inventing the rung it names.
    if (!rung) break
    titles.push(rung.title)
    above = rung.contributes_to
  }

  return titles
}
