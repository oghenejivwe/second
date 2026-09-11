import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesInitialized,
  useNodesState,
  useReactFlow,
  type DefaultEdgeOptions,
  type EdgeTypes,
  type NodeTypes,
} from '@xyflow/react'
import '@xyflow/react/dist/base.css'

import { DependencyEdge } from '../components/flow/DependencyEdge'
import { GoalNode, RouteNode, TaskNode } from '../components/flow/nodes'
import type { SecondFlowEdge, SecondFlowNode } from '../components/flow/types'
import { Problem } from '../components/Problem'
import { buildFlowModel, HORIZON_LABEL } from '../lib/livingGraph'
import { useSecond } from '../store/useSecond'
import type { LivingGraph } from '../types/contract'
import styles from './LivingGraphScreen.module.css'

/**
 * The centrepiece. Goals ladder down to routes, routes to tasks, and the graph
 * visibly changes after a run.
 *
 * `base.css` rather than `style.css`: style.css adds a default node skin whose
 * every rule would have to be undone. The dark palette is set in
 * styles/flow.css, and the un-suffixed `--xy-*` names there are deliberate --
 * the `-default` spellings lose to `.react-flow.dark` on specificity and
 * silently do nothing.
 *
 * Node and edge type maps are at module scope. A fresh object identity on every
 * render breaks the memo on every node wrapper, and the library warns about it.
 */

const nodeTypes: NodeTypes = { goal: GoalNode, route: RouteNode, task: TaskNode }
const edgeTypes: EdgeTypes = { dependency: DependencyEdge }

/** One fit spec for both triggers, so a change to one cannot drift from the
 * other. `minZoom` here is deliberately higher than the canvas minimum: a fit
 * that has to clamp should still be readable, and the user can zoom further out
 * by hand if they want to. */
const FIT = { padding: 0.14, duration: 320, minZoom: 0.35, maxZoom: 1 } as const

const defaultEdgeOptions: DefaultEdgeOptions = {
  type: 'smoothstep',
  markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12 },
}

export function LivingGraphScreen() {
  const graph = useSecond((state) => state.graph)
  const loading = useSecond((state) => state.loading)
  const errors = useSecond((state) => state.errors)
  const loadGraph = useSecond((state) => state.loadGraph)
  const runDaily = useSecond((state) => state.runDaily)
  const diff = useSecond((state) => state.diff)
  const clearDiff = useSecond((state) => state.clearDiff)

  if (errors.graph && !graph) {
    return (
      <div className={styles.screen}>
        <Problem what={errors.graph} onRetry={loadGraph} />
      </div>
    )
  }

  if (!graph) {
    return (
      <div className={styles.screen}>
        <p className={styles.waiting}>{loading.graph ? 'Reading the graph.' : 'No graph loaded.'}</p>
      </div>
    )
  }

  return (
    <div className={styles.screen}>
      <header className={styles.head}>
        <div className={styles.legend}>
          <Count graph={graph} />
          <Bands />
        </div>

        <div className={styles.actions}>
          {diff?.any && (
            <button type="button" className={styles.ghost} onClick={clearDiff}>
              Clear highlights
            </button>
          )}
          <button
            type="button"
            className={styles.run}
            onClick={() => void runDaily()}
            disabled={loading.run}
          >
            {loading.run ? 'Running the day' : 'Run the day'}
          </button>
        </div>
      </header>

      {errors.run && <Problem what={errors.run} onRetry={() => void runDaily()} />}

      {/* What the run actually did. Persistent rather than a pulse that fades:
        * on a recording, a highlight nobody scrubbed back for did not happen. */}
      {diff?.any && (
        <div className={styles.changed}>
          <p className={styles.changedWhat}>
            {describeDiff(diff.changed.size, diff.added.size)}
          </p>
          {diff.personFacts.length > 0 && (
            <p className={styles.learned}>
              <span className="label">Second also learned</span>
              {diff.personFacts.join(' · ')}
            </p>
          )}
        </div>
      )}

      <div className={styles.canvas}>
        <ReactFlowProvider>
          <Canvas graph={graph} changed={changedIds(diff)} />
        </ReactFlowProvider>
      </div>
    </div>
  )
}

function Canvas({ graph, changed }: { graph: LivingGraph; changed: Set<string> }) {
  const model = useMemo(() => buildFlowModel(graph), [graph])

  const flowNodes = useMemo<SecondFlowNode[]>(
    () =>
      model.nodes.map(
        (node) =>
          ({
            id: node.id,
            type: node.type,
            position: node.position,
            data: { ...node.data, changed: changed.has(node.id) },
            draggable: true,
          }) as SecondFlowNode,
      ),
    [model.nodes, changed],
  )

  const flowEdges = useMemo<SecondFlowEdge[]>(
    () =>
      model.edges.map(
        (edge) =>
          ({
            id: edge.id,
            source: edge.source,
            target: edge.target,
            type: edge.type === 'dependency' ? 'dependency' : 'smoothstep',
            data: edge.data,
          }) as SecondFlowEdge,
      ),
    [model.edges],
  )

  const [nodes, setNodes, onNodesChange] = useNodesState<SecondFlowNode>(flowNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState<SecondFlowEdge>(flowEdges)
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    setNodes(flowNodes)
    setEdges(flowEdges)
  }, [flowNodes, flowEdges, setNodes, setEdges])

  const { fitView } = useReactFlow<SecondFlowNode, SecondFlowEdge>()
  const initialized = useNodesInitialized()

  /**
   * Re-fit when the SET of nodes changes, not on every render and not on a drag.
   * Keyed off a sorted id signature, and deferred one frame so the measured node
   * dimensions have landed -- fitting before measurement zooms to the wrong
   * rectangle.
   */
  const signature = useMemo(() => flowNodes.map((node) => node.id).sort().join('|'), [flowNodes])
  const lastFitted = useRef('')

  useEffect(() => {
    if (!initialized || lastFitted.current === signature) return
    lastFitted.current = signature
    const frame = requestAnimationFrame(() => {
      void fitView(FIT)
    })
    return () => cancelAnimationFrame(frame)
  }, [initialized, signature, fitView])

  /**
   * Re-fit when the CONTAINER resizes, which is a separate problem and a real
   * one: `fitView` solves for the viewport it can see at the moment it runs, and
   * it never runs again. Caught by watching it happen -- the graph fitted itself
   * to a 500px-tall pane, the window was resized to 880, and every node stayed
   * at the zoom the smaller box needed, clamped flat against `minZoom`. Nothing
   * about that recovers on its own, and the first thing anyone does with a graph
   * is make the window bigger.
   *
   * The observer fires once on attach, so the initial fit is covered here too;
   * the effect above still exists because a new node set needs a re-fit at an
   * unchanged size.
   */
  const canvas = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const host = canvas.current
    if (!host || !initialized) return

    let frame = 0
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame)
      // One frame late, so the fit solves against the size after layout rather
      // than the size that triggered the callback.
      frame = requestAnimationFrame(() => void fitView({ ...FIT, duration: 0 }))
    })

    observer.observe(host)
    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [initialized, fitView])

  const detail = selected ? model.nodes.find((node) => node.id === selected) : undefined

  return (
    <>
      <div ref={canvas} className={styles.flow}>
        <ReactFlow<SecondFlowNode, SecondFlowEdge>
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          defaultEdgeOptions={defaultEdgeOptions}
          colorMode="dark"
          fitView
          fitViewOptions={FIT}
          minZoom={0.2}
          maxZoom={1.5}
          nodesConnectable={false}
          elevateEdgesOnSelect
          onNodeClick={(_, node) => setSelected(node.id)}
          onPaneClick={() => setSelected(null)}
        >
          <Background variant={BackgroundVariant.Dots} gap={24} size={1} />
          <Controls showInteractive={false} position="bottom-right" />
        </ReactFlow>
      </div>

      {/* A strip rather than a side panel, so the graph keeps the room. Person
        * facts stay on the nodes; this carries the reasoning that is too long
        * to hang off an edge. */}
      {detail && (
        <div className={styles.detail}>
          {detail.data.kind === 'route' && (
            <>
              <p className={styles.detailTitle}>{detail.data.route.title}</p>
              <p className="evidence">{detail.data.route.rationale}</p>
            </>
          )}
          {detail.data.kind === 'task' && (
            <>
              <p className={styles.detailTitle}>{detail.data.task.title}</p>
              {detail.data.task.slips.length > 0 ? (
                <ul className={styles.slips}>
                  {detail.data.task.slips.map((slip, index) => (
                    <li key={index} className="evidence">
                      {slip.on} · {slip.note || `noticed by ${slip.noticed_by}`}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className={styles.detailNone}>No slips recorded.</p>
              )}
            </>
          )}
          {detail.data.kind === 'goal' && (
            <>
              <p className={styles.detailTitle}>{detail.data.goal.title}</p>
              <p className={styles.detailNone}>
                {HORIZON_LABEL[detail.data.horizon]}
                {detail.data.schedulable
                  ? ' · near enough to hold calendar work'
                  : ' · has to be walked down before it can hold a slot'}
              </p>
            </>
          )}
        </div>
      )}
    </>
  )
}

function Count({ graph }: { graph: LivingGraph }) {
  const routes = graph.goals.flatMap((goal) => goal.routes)
  const tasks = routes.flatMap((route) => route.tasks)
  const slipped = tasks.filter((task) => task.slip_count > 0).length

  return (
    <p className={styles.count}>
      <span>
        {graph.goals.length} {graph.goals.length === 1 ? 'goal' : 'goals'}
      </span>
      <span>
        {routes.length} {routes.length === 1 ? 'route' : 'routes'}
      </span>
      <span>
        {tasks.length} {tasks.length === 1 ? 'task' : 'tasks'}
      </span>
      {slipped > 0 && <span className={styles.countSlipped}>{slipped} slipped</span>}
    </p>
  )
}

/** The vertical axis means something, so it is labelled. */
function Bands() {
  return (
    <p className={styles.bands}>
      <span className="label">rows</span>
      {['life', 'three_year', 'year', 'month'].map((horizon, index) => (
        <span key={horizon}>
          {index > 0 && <span className={styles.bandArrow}>→</span>}
          {HORIZON_LABEL[horizon as keyof typeof HORIZON_LABEL]}
        </span>
      ))}
      <span className={styles.bandArrow}>→</span>
      <span>routes</span>
      <span className={styles.bandArrow}>→</span>
      <span>tasks</span>
    </p>
  )
}

function changedIds(diff: ReturnType<typeof useSecond.getState>['diff']): Set<string> {
  if (!diff) return new Set()
  return new Set([...diff.changed, ...diff.added])
}

function describeDiff(changed: number, added: number): string {
  const parts: string[] = []
  if (changed > 0) parts.push(`${changed} ${changed === 1 ? 'thing' : 'things'} changed`)
  if (added > 0) parts.push(`${added} added`)
  return parts.length > 0
    ? `${parts.join(', ')} in the last run.`
    : 'The last run changed nothing in the graph.'
}
