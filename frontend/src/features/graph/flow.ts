import dagre from '@dagrejs/dagre';
import type { Edge as FlowEdge, Node as FlowNode } from '@xyflow/react';

import type { Edge, EdgeStatus, Repository, WorkflowNode } from '@/api/types';
import type { CallWiring, FilteredGraph, GraphIndex, ParsedRef } from './model';
import { DETAIL_PANEL_WIDTH, edgeTargetId, wiringFor, worstStatus } from './model';

// ---------------------------------------------------------------------------
// Card geometry — the focus file's measurements
// ---------------------------------------------------------------------------

const COLLAPSED_WIDTH = 218;
const COLLAPSED_HEIGHT = 48;
const EXPANDED_WIDTH = 292;
const GROUP_WIDTH = 240;
const GROUP_HEIGHT = 78;
/** Beyond this the expanded card scrolls internally rather than growing. */
export const EXPANDED_MAX_HEIGHT = 340;

/**
 * A deterministic height for an expanded card, so dagre can reserve space
 * before the DOM exists. Anything taller than the cap scrolls inside the card,
 * which keeps the estimate honest without a measure/re-layout round trip.
 */
export function expandedHeight(node: WorkflowNode, wiring: CallWiring[]): number {
  let height = 56; // title + path
  for (const job of node.jobs) {
    height += 19; // job key / name
    if (job.needs.length > 0) height += 15;
    if (job.condition) height += 15;
    const call = wiring.find((entry) => entry.job.id === job.id);
    if (call) {
      height += 16; // "→ target" row
      height += call.bindings.length * 16;
      height += call.missingRequired.length * 16;
    }
    height += 9; // gap between jobs
  }
  if (node.jobs.length === 0) height += 18;
  return Math.min(EXPANDED_MAX_HEIGHT, height + 14);
}

// ---------------------------------------------------------------------------
// Flow node / edge data
// ---------------------------------------------------------------------------

export interface WorkflowNodeData extends Record<string, unknown> {
  variant: 'workflow';
  node: WorkflowNode;
  wiring: CallWiring[];
  status: EdgeStatus | undefined;
  expanded: boolean;
  compact: boolean;
  calleeCount: number;
  callerCount: number;
}

export interface UnresolvedNodeData extends Record<string, unknown> {
  variant: 'unresolved';
  ref: ParsedRef;
  /** True when the target's repository is not in the tracked list. */
  repositoryTracked: boolean;
  callerCount: number;
}

export interface GroupNodeData extends Record<string, unknown> {
  variant: 'group';
  repositoryFullName: string;
  /** Undefined for the untracked-targets group, which has no Repository row. */
  repository: Repository | undefined;
  workflowCount: number;
  internalCallCount: number;
  status: EdgeStatus | undefined;
}

export type CgNodeData = WorkflowNodeData | UnresolvedNodeData | GroupNodeData;
export type CgNode = FlowNode<CgNodeData>;

export interface CgEdgeData extends Record<string, unknown> {
  status: EdgeStatus;
  condition: string | null;
  /** The contract `Edge`s this line stands for — one, or many when grouped. */
  edges: Edge[];
  grouped: boolean;
}
export type CgEdge = FlowEdge<CgEdgeData>;

// ---------------------------------------------------------------------------
// Building the flow graph
// ---------------------------------------------------------------------------

export interface BuildFlowInput {
  filtered: FilteredGraph;
  index: GraphIndex;
  compact: boolean;
  /** One card per repository, ignoring `expandOverrides` entirely. */
  grouped: boolean;
  /** Per-node user overrides of the density default; survives live updates. */
  expandOverrides: ReadonlyMap<string, boolean>;
  repositories: readonly Repository[];
}

export interface BuiltFlow {
  nodes: CgNode[];
  edges: CgEdge[];
}

/**
 * Effective expand state: collapsed is always the default (§3.2) — density
 * (compact vs. detailed) only ever changes a *collapsed* card's own content,
 * never the expand state itself. Only an explicit click, via `overrides`,
 * ever expands a node.
 */
export function isExpanded(nodeId: string, overrides: ReadonlyMap<string, boolean>): boolean {
  return overrides.get(nodeId) ?? false;
}

export function buildFlow({
  filtered,
  index,
  compact,
  grouped,
  expandOverrides,
  repositories,
}: BuildFlowInput): BuiltFlow {
  return grouped
    ? buildGroupedFlow(filtered, repositories)
    : buildNodeFlow(filtered, index, compact, expandOverrides, repositories);
}

function buildNodeFlow(
  filtered: FilteredGraph,
  index: GraphIndex,
  compact: boolean,
  expandOverrides: ReadonlyMap<string, boolean>,
  repositories: readonly Repository[],
): BuiltFlow {
  const trackedRepos = new Set(repositories.map((repo) => repo.full_name));
  const nodes: CgNode[] = [];

  for (const node of filtered.nodes) {
    const wiring = wiringFor(node, index);
    const expanded = isExpanded(node.id, expandOverrides);
    const data: WorkflowNodeData = {
      variant: 'workflow',
      node,
      wiring,
      status: index.nodeStatus.get(node.id),
      expanded,
      compact,
      calleeCount: index.outgoing.get(node.id)?.length ?? 0,
      callerCount: index.incoming.get(node.id)?.length ?? 0,
    };
    nodes.push({
      id: node.id,
      type: 'workflow',
      position: { x: 0, y: 0 },
      data,
      width: expanded ? EXPANDED_WIDTH : COLLAPSED_WIDTH,
      height: expanded ? expandedHeight(node, wiring) : COLLAPSED_HEIGHT,
      draggable: false,
      connectable: false,
      selectable: false,
    });
  }

  for (const [id, ref] of filtered.unresolved) {
    const data: UnresolvedNodeData = {
      variant: 'unresolved',
      ref,
      repositoryTracked: ref.repositoryFullName ? trackedRepos.has(ref.repositoryFullName) : false,
      callerCount: index.incoming.get(id)?.length ?? 0,
    };
    nodes.push({
      id,
      type: 'unresolved',
      position: { x: 0, y: 0 },
      data,
      width: COLLAPSED_WIDTH,
      height: COLLAPSED_HEIGHT + 8,
      draggable: false,
      connectable: false,
      selectable: false,
    });
  }

  const edges: CgEdge[] = filtered.edges.map((edge) => ({
    id: edge.id,
    source: edge.source_node_id,
    target: edgeTargetId(edge),
    type: 'call',
    data: { status: edge.status, condition: edge.condition, edges: [edge], grouped: false },
    interactionWidth: 18,
  }));

  return { nodes, edges };
}

/** The id of the group card a node belongs to. */
export const UNTRACKED_GROUP_ID = 'group:untracked';

function groupIdFor(repositoryFullName: string): string {
  return `group:${repositoryFullName}`;
}

function buildGroupedFlow(filtered: FilteredGraph, repositories: readonly Repository[]): BuiltFlow {
  const repoByName = new Map(repositories.map((repo) => [repo.full_name, repo]));
  const workflowCounts = new Map<string, number>();
  const groupOfNode = new Map<string, string>();

  for (const node of filtered.nodes) {
    const groupId = groupIdFor(node.repository_full_name);
    groupOfNode.set(node.id, groupId);
    workflowCounts.set(groupId, (workflowCounts.get(groupId) ?? 0) + 1);
  }
  for (const [id, ref] of filtered.unresolved) {
    const groupId = ref.repositoryFullName
      ? groupIdFor(ref.repositoryFullName)
      : UNTRACKED_GROUP_ID;
    groupOfNode.set(id, groupId);
    if (!workflowCounts.has(groupId)) workflowCounts.set(groupId, 0);
  }

  const statuses = new Map<string, EdgeStatus[]>();
  const internalCalls = new Map<string, number>();
  const aggregated = new Map<string, { source: string; target: string; edges: Edge[] }>();

  for (const edge of filtered.edges) {
    const source = groupOfNode.get(edge.source_node_id);
    const target = groupOfNode.get(edgeTargetId(edge));
    if (!source || !target) continue;
    pushStatus(statuses, source, edge.status);
    pushStatus(statuses, target, edge.status);
    if (source === target) {
      internalCalls.set(source, (internalCalls.get(source) ?? 0) + 1);
      continue;
    }
    const key = `${source}→${target}`;
    const existing = aggregated.get(key);
    if (existing) existing.edges.push(edge);
    else aggregated.set(key, { source, target, edges: [edge] });
  }

  const nodes: CgNode[] = [...workflowCounts.entries()].map(([groupId, count]) => {
    const fullName =
      groupId === UNTRACKED_GROUP_ID ? 'Untracked targets' : groupId.slice('group:'.length);
    const data: GroupNodeData = {
      variant: 'group',
      repositoryFullName: fullName,
      repository: groupId === UNTRACKED_GROUP_ID ? undefined : repoByName.get(fullName),
      workflowCount: count,
      internalCallCount: internalCalls.get(groupId) ?? 0,
      status: statuses.has(groupId) ? worstStatus(statuses.get(groupId) ?? []) : undefined,
    };
    return {
      id: groupId,
      type: 'group',
      position: { x: 0, y: 0 },
      data,
      width: GROUP_WIDTH,
      height: GROUP_HEIGHT,
      draggable: false,
      connectable: false,
      selectable: false,
    };
  });

  const edges: CgEdge[] = [...aggregated.entries()].map(([key, entry]) => ({
    id: key,
    source: entry.source,
    target: entry.target,
    type: 'call',
    data: {
      status: worstStatus(entry.edges.map((edge) => edge.status)),
      condition: null,
      edges: entry.edges,
      grouped: true,
    },
    interactionWidth: 18,
  }));

  return { nodes, edges };
}

function pushStatus(map: Map<string, EdgeStatus[]>, key: string, status: EdgeStatus): void {
  const existing = map.get(key);
  if (existing) existing.push(status);
  else map.set(key, [status]);
}

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

/**
 * Left-to-right ranked layout: callers on the left, the reusable workflows
 * they call to the right of them. dagre reverses any cycle internally, so a
 * mutually-recursive pair still lays out rather than throwing.
 */
export function layoutFlow(
  built: BuiltFlow,
  options: { compact: boolean; grouped: boolean },
): BuiltFlow {
  const graph = new dagre.graphlib.Graph({ multigraph: true });
  graph.setDefaultEdgeLabel(() => ({}));
  graph.setGraph({
    rankdir: 'LR',
    ranksep: options.compact ? 120 : 150,
    nodesep: options.grouped ? 42 : 22,
    edgesep: 12,
    marginx: 40,
    marginy: 40,
  });

  for (const node of built.nodes) {
    graph.setNode(node.id, { width: node.width ?? 0, height: node.height ?? 0 });
  }
  for (const edge of built.edges) {
    // Parallel edges between the same pair need distinct dagre edge names.
    graph.setEdge(edge.source, edge.target, {}, edge.id);
  }

  dagre.layout(graph);

  const nodes = built.nodes.map((node) => {
    const placed = graph.node(node.id) as { x: number; y: number } | undefined;
    if (!placed) return node;
    return {
      ...node,
      // dagre reports centres; React Flow positions by top-left corner.
      position: { x: placed.x - (node.width ?? 0) / 2, y: placed.y - (node.height ?? 0) / 2 },
    };
  });

  return { nodes, edges: built.edges };
}

// ---------------------------------------------------------------------------
// Pan-to-center an edge, panel-width-aware
// ---------------------------------------------------------------------------

export interface EdgeCenterInput {
  sourceNode: Pick<CgNode, 'position' | 'height'>;
  targetNode: Pick<CgNode, 'position' | 'width' | 'height'>;
}

export interface EdgeCenterOptions {
  canvasWidth: number;
  canvasHeight: number;
  zoom: number;
  /** Was the detail panel already open before this selection? */
  wasAlreadyOpen: boolean;
}

/**
 * Where selecting an edge should pan the canvas so it lands centered in the
 * canvas area that remains once the panel is open — not the pre-panel width.
 * Computed from already-known layout data rather than by measuring the DOM
 * after render, which would race the panel's own grid-column resize (§4.2).
 */
export function computeEdgeCenterViewport(
  { sourceNode, targetNode }: EdgeCenterInput,
  { canvasWidth, canvasHeight, zoom, wasAlreadyOpen }: EdgeCenterOptions,
): { x: number; y: number; zoom: number } {
  const effectiveWidth = wasAlreadyOpen ? canvasWidth : canvasWidth - DETAIL_PANEL_WIDTH;
  const cx = (sourceNode.position.x + targetNode.position.x + (targetNode.width ?? 0)) / 2;
  const cy =
    (sourceNode.position.y +
      (sourceNode.height ?? 0) / 2 +
      targetNode.position.y +
      (targetNode.height ?? 0) / 2) /
    2;
  return { x: effectiveWidth / 2 - cx * zoom, y: canvasHeight / 2 - cy * zoom, zoom };
}
