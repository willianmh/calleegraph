import type { GraphResponse, HealthResponse, Repository, Settings, SettingsUpdate } from './types';

/**
 * Base path for every API call. Same-origin `/api` by default — nginx proxies
 * it to the backend in the container, Vite proxies it in dev. Overridable at
 * build time with `VITE_API_BASE` (contract §6's `API_BASE`).
 */
export const API_BASE: string = (import.meta.env['VITE_API_BASE'] as string | undefined) ?? '/api';

/** An API call that came back with a non-2xx status. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/**
 * FastAPI reports validation problems as `{"detail": ...}` where `detail` is
 * either a string or a list of per-field errors. Pull out something a human
 * can act on without ever guessing at wording the backend did not send.
 */
function extractDetail(body: unknown): string | null {
  if (typeof body !== 'object' || body === null) return null;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) =>
        typeof item === 'object' &&
        item !== null &&
        typeof (item as { msg?: unknown }).msg === 'string'
          ? (item as { msg: string }).msg
          : null,
      )
      .filter((msg): msg is string => msg !== null);
    if (parts.length > 0) return parts.join('; ');
  }
  return null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...(init?.body ? { headers: { 'content-type': 'application/json' } } : {}),
    ...init,
  });

  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      message = extractDetail(await response.json()) ?? message;
    } catch {
      // Body was not JSON; the status line is the best we have.
    }
    throw new ApiError(response.status, message);
  }

  if (response.status === 204) return null as T;
  return (await response.json()) as T;
}

export const api = {
  getHealth: () => request<HealthResponse>('/health'),

  getSettings: () => request<Settings>('/settings'),
  updateSettings: (body: SettingsUpdate) =>
    request<Settings>('/settings', { method: 'PUT', body: JSON.stringify(body) }),

  listRepositories: () => request<Repository[]>('/repositories'),
  addRepository: (fullName: string) =>
    request<Repository>('/repositories', {
      method: 'POST',
      body: JSON.stringify({ full_name: fullName }),
    }),
  removeRepository: (id: number) => request<null>(`/repositories/${id}`, { method: 'DELETE' }),
  refreshRepository: (id: number) =>
    request<Repository>(`/repositories/${id}/refresh`, { method: 'POST' }),

  getGraph: () => request<GraphResponse>('/graph'),
};
