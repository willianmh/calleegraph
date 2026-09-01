import { Handle, Position, type NodeProps } from '@xyflow/react';
import { Link } from 'react-router-dom';

import type { EdgeStatus, JobNode } from '@/api/types';
import type { CgNode, GroupNodeData, UnresolvedNodeData, WorkflowNodeData } from './flow';
import { EXPANDED_MAX_HEIGHT } from './flow';
import { nodeEmphasis, useGraphInteraction, type Emphasis } from './interaction';
import type { CallWiring } from './model';

/**
 * Card chrome, straight from the focus file: paper fill on the newsprint
 * canvas, a hairline border that changes role with emphasis, and the two
 * elevation steps (`--shadow-sm`, `--shadow-md` when open).
 *
 * The border is the only rule this design permits — a card is a discrete
 * item, which is exactly what Broadsheet reserves boxes for.
 */
function cardChrome(
  emphasis: Emphasis,
  status: EdgeStatus | undefined,
  expanded: boolean,
  nodeDimOpacity: number,
) {
  let borderColor = 'var(--color-neutral-300)';
  let background = 'var(--color-paper)';

  if (status === 'error' || status === 'warning') borderColor = 'var(--color-accent-2-300)';
  if (emphasis === 'downstream') borderColor = 'var(--color-accent)';
  if (emphasis === 'upstream') borderColor = 'var(--color-accent-400)';
  if (emphasis === 'focus') {
    borderColor = 'var(--color-accent-700)';
    background = 'var(--color-accent-100)';
  }
  if (expanded) {
    borderColor = 'var(--color-accent-700)';
    background = 'var(--color-paper)';
  }

  return {
    background,
    borderColor,
    boxShadow: expanded ? 'var(--shadow-md)' : 'var(--shadow-sm)',
    opacity: emphasis === 'dim' ? nodeDimOpacity : 1,
  };
}

function Ports() {
  return (
    <>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </>
  );
}

/**
 * `pointer-events-auto` is load-bearing, not decorative: React Flow sets
 * `pointer-events: none` inline on `.react-flow__node` whenever a node has
 * no built-in interactivity (`nodesDraggable`/`nodesConnectable`/
 * `elementsSelectable` are all `false` on this canvas, by design — panning
 * should work over a node, not just empty space), and that `none` inherits
 * straight down to this card unless it's explicitly overridden here. Without
 * it, every onClick/onMouseEnter below is correctly wired and never fires.
 */
const CARD_CLASS =
  'pointer-events-auto h-full w-full overflow-hidden rounded-md border transition-[opacity,background-color,border-color,box-shadow] duration-200';

// ---------------------------------------------------------------------------

export function WorkflowCard({ id, data }: NodeProps<CgNode>) {
  const interaction = useGraphInteraction();
  const {
    node,
    wiring,
    status,
    expanded,
    compact: dataCompact,
    calleeCount,
    callerCount,
  } = data as WorkflowNodeData;
  const emphasis = nodeEmphasis(interaction, id);
  const compact = dataCompact && !expanded;

  return (
    <div
      className={CARD_CLASS}
      style={cardChrome(emphasis, status, expanded, interaction.nodeDimOpacity)}
      onMouseEnter={() => {
        interaction.setHoveredNode(id);
      }}
      onMouseLeave={() => {
        interaction.setHoveredNode(null);
      }}
      onClick={(event) => {
        event.stopPropagation();
        interaction.toggleExpanded(id);
      }}
      role="button"
      tabIndex={0}
      aria-expanded={expanded}
      aria-label={`${node.name} — ${node.repository_full_name}/${node.path}`}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          interaction.toggleExpanded(id);
        }
      }}
      onFocus={() => {
        interaction.setHoveredNode(id);
      }}
      onBlur={() => {
        interaction.setHoveredNode(null);
      }}
    >
      <Ports />
      <div
        className="flex h-full flex-col px-[12px] py-[9px]"
        style={expanded ? { maxHeight: EXPANDED_MAX_HEIGHT, overflowY: 'auto' } : undefined}
      >
        <div className="flex items-baseline gap-[7px]">
          <span
            aria-hidden
            className="mb-px h-[6px] w-[6px] flex-none rounded-full"
            style={{
              background:
                status === 'error' || status === 'warning'
                  ? 'var(--color-accent-2)'
                  : 'var(--color-neutral-400)',
            }}
          />
          {!compact && (
            <span className="font-heading truncate text-[13.5px] leading-[1.2] font-semibold">
              {node.name}
            </span>
          )}
          {node.kind === 'reusable' && !compact && (
            <span className="text-accent-700 ml-auto text-[9px] tracking-[0.1em] uppercase">
              reusable
            </span>
          )}
        </div>
        <div
          className={`cg-mono ml-[13px] truncate ${
            compact ? 'text-[12.5px] text-neutral-900' : 'text-[10.5px] text-neutral-600'
          } mt-[3px]`}
          title={node.path}
        >
          {node.path}
        </div>

        {expanded && (
          <div className="mt-[11px] ml-[13px] flex flex-col gap-[9px]">
            <div className="text-[9.5px] tracking-[0.06em] text-neutral-600 uppercase">
              {callerCount} in · {calleeCount} out · {node.jobs.length}{' '}
              {node.jobs.length === 1 ? 'job' : 'jobs'}
            </div>
            {node.jobs.map((job) => (
              <JobBlock
                key={job.id}
                job={job}
                wiring={wiring.find((entry) => entry.job.id === job.id)}
              />
            ))}
            {node.jobs.length === 0 && (
              <div className="text-[10px] text-neutral-600 italic">No jobs parsed.</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function JobBlock({ job, wiring }: { job: JobNode; wiring: CallWiring | undefined }) {
  return (
    <div>
      <div className="text-[9.5px] tracking-[0.06em] text-neutral-600 uppercase">
        job <span className="cg-mono normal-case">{job.job_key}</span>
        {job.name ? ` · ${job.name}` : ''}
      </div>
      {job.needs.length > 0 && (
        <div className="cg-mono text-[10.5px] leading-[1.35] text-neutral-800">
          needs: {job.needs.join(', ')}
        </div>
      )}
      {job.condition && (
        <div className="cg-mono truncate text-[10.5px] leading-[1.35] text-neutral-800">
          if: {job.condition}
        </div>
      )}
      {wiring && <CallBlock wiring={wiring} />}
    </div>
  );
}

function CallBlock({ wiring }: { wiring: CallWiring }) {
  const { call, target, bindings, missingRequired } = wiring;
  return (
    <div className="mt-[3px]">
      <div className="cg-mono truncate text-[10px] text-neutral-700" title={call.target_ref}>
        → {target ? `${target.repository_full_name}/${target.path}` : call.target_ref}
      </div>
      {bindings.map((binding) => (
        <div key={binding.name} className="cg-mono truncate text-[10.5px] leading-[1.35]">
          <span
            style={{
              color:
                binding.state === 'unknown'
                  ? 'var(--color-accent-2-700)'
                  : 'var(--color-neutral-900)',
            }}
          >
            {binding.name}
          </span>
          <span className="text-neutral-700">: {binding.value}</span>
          {binding.state === 'unknown' && (
            <span className="text-accent-2-700"> · not declared</span>
          )}
        </div>
      ))}
      {missingRequired.map((input) => (
        <div
          key={input.name}
          className="cg-mono text-accent-2-700 truncate text-[10.5px] leading-[1.35]"
        >
          {input.name}: <span className="italic">required, not passed</span>
        </div>
      ))}
      {bindings.length === 0 && missingRequired.length === 0 && (
        <div className="text-[10px] text-neutral-600 italic">no inputs</div>
      )}
      {call.secrets_mode !== 'none' && (
        <div className="cg-mono text-[10px] text-neutral-700">
          secrets: {call.secrets_mode === 'inherit' ? 'inherit' : (call.secrets ?? []).join(', ')}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

/**
 * A call whose target the backend could not resolve. It is drawn as an
 * unprinted plate — an open, dashed outline on the paper — deliberately
 * *not* in the error ink: this is missing data, not a fault.
 */
export function UnresolvedCard({ id, data }: NodeProps<CgNode>) {
  const interaction = useGraphInteraction();
  const { ref, repositoryTracked, callerCount } = data as UnresolvedNodeData;
  const emphasis = nodeEmphasis(interaction, id);

  return (
    <div
      className={`${CARD_CLASS} border-dashed`}
      style={{
        background: 'var(--color-neutral-100)',
        borderColor: emphasis === 'focus' ? 'var(--color-accent-700)' : 'var(--color-neutral-500)',
        boxShadow: 'none',
        opacity: emphasis === 'dim' ? interaction.nodeDimOpacity : 1,
      }}
      onMouseEnter={() => {
        interaction.setHoveredNode(id);
      }}
      onMouseLeave={() => {
        interaction.setHoveredNode(null);
      }}
      aria-label={`Unresolved target ${ref.raw}`}
    >
      <Ports />
      <div className="flex h-full flex-col justify-center px-[12px] py-[8px]">
        <div className="text-[9.5px] tracking-[0.1em] text-neutral-700 uppercase">
          No data yet · {callerCount} {callerCount === 1 ? 'caller' : 'callers'}
        </div>
        <div className="cg-mono truncate text-[11.5px] text-neutral-900" title={ref.raw}>
          {ref.path ?? ref.raw}
        </div>
        {ref.repositoryFullName && !repositoryTracked && (
          <Link
            to="/repositories"
            className="btn btn-ghost mt-[2px] self-start !px-0 text-[10.5px]"
            onClick={(event) => {
              event.stopPropagation();
            }}
          >
            Track {ref.repositoryFullName}
          </Link>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------

/**
 * One card per repository — the large-graph density band. Clicking any group
 * card ungroups the whole canvas back to individual nodes (a global toggle,
 * not a per-repo drill-down — matching both the spec and the reference
 * prototype exactly).
 */
export function GroupCard({ id, data }: NodeProps<CgNode>) {
  const interaction = useGraphInteraction();
  const { repositoryFullName, repository, workflowCount, internalCallCount, status } =
    data as GroupNodeData;
  const emphasis = nodeEmphasis(interaction, id);

  return (
    <div
      className={CARD_CLASS}
      style={cardChrome(emphasis, status, false, interaction.nodeDimOpacity)}
      onMouseEnter={() => {
        interaction.setHoveredNode(id);
      }}
      onMouseLeave={() => {
        interaction.setHoveredNode(null);
      }}
      onClick={(event) => {
        event.stopPropagation();
        interaction.ungroup();
      }}
      role="button"
      tabIndex={0}
      aria-label={`${repositoryFullName} — ${workflowCount} workflows. Ungroup to view individual workflows.`}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          interaction.ungroup();
        }
      }}
    >
      <Ports />
      <div className="flex h-full flex-col justify-center px-[14px] py-[14px]">
        <div className="flex items-baseline gap-[7px]">
          <span
            aria-hidden
            className="mb-px h-[6px] w-[6px] flex-none rounded-full"
            style={{
              background:
                status === 'error' || status === 'warning'
                  ? 'var(--color-accent-2)'
                  : 'var(--color-neutral-400)',
            }}
          />
          <span className="font-heading truncate text-[15px] leading-[1.2] font-semibold">
            {repositoryFullName}
          </span>
          <span className="font-heading text-accent-700 ml-auto text-[20px] leading-none">
            {workflowCount}
          </span>
        </div>
        <div className="cg-mono mt-[3px] ml-[13px] truncate text-[10.5px] text-neutral-600">
          {repository ? repository.default_branch : 'untracked'}
          {internalCallCount > 0 ? ` · ${internalCallCount} internal` : ''}
        </div>
      </div>
    </div>
  );
}
