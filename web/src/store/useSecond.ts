/**
 * The state the screens share, and nothing more.
 *
 * Zustand rather than `useState` for exactly one reason: a Daily run started on
 * Today has to change what the Living Graph screen draws, and retiring a goal on
 * Goals has to change both. Everything that belongs to one screen -- which audit
 * row is open, whether the microphone is live -- stays in that screen.
 *
 * There is no react-query here on purpose. Six screens, nine reads, one
 * in-flight flag each: a cache layer would be more code than it replaces. The
 * nearest thing to invalidation is that a write which changes the graph drops
 * `schedule` and `memory`, and whichever screen shows them next reads again.
 */

import { create } from 'zustand'

import {
  api,
  errorLine,
  fixtureBrief,
  fixtureGraph,
  fixtureSeededGraph,
  isFixtureAcknowledgement,
  USING_FIXTURES,
  type FixtureAcknowledgement,
  type FixtureState,
  type GoalStatuses,
} from '../api/client'
import { diffGraphs, type GraphDiff } from '../lib/diff'
import type {
  AuditEntry,
  DailyBrief,
  Goal,
  GoalStatusChange,
  HorizonAsked,
  HorizonQuestion,
  IntakeResult,
  LivingGraph,
  Memory,
  Schedule,
} from '../types/contract'

export type Screen = 'record' | 'graph' | 'memory' | 'today' | 'schedule' | 'goals'

/**
 * A recurring question answered or skipped this session, and what came back.
 *
 * Kept in the store for the reason `lastStatusChange` is: App.tsx unmounts a
 * screen on navigation, and a question that came back unanswered after a trip
 * to Today would invite a second answer. It also has to outlive a refetch.
 * Live, a settled question is no longer due and drops out of
 * `memory.questions`, and the reply should not drop out with it.
 */
export type SettledQuestion =
  | {
      how: 'answered'
      question: HorizonQuestion
      /** The user's own words, as sent. */
      text: string
      reply: IntakeResult | FixtureAcknowledgement
    }
  | {
      how: 'skipped'
      question: HorizonQuestion
      reply: HorizonAsked | FixtureAcknowledgement
    }

/**
 * Which asking of a question a settled reply belongs to.
 *
 * The horizon alone used to be the key, so a week question that came due again
 * in the same session opened with the last outcome where its box belongs. The
 * text tells apart a question about a different goal. `last_asked` tells apart
 * the same question asked again: it is null the first time, and the day it was
 * last answered or skipped every time after.
 */
export function questionKey(question: HorizonQuestion): string {
  return [question.horizon, question.question, question.last_asked ?? ''].join('\n')
}

/**
 * The settled replies still worth keeping once memory has been read again.
 *
 * A reply goes when its horizon now has a different question due, because that
 * is a new asking and the old outcome would stand in for its box. A reply whose
 * horizon has nothing due stays: live, answering is what stops a question being
 * due, and the reply should not vanish with it.
 */
function stillSettled(
  settled: Record<string, SettledQuestion>,
  due: HorizonQuestion[],
): Record<string, SettledQuestion> {
  const dueNow = new Map(due.map((question) => [question.horizon, questionKey(question)]))
  return Object.fromEntries(
    Object.entries(settled).filter(([key, entry]) => {
      const current = dueNow.get(entry.question.horizon)
      return current === undefined || current === key
    }),
  )
}

interface State {
  screen: Screen
  show: (screen: Screen) => void

  graph: LivingGraph | null
  brief: DailyBrief | null
  /**
   * Fixture mode only: which morning run every screen is showing.
   *
   * Set by whatever put the brief on screen: the first read (quiet), Run the day
   * (prepared), or Today's state buttons. The graph, Schedule and Memory pick
   * their files by this name, never by looking at the brief. Unused live.
   */
  fixtureState: FixtureState
  /**
   * Fixture mode only: goal statuses set this session, laid over each state's
   * graph (api/client.ts says why). Kept through a state switch, because a
   * retired goal does not come back by looking at another morning. Unused live.
   */
  goalStatuses: GoalStatuses
  audit: AuditEntry[]
  schedule: Schedule | null
  memory: Memory | null
  /** By `questionKey`. */
  settled: Record<string, SettledQuestion>

  /** What the last Daily run changed. Drives the highlight on the Living Graph. */
  diff: GraphDiff | null
  /** What the last pause or retire released. Drives the freed-time line on Goals. */
  lastStatusChange: GoalStatusChange | null

  loading: {
    graph: boolean
    brief: boolean
    audit: boolean
    run: boolean
    status: boolean
    schedule: boolean
    memory: boolean
  }
  errors: {
    graph: string | null
    brief: string | null
    audit: string | null
    run: string | null
    schedule: string | null
    memory: string | null
  }

  loadGraph: () => Promise<void>
  loadBrief: () => Promise<void>
  loadAudit: (limit?: number) => Promise<void>
  loadSchedule: () => Promise<void>
  loadMemory: () => Promise<void>
  runDaily: () => Promise<void>
  setGoalStatus: (goalId: string, status: Goal['status']) => Promise<void>
  /** Rejects with the failure, so the question that sent it can say what failed beside itself. */
  answerQuestion: (question: HorizonQuestion, text: string) => Promise<void>
  /** Rejects with the failure, for the same reason. */
  skipQuestion: (question: HorizonQuestion) => Promise<void>
  clearDiff: () => void
  clearStatusChange: () => void
  /** Fixture mode only: step Today, Schedule and Memory through the four states together. */
  showBrief: (state: FixtureState) => void
}

/**
 * Fixture mode only: everything that moves when the screens move to another morning.
 *
 * The brief and the graph are that state's own, the graph carrying this
 * session's goal statuses. A diff on screen is taken again against the seeded
 * world, because a highlight worked out for another state's graph marks nodes
 * that did not change in this one. Schedule and memory are dropped and read
 * again on arrival. A settled question and the last status change are dropped
 * only when the state really changes: an answer's placements and a retire's
 * freed slots were generated for one morning and are not known to hold in
 * another.
 */
function fixtureMove(
  state: State,
  to: FixtureState,
): Pick<State, 'fixtureState' | 'brief' | 'diff' | 'schedule' | 'memory'> &
  Partial<Pick<State, 'settled' | 'lastStatusChange'>> & { graph: LivingGraph } {
  const graph = fixtureGraph(to, state.goalStatuses)
  return {
    fixtureState: to,
    brief: fixtureBrief(to),
    graph,
    diff: state.diff ? diffGraphs(fixtureSeededGraph(state.goalStatuses), graph) : null,
    schedule: null,
    memory: null,
    ...(state.fixtureState === to ? {} : { settled: {}, lastStatusChange: null }),
  }
}

export const useSecond = create<State>((set, get) => ({
  screen: 'today',
  show: (screen) => set({ screen }),

  graph: null,
  brief: null,
  fixtureState: 'quiet',
  goalStatuses: {},
  audit: [],
  schedule: null,
  memory: null,
  settled: {},
  diff: null,
  lastStatusChange: null,

  loading: {
    graph: false,
    brief: false,
    audit: false,
    run: false,
    status: false,
    schedule: false,
    memory: false,
  },
  errors: { graph: null, brief: null, audit: null, run: null, schedule: null, memory: null },

  loadGraph: async () => {
    // Fixture mode reads the graph of the state on screen, with the statuses
    // set this session, so both are read here and passed along.
    const shownState = get().fixtureState
    const statuses = get().goalStatuses
    set((state) => ({ loading: { ...state.loading, graph: true } }))
    try {
      const graph = await api.graph(shownState, statuses)

      // The state or a goal's status changed while this was read, so the graph
      // in hand is of a world no longer on screen. Read again for the one that is.
      if (USING_FIXTURES && (get().fixtureState !== shownState || get().goalStatuses !== statuses)) {
        set((state) => ({ loading: { ...state.loading, graph: false } }))
        void get().loadGraph()
        return
      }

      set((state) => ({
        graph,
        loading: { ...state.loading, graph: false },
        errors: { ...state.errors, graph: null },
      }))
    } catch (error) {
      set((state) => ({
        loading: { ...state.loading, graph: false },
        errors: { ...state.errors, graph: errorLine(error) },
      }))
    }
  },

  loadBrief: async () => {
    set((state) => ({ loading: { ...state.loading, brief: true } }))
    try {
      const brief = await api.today()
      set((state) => ({
        brief,
        // Fixture mode answers this read with the quiet run's brief. If Today had
        // moved to another state meanwhile, every screen moves back with it.
        ...(USING_FIXTURES && state.fixtureState !== 'quiet' ? fixtureMove(state, 'quiet') : {}),
        loading: { ...state.loading, brief: false },
        errors: { ...state.errors, brief: null },
      }))
    } catch (error) {
      set((state) => ({
        loading: { ...state.loading, brief: false },
        errors: { ...state.errors, brief: errorLine(error) },
      }))
    }
  },

  loadAudit: async (limit = 60) => {
    set((state) => ({ loading: { ...state.loading, audit: true } }))
    try {
      const audit = await api.audit(limit)
      set((state) => ({
        audit,
        loading: { ...state.loading, audit: false },
        errors: { ...state.errors, audit: null },
      }))
    } catch (error) {
      set((state) => ({
        loading: { ...state.loading, audit: false },
        errors: { ...state.errors, audit: errorLine(error) },
      }))
    }
  },

  loadSchedule: async () => {
    // The screen asks whenever `schedule` is null, which can happen more than
    // once before the first answer lands. One request is enough.
    if (get().loading.schedule) return
    // Fixture mode picks the schedule generated in the same state as the brief, as memory does.
    const shownState = get().fixtureState
    set((state) => ({ loading: { ...state.loading, schedule: true } }))
    try {
      const schedule = await api.schedule(undefined, shownState)

      // Today changed state while this was read: the answer belongs to the state that left.
      if (USING_FIXTURES && get().fixtureState !== shownState) {
        set((state) => ({ loading: { ...state.loading, schedule: false } }))
        void get().loadSchedule()
        return
      }

      set((state) => ({
        schedule,
        loading: { ...state.loading, schedule: false },
        errors: { ...state.errors, schedule: null },
      }))
    } catch (error) {
      set((state) => ({
        loading: { ...state.loading, schedule: false },
        errors: { ...state.errors, schedule: errorLine(error) },
      }))
    }
  },

  loadMemory: async () => {
    if (get().loading.memory) return
    // Fixture mode picks which generated memory to show by the state Today is
    // in, so the state is read here and passed along. Live, the server reads
    // its own store and the argument is not sent.
    const shownState = get().fixtureState
    set((state) => ({ loading: { ...state.loading, memory: true } }))
    try {
      const memory = await api.memory(shownState)

      // Today changed state while this was being read, so the memory in hand
      // belongs to the state that left. It is thrown away and read again for
      // the one on screen now.
      if (USING_FIXTURES && get().fixtureState !== shownState) {
        set((state) => ({ loading: { ...state.loading, memory: false } }))
        void get().loadMemory()
        return
      }

      set((state) => ({
        memory,
        settled: stillSettled(state.settled, memory.questions),
        loading: { ...state.loading, memory: false },
        errors: { ...state.errors, memory: null },
      }))
    } catch (error) {
      set((state) => ({
        loading: { ...state.loading, memory: false },
        errors: { ...state.errors, memory: errorLine(error) },
      }))
    }
  },

  /** The demo's central beat: run the day, then show what moved in the graph. */
  runDaily: async () => {
    const before = get().graph
    set((state) => ({ loading: { ...state.loading, run: true }, errors: { ...state.errors, run: null } }))

    try {
      const brief = await api.runDaily()

      // Fixture mode answers a run with the prepared run's brief, and every
      // screen moves to that state. The graph is the one the prepared run left,
      // diffed against the seeded world before any run, so the highlight shows
      // what a run changed and not what separates two fixture states.
      if (USING_FIXTURES) {
        set((state) => {
          const moved = fixtureMove(state, 'prepared')
          return {
            ...moved,
            brief,
            diff: diffGraphs(fixtureSeededGraph(state.goalStatuses), moved.graph),
            loading: { ...state.loading, run: false },
          }
        })
        void get().loadAudit()
        return
      }

      // Live, the graph is refetched because the run wrote to it.
      const after = await api.graph()

      set((state) => ({
        brief,
        graph: after,
        diff: diffGraphs(before, after),
        // The run moved slots and cached the brief the email source reads, so
        // both reads built on the old graph are dropped rather than shown stale.
        schedule: null,
        memory: null,
        loading: { ...state.loading, run: false },
      }))
      void get().loadAudit()
    } catch (error) {
      set((state) => ({
        loading: { ...state.loading, run: false },
        errors: { ...state.errors, run: errorLine(error) },
      }))
    }
  },

  setGoalStatus: async (goalId, status) => {
    const shownState = get().fixtureState
    const statuses = get().goalStatuses
    set((state) => ({ loading: { ...state.loading, status: true } }))
    try {
      const change = await api.setGoalStatus(goalId, status, shownState, statuses)

      // Fixture mode: the state moved, or another goal's status landed, while
      // this was answered. The reply's graph and freed slots are for a world no
      // longer on screen, so it is asked again for the one that is.
      if (USING_FIXTURES && (get().fixtureState !== shownState || get().goalStatuses !== statuses)) {
        set((state) => ({ loading: { ...state.loading, status: false } }))
        return get().setGoalStatus(goalId, status)
      }

      set((state) => ({
        graph: change.graph,
        lastStatusChange: change,
        ...(USING_FIXTURES ? { goalStatuses: { ...state.goalStatuses, [goalId]: status } } : {}),
        // A paused or retired goal releases its slots and stops its routes
        // being proposed, so the schedule and memory built before it are wrong.
        // Fixture mode reads the same checked-in files again, so Today,
        // Schedule and Memory take that goal's work off against `graph`
        // (lib/withdrawn.ts).
        schedule: null,
        memory: null,
        loading: { ...state.loading, status: false },
        errors: { ...state.errors, graph: null },
      }))
    } catch (error) {
      set((state) => ({
        loading: { ...state.loading, status: false },
        errors: { ...state.errors, graph: errorLine(error) },
      }))
    }
  },

  answerQuestion: async (question, text) => {
    // Fixture mode: which generated reply holds depends on the state on screen.
    const shownState = get().fixtureState
    const reply = await api.answerQuestion(question.horizon, text, shownState)
    const key = questionKey(question)
    const settled: SettledQuestion = { how: 'answered', question, text, reply }

    // Fixture mode writes nothing, whichever reply came back. The generated
    // week answer carries the graph as intake wrote it after the prepared run,
    // before any retire in this session, so putting that graph in the store
    // would quietly undo those on every other screen. The reply is shown on the
    // question, and the question says it is shown nowhere else.
    if (USING_FIXTURES || isFixtureAcknowledgement(reply)) {
      // The state moved while this was answered: the reply was for the morning
      // that left, and so was the question that sent it.
      if (USING_FIXTURES && get().fixtureState !== shownState) return
      set((state) => ({ settled: { ...state.settled, [key]: settled } }))
      return
    }

    // Intake wrote goals and perhaps slots, and hands back the graph as written.
    // The schedule is dropped because it is not on screen. Memory is on screen,
    // so it is read again in the background and the page keeps what it has
    // until the new one lands, instead of blanking under the user's answer.
    // The brief and the audit are read again for Today. `/api/today` is a read
    // and runs nothing: it assembles the day from the graph as written, unless
    // a brief was already computed today, which it returns as it was.
    set((state) => ({
      settled: { ...state.settled, [key]: settled },
      graph: reply.graph,
      schedule: null,
    }))
    void get().loadMemory()
    void get().loadBrief()
    void get().loadAudit()
  },

  skipQuestion: async (question) => {
    const shownState = get().fixtureState
    const reply = await api.skipQuestion(question.horizon, shownState)
    if (USING_FIXTURES && get().fixtureState !== shownState) return
    // Nothing else in the browser reads `asked_on`, so a skip changes nothing
    // on screen but this question, and there is nothing to refetch.
    set((state) => ({
      settled: { ...state.settled, [questionKey(question)]: { how: 'skipped', question, reply } },
    }))
  },

  clearDiff: () => set({ diff: null }),

  // Dismissing the freed band has to outlive the screen. It was component state
  // in Goals, and App.tsx unmounts Goals on navigation -- so leaving and coming
  // back resurrected a band the user had already dismissed, for a status change
  // from minutes ago.
  clearStatusChange: () => set({ lastStatusChange: null }),

  // The graph, Memory and Schedule in fixture mode are chosen by the state, so
  // switching it moves all of them with the brief (`fixtureMove`).
  showBrief: (to) => set((state) => fixtureMove(state, to)),
}))
