import { SectionLabel } from '@/components/ui';
import type { EdgeStatus } from '@/api/types';
import {
  CONDITIONAL_DASH,
  CONDITIONAL_STROKE,
  DOWNSTREAM_STROKE,
  EDGE_VISUALS,
  UPSTREAM_HOVER_DASH,
  UPSTREAM_STROKE,
} from './model';

interface Row {
  stroke: string;
  dash: string | undefined;
  width: number;
  ring?: boolean;
  label: string;
  note: string;
}

const STATUS_ORDER: EdgeStatus[] = ['ok', 'warning', 'error', 'unresolved'];

const STATUS_NOTES: Record<EdgeStatus, string> = {
  ok: 'the callee declares every input passed',
  warning: 'valid call, softer problem — e.g. a condition we cannot evaluate',
  error: 'the call is broken; open it for the exact reason',
  unresolved: 'no data for the target yet — not a fault',
};

const HOVER_ROWS: Row[] = [
  {
    stroke: DOWNSTREAM_STROKE,
    dash: undefined,
    width: 2.4,
    label: 'Downstream',
    note: 'what the hovered workflow calls',
  },
  {
    stroke: UPSTREAM_STROKE,
    dash: UPSTREAM_HOVER_DASH,
    width: 2.4,
    label: 'Upstream',
    note: 'what calls it',
  },
];

/** Always-on, not just under hover — a job's `if:` gate has its own treatment. */
const CONDITIONAL_ROW: Row = {
  stroke: CONDITIONAL_STROKE,
  dash: CONDITIONAL_DASH,
  width: 1.3,
  label: 'Conditional (if:)',
  note: 'gated by a job-level if: expression',
};

function LegendLine({ row }: { row: Row }) {
  return (
    <div className="flex items-start gap-[9px]">
      <svg width="30" height="12" className="mt-[3px] flex-none" aria-hidden>
        <line
          x1="0"
          y1="6"
          x2={row.ring ? 22 : 30}
          y2="6"
          stroke={row.stroke}
          strokeWidth={row.width}
          strokeDasharray={row.dash}
        />
        {row.ring && (
          <circle cx="26" cy="6" r="3" fill="none" stroke={row.stroke} strokeWidth="1.6" />
        )}
      </svg>
      <span className="text-[11.5px] leading-[1.35] text-neutral-800">
        {row.label}
        <span className="block text-[10.5px] text-neutral-600">{row.note}</span>
      </span>
    </div>
  );
}

/** Explains the four edge statuses and the hover colour coding (§4.2). */
export function Legend() {
  return (
    <div>
      <SectionLabel>Legend</SectionLabel>
      <div className="flex flex-col gap-[7px]">
        {STATUS_ORDER.map((status) => {
          const visual = EDGE_VISUALS[status];
          return (
            <LegendLine
              key={status}
              row={{
                stroke: visual.stroke,
                dash: visual.dash,
                width: visual.width,
                ring: status === 'unresolved',
                label: visual.label,
                note: STATUS_NOTES[status],
              }}
            />
          );
        })}
        {HOVER_ROWS.map((row) => (
          <LegendLine key={row.label} row={row} />
        ))}
        <LegendLine row={CONDITIONAL_ROW} />
        <div className="text-[10.5px] leading-[1.35] text-neutral-600">
          A conditional call shows its <span className="cg-mono">if:</span> expression on the line
          while it is highlighted.
        </div>
      </div>
    </div>
  );
}
