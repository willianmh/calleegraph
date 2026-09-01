import type {
  Edge,
  EdgeStatus,
  GraphResponse,
  IOType,
  JobCall,
  JobNode,
  NodeKind,
  WorkflowIODef,
  WorkflowNode,
} from '@/api/types';

// ---------------------------------------------------------------------------
// Adaptive density (§4.2)
// ---------------------------------------------------------------------------

/** What the user asked for. `auto` re-derives itself from the node count. */
export type DensityMode = 'auto' | 'detailed' | 'compact' | 'grouped';
/** What is actually drawn. */
export type Density = 'detailed' | 'compact' | 'grouped';

/** Under this many nodes, every card opens itself and shows job/input detail. */
export const DETAILED_BELOW = 15;
/** Over this many nodes, cards collapse into one card per repository. */
export const GROUPED_ABOVE = 40;

/**
 * Recomputed from the live node count on every render — a repo added or
 * removed, or a re-sync that changes the workflow count, moves the graph
 * between bands without any first-load latching.
 */
export function resolveDensity(nodeCount: number, mode: DensityMode): Density {
  if (mode !== 'auto') return mode;
  if (nodeCount < DETAILED_BELOW) return 'detailed';
  if (nodeCount > GROUPED_ABOVE) return 'grouped';
  return 'compact';
}

export function densityLabel(density: Density, count: number): string {
  const noun = count === 1 ? 'node' : 'nodes';
  if (density === 'grouped')
    return `Grouped — ${count} ${count === 1 ? 'repository' : 'repositories'}`;
  if (density === 'compact') return `Compact — ${count} ${noun}`;
  return `Detailed — ${count} ${noun}`;
}

// ---------------------------------------------------------------------------
// Edge styling (§4.2) — four statuses, four distinct treatments
// ---------------------------------------------------------------------------

export interface EdgeVisual {
  /** A `var(--color-*)` reference — never a literal. */
  stroke: string;
  width: number;
  /** SVG `stroke-dasharray`, or undefined for a solid line. */
  dash: string | undefined;
  /** `url(#…)` into the marker defs rendered by `<EdgeMarkers />`. */
  marker: string;
  /** Short human label, used in the legend, tooltips and aria descriptions. */
  label: string;
}

/**
 * Broadsheet carries exactly two inks. Severity is therefore expressed on the
 * magenta ramp (its "input mismatch" spot colour) by tone and weight, and
 * `unresolved` deliberately stays *neutral* — a data-completeness gap is not a
 * fault, and must never read as one. Its open, ring-terminated line says "we
 * have nothing at the other end of this yet".
 */
export const EDGE_VISUALS: Record<EdgeStatus, EdgeVisual> = {
  ok: {
    stroke: 'var(--color-neutral-400)',
    width: 1.3,
    dash: undefined,
    marker: 'url(#cg-arrow-dim)',
    label: 'Resolved call',
  },
  warning: {
    stroke: 'var(--color-accent-2-500)',
    width: 1.8,
    dash: '6 4',
    marker: 'url(#cg-arrow-warn)',
    label: 'Warning',
  },
  error: {
    stroke: 'var(--color-accent-2)',
    width: 2.4,
    dash: undefined,
    marker: 'url(#cg-arrow-error)',
    label: 'Input mismatch',
  },
  unresolved: {
    stroke: 'var(--color-neutral-500)',
    width: 1.6,
    dash: '1.5 6',
    marker: 'url(#cg-ring-open)',
    label: 'Unresolved target',
  },
};

/** Hover overlay colours, from the focus file's legend. */
export const DOWNSTREAM_STROKE = 'var(--color-accent)';
export const UPSTREAM_STROKE = 'var(--color-accent-400)';
export const DOWNSTREAM_MARKER = 'url(#cg-arrow-downstream)';
export const UPSTREAM_MARKER = 'url(#cg-arrow-upstream)';

/** How far a de-emphasised element fades (the prototype's `dimOpacity`). */
export const DIM_OPACITY = 0.16;
/** Nodes keep a touch more presence than edges so the layout stays readable. */
export const NODE_DIM_OPACITY = 0.3;

/** Rank used to pick a repository group's worst edge status. */
const STATUS_RANK: Record<EdgeStatus, number> = {
  ok: 0,
  unresolved: 1,
  warning: 2,
  error: 3,
};

export function worstStatus(statuses: readonly EdgeStatus[]): EdgeStatus {
  let worst: EdgeStatus = 'ok';
  for (const status of statuses) {
    if (STATUS_RANK[status] > STATUS_RANK[worst]) worst = status;
  }
  return worst;
}

const ISSUE_CODE_LABELS: Record<string, string> = {
  unknown_input: 'Unknown input',
  missing_required_input: 'Missing required input',
  type_mismatch: 'Type mismatch',
  unresolvable_condition: 'Unresolvable condition',
  unresolved_target: 'Unresolved target',
};

/**
 * Only the *code* is humanised for use as a kicker. Issue `message` and
 * `suggestion` are always rendered verbatim, never through this function.
 */
export function issueCodeLabel(code: string): string {
  return ISSUE_CODE_LABELS[code] ?? code.replace(/_/g, ' ');
}

// ---------------------------------------------------------------------------
// `uses:` references
// ---------------------------------------------------------------------------

export interface ParsedRef {
  /** `owner/repo`, when the ref is a cross-repo reusable workflow call. */
  repositoryFullName: string | null;
  /** The workflow path inside that repo. */
  path: string | null;
  /** The git ref after `@`. */
  gitRef: string | null;
  /** The original string, always kept for display (§5). */
  raw: string;
}

/**
 * Splits `owner/repo/.github/workflows/file.yml@ref` — and the local
 * `./.github/workflows/file.yml` form — without inventing anything: any part
 * that is not present comes back null and the raw string is shown instead.
 */
export function parseTargetRef(raw: string): ParsedRef {
  const atIndex = raw.lastIndexOf('@');
  const gitRef = atIndex > 0 ? raw.slice(atIndex + 1) : null;
  const withoutRef = atIndex > 0 ? raw.slice(0, atIndex) : raw;

  if (withoutRef.startsWith('./') || withoutRef.startsWith('.github/')) {
    return { repositoryFullName: null, path: withoutRef.replace(/^\.\//, ''), gitRef, raw };
  }

  const segments = withoutRef.split('/');
  if (segments.length >= 3 && segments[0] && segments[1]) {
    return {
      repositoryFullName: `${segments[0]}/${segments[1]}`,
      path: segments.slice(2).join('/'),
      gitRef,
      raw,
    };
  }
  return { repositoryFullName: null, path: null, gitRef, raw };
}

/** Stable synthetic id for a call target the backend could not resolve. */
export function unresolvedNodeId(targetRef: string): string {
  return `unresolved:${targetRef}`;
}

// ---------------------------------------------------------------------------
// Index
// ---------------------------------------------------------------------------

export interface GraphIndex {
  nodesById: Map<string, WorkflowNode>;
  /** Edges leaving a node — "what it calls". */
  outgoing: Map<string, Edge[]>;
  /** Edges arriving at a node, keyed by the resolved *or synthetic* target. */
  incoming: Map<string, Edge[]>;
  /** The worst status of any edge touching a node. */
  nodeStatus: Map<string, EdgeStatus>;
  /** Every distinct unresolved target, keyed by its synthetic node id. */
  unresolvedTargets: Map<string, ParsedRef>;
}

/** The id an edge points at — the resolved node, or its synthetic stand-in. */
export function edgeTargetId(edge: Edge): string {
  return edge.target_node_id ?? unresolvedNodeId(edge.target_ref);
}

export function buildIndex(graph: GraphResponse): GraphIndex {
  const nodesById = new Map(graph.nodes.map((node) => [node.id, node]));
  const outgoing = new Map<string, Edge[]>();
  const incoming = new Map<string, Edge[]>();
  const nodeStatus = new Map<string, EdgeStatus>();
  const unresolvedTargets = new Map<string, ParsedRef>();

  const bump = (id: string, status: EdgeStatus) => {
    const current = nodeStatus.get(id);
    nodeStatus.set(id, current ? worstStatus([current, status]) : status);
  };

  for (const edge of graph.edges) {
    const targetId = edgeTargetId(edge);
    push(outgoing, edge.source_node_id, edge);
    push(incoming, targetId, edge);
    bump(edge.source_node_id, edge.status);
    bump(targetId, edge.status);
    if (!edge.target_node_id) {
      unresolvedTargets.set(targetId, parseTargetRef(edge.target_ref));
    }
  }

  return { nodesById, outgoing, incoming, nodeStatus, unresolvedTargets };
}

function push<K, V>(map: Map<K, V[]>, key: K, value: V): void {
  const existing = map.get(key);
  if (existing) existing.push(value);
  else map.set(key, [value]);
}

// ---------------------------------------------------------------------------
// Hover neighbourhood (§4.2) — walks the real edge list
// ---------------------------------------------------------------------------

export interface Neighbourhood {
  /** What the focused node calls. */
  downstream: Set<string>;
  /** What calls the focused node. */
  upstream: Set<string>;
  /** Every edge id incident on it. */
  edges: Set<string>;
}

export function neighbourhoodOf(index: GraphIndex, nodeId: string): Neighbourhood {
  const downstream = new Set<string>();
  const upstream = new Set<string>();
  const edges = new Set<string>();

  for (const edge of index.outgoing.get(nodeId) ?? []) {
    downstream.add(edgeTargetId(edge));
    edges.add(edge.id);
  }
  for (const edge of index.incoming.get(nodeId) ?? []) {
    upstream.add(edge.source_node_id);
    edges.add(edge.id);
  }
  return { downstream, upstream, edges };
}

// ---------------------------------------------------------------------------
// Job wiring: the caller's `with:` against the callee's `declared_inputs`
// ---------------------------------------------------------------------------

export type BindingState = 'declared' | 'unknown' | 'unchecked';

export interface InputBinding {
  name: string;
  /** The raw expression or literal the caller assigns. */
  value: string;
  state: BindingState;
  required: boolean;
  type: IOType | null;
}

export interface CallWiring {
  job: JobNode;
  call: JobCall;
  target: WorkflowNode | null;
  targetRef: ParsedRef;
  bindings: InputBinding[];
  /** Declared, required, and not passed by this caller. */
  missingRequired: WorkflowIODef[];
}

/**
 * Derived entirely from the payload: the caller's `with` map on one side, the
 * target's `declared_inputs` on the other. When the target is unresolved there
 * is nothing to check against, and every binding stays `unchecked` rather than
 * being guessed at.
 */
export function wiringFor(node: WorkflowNode, index: GraphIndex): CallWiring[] {
  const result: CallWiring[] = [];
  for (const job of node.jobs) {
    if (!job.call) continue;
    const target = job.call.target_node_id
      ? (index.nodesById.get(job.call.target_node_id) ?? null)
      : null;
    const declared = new Map((target?.declared_inputs ?? []).map((input) => [input.name, input]));
    const passed = new Set(Object.keys(job.call.with));

    const bindings: InputBinding[] = Object.entries(job.call.with).map(([name, value]) => {
      const definition = declared.get(name);
      if (!target) return { name, value, state: 'unchecked', required: false, type: null };
      return definition
        ? { name, value, state: 'declared', required: definition.required, type: definition.type }
        : { name, value, state: 'unknown', required: false, type: null };
    });

    const missingRequired = target
      ? target.declared_inputs.filter((input) => input.required && !passed.has(input.name))
      : [];

    result.push({
      job,
      call: job.call,
      target,
      targetRef: parseTargetRef(job.call.target_ref),
      bindings,
      missingRequired,
    });
  }
  return result;
}

// ---------------------------------------------------------------------------
// Filters (§4.2 canvas controls)
// ---------------------------------------------------------------------------

export type KindFilter = 'all' | NodeKind;
export type StatusFilter = 'all' | EdgeStatus;

export interface GraphFilters {
  /** Repository full names that are switched on. `null` means "all". */
  repositories: ReadonlySet<string> | null;
  kind: KindFilter;
  status: StatusFilter;
  query: string;
}

export const EMPTY_FILTERS: GraphFilters = {
  repositories: null,
  kind: 'all',
  status: 'all',
  query: '',
};

export function nodeMatchesQuery(node: WorkflowNode, query: string): boolean {
  if (!query) return true;
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return (
    node.name.toLowerCase().includes(needle) ||
    node.path.toLowerCase().includes(needle) ||
    node.repository_full_name.toLowerCase().includes(needle)
  );
}

export interface FilteredGraph {
  nodes: WorkflowNode[];
  edges: Edge[];
  /** Synthetic stand-ins for call targets with no data yet. */
  unresolved: Map<string, ParsedRef>;
}

/**
 * Filtering keeps an edge only when both of its endpoints survive, so the
 * canvas never draws a line into empty space. Unresolved targets survive
 * alongside the edge that produced them.
 */
export function filterGraph(
  graph: GraphResponse,
  index: GraphIndex,
  filters: GraphFilters,
): FilteredGraph {
  const nodes = graph.nodes.filter((node) => {
    if (filters.repositories && !filters.repositories.has(node.repository_full_name)) return false;
    if (filters.kind !== 'all' && node.kind !== filters.kind) return false;
    if (filters.status !== 'all' && index.nodeStatus.get(node.id) !== filters.status) return false;
    return nodeMatchesQuery(node, filters.query);
  });

  const keptIds = new Set(nodes.map((node) => node.id));
  const unresolved = new Map<string, ParsedRef>();

  const edges = graph.edges.filter((edge) => {
    if (!keptIds.has(edge.source_node_id)) return false;
    if (filters.status !== 'all' && edge.status !== filters.status) return false;
    if (edge.target_node_id) return keptIds.has(edge.target_node_id);
    const id = unresolvedNodeId(edge.target_ref);
    const parsed = index.unresolvedTargets.get(id);
    if (parsed) unresolved.set(id, parsed);
    return true;
  });

  return { nodes, edges, unresolved };
}
