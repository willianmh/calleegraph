import { Link } from 'react-router-dom';

import type { Edge, Repository, WorkflowNode } from '@/api/types';
import { RepoStatusDot } from '@/components/StatusDot';
import { SectionLabel, Segmented } from '@/components/ui';
import { Legend } from './Legend';
import type { DensityMode, GraphFilters, KindFilter, StatusFilter } from './model';
import { issueCodeLabel } from './model';

const KIND_OPTIONS = [
  { value: 'all' as const, label: 'All' },
  { value: 'reusable' as const, label: 'Reusable' },
  { value: 'top_level' as const, label: 'Top-level' },
];

const STATUS_OPTIONS = [
  { value: 'all' as const, label: 'All' },
  { value: 'error' as const, label: 'Errors' },
  { value: 'warning' as const, label: 'Warnings' },
  { value: 'unresolved' as const, label: 'Unresolved' },
];

const DENSITY_OPTIONS = [
  { value: 'auto' as const, label: 'Auto' },
  { value: 'detailed' as const, label: 'Detailed' },
  { value: 'compact' as const, label: 'Compact' },
  { value: 'grouped' as const, label: 'Grouped' },
];

export interface GraphSidebarProps {
  repositories: readonly Repository[];
  nodes: readonly WorkflowNode[];
  /** Every edge that carries at least one issue, in payload order. */
  issueEdges: readonly Edge[];
  nodesById: ReadonlyMap<string, WorkflowNode>;
  filters: GraphFilters;
  onFiltersChange: (next: GraphFilters) => void;
  densityMode: DensityMode;
  onDensityModeChange: (mode: DensityMode) => void;
  selectedEdgeId: string | null;
  onSelectEdge: (id: string) => void;
  onJumpToNode: (id: string) => void;
  workflowCounts: ReadonlyMap<string, number>;
}

export function GraphSidebar({
  repositories,
  nodes,
  issueEdges,
  nodesById,
  filters,
  onFiltersChange,
  densityMode,
  onDensityModeChange,
  selectedEdgeId,
  onSelectEdge,
  onJumpToNode,
  workflowCounts,
}: GraphSidebarProps) {
  const query = filters.query.trim().toLowerCase();
  const matches = query
    ? nodes
        .filter(
          (node) =>
            node.name.toLowerCase().includes(query) ||
            node.path.toLowerCase().includes(query) ||
            node.repository_full_name.toLowerCase().includes(query),
        )
        .slice(0, 8)
    : [];

  const activeRepos = filters.repositories;
  const toggleRepo = (fullName: string) => {
    const current = new Set(activeRepos ?? repositories.map((repo) => repo.full_name));
    if (current.has(fullName)) current.delete(fullName);
    else current.add(fullName);
    onFiltersChange({ ...filters, repositories: current });
  };

  return (
    <aside className="flex min-h-0 flex-col gap-[26px] overflow-y-auto py-[20px] pr-[22px] pl-[26px]">
      <div>
        <label htmlFor="graph-search" className="sr-only">
          Search workflows
        </label>
        <input
          id="graph-search"
          type="search"
          className="input cg-mono px-[9px] py-[7px] text-[12px]"
          placeholder="Search workflows…"
          value={filters.query}
          onChange={(event) => {
            onFiltersChange({ ...filters, query: event.target.value });
          }}
        />
        {query.length > 0 && (
          <div className="mt-[8px] flex flex-col">
            {matches.map((node) => (
              <button
                key={node.id}
                type="button"
                className="cg-hit cursor-pointer border-0 bg-transparent px-[7px] py-[5px] text-left"
                onClick={() => {
                  onJumpToNode(node.id);
                }}
              >
                <span className="cg-mono text-[11.5px]">{node.path}</span>
                <span className="block text-[10.5px] text-neutral-600">
                  {node.repository_full_name}
                </span>
              </button>
            ))}
            {matches.length === 0 && (
              <span className="px-[7px] py-[5px] text-[11.5px] text-neutral-600 italic">
                No workflow matches that.
              </span>
            )}
          </div>
        )}
      </div>

      <div>
        <SectionLabel>Repositories</SectionLabel>
        <div className="flex flex-col gap-[9px]">
          {repositories.map((repo) => {
            const on = !activeRepos || activeRepos.has(repo.full_name);
            return (
              <button
                key={repo.id}
                type="button"
                className="flex w-full cursor-pointer items-center gap-[10px] border-0 bg-transparent px-0 py-[3px] text-left"
                style={{ opacity: on ? 1 : 0.42 }}
                aria-pressed={on}
                onClick={() => {
                  toggleRepo(repo.full_name);
                }}
              >
                <span
                  aria-hidden
                  className="grid h-[22px] w-[22px] flex-none place-items-center rounded-sm text-[11px] font-bold"
                  style={{
                    color: 'var(--color-bg)',
                    background: on ? 'var(--color-neutral-800)' : 'var(--color-neutral-400)',
                  }}
                >
                  {repo.name.slice(0, 1).toUpperCase()}
                </span>
                <span className="flex min-w-0 flex-col items-start leading-[1.25]">
                  <span className="cg-mono truncate text-[11.5px]">{repo.full_name}</span>
                  <span className="flex items-center gap-[5px] text-[10px] text-neutral-600">
                    <RepoStatusDot status={repo.status} />
                    {repo.default_branch}
                  </span>
                </span>
                <span className="ml-auto text-[11px] text-neutral-600">
                  {workflowCounts.get(repo.full_name) ?? 0} wf
                </span>
              </button>
            );
          })}
          {repositories.length === 0 && (
            <span className="text-[11.5px] text-neutral-600 italic">None tracked yet.</span>
          )}
        </div>
        <Link to="/repositories" className="btn btn-ghost mt-[10px] px-0 py-[4px] text-[11.5px]">
          Add or remove repositories
        </Link>
      </div>

      <div>
        <SectionLabel>Type</SectionLabel>
        <Segmented
          label="Filter by workflow type"
          options={KIND_OPTIONS}
          value={filters.kind}
          onChange={(kind: KindFilter) => {
            onFiltersChange({ ...filters, kind });
          }}
        />
        <div className="mt-[16px]">
          <SectionLabel>Call status</SectionLabel>
          <Segmented
            label="Filter by call status"
            options={STATUS_OPTIONS}
            value={filters.status}
            onChange={(status: StatusFilter) => {
              onFiltersChange({ ...filters, status });
            }}
          />
        </div>
        <div className="mt-[16px]">
          <SectionLabel>Density</SectionLabel>
          <Segmented
            label="Graph density"
            options={DENSITY_OPTIONS}
            value={densityMode}
            onChange={onDensityModeChange}
          />
        </div>
      </div>

      <div>
        <SectionLabel>Mismatches</SectionLabel>
        <div className="flex flex-col gap-[3px]">
          {issueEdges.map((edge) => {
            const active = selectedEdgeId === edge.id;
            const first = edge.issues[0];
            const source = nodesById.get(edge.source_node_id);
            const target = edge.target_node_id ? nodesById.get(edge.target_node_id) : undefined;
            return (
              <button
                key={edge.id}
                type="button"
                className="cursor-pointer border-0 px-[10px] py-[7px] text-left"
                style={{
                  background: active ? 'var(--color-accent-2-100)' : 'transparent',
                  borderLeft: '2px solid var(--color-accent-2)',
                }}
                onClick={() => {
                  onSelectEdge(edge.id);
                }}
              >
                <span className="text-[12px] font-semibold">
                  {first ? issueCodeLabel(first.code) : 'Issue'}
                </span>
                <span className="cg-mono mt-[2px] block text-[10px] text-neutral-700">
                  {source?.path ?? edge.source_node_id} → {target?.path ?? edge.target_ref}
                </span>
              </button>
            );
          })}
          {issueEdges.length === 0 && (
            <span className="text-[11.5px] text-neutral-600 italic">
              No mismatched calls in the current graph.
            </span>
          )}
        </div>
      </div>

      <Legend />
    </aside>
  );
}
