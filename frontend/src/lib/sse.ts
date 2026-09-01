import type { QueryClient } from '@tanstack/react-query';

import { API_BASE } from '@/api/client';
import { queryKeys } from '@/api/queries';
import type { GraphResponse, Repository } from '@/api/types';

export type ConnectionState = 'connecting' | 'open' | 'reconnecting' | 'closed';

interface SubscribeOptions {
  client: QueryClient;
  onStateChange: (state: ConnectionState) => void;
}

/** Exponential backoff, capped — a backend restart must not spin the browser. */
const BACKOFF_MS = [1_000, 2_000, 4_000, 8_000, 15_000, 30_000] as const;

function backoffFor(attempt: number): number {
  return BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)] ?? 30_000;
}

/**
 * The single global SSE subscription (§5). One `EventSource` for the whole
 * app, opened at shell level:
 *
 *  - `repository_updated` upserts one `Repository` into the repositories cache
 *    by `id`;
 *  - `graph_updated` replaces the cached `GraphResponse` wholesale — the
 *    canvas then diffs by `node.id` / `edge.id` when it re-renders, so pan,
 *    zoom and per-node expand state survive (§4.2).
 *
 * Returns an unsubscribe function.
 */
export function subscribeToEvents({ client, onStateChange }: SubscribeOptions): () => void {
  let source: EventSource | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let attempt = 0;
  let stopped = false;

  const upsertRepository = (repository: Repository) => {
    client.setQueryData<Repository[]>(queryKeys.repositories, (previous) => {
      if (!previous) return [repository];
      const index = previous.findIndex((item) => item.id === repository.id);
      if (index === -1) return [...previous, repository];
      const next = previous.slice();
      next[index] = repository;
      return next;
    });
  };

  const parse = (event: MessageEvent<string>): unknown => {
    try {
      return JSON.parse(event.data);
    } catch {
      // A truncated or malformed frame must not take the stream down; the
      // next full payload supersedes it anyway.
      return null;
    }
  };

  const connect = () => {
    if (stopped) return;
    onStateChange(attempt === 0 ? 'connecting' : 'reconnecting');

    const next = new EventSource(`${API_BASE}/events/stream`);
    source = next;

    next.onopen = () => {
      attempt = 0;
      onStateChange('open');
      // A dropped connection may have hidden any number of events. Re-read
      // both resources once on (re)connect so the UI cannot sit on stale data.
      void client.invalidateQueries({ queryKey: queryKeys.repositories });
      void client.invalidateQueries({ queryKey: queryKeys.graph });
    };

    next.addEventListener('repository_updated', (event) => {
      const repository = parse(event as MessageEvent<string>) as Repository | null;
      if (repository) upsertRepository(repository);
    });

    next.addEventListener('graph_updated', (event) => {
      const graph = parse(event as MessageEvent<string>) as GraphResponse | null;
      if (!graph) return;
      client.setQueryData<GraphResponse>(queryKeys.graph, graph);
      // The graph payload carries the authoritative repository list too.
      client.setQueryData<Repository[]>(queryKeys.repositories, graph.repositories);
    });

    next.onerror = () => {
      next.close();
      if (source === next) source = null;
      if (stopped) return;
      onStateChange('reconnecting');
      const delay = backoffFor(attempt);
      attempt += 1;
      retryTimer = setTimeout(connect, delay);
    };
  };

  connect();

  return () => {
    stopped = true;
    if (retryTimer !== null) clearTimeout(retryTimer);
    source?.close();
    source = null;
    onStateChange('closed');
  };
}
