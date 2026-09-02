import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';

import { useGraph, useRepositories } from '@/api/queries';
import type { GraphResponse } from '@/api/types';
import { ConnectionDot } from '@/components/StatusDot';
import { buildIndex, EMPTY_FILTERS, filterGraph, type GraphFilters } from '@/features/graph/model';
import { subscribeToEvents, type ConnectionState } from '@/lib/sse';

const NAV = [
  { to: '/', label: 'Graph', end: true },
  { to: '/repositories', label: 'Repositories', end: false },
  { to: '/settings', label: 'Settings', end: false },
] as const;

const EMPTY_GRAPH: GraphResponse = { repositories: [], nodes: [], edges: [], generated_at: '' };

/**
 * Shared with `GraphScreen` via `useOutletContext` so the masthead's stat
 * line and the canvas filter the same graph the same way (§4.2) — filters
 * live here, one level above the graph route, because the masthead that
 * needs to respect them lives here too.
 */
export interface GraphOutletContext {
  filters: GraphFilters;
  setFilters: Dispatch<SetStateAction<GraphFilters>>;
}

/**
 * The app shell: the front-page masthead, the thick-thin rule pair carrying
 * the running stat line, and the one global SSE subscription (§4.1/§5).
 */
export function App() {
  const client = useQueryClient();
  const [connection, setConnection] = useState<ConnectionState>('connecting');
  const [filters, setFilters] = useState<GraphFilters>(EMPTY_FILTERS);
  const repositories = useRepositories();
  const graph = useGraph();
  const location = useLocation();

  useEffect(() => {
    return subscribeToEvents({ client, onStateChange: setConnection });
  }, [client]);

  const repos = repositories.data ?? [];
  const syncing = repos.filter(
    (repo) => repo.status === 'fetching' || repo.status === 'parsing' || repo.status === 'pending',
  ).length;
  const synced = repos.filter((repo) => repo.status === 'done').length;
  const failed = repos.filter((repo) => repo.status === 'error').length;

  /**
   * A small, deliberate duplication of the same `buildIndex`/`filterGraph`
   * pass `GraphScreen` runs on `graph.data` — inconsequential at this app's
   * scale, and it keeps the masthead and the canvas independently correct
   * off the same inputs rather than coupling their render cycles.
   */
  const index = useMemo(() => buildIndex(graph.data ?? EMPTY_GRAPH), [graph.data]);
  const filtered = useMemo(
    () => filterGraph(graph.data ?? EMPTY_GRAPH, index, filters),
    [graph.data, index, filters],
  );

  const statLine = useMemo(() => {
    if (repos.length === 0) return 'No repositories tracked';
    const parts = [`${repos.length} ${repos.length === 1 ? 'repository' : 'repositories'}`];
    const nodes = filtered.nodes.length;
    const edges = filtered.edges.length;
    parts.push(`${nodes} ${nodes === 1 ? 'workflow' : 'workflows'}`);
    parts.push(`${edges} ${edges === 1 ? 'call edge' : 'call edges'}`);
    return parts.join(' · ');
  }, [repos.length, filtered]);

  const syncLine = [
    synced > 0 ? `${synced} synced` : null,
    syncing > 0 ? `${syncing} syncing` : null,
    failed > 0 ? `${failed} failed` : null,
  ]
    .filter((part): part is string => part !== null)
    .join(' · ');

  /** Broader than the Mismatches list on purpose — "issues" includes warnings. */
  const issueCount = filtered.edges.filter((edge) => edge.issues.length > 0).length;

  return (
    <div className="grid h-full grid-rows-[auto_1fr] overflow-hidden">
      <header className="px-[26px] pt-[14px]">
        <div className="flex items-baseline gap-[18px]">
          <div className="flex items-baseline gap-[10px]">
            <span className="font-heading text-[26px] leading-none font-bold tracking-[-0.01em]">
              Calleegraph
            </span>
            <span className="text-[12px] text-neutral-600 italic">workflow dependency atlas</span>
          </div>
          <nav className="ml-auto flex items-center gap-[4px]" aria-label="Primary">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className="btn btn-ghost px-[11px] py-[5px] text-[12.5px]"
                style={({ isActive }) =>
                  isActive
                    ? { background: 'var(--color-accent-100)', color: 'var(--color-accent-700)' }
                    : undefined
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
        <div
          className="mt-[10px] flex items-baseline gap-[14px] py-[5px] text-[11px] tracking-[0.09em] text-neutral-700 uppercase"
          style={{
            borderTop: '3px solid var(--color-text)',
            borderBottom: '1px solid var(--color-text)',
          }}
        >
          <span>{statLine}</span>
          {issueCount > 0 && location.pathname === '/' && (
            <span style={{ color: 'var(--color-accent-2-700)' }}>
              {issueCount} {issueCount === 1 ? 'call with issues' : 'calls with issues'}
            </span>
          )}
          <span className="ml-auto flex items-center gap-[14px]">
            {syncLine && <span>{syncLine}</span>}
            <ConnectionDot state={connection} />
          </span>
        </div>
      </header>
      <main className="min-h-0">
        <Outlet context={{ filters, setFilters } satisfies GraphOutletContext} />
      </main>
    </div>
  );
}
