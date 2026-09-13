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

import { findReply } from '../lib/findReply'
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
import graphCheckinFixture from '../fixtures/living-graph-checkin.json'
import graphDecisionFixture from '../fixtures/living-graph-decision.json'
import graphQuietFixture from '../fixtures/living-graph-quiet.json'
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
import { longDate } from '../lib/datetime'

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
 * Fixture mode only: each morning run's brief, and the memory, schedule and graph written from the same store.
 *
 * make_fixtures.py writes all four straight after each run. One schedule for every brief put the
 * gym at 07:00 on Schedule while the decision brief, whose Adapter never ran, put it at 18:00 on
 * Today. One graph for every brief did the same on the Living Graph and Goals: they drew the seeded
 * world's 18:00 gym beside a quiet Today at 07:00. The store names the state it is showing and the
 * files are picked by that name, never by looking at the brief, so no two screens can show two
 * different mornings.
 */
const FIXTURE_WORLDS: Record<
  FixtureState,
  { brief: DailyBrief; memory: Memory; schedule: Schedule; graph: LivingGraph }
> = {
  quiet: {
    brief: briefQuietFixture as DailyBrief,
    memory: memoryQuietFixture as Memory,
    schedule: scheduleQuietFixture as Schedule,
    graph: graphQuietFixture as LivingGraph,
  },
  prepared: {
    brief: briefPreparedFixture as DailyBrief,
    memory: memoryFixture as Memory,
    schedule: scheduleFixture as Schedule,
    graph: graphAfterRunFixture as LivingGraph,
  },
  decision: {
    brief: briefDecisionFixture as DailyBrief,
    memory: memoryDecisionFixture as Memory,
    schedule: scheduleDecisionFixture as Schedule,
    graph: graphDecisionFixture as LivingGraph,
  },
  checkIn: {
    brief: briefCheckinFixture as DailyBrief,
    memory: memoryCheckinFixture as Memory,
    schedule: scheduleCheckinFixture as Schedule,
    graph: graphCheckinFixture as LivingGraph,
  },
}

/**
 * Fixture mode only: the goal statuses set this session, by goal id.
 *
 * Nothing can be written to a checked-in graph, so a pause or retire is kept as this and laid over
 * whichever state's graph is on screen. That is the whole of what the write does to the graph:
 * goal-retired.json and goal-paused.json differ from the graph they were made from in that one
 * goal's status and nothing else. Laying it over each state's own graph keeps a retire through a
 * state switch, and keeps a second change from undoing the first, which returning the whole
 * checked-in graph did.
 */
export type GoalStatuses = Record<string, Goal['status']>

function withStatuses(graph: LivingGraph, statuses: GoalStatuses): LivingGraph {
  if (Object.keys(statuses).length === 0) return graph
  return {
    ...graph,
    goals: graph.goals.map((goal) =>
      statuses[goal.id] === undefined ? goal : { ...goal, status: statuses[goal.id] },
    ),
  }
}

/** Fixture mode only: the graph a state's run left, with this session's goal statuses laid over it. */
export function fixtureGraph(state: FixtureState, statuses: GoalStatuses = {}): LivingGraph {
  return withStatuses(FIXTURE_WORLDS[state].graph, statuses)
}

/**
 * Fixture mode only: the seeded world before any run, with the same statuses laid over it.
 *
 * The Living Graph diffs a state's graph against this. The statuses go on both sides so a retire
 * made this session is not reported as something a run changed.
 */
export function fixtureSeededGraph(statuses: GoalStatuses = {}): LivingGraph {
  return withStatuses(graphFixture as LivingGraph, statuses)
}

/**
 * The day the week answer, the week skip and the two goal status changes were generated on.
 *
 * make_fixtures.py makes all four from `prepared_world()`, the prepared run on TODAY, so the
 * prepared brief's own date is that day and nothing here restates it.
 */
const GENERATED_ON = FIXTURE_WORLDS.prepared.brief.on

/**
 * Fixture mode only: the states the generated week answer and week skip are true in.
 *
 * Both were generated after the prepared run on Thursday 10 September. The quiet run leaves the
 * same graph, so they hold there too. The decision run leaves a different graph, and the check-in
 * is the next morning: the answer's placements were checked against a world neither state has, and
 * the skip says it was recorded on a day that is not the check-in's. So those two get a line saying
 * nothing was generated for them, in place of a reply that never happened there.
 */
const WEEK_REPLIES_HOLD_IN: readonly FixtureState[] = ['quiet', 'prepared']

export function fixtureWeekRepliesHold(state: FixtureState): boolean {
  return WEEK_REPLIES_HOLD_IN.includes(state)
}

const GENERATED_STATUS_CHANGES = [goalRetiredFixture, goalPausedFixture] as GoalStatusChange[]

/**
 * A goal with its status taken out, and the ids and titles of the goals above it.
 *
 * What a pause or retire frees is read off exactly these: the goal's own tasks and their slots, and
 * the ladder each freed block names in `serves`. When they are the same in two graphs on the same
 * day, the same change frees the same slots in both.
 */
function footprint(graph: LivingGraph, goalId: string): string | null {
  const byId = new Map(graph.goals.map((goal) => [goal.id, goal]))
  const goal = byId.get(goalId)
  if (!goal) return null
  const { status: _status, ...rest } = goal
  const above: string[] = []
  const seen = new Set([goal.id])
  let parent = goal.contributes_to ? byId.get(goal.contributes_to) : undefined
  while (parent && !seen.has(parent.id)) {
    seen.add(parent.id)
    above.push(`${parent.id}:${parent.title}`)
    parent = parent.contributes_to ? byId.get(parent.contributes_to) : undefined
  }
  return JSON.stringify([rest, above])
}

/**
 * Fixture mode only: the reply to a pause or retire, true of the state on screen.
 *
 * Two changes were generated: retiring one goal and pausing another, on the prepared world. A
 * generated reply is returned only for that goal and that status, in a state on the same day whose
 * graph gives that goal the same tasks, slots and ladder. Anywhere else the freed slots it lists are
 * not known, so the reply names the change, which the graph does carry, and says why no freed time
 * is shown.
 */
function fixtureStatusChange(
  goalId: string,
  status: Goal['status'],
  state: FixtureState,
  statuses: GoalStatuses,
): GoalStatusChange {
  const graph = fixtureGraph(state, { ...statuses, [goalId]: status })
  const title = graph.goals.find((goal) => goal.id === goalId)?.title ?? goalId
  const nothingFreed = (note: string): GoalStatusChange => ({
    goal_id: goalId,
    goal_title: title,
    status,
    graph,
    freed: [],
    freed_minutes: 0,
    note,
  })

  if (status === 'active') return nothingFreed('Active again.')

  const doing = status === 'retired' ? 'retiring' : 'pausing'
  const opening = `Fixture mode: “${title}” is now ${status} on every screen.`

  const generated = GENERATED_STATUS_CHANGES.find(
    (change) => change.goal_id === goalId && change.status === status,
  )
  if (!generated) {
    return nothingFreed(`${opening} What ${doing} it released was not generated, so no freed time is shown.`)
  }

  const sameDay = FIXTURE_WORLDS[state].brief.on === GENERATED_ON
  const sameGoal = footprint(FIXTURE_WORLDS[state].graph, goalId) === footprint(generated.graph, goalId)
  if (!sameDay || !sameGoal) {
    return nothingFreed(
      `${opening} What ${doing} it released was generated for ${longDate(GENERATED_ON)} ` +
        'and does not hold for this state, so no freed time is shown.',
    )
  }

  return { ...generated, graph }
}

/** The cadence the generated memory fixture carries for a horizon, quoted
 * rather than restated, so the fixture-mode line cannot drift from settings.py. */
function fixtureCadence(horizon: QuestionHorizon): string {
  const asked = (memoryFixture as Memory).questions.find((question) => question.horizon === horizon)
  return asked ? ` Live, this question is not asked again for ${asked.every_days} days.` : ''
}

export const api = {
  /** `state` and `statuses` matter only in fixture mode: the graph the state's run left, with this
   * session's goal statuses laid over it. Live, the server's graph already carries both. */
  graph(state: FixtureState = 'quiet', statuses: GoalStatuses = {}): Promise<LivingGraph> {
    if (USING_FIXTURES) return fixture(fixtureGraph(state, statuses))
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

  /** Answer a recurring question. Live, it is planned like a brain dump, so tens of seconds.
   * `state` matters only in fixture mode, for the reason `fixtureWeekRepliesHold` gives. */
  answerQuestion(
    horizon: QuestionHorizon,
    text: string,
    state: FixtureState = 'quiet',
  ): Promise<IntakeResult | FixtureAcknowledgement> {
    if (USING_FIXTURES) {
      // A request to go and find something gets its own reply, whatever the state.
      const found = findReply(text)
      if (found) return fixture({ fixture: true, line: found } satisfies FixtureAcknowledgement, 1200)

      // The week answer was generated through the real intake graph, in one
      // world. The month answer never was. Either way, where nothing was
      // generated the reply is a line saying nothing happened rather than a
      // plan made for some other sentence or some other morning.
      if (horizon === 'week' && fixtureWeekRepliesHold(state)) {
        return fixture(questionAnswerWeekFixture, 1600)
      }
      if (horizon === 'week') {
        return fixture(
          {
            fixture: true,
            line:
              'Fixture mode: an answer to the week question was generated only for the quiet and ' +
              `prepared states on ${longDate(GENERATED_ON)}. None was generated for this state, so ` +
              'this one was not sent, nothing was planned and nothing was written.',
          } satisfies FixtureAcknowledgement,
          900,
        )
      }
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
  skipQuestion(
    horizon: QuestionHorizon,
    state: FixtureState = 'quiet',
  ): Promise<HorizonAsked | FixtureAcknowledgement> {
    if (USING_FIXTURES) {
      // Generated from `service.skip_question` for the week only, in the states
      // the week answer holds in, for the same reason as the answer above.
      if (horizon === 'week' && fixtureWeekRepliesHold(state)) return fixture(questionSkipWeekFixture)
      if (horizon === 'week') {
        return fixture({
          fixture: true,
          line:
            'Fixture mode: a skip of the week question was generated only for the quiet and ' +
            `prepared states on ${longDate(GENERATED_ON)}. None was generated for this state, so it ` +
            `was not recorded and reloading the page brings it back.${fixtureCadence(horizon)}`,
        } satisfies FixtureAcknowledgement)
      }
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

  /** `state` and `statuses` matter only in fixture mode: the state on screen, and the statuses set
   * earlier this session, which the returned graph carries along with this one. */
  setGoalStatus(
    goalId: string,
    status: Goal['status'],
    state: FixtureState = 'quiet',
    statuses: GoalStatuses = {},
  ): Promise<GoalStatusChange> {
    if (USING_FIXTURES) return fixture(fixtureStatusChange(goalId, status, state, statuses), 420)
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

/** Every brief by state, so the demo can show each state Today has without
 * waiting for a live run to happen to produce one. */
export function fixtureBrief(state: FixtureState): DailyBrief {
  return FIXTURE_WORLDS[state].brief
}
