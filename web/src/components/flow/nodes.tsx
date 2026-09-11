import { Handle, Position, type NodeProps } from '@xyflow/react'

import { clockTime, shortDate } from '../../lib/datetime'
import { HORIZON_LABEL, type Annotation } from '../../lib/livingGraph'
import type { GoalFlowNode, RouteFlowNode, TaskFlowNode } from './types'
import styles from './nodes.module.css'

/**
 * The three node kinds. All three are plain divs with a 1px rule.
 *
 * Colour carries information and nothing else. A task is red because it slipped,
 * never because it is important; a person-layer fact is green because the slot
 * held. Nothing here is coloured to draw the eye.
 *
 * Handles are present but invisible (see styles/flow.css) -- edges need
 * somewhere to attach and nobody connects anything by hand in this app.
 */

export function GoalNode({ data, selected }: NodeProps<GoalFlowNode>) {
  const { goal, horizon, schedulable, stalled, broken, annotations, changed } = data

  return (
    <div
      className={styles.node}
      data-kind="goal"
      data-schedulable={schedulable}
      data-status={goal.status}
      data-selected={selected}
      data-changed={changed}
    >
      <Handle type="target" position={Position.Top} isConnectable={false} />
      {changed && <span className={styles.changed}>changed</span>}

      <p className={styles.horizon}>{HORIZON_LABEL[horizon]}</p>
      <p className={styles.title}>{goal.title}</p>

      <p className={styles.meta}>
        {goal.status !== 'active' && <span data-status={goal.status}>{goal.status}</span>}
        {goal.deadline && <span>by {shortDate(goal.deadline)}</span>}
        {goal.routes.length > 0 && (
          <span>
            {goal.routes.length} {goal.routes.length === 1 ? 'route' : 'routes'}
          </span>
        )}
      </p>

      {/* An ambition with no children and no routes is a wish. Said plainly,
        * because it is the Cascader's work queue and a judge should see it. */}
      {stalled && <p className={styles.stalled}>Nothing doable under this yet.</p>}
      {broken && <p className={styles.broken}>Points at a goal that is not in the graph.</p>}

      <Annotations items={annotations} />
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  )
}

export function RouteNode({ data, selected }: NodeProps<RouteFlowNode>) {
  const { route, annotations, changed } = data

  return (
    <div
      className={styles.node}
      data-kind="route"
      data-status={route.status}
      data-selected={selected}
      data-changed={changed}
    >
      <Handle type="target" position={Position.Top} isConnectable={false} />
      {changed && <span className={styles.changed}>changed</span>}

      <p className={styles.cadence}>{route.cadence}</p>
      <p className={styles.title}>{route.title}</p>
      {route.status !== 'approved' && <p className={styles.meta}>{route.status}</p>}

      <Annotations items={annotations} />
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  )
}

export function TaskNode({ data, selected }: NodeProps<TaskFlowNode>) {
  const { task, slipped, blockedBy, annotations, changed } = data

  // The latest slot, not "the next one": deciding which slot is next needs a
  // today to compare against, and the node has none. Every slot on a task
  // shares its route's hour anyway, so this is the time of day it sits at.
  const latestSlot = task.scheduled_slots.at(-1)

  return (
    <div
      className={styles.node}
      data-kind="task"
      data-slipped={slipped}
      data-blocked={blockedBy.length > 0}
      data-status={task.status}
      data-selected={selected}
      data-changed={changed}
    >
      <Handle type="target" position={Position.Top} isConnectable={false} />
      {changed && <span className={styles.changed}>changed</span>}

      <p className={styles.title}>{task.title}</p>

      <p className={styles.meta}>
        {/* Naive datetime: read off the string, never through Date. A slot is
          * wall-clock time and the browser's zone is not the user's. */}
        {latestSlot && <span className="tabular">{clockTime(latestSlot)}</span>}
        {slipped && (
          <span className={styles.slips}>
            slipped {task.slip_count}
            {task.slip_count === 1 ? ' time' : ' times'}
          </span>
        )}
        {task.status === 'done' && <span className={styles.done}>done</span>}
      </p>

      {blockedBy.length > 0 && <p className={styles.blocked}>waiting on {blockedBy.join(', ')}</p>}

      {/* Written from the user's own answer. Once set, Second never asks again. */}
      {task.known_blocker && <p className={styles.knownBlocker}>{task.known_blocker}</p>}

      <Annotations items={annotations} />
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  )
}

/**
 * Person-layer facts, hung off the edge of the node they are about.
 *
 * At the edge rather than inside, and small, because the brief is right that
 * these are context and not content: "Tue 19:00, attended every week" explains
 * a node, it is not a thing to read in its own right.
 */
function Annotations({ items }: { items: Annotation[] }) {
  if (items.length === 0) return null

  return (
    <ul className={styles.annotations}>
      {items.map((item, index) => (
        <li key={`${item.kind}:${index}`} className={styles.annotation} data-tone={item.tone}>
          <span className={styles.annotationText}>{item.text}</span>
          {item.note && <span className={styles.annotationNote}>{item.note}</span>}
        </li>
      ))}
    </ul>
  )
}
