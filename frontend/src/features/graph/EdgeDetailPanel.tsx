import { Link } from 'react-router-dom';

import type { Edge, EdgeIssue } from '@/api/types';
import { SectionLabel } from '@/components/ui';
import { workflowFileUrl } from '@/lib/github';
import type { CgEdgeData } from './flow';
import { EDGE_VISUALS, issueCodeLabel, parseTargetRef, wiringFor, type GraphIndex } from './model';

export interface EdgeDetailPanelProps {
  /** The contract edges behind the selected line — several when grouped. */
  selection: CgEdgeData;
  index: GraphIndex;
  apiBase: string;
  trackedRepositories: ReadonlySet<string>;
  onClose: () => void;
  onSelectEdge: (id: string) => void;
}

export function EdgeDetailPanel({
  selection,
  index,
  apiBase,
  trackedRepositories,
  onClose,
  onSelectEdge,
}: EdgeDetailPanelProps) {
  const primary = selection.edges[0];
  if (!primary) return null;

  return (
    <aside
      className="flex min-h-0 flex-col gap-[20px] overflow-y-auto px-[24px] py-[20px]"
      style={{ background: 'var(--color-surface)' }}
      aria-label="Call detail"
    >
      <div className="flex items-baseline gap-[10px]">
        <span className="text-[10.5px] tracking-[0.1em] text-neutral-600 uppercase">
          {selection.grouped
            ? `${selection.edges.length} calls between these repositories`
            : kickerFor(primary)}
        </span>
        <button
          type="button"
          className="btn btn-ghost ml-auto px-[6px] py-[2px] text-[11px]"
          onClick={onClose}
        >
          Close
        </button>
      </div>

      {selection.grouped ? (
        <GroupedList edges={selection.edges} index={index} onSelectEdge={onSelectEdge} />
      ) : (
        <SingleEdgeDetail
          edge={primary}
          index={index}
          apiBase={apiBase}
          trackedRepositories={trackedRepositories}
        />
      )}
    </aside>
  );
}

function kickerFor(edge: Edge): string {
  const first = edge.issues[0];
  if (first)
    return `${first.severity === 'error' ? 'Mismatch' : 'Warning'} · ${issueCodeLabel(first.code)}`;
  if (edge.status === 'unresolved') return 'Unresolved target';
  return 'Connection';
}

function GroupedList({
  edges,
  index,
  onSelectEdge,
}: {
  edges: Edge[];
  index: GraphIndex;
  onSelectEdge: (id: string) => void;
}) {
  return (
    <div>
      <p className="m-0 mb-[12px] text-[14px] leading-[1.5]">
        Selecting a specific call below ungroups the graph to show it.
      </p>
      <div className="flex flex-col gap-[3px]">
        {edges.map((edge) => {
          const source = index.nodesById.get(edge.source_node_id);
          const target = edge.target_node_id ? index.nodesById.get(edge.target_node_id) : undefined;
          return (
            <button
              key={edge.id}
              type="button"
              className="cursor-pointer border-0 bg-transparent px-[10px] py-[6px] text-left"
              style={{ borderLeft: `2px solid ${EDGE_VISUALS[edge.status].stroke}` }}
              onClick={() => {
                onSelectEdge(edge.id);
              }}
            >
              <span className="cg-mono block text-[11px]">
                {source?.path ?? edge.source_node_id} → {target?.path ?? edge.target_ref}
              </span>
              <span className="text-[10.5px] text-neutral-700 uppercase">
                {EDGE_VISUALS[edge.status].label}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function SingleEdgeDetail({
  edge,
  index,
  apiBase,
  trackedRepositories,
}: {
  edge: Edge;
  index: GraphIndex;
  apiBase: string;
  trackedRepositories: ReadonlySet<string>;
}) {
  const source = index.nodesById.get(edge.source_node_id);
  const target = edge.target_node_id ? index.nodesById.get(edge.target_node_id) : undefined;
  const wiring = source
    ? wiringFor(source, index).find((entry) => entry.job.id === edge.source_job_id)
    : undefined;
  const parsedRef = parseTargetRef(edge.target_ref);
  const errors = edge.issues.filter((issue) => issue.severity === 'error');
  const warnings = edge.issues.filter((issue) => issue.severity === 'warning');
  const sourceUrl = source
    ? workflowFileUrl(apiBase, source.repository_full_name, 'HEAD', source.path)
    : null;

  return (
    <>
      <div>
        <h2 className="font-heading m-0 mb-[8px] text-[23px] leading-[1.18] text-pretty">
          {source ? source.name : edge.source_node_id}
          <span className="text-neutral-600"> calls </span>
          {target ? target.name : (parsedRef.path ?? edge.target_ref)}
        </h2>
        <div className="cg-mono text-[11px] leading-[1.5] text-neutral-700">
          {edge.source_node_id}
          <br />→ {edge.target_ref}
          {edge.condition ? (
            <>
              <br />
              if: {edge.condition}
            </>
          ) : null}
        </div>
      </div>

      {edge.issues.length === 0 && (
        <p className="m-0 text-[14.5px] leading-[1.5] text-pretty">
          {edge.status === 'unresolved'
            ? 'Calleegraph has no parsed data for the workflow at the other end of this call yet, so its inputs cannot be checked. This is a gap in what has been synced, not a fault in the call.'
            : `This call passes ${Object.keys(wiring?.call.with ?? {}).length} input${
                Object.keys(wiring?.call.with ?? {}).length === 1 ? '' : 's'
              } to a workflow that declares every one of them.`}
        </p>
      )}

      {errors.length > 0 && <IssueList label="Problems" issues={errors} tone="error" />}
      {warnings.length > 0 && <IssueList label="Warnings" issues={warnings} tone="warning" />}

      {edge.status === 'unresolved' && parsedRef.repositoryFullName && (
        <div>
          <SectionLabel>Target repository</SectionLabel>
          <p className="m-0 mb-[10px] text-[14px] leading-[1.5]">
            <span className="cg-mono">{parsedRef.repositoryFullName}</span>{' '}
            {trackedRepositories.has(parsedRef.repositoryFullName)
              ? 'is tracked, but this ref has not resolved to a synced workflow.'
              : 'is not tracked yet. Add it and this call will resolve.'}
          </p>
          <Link to="/repositories" className="btn btn-primary text-[12.5px]">
            {trackedRepositories.has(parsedRef.repositoryFullName)
              ? 'Open Repositories'
              : `Track ${parsedRef.repositoryFullName}`}
          </Link>
        </div>
      )}

      {wiring && (
        <div>
          <SectionLabel>
            Caller — {source?.repository_full_name}/{source?.path}
          </SectionLabel>
          <pre
            className="cg-mono m-0 overflow-x-auto px-[12px] py-[11px] text-[11px] leading-[1.55] whitespace-pre-wrap"
            style={{
              background: 'var(--color-paper)',
              borderLeft: `2px solid ${
                edge.status === 'error' ? 'var(--color-accent-2)' : 'var(--color-neutral-400)'
              }`,
            }}
          >
            {'jobs:\n'}
            {`  ${wiring.job.job_key}:\n`}
            {`    uses: ${wiring.call.target_ref}\n`}
            {wiring.job.condition ? `    if: ${wiring.job.condition}\n` : ''}
            {wiring.bindings.length > 0 ? '    with:\n' : ''}
            {wiring.bindings.map((binding) => (
              <span
                key={binding.name}
                style={
                  binding.state === 'unknown' ? { color: 'var(--color-accent-2-700)' } : undefined
                }
              >
                {`      ${binding.name}: ${binding.value}`}
                {binding.state === 'unknown' ? '   # not declared by the callee' : ''}
                {'\n'}
              </span>
            ))}
            {wiring.call.secrets_mode === 'inherit' ? '    secrets: inherit\n' : ''}
            {wiring.call.secrets_mode === 'explicit'
              ? `    secrets:\n${(wiring.call.secrets ?? [])
                  .map((name) => `      ${name}: …\n`)
                  .join('')}`
              : ''}
          </pre>
        </div>
      )}

      {target && (
        <div>
          <SectionLabel>
            Callee — {target.repository_full_name}/{target.path}
          </SectionLabel>
          <pre
            className="cg-mono m-0 overflow-x-auto px-[12px] py-[11px] text-[11px] leading-[1.55] whitespace-pre-wrap"
            style={{
              background: 'var(--color-paper)',
              borderLeft: '2px solid var(--color-neutral-400)',
            }}
          >
            {'on:\n  workflow_call:\n'}
            {target.declared_inputs.length > 0 ? '    inputs:\n' : '    inputs: {}\n'}
            {target.declared_inputs.map((input) => (
              <span key={input.name}>
                {`      ${input.name}: { required: ${String(input.required)}, type: ${input.type}${
                  input.default !== null ? `, default: ${String(input.default)}` : ''
                } }\n`}
              </span>
            ))}
            {target.declared_secrets.length > 0
              ? `    secrets:\n${target.declared_secrets
                  .map((name) => `      ${name}: {}\n`)
                  .join('')}`
              : ''}
          </pre>
        </div>
      )}

      {sourceUrl && (
        <div className="flex gap-[8px]">
          <a
            className="btn btn-primary text-[12.5px]"
            href={sourceUrl}
            target="_blank"
            rel="noreferrer noopener"
          >
            Open caller in GitHub
          </a>
        </div>
      )}
    </>
  );
}

/**
 * Issue text is printed exactly as the backend sent it. The only thing this
 * component contributes is the code's title case and the layout — never a
 * word of the `message` or `suggestion`.
 */
function IssueList({
  label,
  issues,
  tone,
}: {
  label: string;
  issues: EdgeIssue[];
  tone: 'error' | 'warning';
}) {
  return (
    <div>
      <SectionLabel tone="accent-2">{label}</SectionLabel>
      <div className="flex flex-col gap-[14px]">
        {issues.map((issue, position) => (
          <div
            key={`${issue.code}-${issue.input_name ?? position}`}
            className="border-l-2 pl-[10px]"
            style={{
              borderColor: tone === 'error' ? 'var(--color-accent-2)' : 'var(--color-accent-2-400)',
            }}
          >
            <div className="text-accent-2-700 text-[10.5px] tracking-[0.1em] uppercase">
              {issueCodeLabel(issue.code)}
              {issue.input_name ? (
                <span className="cg-mono normal-case"> · {issue.input_name}</span>
              ) : null}
            </div>
            <p className="m-0 mt-[4px] text-[14px] leading-[1.5]">{issue.message}</p>
            {issue.suggestion && (
              <p className="m-0 mt-[8px] text-[13.5px] leading-[1.5] text-neutral-800">
                <span className="text-[10.5px] tracking-[0.1em] text-neutral-600 uppercase">
                  Suggested fix
                </span>
                <br />
                {issue.suggestion}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
