/**
 * The state three screens share, and nothing more.
 *
 * Zustand rather than `useState` for exactly one reason: a Daily run started on
 * Today has to change what the Living Graph screen draws, and retiring a goal on
 * Goals has to change both. Everything that belongs to one screen -- which audit
 * row is open, whether the microphone is live -- stays in that screen.
 *
 * There is no react-query here on purpose. Four screens, seven reads, one
 * in-flight flag each: a cache layer would be more code than it replaces.
 */

import { create } from 'zustand'

import { api, errorLine, fixtureGraphAfterRun, USING_FIXTURES } from '../api/client'
import { diffGraphs, type GraphDiff } from '../lib/diff'
import type { AuditEntry, DailyBrief, Goal, GoalStatusChange, LivingGraph } from '../types/contract'

export type Screen = 'record' | 'graph' | 'today' | 'goals'

interface State {
  screen: Screen
  show: (screen: Screen) => void

  graph: LivingGraph | null
  brief: DailyBrief | null
  audit: AuditEntry[]

  /** What the last Daily run changed. Drives the highlight on the Living Graph. */
  diff: GraphDiff | null
  /** What the last pause or retire released. Drives the freed-time line on Goals. */
  lastStatusChange: GoalStatusChange | null

  loading: { graph: boolean; brief: boolean; audit: boolean; run: boolean; status: boolean }
  errors: { graph: string | null; brief: string | null; audit: string | null; run: string | null }

  loadGraph: () => Promise<void>
  loadBrief: () => Promise<void>
  loadAudit: (limit?: number) => Promise<void>
  runDaily: () => Promise<void>
  setGoalStatus: (goalId: string, status: Goal['status']) => Promise<void>
  clearDiff: () => void
  /** Fixture mode only: step Today through its states without a live run. */
  showBrief: (brief: DailyBrief) => void
}

export const useSecond = create<State>((set, get) => ({
  screen: 'today',
  show: (screen) => set({ screen }),

  graph: null,
  brief: null,
  audit: [],
  diff: null,
  lastStatusChange: null,

  loading: { graph: false, brief: false, audit: false, run: false, status: false },
  errors: { graph: null, brief: null, audit: null, run: null },

  loadGraph: async () => {
    set((state) => ({ loading: { ...state.loading, graph: true } }))
    try {
      const graph = await api.graph()
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

  /** The demo's central beat: run the day, then show what moved in the graph. */
  runDaily: async () => {
    const before = get().graph
    set((state) => ({ loading: { ...state.loading, run: true }, errors: { ...state.errors, run: null } }))

    try {
      const brief = await api.runDaily()

      // Live, the graph is refetched because the run wrote to it. In fixture
      // mode there is a second checked-in graph showing the same writes, so the
      // beat is identical without a backend.
      const after = USING_FIXTURES ? fixtureGraphAfterRun : await api.graph()

      set((state) => ({
        brief,
        graph: after,
        diff: diffGraphs(before, after),
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
    set((state) => ({ loading: { ...state.loading, status: true } }))
    try {
      const change = await api.setGoalStatus(goalId, status)
      set((state) => ({
        graph: change.graph,
        lastStatusChange: change,
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

  clearDiff: () => set({ diff: null }),
  showBrief: (brief) => set({ brief }),
}))
