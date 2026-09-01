/* eslint-disable react-refresh/only-export-components -- `repoStatusLabel` reads the
   same REPO_STATUS_STYLE map the dots render from; splitting them into two modules to
   satisfy fast refresh would duplicate the palette. Dev-only HMR nicety, not a runtime
   concern. */
import type { RepoStatus } from '@/api/types';
import type { ConnectionState } from '@/lib/sse';

/**
 * Repository status colours. Broadsheet carries exactly two inks, so the
 * progression runs up the cyan ramp and only a failure takes the magenta —
 * which keeps §6's rule that the error colour is never decorative.
 */
const REPO_STATUS_STYLE: Record<RepoStatus, { color: string; label: string; live: boolean }> = {
  pending: { color: 'var(--color-neutral-500)', label: 'Pending', live: false },
  fetching: { color: 'var(--color-accent-400)', label: 'Fetching', live: true },
  parsing: { color: 'var(--color-accent)', label: 'Parsing', live: true },
  done: { color: 'var(--color-accent-700)', label: 'Synced', live: false },
  error: { color: 'var(--color-accent-2)', label: 'Error', live: false },
};

export function repoStatusLabel(status: RepoStatus): string {
  return REPO_STATUS_STYLE[status].label;
}

export function RepoStatusDot({ status }: { status: RepoStatus }) {
  const style = REPO_STATUS_STYLE[status];
  return (
    <span
      aria-hidden
      className={`inline-block h-[7px] w-[7px] flex-none rounded-full ${style.live ? 'cg-pulse' : ''}`}
      style={{ background: style.color }}
    />
  );
}

export function RepoStatusBadge({ status }: { status: RepoStatus }) {
  const style = REPO_STATUS_STYLE[status];
  return (
    <span className="inline-flex items-center gap-[6px] text-[10.5px] tracking-[0.1em] uppercase">
      <RepoStatusDot status={status} />
      <span style={{ color: style.color }}>{style.label}</span>
    </span>
  );
}

const CONNECTION_STYLE: Record<ConnectionState, { color: string; label: string; live: boolean }> = {
  connecting: { color: 'var(--color-accent-400)', label: 'Connecting', live: true },
  open: { color: 'var(--color-accent-700)', label: 'Live', live: false },
  reconnecting: { color: 'var(--color-accent-2)', label: 'Reconnecting', live: true },
  closed: { color: 'var(--color-neutral-500)', label: 'Offline', live: false },
};

/** The top-bar connection dot (§4.1). */
export function ConnectionDot({ state }: { state: ConnectionState }) {
  const style = CONNECTION_STYLE[state];
  return (
    <span
      className="inline-flex items-center gap-[6px]"
      title={`Event stream: ${style.label.toLowerCase()}`}
    >
      <span
        aria-hidden
        className={`inline-block h-[7px] w-[7px] rounded-full ${style.live ? 'cg-pulse' : ''}`}
        style={{ background: style.color }}
      />
      <span style={{ color: style.color }}>{style.label}</span>
    </span>
  );
}

/**
 * The four-stage progress rail from the design's loading screen, driven by
 * the repository's real status rather than a timer. Nothing here animates a
 * completion the backend has not reported.
 */
const STAGE_INDEX: Record<RepoStatus, number> = {
  pending: 0,
  fetching: 1,
  parsing: 2,
  done: 4,
  error: 4,
};

export function SyncRail({ status }: { status: RepoStatus }) {
  const filled = STAGE_INDEX[status];
  const color = status === 'error' ? 'var(--color-accent-2)' : REPO_STATUS_STYLE[status].color;
  return (
    <div className="flex gap-[3px]" aria-hidden>
      {[0, 1, 2, 3].map((cell) => (
        <span
          key={cell}
          className={`h-[6px] flex-1 ${cell === filled - 1 && status !== 'done' && status !== 'error' ? 'cg-pulse' : ''}`}
          style={{ background: cell < filled ? color : 'var(--color-neutral-300)' }}
        />
      ))}
    </div>
  );
}
