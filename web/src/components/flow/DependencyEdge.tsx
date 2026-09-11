import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, type EdgeProps } from '@xyflow/react'

import type { DependencyFlowEdge } from './types'
import styles from './nodes.module.css'

/**
 * A task that cannot happen until another one does.
 *
 * This is the edge the demo points at. In the seeded world `t-flights` depends
 * on `t-leave`, and `t-leave` has no slot at all -- so the booking keeps slipping
 * for a reason that is structural and visible rather than a matter of
 * motivation. Highlighting it is the graph saying *this is why*.
 *
 * `data.blocked` is computed once when the model is built, not here. An edge
 * component that reaches for the upstream task's status would be doing the
 * model's job, and it would do it on every render.
 *
 * Drawn dashed rather than merely coloured: a dashed line reads as a
 * dependency even in a grayscale screenshot, and colour alone is not a signal
 * everyone can see.
 */
export function DependencyEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  data,
}: EdgeProps<DependencyFlowEdge>) {
  const [path, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    borderRadius: 6,
  })

  const blocked = data?.blocked ?? false

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        className={blocked ? styles.depBlocked : styles.dep}
      />
      {data?.label && (
        <EdgeLabelRenderer>
          <div
            className={styles.edgeLabel}
            data-blocked={blocked}
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
          >
            {data.label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}
