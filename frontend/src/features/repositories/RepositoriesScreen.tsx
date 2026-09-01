import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import {
  useAddRepository,
  useGraph,
  useRefreshRepository,
  useRemoveRepository,
  useRepositories,
  useSettings,
} from '@/api/queries';
import type { Repository } from '@/api/types';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { RepoStatusBadge, SyncRail } from '@/components/StatusDot';
import { Notice, SectionLabel } from '@/components/ui';

const FULL_NAME_PATTERN = /^[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/;

export function RepositoriesScreen() {
  const repositories = useRepositories();
  const settings = useSettings();
  const graph = useGraph();
  const add = useAddRepository();
  const remove = useRemoveRepository();
  const refresh = useRefreshRepository();

  const [fullName, setFullName] = useState('');
  const [pendingRemoval, setPendingRemoval] = useState<Repository | null>(null);

  const rows = useMemo(
    () => [...(repositories.data ?? [])].sort((a, b) => a.full_name.localeCompare(b.full_name)),
    [repositories.data],
  );

  const workflowCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const node of graph.data?.nodes ?? []) {
      counts.set(node.repository_full_name, (counts.get(node.repository_full_name) ?? 0) + 1);
    }
    return counts;
  }, [graph.data]);

  const trimmed = fullName.trim();
  const valid = FULL_NAME_PATTERN.test(trimmed);
  const duplicate = rows.some((repo) => repo.full_name.toLowerCase() === trimmed.toLowerCase());

  /** How many edges would be orphaned by removing this repository. */
  const dependentEdgeCount = useMemo(() => {
    if (!pendingRemoval || !graph.data) return 0;
    const ids = new Set(
      graph.data.nodes
        .filter((node) => node.repository_full_name === pendingRemoval.full_name)
        .map((node) => node.id),
    );
    return graph.data.edges.filter(
      (edge) =>
        edge.target_node_id !== null &&
        ids.has(edge.target_node_id) &&
        !ids.has(edge.source_node_id),
    ).length;
  }, [pendingRemoval, graph.data]);

  return (
    <div className="h-full overflow-y-auto px-[26px] pt-[44px] pb-[60px]">
      <div className="grid max-w-[1080px] grid-cols-[minmax(0,620px)_minmax(0,320px)] gap-[70px] max-[980px]:grid-cols-1 max-[980px]:gap-[40px]">
        <div>
          <h1 className="font-heading m-0 mb-[12px] text-[42px] leading-[1.06] tracking-[-0.015em]">
            Choose the repositories to map
          </h1>
          <p className="m-0 mb-[30px] max-w-[46ch] text-[16px] leading-[1.5] text-neutral-800">
            Calleegraph reads every file under{' '}
            <span className="cg-mono text-[14px]">.github/workflows</span> and follows each{' '}
            <span className="cg-mono text-[14px]">uses:</span> call it finds. Add as many as you
            like — cross-repo calls resolve automatically once both ends are tracked.
          </p>

          <form
            className="flex max-w-[520px] items-start gap-[10px]"
            onSubmit={(event) => {
              event.preventDefault();
              if (!valid || duplicate) return;
              add.mutate(trimmed, {
                onSuccess: () => {
                  setFullName('');
                },
              });
            }}
          >
            <div className="flex-1">
              <label htmlFor="repo-full-name" className="sr-only">
                Repository, as owner/name
              </label>
              <input
                id="repo-full-name"
                className="input cg-mono px-[11px] py-[9px] text-[13px]"
                placeholder="owner/name"
                value={fullName}
                autoComplete="off"
                spellCheck={false}
                aria-invalid={trimmed.length > 0 && (!valid || duplicate)}
                onChange={(event) => {
                  setFullName(event.target.value);
                }}
              />
              {trimmed.length > 0 && !valid && (
                <p className="text-accent-2-700 m-0 mt-[5px] text-[12px]">
                  Enter the repository as <span className="cg-mono">owner/name</span>.
                </p>
              )}
              {duplicate && (
                <p className="text-accent-2-700 m-0 mt-[5px] text-[12px]">
                  That repository is already tracked.
                </p>
              )}
            </div>
            <button
              type="submit"
              className="btn btn-primary text-[14px]"
              disabled={!valid || duplicate || add.isPending}
            >
              {add.isPending ? 'Adding…' : 'Add repository'}
            </button>
          </form>

          {add.isError && (
            <div className="mt-[14px] max-w-[520px]">
              <Notice tone="problem">{add.error.message}</Notice>
            </div>
          )}

          <div className="mt-[40px]">
            <SectionLabel>Tracked</SectionLabel>
            <div className="flex flex-col gap-[26px]">
              {rows.map((repo) => (
                <RepositoryRow
                  key={repo.id}
                  repository={repo}
                  workflowCount={workflowCounts.get(repo.full_name) ?? 0}
                  onRefresh={() => {
                    refresh.mutate(repo.id);
                  }}
                  refreshing={refresh.isPending && refresh.variables === repo.id}
                  onRemove={() => {
                    setPendingRemoval(repo);
                  }}
                />
              ))}
              {rows.length === 0 && !repositories.isPending && (
                <p className="m-0 max-w-[46ch] text-[14px] text-neutral-700 italic">
                  Nothing tracked yet. Add the repository whose workflows you want to map — then add
                  the repositories it calls into, so those edges resolve.
                </p>
              )}
              {repositories.isPending && (
                <p className="m-0 text-[14px] text-neutral-600 italic">Loading…</p>
              )}
            </div>
          </div>
        </div>

        <div className="pt-[96px] max-[980px]:pt-0">
          <SectionLabel>GitHub access</SectionLabel>
          <p className="m-0 mb-[18px] text-[13px] leading-[1.5] text-neutral-700">
            {settings.data?.pat_set
              ? `A personal access token is stored${
                  settings.data.github_actor_login
                    ? ` and authenticates as ${settings.data.github_actor_login}`
                    : ''
                }.`
              : 'No token stored. Public repositories still work, at much lower GitHub rate limits.'}
          </p>
          <Link to="/settings" className="btn btn-secondary text-[13px]">
            {settings.data?.pat_set ? 'Manage token' : 'Add a token'}
          </Link>

          <div className="mt-[40px]">
            <SectionLabel>How syncing works</SectionLabel>
            <p className="m-0 text-[13px] leading-[1.5] text-neutral-700">
              Adding a repository returns immediately; fetching and parsing run in the background
              and the rows above update themselves over the live event stream. There is nothing to
              refresh by hand.
            </p>
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={pendingRemoval !== null}
        title={`Remove ${pendingRemoval?.full_name ?? ''}?`}
        confirmLabel="Remove"
        body={
          <>
            <p className="m-0 mb-[10px]">
              Its workflows disappear from the graph.{' '}
              {dependentEdgeCount > 0 ? (
                <>
                  {dependentEdgeCount} call{dependentEdgeCount === 1 ? '' : 's'} from other
                  repositories point at it, and{' '}
                  {dependentEdgeCount === 1 ? 'that edge flips' : 'those edges flip'} to the{' '}
                  <em>unresolved</em> treatment — no data for the target, rather than an error.
                </>
              ) : (
                'No other tracked repository calls into it.'
              )}
            </p>
            <p className="m-0">You can add it back at any time; nothing is deleted on GitHub.</p>
          </>
        }
        onCancel={() => {
          setPendingRemoval(null);
        }}
        onConfirm={() => {
          if (pendingRemoval) remove.mutate(pendingRemoval.id);
          setPendingRemoval(null);
        }}
      />
    </div>
  );
}

function RepositoryRow({
  repository,
  workflowCount,
  onRefresh,
  refreshing,
  onRemove,
}: {
  repository: Repository;
  workflowCount: number;
  onRefresh: () => void;
  refreshing: boolean;
  onRemove: () => void;
}) {
  const syncedAt = repository.last_synced_at
    ? new Date(repository.last_synced_at).toLocaleString()
    : null;

  return (
    <div className="grid grid-cols-[1fr_auto] items-baseline gap-x-[18px] gap-y-[8px]">
      <span className="cg-mono text-[14px]">{repository.full_name}</span>
      <RepoStatusBadge status={repository.status} />

      <div className="col-span-2">
        <SyncRail status={repository.status} />
      </div>

      <span className="col-span-2 text-[11.5px] text-neutral-600">
        {repository.default_branch}
        {repository.last_synced_commit_sha
          ? ` · ${repository.last_synced_commit_sha.slice(0, 7)}`
          : ''}
        {syncedAt ? ` · synced ${syncedAt}` : ''}
        {repository.status === 'done'
          ? ` · ${workflowCount} ${workflowCount === 1 ? 'workflow' : 'workflows'}`
          : ''}
      </span>

      {repository.error && (
        <div className="col-span-2">
          <Notice tone="problem">{repository.error}</Notice>
        </div>
      )}

      <div className="col-span-2 flex gap-[8px]">
        <button
          type="button"
          className="btn btn-secondary text-[12.5px]"
          onClick={onRefresh}
          disabled={refreshing}
        >
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </button>
        <button type="button" className="btn btn-ghost text-[12.5px]" onClick={onRemove}>
          Remove
        </button>
      </div>
    </div>
  );
}
