/**
 * The thirteen routes, and nothing else.
 *
 * **Errors say what failed.** The product's voice is evidence-first and that
 * applies to its failures: no "Something went wrong". An `ApiError` carries the
 * line the screen shows, and the server's own message is preferred over
 * anything invented here -- when the backend says
 * `second.agents.observer does not exist yet (owned by AGENTS)`, that sentence
 * is more useful to everyone, including a judge, than "Failed to load".
 *
 * **Fixture mode is explicit and visible.** Set `VITE_SOURCE=fixtures` to
 * develop against checked-in payloads generated from the real code paths. The
 * rail shows a marker while it is on, because a screen full of fixture data
 * that looks live is the one kind of dishonesty this app must not commit.
 */

import type {
  AuditEntry,
  DailyBrief,
  FeedbackResult,
  Goal,
  GoalStatusChange,
  HorizonAsked,
  HorizonQuestion,
  IntakeResult,
  LivingGraph,
  Memory,
  Schedule,
} from '../types/contract'

import auditFixture from '../fixtures/audit.json'
import briefCheckinFixture from '../fixtures/brief-checkin.json'
import briefDecisionFixture from '../fixtures/brief-decision.json'
import briefPreparedFixture from '../fixtures/brief-prepared.json'
import briefQuietFixture from '../fixtures/brief-quiet.json'
import goalPausedFixture from '../fixtures/goal-paused.json'
import goalRetiredFixture from '../fixtures/goal-retired.json'
import graphAfterRunFixture from '../fixtures/living-graph-after-run.json'
import graphFixture from '../fixtures/living-graph.json'
import intakePlannedFixture from '../fixtures/intake-planned.json'
import intakeQuestionsFixture from '../fixtures/intake-questions.json'
import memoryCheckinFixture from '../fixtures/memory-checkin.json'
import memoryDecisionFixture from '../fixtures/memory-decision.json'
import memoryQuietFixture from '../fixtures/memory-quiet.json'
import memoryFixture from '../fixtures/memory.json'
import questionAnswerWeekFixture from '../fixtures/question-answer-week.json'
import questionSkipWeekFixture from '../fixtures/question-skip-week.json'
import scheduleCheckinFixture from '../fixtures/schedule-checkin.json'
import scheduleDecisionFixture from '../fixtures/schedule-decision.json'
import scheduleQuietFixture from '../fixtures/schedule-quiet.json'
import scheduleFixture from '../fixtures/schedule.json'

export const USING_FIXTURES = import.meta.env.VITE_SOURCE === 'fixtures'

/** Phrases that mark an intake as too unsure to plan on. Fixture mode only.
 * Whole phrases rather than short fragments, because a fragment like "uh" is
 * inside ordinary words and would send clear goals to the questions result. */
const HEDGES = ['umm', 'i guess', 'sort of', 'kind of', 'maybe', 'not sure']

export class ApiError extends Error {
  readonly status: number
  readonly route: string

  constructor(message: string, status: number, route: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.route = route
  }
}

/** The line a screen puts on the page. Plain, specific, no apology. */
export function errorLine(error: unknown): string {
  if (error instanceof ApiError) {
    return error.status === 0 ? `${error.message} (${error.route})` : error.message
  }
  if (error instanceof Error) return error.message
  return String(error)
}

async function call<T>(route: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(route, {
      ...init,
      headers: { Accept: 'application/json', ...(init?.headers ?? {}) },
    })
  } catch (cause) {
    // A failed fetch has no status and no body. Saying which call could not be
    // made is the only useful thing available.
    throw new ApiError('The API did not answer. Is uvicorn running on port 8000?', 0, route)
  }

  if (!response.ok) throw new ApiError(await serverMessage(response, route), response.status, route)

  return (await response.json()) as T
}

/** FastAPI puts a plain string in `detail`; anything else is reported verbatim. */
async function serverMessage(response: Response, route: string): Promise<string> {
  const raw = await response.text()
  try {
    const body = JSON.parse(raw) as { detail?: unknown }
    if (typeof body.detail === 'string' && body.detail.trim()) return body.detail
    if (body.detail) return JSON.stringify(body.detail)
  } catch {
    if (raw.trim()) return raw.trim().slice(0, 300)
  }
  return `${route} returned ${response.status} ${response.statusText}`.trim()
}

function json(body: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

/** Fixture mode pauses briefly so loading states are real rather than theoretical. */
function fixture<T>(value: unknown, delayMs = 260): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value as T), delayMs))
}

// ---------------------------------------------------------------------------

export type VoiceStatus = 'running' | 'done' | 'failed'

export interface VoiceJob {
  status: VoiceStatus
  transcript: string | null
  /** Why it failed, in Transcribe's own words.
   *
   * `second.voice.get_transcription` never returns `failed` -- it raises, with
   * Amazon Transcribe's `FailureReason` attached -- and the HTTP layer converts
   * that into this field. So a failed job always has something to say, and the
   * screen should say it rather than reporting that no reason exists. */
  detail?: string | null
}

export type QuestionHorizon = HorizonQuestion['horizon']

/**
 * What answering or skipping the month question comes back with when there is no backend.
 *
 * The week question has generated replies: make_fixtures.py sends one answer
 * through the real intake graph and one skip through `service.skip_question`,
 * and those two payloads are returned below. Nothing was generated for the
 * month question. `intake-planned.json` is a plan for a different sentence, and
 * the week skip names the week's cadence; returning either would show the user
 * a result that never happened. So the month question gets this, which says
 * what did happen, and the screen shows it in place of a result.
 */
export interface FixtureAcknowledgement {
  fixture: true
  line: string
}

export function isFixtureAcknowledgement(reply: object): reply is FixtureAcknowledgement {
  return 'fixture' in reply && reply.fixture === true
}

/** The four morning runs make_fixtures.py generates. Fixture mode only. */
export type FixtureState = 'quiet' | 'prepared' | 'decision' | 'checkIn'

/**
 * Fixture mode only: each morning run's brief, and the memory and schedule written from the same store.
 *
 * make_fixtures.py writes all three straight after each run. One schedule for every brief put the
 * gym at 07:00 on Schedule while the decision brief, whose Adapter never ran, put it at 18:00 on
 * Today. The store names the state it is showing and the files are picked by that name, never by
 * looking at the brief, so the three screens cannot show two different mornings.
 */
const FIXTURE_WORLDS: Record<FixtureState, { brief: DailyBrief; memory: Memory; schedule: Schedule }> = {
  quiet: {
    brief: briefQuietFixture as DailyBrief,
    memory: memoryQuietFixture as Memory,
    schedule: scheduleQuietFixture as Schedule,
  },
  prepared: {
    brief: briefPreparedFixture as DailyBrief,
    memory: memoryFixture as Memory,
    schedule: scheduleFixture as Schedule,
  },
  decision: {
    brief: briefDecisionFixture as DailyBrief,
    memory: memoryDecisionFixture as Memory,
    schedule: scheduleDecisionFixture as Schedule,
  },
  checkIn: {
    brief: briefCheckinFixture as DailyBrief,
    memory: memoryCheckinFixture as Memory,
    schedule: scheduleCheckinFixture as Schedule,
  },
}

/** The cadence the generated memory fixture carries for a horizon, quoted
 * rather than restated, so the fixture-mode line cannot drift from settings.py. */
function fixtureCadence(horizon: QuestionHorizon): string {
  const asked = (memoryFixture as Memory).questions.find((question) => question.horizon === horizon)
  return asked ? ` Live, this question is not asked again for ${asked.every_days} days.` : ''
}

export const api = {
  graph(): Promise<LivingGraph> {
    if (USING_FIXTURES) return fixture(graphFixture)
    return call<{ graph: LivingGraph }>('/api/graph').then((body) => body.graph)
  },

  /** Fixture mode answers with the quiet run's brief; the store records that as the state. */
  today(): Promise<DailyBrief> {
    if (USING_FIXTURES) return fixture(FIXTURE_WORLDS.quiet.brief)
    return call<DailyBrief>('/api/today')
  },

  /** Runs the whole Daily graph. Tens of seconds when it is real. Fixture mode
   * answers with the prepared run's brief; the store records that as the state. */
  runDaily(): Promise<DailyBrief> {
    if (USING_FIXTURES) return fixture(FIXTURE_WORLDS.prepared.brief, 1400)
    return call<DailyBrief>('/api/daily/run', { method: 'POST' })
  },

  /** Today and the days after it, placed and proposed. A read: no model, no write.
   * With no `days`, the server's own default window applies.
   *
   * `state` matters only in fixture mode, for the reason `memory` gives. */
  schedule(days?: number, state: FixtureState = 'quiet'): Promise<Schedule> {
    if (USING_FIXTURES) {
      // The fixture holds the seven days the generator produced. A shorter
      // window is the start of it; a longer one gets those seven, because a day
      // the generator did not compute is not one this file can make up.
      const generated = FIXTURE_WORLDS[state].schedule
      return fixture({ ...generated, days: generated.days.slice(0, days ?? generated.days.length) })
    }
    return call<Schedule>(days === undefined ? '/api/schedule' : `/api/schedule?days=${days}`)
  },

  /** Today's items from every source, each source's status, and any due question. A read.
   *
   * `state` matters only in fixture mode, and the store passes the one Today is
   * showing. Each memory fixture was generated straight after one of the four
   * morning runs, so it lists only what that run left behind, and Memory cannot
   * contradict Today by listing a draft the brief on screen never prepared.
   * Live, the server reads its own store and the argument is not sent. */
  memory(state: FixtureState = 'quiet'): Promise<Memory> {
    if (USING_FIXTURES) return fixture(FIXTURE_WORLDS[state].memory)
    return call<Memory>('/api/memory')
  },

  /** Answer a recurring question. Live, it is planned like a brain dump, so tens of seconds. */
  answerQuestion(horizon: QuestionHorizon, text: string): Promise<IntakeResult | FixtureAcknowledgement> {
    if (USING_FIXTURES) {
      // The week answer was generated through the real intake graph. The month
      // answer never was, so it gets a line saying nothing happened rather than
      // a plan made for some other sentence.
      if (horizon === 'week') return fixture(questionAnswerWeekFixture, 1600)
      return fixture(
        {
          fixture: true,
          line:
            'Fixture mode: no answer to the month question was generated, so this one was not ' +
            'sent, nothing was planned and nothing was written.',
        } satisfies FixtureAcknowledgement,
        900,
      )
    }
    return call<IntakeResult>('/api/questions/answer', json({ horizon, text }))
  },

  /** Not now. Live, the server records the day and says when the question may come back. */
  skipQuestion(horizon: QuestionHorizon): Promise<HorizonAsked | FixtureAcknowledgement> {
    if (USING_FIXTURES) {
      // Generated from `service.skip_question` for the week only, for the same
      // reason as the answer above.
      if (horizon === 'week') return fixture(questionSkipWeekFixture)
      return fixture({
        fixture: true,
        line:
          'Fixture mode: no skip of the month question was generated, so it was not recorded ' +
          `and reloading the page brings it back.${fixtureCadence(horizon)}`,
      } satisfies FixtureAcknowledgement)
    }
    return call<HorizonAsked>('/api/questions/skip', json({ horizon }))
  },

  audit(limit = 50): Promise<AuditEntry[]> {
    if (USING_FIXTURES) return fixture((auditFixture as AuditEntry[]).slice(0, limit))
    return call<{ entries: AuditEntry[] }>(`/api/audit?limit=${limit}`).then((body) => body.entries)
  },

  intake(transcript: string): Promise<IntakeResult> {
    if (USING_FIXTURES) {
      // Hesitation, not length, picks the fixture. This used to be
      // `length < 40`, which sent each fixture's own sentence to the wrong
      // result: "I want to write in public every week." is 37 characters and
      // came back asking whether "fitter" meant running or climbing, while
      // "umm, I guess I want to be fitter, sort of, this year maybe" is 58 and
      // came back with a confident writing plan. On camera that reads as the
      // product not listening. Now a clear sentence gets the plan and a hedged
      // one gets the questions, which is the distinction the two payloads were
      // generated to show. Anything this short is too little to plan on either.
      const said = transcript.trim().toLowerCase()
      const hedged = HEDGES.some((hedge) => said.includes(hedge))
      const muddy = said.length < 15 || hedged
      return fixture(muddy ? intakeQuestionsFixture : intakePlannedFixture, 1600)
    }
    return call<IntakeResult>('/api/intake', json({ transcript }))
  },

  feedback(text: string): Promise<FeedbackResult> {
    if (USING_FIXTURES) {
      return fixture({
        completions: [],
        updates: [],
        intentions: [],
        acknowledgement: 'Noted. The next run will use it.',
      })
    }
    return call<FeedbackResult>('/api/feedback', json({ text }))
  },

  setGoalStatus(goalId: string, status: Goal['status']): Promise<GoalStatusChange> {
    if (USING_FIXTURES) {
      if (status === 'retired') return fixture(goalRetiredFixture, 420)
      if (status === 'paused') return fixture(goalPausedFixture, 420)
      return fixture({ graph: graphFixture, freed: [], freed_minutes: 0, note: 'Active again.' }, 420)
    }
    return call<GoalStatusChange>(`/api/goals/${encodeURIComponent(goalId)}/status`, json({ status }))
  },

  startVoice(audio: Blob): Promise<string> {
    if (USING_FIXTURES) return fixture('fixture-job', 200)
    const form = new FormData()
    // The filename is for the S3 object and the logs, not for format detection:
    // `start_transcription` passes MediaFormat to Transcribe explicitly. What
    // has to be right is the blob's type -- bare `audio/webm`, no codecs
    // parameter -- because a presigned PUT signs the content type.
    form.append('audio', audio, 'intake.webm')
    return call<{ job_id: string }>('/api/voice', { method: 'POST', body: form }).then(
      (body) => body.job_id,
    )
  },

  voiceJob(jobId: string): Promise<VoiceJob> {
    if (USING_FIXTURES) {
      // A done job with a null transcript, which is a real case: the accurate
      // version has nothing to add, so the live one stands.
      return fixture({ status: 'done', transcript: null } satisfies VoiceJob, 400)
    }
    return call<VoiceJob>(`/api/voice/${encodeURIComponent(jobId)}`)
  },
}

/** The graph as it stands after a Daily run. Fixture mode only -- live, the
 * screen simply refetches `/api/graph`, which is the point of the demo beat. */
export const fixtureGraphAfterRun = graphAfterRunFixture as LivingGraph

/** Every brief by state, so the demo can show each state Today has without
 * waiting for a live run to happen to produce one. */
export function fixtureBrief(state: FixtureState): DailyBrief {
  return FIXTURE_WORLDS[state].brief
}
