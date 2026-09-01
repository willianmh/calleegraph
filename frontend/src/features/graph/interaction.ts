import { createContext, useContext } from 'react';

import type { Neighbourhood } from './model';

/**
 * Hover / selection state lives in context rather than in each node's `data`,
 * so moving the mouse never rebuilds the node array — no relayout, no
 * position churn, and the canvas stays still while it highlights.
 */
export interface GraphInteraction {
  /** The node under the pointer, if any. */
  hoveredNodeId: string | null;
  /** Its dependents/dependencies, walked from the real edge list. */
  neighbourhood: Neighbourhood | null;
  /** The edge whose detail panel is open. */
  selectedEdgeId: string | null;
  /** The edge under the pointer. */
  hoveredEdgeId: string | null;
  /** Node ids matching the search box; null when the box is empty. */
  matchedNodeIds: ReadonlySet<string> | null;
  /** Endpoints of the selected edge, so both cards stay lit. */
  selectedEndpoints: ReadonlySet<string>;
  setHoveredNode: (id: string | null) => void;
  setHoveredEdge: (id: string | null) => void;
  selectEdge: (id: string | null) => void;
  toggleExpanded: (id: string) => void;
}

const noop = () => undefined;

export const defaultInteraction: GraphInteraction = {
  hoveredNodeId: null,
  neighbourhood: null,
  selectedEdgeId: null,
  hoveredEdgeId: null,
  matchedNodeIds: null,
  selectedEndpoints: new Set<string>(),
  setHoveredNode: noop,
  setHoveredEdge: noop,
  selectEdge: noop,
  toggleExpanded: noop,
};

export const GraphInteractionContext = createContext<GraphInteraction>(defaultInteraction);

export function useGraphInteraction(): GraphInteraction {
  return useContext(GraphInteractionContext);
}

/** How prominently a node or edge should be drawn right now. */
export type Emphasis = 'focus' | 'downstream' | 'upstream' | 'normal' | 'dim';

export function nodeEmphasis(interaction: GraphInteraction, nodeId: string): Emphasis {
  const { hoveredNodeId, neighbourhood, matchedNodeIds, selectedEndpoints } = interaction;

  if (hoveredNodeId) {
    if (hoveredNodeId === nodeId) return 'focus';
    if (neighbourhood?.downstream.has(nodeId)) return 'downstream';
    if (neighbourhood?.upstream.has(nodeId)) return 'upstream';
    return 'dim';
  }
  if (selectedEndpoints.size > 0) {
    return selectedEndpoints.has(nodeId) ? 'focus' : 'dim';
  }
  if (matchedNodeIds) {
    return matchedNodeIds.has(nodeId) ? 'focus' : 'dim';
  }
  return 'normal';
}

export interface EdgeEmphasis {
  emphasis: Emphasis;
  /** Set when the hovered node is this edge's source ("what it calls"). */
  direction: 'downstream' | 'upstream' | null;
}

export function edgeEmphasis(
  interaction: GraphInteraction,
  edge: { id: string; source: string; target: string },
): EdgeEmphasis {
  const { hoveredNodeId, selectedEdgeId, hoveredEdgeId, matchedNodeIds } = interaction;

  if (selectedEdgeId) {
    return selectedEdgeId === edge.id
      ? { emphasis: 'focus', direction: null }
      : { emphasis: 'dim', direction: null };
  }
  if (hoveredEdgeId) {
    return hoveredEdgeId === edge.id
      ? { emphasis: 'focus', direction: null }
      : { emphasis: 'dim', direction: null };
  }
  if (hoveredNodeId) {
    if (edge.source === hoveredNodeId) return { emphasis: 'downstream', direction: 'downstream' };
    if (edge.target === hoveredNodeId) return { emphasis: 'upstream', direction: 'upstream' };
    return { emphasis: 'dim', direction: null };
  }
  if (matchedNodeIds) {
    const lit = matchedNodeIds.has(edge.source) || matchedNodeIds.has(edge.target);
    return { emphasis: lit ? 'normal' : 'dim', direction: null };
  }
  return { emphasis: 'normal', direction: null };
}
