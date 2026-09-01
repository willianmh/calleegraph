import { MiniMap, ReactFlow, ReactFlowProvider, useReactFlow, useStore } from '@xyflow/react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useOutletContext } from 'react-router-dom';

import { useGraph, useRepositories, useSettings } from '@/api/queries';
import type { WorkflowNode } from '@/api/types';
import type { GraphOutletContext } from '@/App';
import { EdgeDetailPanel } from './EdgeDetailPanel';
import { EmptyState } from './EmptyState';
import { GraphSidebar } from './GraphSidebar';
import { CallEdge, EdgeMarkers } from './edges';
import {
  buildFlow,
  computeEdgeCenterViewport,
  layoutFlow,
  type CgEdge,
  type CgNode,
  type CgNodeData,
} from './flow';
import { GraphInteractionContext, type GraphInteraction } from './interaction';
import { GroupCard, UnresolvedCard, WorkflowCard } from './nodes';
import {
  buildIndex,
  densityLabel,
  DETAIL_PANEL_WIDTH,
  DIM_OPACITY,
  filterGraph,
  nodeMatchesQuery,
  resolveCompact,
  type DensityMode,
  type GraphFilters,
  type Neighbourhood,
} from './model';

const nodeTypes = {
  workflow: WorkflowCard,
  unresolved: UnresolvedCard,
  group: GroupCard,
};
const edgeTypes = { call: CallEdge };

/**
 * §9 configuration surface: embed-time props, not a live in-app control — the
 * rail's Type/Status segments and the canvas's Group-by-repo toggle are the
 * only density-adjacent UI this design has.
 */
export interface GraphScreenProps {
  density?: DensityMode;
  showMinimap?: boolean;
  dimOpacity?: number;
}

export function GraphScreen(props: GraphScreenProps) {
  return (
    <ReactFlowProvider>
      <GraphScreenInner {...props} />
    </ReactFlowProvider>
  );
}

function GraphScreenInner({
  density = 'auto',
  showMinimap = true,
  dimOpacity = DIM_OPACITY,
}: GraphScreenProps) {
  const graphQuery = useGraph();
  const repositoriesQuery = useRepositories();
  const settingsQuery = useSettings();
  const flow = useReactFlow<CgNode, CgEdge>();

  const { filters, setFilters } = useOutletContext<GraphOutletContext>();
  const [grouped, setGrouped] = useState(false);
  const [rawExpandOverrides, setExpandOverrides] = useState<ReadonlyMap<string, boolean>>(
    new Map(),
  );
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [hoveredEdgeId, setHoveredEdgeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const hasFitted = useRef(false);

  /**
   * Compact-vs-detailed is derived from the live zoom transform (or forced by
   * `grouped`) — never from node count. `state.width`/`state.height` are React
   * Flow's own measured-pane size, the same `ResizeObserver`-backed source
   * `fitView`/`setCenter` use internally.
   */
  const zoomScale = useStore((state) => state.transform[2]);
  const canvasWidth = useStore((state) => state.width);
  const canvasHeight = useStore((state) => state.height);
  const compact = resolveCompact({ densityMode: density, grouped, zoomScale });

  const graph = graphQuery.data;
  const repositories = useMemo(
    () => repositoriesQuery.data ?? graph?.repositories ?? [],
    [repositoriesQuery.data, graph],
  );

  const index = useMemo(
    () => buildIndex(graph ?? { repositories: [], nodes: [], edges: [], generated_at: '' }),
    [graph],
  );

  /**
   * §4.2: a live update must not throw away what the user opened. Overrides are
   * pruned to the ids that still exist and otherwise carried through untouched,
   * so surviving nodes keep their expand state.
   *
   * Derived during render rather than synced in an effect: an effect would
   * render once with the stale map and then immediately re-render, which is the
   * cascading-render pattern `react-hooks/set-state-in-effect` warns about. A
   * stale entry for a deleted node is inert here — nothing looks it up — so
   * pruning is presentation-only.
   */
  const expandOverrides = useMemo(() => {
    if (!graph || rawExpandOverrides.size === 0) return rawExpandOverrides;
    const alive = new Set(graph.nodes.map((node) => node.id));
    let changed = false;
    const next = new Map<string, boolean>();
    for (const [id, value] of rawExpandOverrides) {
      if (alive.has(id)) next.set(id, value);
      else changed = true;
    }
    return changed ? next : rawExpandOverrides;
  }, [graph, rawExpandOverrides]);

  const filtered = useMemo(
    () =>
      graph
        ? filterGraph(graph, index, filters)
        : { nodes: [] as WorkflowNode[], edges: [], unresolved: new Map() },
    [graph, index, filters],
  );

  /**
   * Both layouts are always computed — cheap at this app's scale — so
   * `builtUngrouped` always holds current, real node positions. That is what
   * lets a forced ungroup (selecting a real edge id while grouped) center
   * correctly with no extra render round-trip.
   */
  const builtUngrouped = useMemo(
    () =>
      layoutFlow(
        buildFlow({ filtered, index, compact, grouped: false, expandOverrides, repositories }),
        { compact, grouped: false },
      ),
    [filtered, index, compact, expandOverrides, repositories],
  );
  const builtGrouped = useMemo(
    () =>
      layoutFlow(
        buildFlow({
          filtered,
          index,
          compact: true,
          grouped: true,
          expandOverrides,
          repositories,
        }),
        { compact: true, grouped: true },
      ),
    [filtered, index, expandOverrides, repositories],
  );
  const built = grouped ? builtGrouped : builtUngrouped;

  const matchedNodeIds = useMemo(() => {
    if (!filters.query.trim() || !graph) return null;
    return new Set(
      graph.nodes.filter((node) => nodeMatchesQuery(node, filters.query)).map((node) => node.id),
    );
  }, [filters.query, graph]);

  const selectedEdge = useMemo(
    () => built.edges.find((edge) => edge.id === selectedEdgeId) ?? null,
    [built.edges, selectedEdgeId],
  );

  const selectedEndpoints = useMemo(() => {
    if (!selectedEdge) return new Set<string>();
    return new Set([selectedEdge.source, selectedEdge.target]);
  }, [selectedEdge]);

  const neighbourhood = useMemo(
    () => (hoveredNodeId ? neighbourhoodOfBuilt(built, hoveredNodeId) : null),
    [built, hoveredNodeId],
  );

  /** Only one node is ever expanded at a time (§3.2): expanding replaces the
   * whole override map rather than adding to it. */
  const toggleExpanded = useCallback((id: string) => {
    setExpandOverrides((previous) => (previous.get(id) ? new Map() : new Map([[id, true]])));
    setSelectedEdgeId(null);
  }, []);

  const ungroup = useCallback(() => {
    setGrouped(false);
    setExpandOverrides(new Map());
    setSelectedEdgeId(null);
  }, []);

  const toggleGrouped = useCallback(() => {
    setGrouped((value) => !value);
    setExpandOverrides(new Map());
    setSelectedEdgeId(null);
  }, []);

  /**
   * The one handler behind every edge selection — canvas click, the
   * Mismatches list, and the panel's own grouped sub-list. When the id only
   * resolves in the ungrouped layout (a real edge reached while `grouped` is
   * on), it ungroups first so the selection has something real to show, then
   * centers using `builtUngrouped`'s always-current positions.
   */
  const selectEdgeAndCenter = useCallback(
    (edgeId: string) => {
      const inCurrent = built.edges.find((edge) => edge.id === edgeId);
      const source = inCurrent ? built : builtUngrouped;
      const wasAlreadyOpen = selectedEdgeId !== null;
      if (!inCurrent) {
        setGrouped(false);
        setExpandOverrides(new Map());
      }
      setSelectedEdgeId(edgeId);
      const edge = source.edges.find((candidate) => candidate.id === edgeId);
      const sourceNode = edge && source.nodes.find((node) => node.id === edge.source);
      const targetNode = edge && source.nodes.find((node) => node.id === edge.target);
      if (!edge || !sourceNode || !targetNode) return;
      void flow.setViewport(
        computeEdgeCenterViewport(
          { sourceNode, targetNode },
          { canvasWidth, canvasHeight, zoom: flow.getZoom(), wasAlreadyOpen },
        ),
        { duration: 300 },
      );
    },
    [built, builtUngrouped, canvasWidth, canvasHeight, flow, selectedEdgeId],
  );

  /** Type/Status/repo-toggle changes clear both the expanded node and the
   * selected edge (§4.2); the search box is lighter-weight — see below. */
  const handleFiltersChange = useCallback(
    (next: GraphFilters) => {
      setFilters(next);
      setSelectedEdgeId(null);
      setExpandOverrides(new Map());
    },
    [setFilters],
  );

  const handleQueryChange = useCallback(
    (query: string) => {
      setFilters((previous) => ({ ...previous, query }));
      setSelectedEdgeId(null);
    },
    [setFilters],
  );

  const interaction: GraphInteraction = useMemo(
    () => ({
      hoveredNodeId,
      neighbourhood,
      selectedEdgeId,
      hoveredEdgeId,
      matchedNodeIds,
      selectedEndpoints,
      dimOpacity,
      nodeDimOpacity: dimOpacity + 0.14,
      setHoveredNode: setHoveredNodeId,
      setHoveredEdge: setHoveredEdgeId,
      selectEdge: selectEdgeAndCenter,
      toggleExpanded,
      ungroup,
    }),
    [
      hoveredNodeId,
      neighbourhood,
      selectedEdgeId,
      hoveredEdgeId,
      matchedNodeIds,
      selectedEndpoints,
      dimOpacity,
      selectEdgeAndCenter,
      toggleExpanded,
      ungroup,
    ],
  );

  /**
   * Fit once, the first time there is anything to fit. Every later update —
   * including a `graph_updated` event — leaves the viewport exactly where the
   * user put it (§4.2).
   */
  useEffect(() => {
    if (hasFitted.current || built.nodes.length === 0) return;
    hasFitted.current = true;
    void flow.fitView({ padding: 0.15, maxZoom: 1 });
  }, [built.nodes.length, flow]);

  const jumpToNode = useCallback(
    (id: string) => {
      if (grouped) setGrouped(false);
      setExpandOverrides(new Map([[id, true]]));
      setHoveredNodeId(id);
      const node = builtUngrouped.nodes.find((candidate) => candidate.id === id);
      if (!node) return;
      void flow.setCenter(
        node.position.x + (node.width ?? 0) / 2,
        node.position.y + (node.height ?? 0) / 2,
        { zoom: Math.max(flow.getZoom(), 0.9), duration: 400 },
      );
    },
    [grouped, builtUngrouped.nodes, flow],
  );

  const workflowCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const node of graph?.nodes ?? []) {
      counts.set(node.repository_full_name, (counts.get(node.repository_full_name) ?? 0) + 1);
    }
    return counts;
  }, [graph]);

  /** Errors only — a warning-only edge belongs in the panel, not this list (§4.2). */
  const issueEdges = useMemo(
    () => (graph?.edges ?? []).filter((edge) => edge.status === 'error'),
    [graph],
  );

  if (repositoriesQuery.isSuccess && repositories.length === 0) {
    return <EmptyState patSet={settingsQuery.data?.pat_set ?? false} />;
  }

  if (graphQuery.isError) {
    return (
      <div className="px-[26px] py-[44px]">
        <h1 className="font-heading text-[34px]">The graph could not be loaded.</h1>
        <p className="max-w-[52ch] text-[15px] text-neutral-800">{graphQuery.error.message}</p>
      </div>
    );
  }

  const panelOpen = selectedEdge !== null;

  return (
    <GraphInteractionContext.Provider value={interaction}>
      <div
        className="grid h-full min-h-0"
        style={{
          gridTemplateColumns: panelOpen
            ? `268px minmax(0, 1fr) ${DETAIL_PANEL_WIDTH}px`
            : '268px minmax(0, 1fr)',
        }}
      >
        <GraphSidebar
          repositories={repositories}
          nodes={graph?.nodes ?? []}
          issueEdges={issueEdges}
          nodesById={index.nodesById}
          filters={filters}
          onFiltersChange={handleFiltersChange}
          onQueryChange={handleQueryChange}
          selectedEdgeId={selectedEdgeId}
          onSelectEdge={selectEdgeAndCenter}
          onJumpToNode={jumpToNode}
          workflowCounts={workflowCounts}
        />

        <section
          className="relative min-h-0 overflow-hidden"
          style={{ background: 'var(--color-neutral-100)' }}
        >
          <EdgeMarkers />
          <ReactFlow<CgNode, CgEdge>
            nodes={built.nodes}
            edges={built.edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            onPaneClick={() => {
              setSelectedEdgeId(null);
              setHoveredNodeId(null);
              setExpandOverrides(new Map());
            }}
            proOptions={{ hideAttribution: false }}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            minZoom={0.15}
            maxZoom={2}
            panOnScroll
            zoomOnDoubleClick={false}
          >
            {showMinimap && (
              <MiniMap
                pannable
                zoomable
                position="bottom-right"
                style={{
                  background: 'var(--color-paper)',
                  border: '1px solid var(--color-neutral-300)',
                }}
                maskColor="color-mix(in srgb, var(--color-neutral-500) 22%, transparent)"
                nodeColor={(node) => nodeMiniColor(node.data as CgNodeData)}
                nodeStrokeWidth={0}
              />
            )}
          </ReactFlow>

          <CanvasControls grouped={grouped} onToggleGrouped={toggleGrouped} />

          <div className="pointer-events-none absolute top-[14px] right-[16px] text-right text-[10.5px] tracking-[0.08em] text-neutral-600 uppercase">
            {densityLabel({ grouped, compact, count: built.nodes.length })}
          </div>

          {graphQuery.isPending && (
            <div className="pointer-events-none absolute inset-0 grid place-items-center text-[13px] text-neutral-600 italic">
              Reading the graph…
            </div>
          )}
          {graphQuery.isSuccess && built.nodes.length === 0 && (
            <div className="pointer-events-none absolute inset-0 grid place-items-center px-[26px] text-center text-[13px] text-neutral-700 italic">
              {(graph?.nodes.length ?? 0) === 0
                ? 'No workflows parsed yet. Repositories still syncing will appear here as they finish.'
                : 'No workflow matches the current filters.'}
            </div>
          )}
        </section>

        {selectedEdge?.data && (
          <EdgeDetailPanel
            selection={selectedEdge.data}
            index={index}
            apiBase={settingsQuery.data?.github_api_base ?? 'https://api.github.com'}
            trackedRepositories={new Set(repositories.map((repo) => repo.full_name))}
            onClose={() => {
              setSelectedEdgeId(null);
            }}
            onSelectEdge={selectEdgeAndCenter}
          />
        )}
      </div>
    </GraphInteractionContext.Provider>
  );
}

/**
 * The hovered node's dependents and dependencies, walked over the edges that
 * are actually on the canvas (so it stays correct in grouped density too).
 */
function neighbourhoodOfBuilt(built: { edges: CgEdge[] }, nodeId: string): Neighbourhood {
  const downstream = new Set<string>();
  const upstream = new Set<string>();
  const edges = new Set<string>();
  for (const edge of built.edges) {
    if (edge.source === nodeId) {
      downstream.add(edge.target);
      edges.add(edge.id);
    } else if (edge.target === nodeId) {
      upstream.add(edge.source);
      edges.add(edge.id);
    }
  }
  return { downstream, upstream, edges };
}

function nodeMiniColor(data: CgNodeData): string {
  if (data.variant === 'unresolved') return 'var(--color-neutral-400)';
  const status = data.status;
  return status === 'error' || status === 'warning'
    ? 'var(--color-accent-2)'
    : 'var(--color-neutral-500)';
}

function CanvasControls({
  grouped,
  onToggleGrouped,
}: {
  grouped: boolean;
  onToggleGrouped: () => void;
}) {
  const flow = useReactFlow();
  const zoom = useStore((state) => state.transform[2]);

  return (
    <div
      className="absolute bottom-[16px] left-[16px] flex items-center gap-[6px] px-[7px] py-[5px]"
      style={{
        background: 'color-mix(in srgb, var(--color-paper) 90%, transparent)',
        border: '1px solid var(--color-neutral-300)',
      }}
    >
      <button
        type="button"
        className="btn btn-secondary px-[10px] py-[4px] text-[14px]"
        aria-label="Zoom out"
        onClick={() => void flow.zoomOut({ duration: 150 })}
      >
        –
      </button>
      <span className="cg-mono min-w-[34px] text-center text-[11px] text-neutral-700">
        {Math.round(zoom * 100)}%
      </span>
      <button
        type="button"
        className="btn btn-secondary px-[10px] py-[4px] text-[14px]"
        aria-label="Zoom in"
        onClick={() => void flow.zoomIn({ duration: 150 })}
      >
        +
      </button>
      <button
        type="button"
        className="btn btn-ghost px-[8px] py-[4px] text-[11.5px]"
        onClick={() => void flow.fitView({ padding: 0.15, duration: 300 })}
      >
        Fit
      </button>
      <button
        type="button"
        className="btn btn-ghost px-[8px] py-[4px] text-[11.5px]"
        aria-pressed={grouped}
        style={
          grouped
            ? { background: 'var(--color-accent-100)', color: 'var(--color-accent-700)' }
            : undefined
        }
        onClick={onToggleGrouped}
      >
        Group by repo
      </button>
    </div>
  );
}
