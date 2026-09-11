/**
 * The nine routes, and nothing else.
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
  IntakeResult,
  LivingGraph,
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

export const USING_FIXTURES = import.meta.env.VITE_SOURCE === 'fixtures'

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

export const api = {
  graph(): Promise<LivingGraph> {
    if (USING_FIXTURES) return fixture(graphFixture)
    return call<{ graph: LivingGraph }>('/api/graph').then((body) => body.graph)
  },

  today(): Promise<DailyBrief> {
    if (USING_FIXTURES) return fixture(briefQuietFixture)
    return call<DailyBrief>('/api/today')
  },

  /** Runs the whole Daily graph. Tens of seconds when it is real. */
  runDaily(): Promise<DailyBrief> {
    if (USING_FIXTURES) return fixture(briefPreparedFixture, 1400)
    return call<DailyBrief>('/api/daily/run', { method: 'POST' })
  },

  audit(limit = 50): Promise<AuditEntry[]> {
    if (USING_FIXTURES) return fixture((auditFixture as AuditEntry[]).slice(0, limit))
    return call<{ entries: AuditEntry[] }>(`/api/audit?limit=${limit}`).then((body) => body.entries)
  },

  intake(transcript: string): Promise<IntakeResult> {
    if (USING_FIXTURES) {
      const muddy = transcript.trim().length < 40
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

/** The other two briefs, so the demo can show every state Today has without
 * waiting for a live run to happen to produce one. */
export const fixtureBriefs = {
  quiet: briefQuietFixture as DailyBrief,
  prepared: briefPreparedFixture as DailyBrief,
  decision: briefDecisionFixture as DailyBrief,
  checkIn: briefCheckinFixture as DailyBrief,
}
