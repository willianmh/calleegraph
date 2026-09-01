/**
 * Turns the configured API base into the matching HTML base, so "Open in
 * GitHub" also works against GitHub Enterprise (`https://host/api/v3` →
 * `https://host`). Returns null rather than guessing when the shape is
 * unfamiliar — a dead link is worse than no link.
 */
export function htmlBaseFor(apiBase: string): string | null {
  try {
    const url = new URL(apiBase);
    if (url.hostname === 'api.github.com') return 'https://github.com';
    if (url.pathname.replace(/\/$/, '').endsWith('/api/v3')) {
      return `${url.origin}${url.pathname.replace(/\/api\/v3\/?$/, '')}`;
    }
    return url.origin;
  } catch {
    return null;
  }
}

export function workflowFileUrl(
  apiBase: string,
  repositoryFullName: string,
  ref: string,
  path: string,
): string | null {
  const base = htmlBaseFor(apiBase);
  if (!base) return null;
  return `${base}/${repositoryFullName}/blob/${ref}/${path}`;
}
