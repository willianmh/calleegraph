import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from '@xyflow/react';

import type { CgEdge } from './flow';
import { edgeEmphasis, useGraphInteraction } from './interaction';
import {
  DIM_OPACITY,
  DOWNSTREAM_MARKER,
  DOWNSTREAM_STROKE,
  EDGE_VISUALS,
  UPSTREAM_MARKER,
  UPSTREAM_STROKE,
} from './model';

/**
 * Arrowheads and the unresolved terminal, defined once and referenced by
 * `url(#…)`. Rendered inside the flow's own SVG surface so the references
 * resolve in every browser.
 */
export function EdgeMarkers() {
  return (
    <svg className="pointer-events-none absolute h-0 w-0" aria-hidden focusable="false">
      <defs>
        {[
          ['cg-arrow-dim', 'var(--color-neutral-400)', 6],
          ['cg-arrow-warn', 'var(--color-accent-2-500)', 6.6],
          ['cg-arrow-error', 'var(--color-accent-2)', 7],
          ['cg-arrow-downstream', 'var(--color-accent)', 6.6],
          ['cg-arrow-upstream', 'var(--color-accent-400)', 6.6],
        ].map(([id, fill, size]) => (
          <marker
            key={id as string}
            id={id as string}
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth={size as number}
            markerHeight={size as number}
            orient="auto-start-reverse"
          >
            <path d="M 0 1 L 9 5 L 0 9 z" fill={fill as string} />
          </marker>
        ))}
        {/* Unresolved: an open ring, not an arrowhead — the line stops at a
            target we have no data for rather than landing on one. */}
        <marker
          id="cg-ring-open"
          viewBox="0 0 10 10"
          refX="5"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <circle
            cx="5"
            cy="5"
            r="3"
            fill="none"
            stroke="var(--color-neutral-500)"
            strokeWidth="1.6"
          />
        </marker>
      </defs>
    </svg>
  );
}

export function CallEdge({
  id,
  source,
  target,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
}: EdgeProps<CgEdge>) {
  const interaction = useGraphInteraction();
  const edgeData = data;
  const status = edgeData?.status ?? 'ok';
  const visual = EDGE_VISUALS[status];
  const { emphasis, direction } = edgeEmphasis(interaction, { id, source, target });

  const [path, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    curvature: 0.35,
  });

  // Status owns colour, weight and terminal. Hover overlays the caller/callee
  // direction on top of it — except for `error`, which keeps its own ink so a
  // broken call never stops looking broken while you inspect it.
  let stroke = visual.stroke;
  let marker = visual.marker;
  let width = visual.width;

  if (direction && status !== 'error') {
    stroke = direction === 'downstream' ? DOWNSTREAM_STROKE : UPSTREAM_STROKE;
    marker = direction === 'downstream' ? DOWNSTREAM_MARKER : UPSTREAM_MARKER;
    width = Math.max(width, 2.2);
  } else if (direction) {
    width = 2.8;
  }
  if (emphasis === 'focus') {
    width = Math.max(width, status === 'error' ? 3 : 2.8);
    if (status === 'ok') {
      stroke = 'var(--color-accent-700)';
      marker = DOWNSTREAM_MARKER;
    }
  }

  const opacity = emphasis === 'dim' ? DIM_OPACITY : 1;
  const condition = edgeData?.condition ?? null;
  const showLabel = condition !== null && (emphasis === 'focus' || direction !== null);

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={marker}
        style={{
          stroke,
          strokeWidth: width,
          strokeDasharray: visual.dash,
          opacity,
        }}
      />
      {/* A fat transparent hit area: a 1.3px line is not a click target. */}
      <path
        d={path}
        fill="none"
        stroke="transparent"
        strokeWidth={18}
        className="cursor-pointer"
        onMouseEnter={() => {
          interaction.setHoveredEdge(id);
        }}
        onMouseLeave={() => {
          interaction.setHoveredEdge(null);
        }}
        onClick={(event) => {
          event.stopPropagation();
          interaction.selectEdge(id);
        }}
      />
      {showLabel && (
        <EdgeLabelRenderer>
          <div
            className="cg-mono pointer-events-none absolute max-w-[220px] truncate rounded-sm px-[5px] py-px text-[10px]"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              background: 'var(--color-bg)',
              color: 'var(--color-neutral-700)',
              border: '1px solid var(--color-neutral-300)',
            }}
          >
            if: {condition}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
