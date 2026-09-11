import type { Edge, Node } from '@xyflow/react'

import type { GoalNodeData, RouteNodeData, TaskNodeData } from '../../lib/livingGraph'

/**
 * The xyflow view of the model.
 *
 * `Node<Data, 'type'>` is a discriminated union on the type string, which is
 * what lets a node component be typed as `NodeProps<TaskFlowNode>` and read
 * `data.task` without a cast.
 *
 * The data types are declared as type aliases rather than interfaces in
 * `lib/livingGraph.ts`, and that is load-bearing: `Node<T>` constrains
 * `T extends Record<string, unknown>`, and TypeScript grants an implicit index
 * signature to a type alias but not to an interface.
 */
export type GoalFlowNode = Node<GoalNodeData, 'goal'>
export type RouteFlowNode = Node<RouteNodeData, 'route'>
export type TaskFlowNode = Node<TaskNodeData, 'task'>
export type SecondFlowNode = GoalFlowNode | RouteFlowNode | TaskFlowNode

export type EdgePayload = { blocked: boolean; label: string }

export type ContainmentFlowEdge = Edge<EdgePayload, 'containment'>
export type DependencyFlowEdge = Edge<EdgePayload, 'dependency'>
export type SecondFlowEdge = ContainmentFlowEdge | DependencyFlowEdge
