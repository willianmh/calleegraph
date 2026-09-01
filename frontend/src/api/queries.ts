import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './client';
import type { GraphResponse, Repository, Settings, SettingsUpdate } from './types';

/**
 * One place that owns every cache key, so the SSE subscription in
 * `lib/sse.ts` writes to exactly the keys these hooks read from.
 */
export const queryKeys = {
  settings: ['settings'] as const,
  repositories: ['repositories'] as const,
  graph: ['graph'] as const,
};

/**
 * The stream is the source of truth for freshness: `repository_updated` and
 * `graph_updated` push every change. Polling on top of that would only cause
 * the canvas to churn, so these queries never refetch on their own.
 */
const liveOptions = {
  staleTime: Infinity,
  refetchOnWindowFocus: false,
  refetchInterval: false,
} as const;

export function useRepositories() {
  return useQuery({
    queryKey: queryKeys.repositories,
    queryFn: api.listRepositories,
    ...liveOptions,
  });
}

export function useGraph() {
  return useQuery({
    queryKey: queryKeys.graph,
    queryFn: api.getGraph,
    ...liveOptions,
  });
}

export function useSettings() {
  return useQuery({
    queryKey: queryKeys.settings,
    queryFn: api.getSettings,
    ...liveOptions,
  });
}

export function useUpdateSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: SettingsUpdate) => api.updateSettings(body),
    onSuccess: (settings: Settings) => {
      client.setQueryData(queryKeys.settings, settings);
    },
  });
}

export function useAddRepository() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (fullName: string) => api.addRepository(fullName),
    onSuccess: (repository: Repository) => {
      // §5: POST returns immediately with status "pending"; the fetch/parse
      // transitions arrive later over SSE. Seed the cache so the new row is
      // on screen before the first event lands.
      client.setQueryData<Repository[]>(queryKeys.repositories, (previous) => {
        const rest = (previous ?? []).filter((item) => item.id !== repository.id);
        return [...rest, repository];
      });
    },
  });
}

export function useRemoveRepository() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.removeRepository(id),
    onSuccess: (_result, id) => {
      client.setQueryData<Repository[]>(queryKeys.repositories, (previous) =>
        (previous ?? []).filter((item) => item.id !== id),
      );
      // Drop the removed repo's nodes straight away rather than waiting for
      // the `graph_updated` event, so edges pointing at it flip to their
      // "unresolved" treatment immediately.
      client.setQueryData<GraphResponse>(queryKeys.graph, (previous) => {
        if (!previous) return previous;
        const removed = previous.repositories.find((item) => item.id === id);
        if (!removed) return previous;
        const survivingNodes = previous.nodes.filter(
          (node) => node.repository_full_name !== removed.full_name,
        );
        const survivingIds = new Set(survivingNodes.map((node) => node.id));
        return {
          ...previous,
          repositories: previous.repositories.filter((item) => item.id !== id),
          nodes: survivingNodes,
          edges: previous.edges
            .filter((edge) => survivingIds.has(edge.source_node_id))
            .map((edge) =>
              edge.target_node_id && !survivingIds.has(edge.target_node_id)
                ? { ...edge, target_node_id: null, status: 'unresolved' as const }
                : edge,
            ),
        };
      });
    },
  });
}

export function useRefreshRepository() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.refreshRepository(id),
    onSuccess: (repository: Repository) => {
      client.setQueryData<Repository[]>(queryKeys.repositories, (previous) =>
        (previous ?? []).map((item) => (item.id === repository.id ? repository : item)),
      );
    },
  });
}
