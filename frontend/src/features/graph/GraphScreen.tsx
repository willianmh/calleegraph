import { MiniMap, ReactFlow, ReactFlowProvider, useReactFlow, useStore } from '@xyflow/react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useGraph, useRepositories, useSettings } from '@/api/queries';
import type { WorkflowNode } from '@/api/types';
import { EdgeDetailPanel } from './EdgeDetailPanel';
import { EmptyState } from './EmptyState';
import { GraphSidebar } from './GraphSidebar';
import { CallEdge, EdgeMarkers } from './edges';
import { buildFlow, layoutFlow, type CgEdge, type CgNode, type CgNodeData } from './flow';
import { GraphInteractionContext, type GraphInteraction } from './interaction';
import { GroupCard, UnresolvedCard, WorkflowCard } from './nodes';
import {
  buildIndex,
  densityLabel,
  EMPTY_FILTERS,
  filterGraph,
  nodeMatchesQuery,
  resolveDensity,
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

export function GraphScreen() {
  return (
    <ReactFlowProvider>
      <GraphScreenInner />
    </ReactFlowProvider>
  );
}

function GraphScreenInner() {
  const graphQuery = useGraph();
  const repositoriesQuery = useRepositories();
  const settingsQuery = useSettings();
  const flow = useReactFlow<CgNode, CgEdge>();

  const [filters, setFilters] = useState<GraphFilters>(EMPTY_FILTERS);
  const [densityMode, setDensityMode] = useState<DensityMode>('auto');
  const [rawExpandOverrides, setExpandOverrides] = useState<ReadonlyMap<string, boolean>>(
    new Map(),
  );
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [hoveredEdgeId, setHoveredEdgeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const hasFitted = useRef(false);

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

  const density = resolveDensity(graph?.nodes.length ?? 0, densityMode);

  const filtered = useMemo(
    () =>
      graph
        ? filterGraph(graph, index, filters)
        : { nodes: [] as WorkflowNode[], edges: [], unresolved: new Map() },
    [graph, index, filters],
  );

  const built = useMemo(
    () =>
      layoutFlow(buildFlow({ filtered, index, density, expandOverrides, repositories }), density),
    [filtered, index, density, expandOverrides, repositories],
  );

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

  const toggleExpanded = useCallback((id: string) => {
    setExpandOverrides((previous) => {
      const next = new Map(previous);
      const current = next.get(id);
      next.set(id, current === undefined ? true : !current);
      return next;
    });
    setSelectedEdgeId(null);
  }, []);

  const interaction: GraphInteraction = useMemo(
    () => ({
      hoveredNodeId,
      neighbourhood,
      selectedEdgeId,
      hoveredEdgeId,
      matchedNodeIds,
      selectedEndpoints,
      setHoveredNode: setHoveredNodeId,
      setHoveredEdge: setHoveredEdgeId,
      selectEdge: setSelectedEdgeId,
      toggleExpanded,
    }),
    [
      hoveredNodeId,
      neighbourhood,
      selectedEdgeId,
      hoveredEdgeId,
      matchedNodeIds,
      selectedEndpoints,
      toggleExpanded,
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
      const node = built.nodes.find((candidate) => candidate.id === id);
      if (!node) return;
      void flow.setCenter(
        node.position.x + (node.width ?? 0) / 2,
        node.position.y + (node.height ?? 0) / 2,
        { zoom: Math.max(flow.getZoom(), 0.9), duration: 400 },
      );
      setExpandOverrides((previous) => new Map(previous).set(id, true));
    },
    [built.nodes, flow],
  );

  const workflowCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const node of graph?.nodes ?? []) {
      counts.set(node.repository_full_name, (counts.get(node.repository_full_name) ?? 0) + 1);
    }
    return counts;
  }, [graph]);

  const issueEdges = useMemo(
    () => (graph?.edges ?? []).filter((edge) => edge.issues.length > 0),
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
          gridTemplateColumns: panelOpen ? '268px minmax(0, 1fr) 372px' : '268px minmax(0, 1fr)',
        }}
      >
        <GraphSidebar
          repositories={repositories}
          nodes={graph?.nodes ?? []}
          issueEdges={issueEdges}
          nodesById={index.nodesById}
          filters={filters}
          onFiltersChange={setFilters}
          densityMode={densityMode}
          onDensityModeChange={setDensityMode}
          selectedEdgeId={selectedEdgeId}
          onSelectEdge={setSelectedEdgeId}
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
            {built.nodes.length > 24 && (
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

          <CanvasControls density={densityMode} onDensityChange={setDensityMode} />

          <div className="pointer-events-none absolute top-[14px] right-[16px] text-right text-[10.5px] tracking-[0.08em] text-neutral-600 uppercase">
            {densityLabel(density, built.nodes.length)}
            {densityMode !== 'auto' && <span className="block">manual override</span>}
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
            onSelectEdge={setSelectedEdgeId}
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
  density,
  onDensityChange,
}: {
  density: DensityMode;
  onDensityChange: (mode: DensityMode) => void;
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
        aria-pressed={density === 'grouped'}
        style={
          density === 'grouped'
            ? { background: 'var(--color-accent-100)', color: 'var(--color-accent-700)' }
            : undefined
        }
        onClick={() => {
          onDensityChange(density === 'grouped' ? 'auto' : 'grouped');
        }}
      >
        Group by repo
      </button>
    </div>
  );
}
