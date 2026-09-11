/**
 * A tidy top-down tree layout. Twelve lines of maths instead of a dependency.
 *
 * **Why this is hand-rolled.** The brief said `@xyflow/react` does hierarchical
 * layout out of the box. It does not: version 12.11.6 exports no layout engine
 * at all -- checked against the installed package, not the docs -- and the
 * project's own layouting guide points you at dagre or elkjs. For a forest of
 * about twenty nodes and a maximum depth of five, both are a build-time and
 * bundle-size cost for an algorithm that fits on a screen. The classic
 * Reingold-Tilford first pass is all this shape needs:
 *
 *   1. Walk depth-first. Give each leaf the next free x.
 *   2. Give each parent the midpoint of its children.
 *
 * That is it. No second pass to resolve subtree collisions, because siblings are
 * laid out in order and never overlap when every leaf takes its own column.
 *
 * **Ragged depth is a feature here.** A goal ladder can be four rungs deep
 * ("speak to a room" under "raise a Series A" under "build a company") or one
 * rung ("be at my sister's wedding"), so subtrees end at different rows. That
 * asymmetry is the thing worth looking at: it shows at a glance which ambitions
 * have been cashed down into something doable and which have not.
 */

export interface TreeInput<T> {
  id: string
  /** Parent id, or null for a root. Unknown parents are treated as roots. */
  parent: string | null
  /** Horizontal space this node needs, including the gap after it. */
  width: number
  /** Which row it sits on. Derived from the structure, not supplied. */
  payload: T
}

export interface Placed<T> {
  id: string
  x: number
  y: number
  depth: number
  payload: T
}

export interface LayoutOptions {
  /** Vertical distance between rows. */
  rowHeight?: number
  /** Horizontal gap between adjacent leaves. */
  columnGap?: number
}

/**
 * Place a forest. Returns one entry per input, in input order.
 *
 * `x` is the CENTRE of the node, so a renderer subtracts half its own width.
 * That keeps the arithmetic here independent of how wide anything draws.
 *
 * A cycle in `parent` cannot hang this: nodes are only ever visited from a root,
 * so anything in a cycle is simply never placed, and `placedCount` lets the
 * caller notice. Failure direction: draw the tree you can prove, not a tree that
 * might be wrong.
 */
export function layoutForest<T>(
  nodes: TreeInput<T>[],
  { rowHeight = 128, columnGap = 24 }: LayoutOptions = {},
): { placed: Placed<T>[]; width: number; depth: number } {
  const byId = new Map(nodes.map((node) => [node.id, node]))
  const children = new Map<string, TreeInput<T>[]>()
  const roots: TreeInput<T>[] = []

  for (const node of nodes) {
    const parent = node.parent && byId.has(node.parent) ? node.parent : null
    if (parent === null) {
      roots.push(node)
      continue
    }
    const siblings = children.get(parent)
    if (siblings) siblings.push(node)
    else children.set(parent, [node])
  }

  const positions = new Map<string, { x: number; depth: number }>()
  let cursor = 0
  let maxDepth = 0

  const place = (node: TreeInput<T>, depth: number): number => {
    maxDepth = Math.max(maxDepth, depth)
    const kids = children.get(node.id) ?? []

    if (kids.length === 0) {
      const centre = cursor + node.width / 2
      cursor += node.width + columnGap
      positions.set(node.id, { x: centre, depth })
      return centre
    }

    const centres = kids.map((kid) => place(kid, depth + 1))
    const centre = (Math.min(...centres) + Math.max(...centres)) / 2

    // A parent wider than the span of its children would overhang the subtree
    // to its left, so claim the difference.
    const span = Math.max(...centres) - Math.min(...centres)
    if (node.width > span) cursor = Math.max(cursor, centre + node.width / 2 + columnGap)

    positions.set(node.id, { x: centre, depth })
    return centre
  }

  for (const root of roots) place(root, 0)

  const placed: Placed<T>[] = []
  for (const node of nodes) {
    const at = positions.get(node.id)
    if (!at) continue
    placed.push({ id: node.id, x: at.x, y: at.depth * rowHeight, depth: at.depth, payload: node.payload })
  }

  return { placed, width: cursor, depth: maxDepth }
}
