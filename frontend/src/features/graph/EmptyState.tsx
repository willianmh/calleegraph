import { Link } from 'react-router-dom';

/**
 * First run (§4.4). The design's front-page treatment: a kicker, one very
 * large flush-left serif line, a measured paragraph, and the actions — no
 * boxes, no sample graph. There is nothing to draw and the page says so.
 */
export function EmptyState({ patSet }: { patSet: boolean }) {
  return (
    <div className="place-content-center-start grid max-w-[640px] px-[26px] pb-[60px]">
      <div className="text-accent-700 mb-[14px] text-[11px] tracking-[0.12em] uppercase">
        No. 1 — first run
      </div>
      <h1 className="font-heading m-0 mb-[16px] text-[54px] leading-[1.02] tracking-[-0.02em] text-balance">
        Nothing to draw yet.
      </h1>
      <p className="m-0 mb-[30px] max-w-[42ch] text-[17px] leading-[1.55] text-neutral-800">
        Point Calleegraph at a repository and it will parse every workflow, follow each{' '}
        <span className="cg-mono text-[15px]">uses:</span> call, and lay the whole system out as one
        map. Cross-repo calls are traced automatically once both repositories are tracked.
      </p>
      <div className="flex items-center gap-[10px]">
        <Link to="/repositories" className="btn btn-primary text-[14.5px]">
          Add a repository
        </Link>
        {!patSet && (
          <Link to="/settings" className="btn btn-ghost text-[13px]">
            Add a GitHub token first
          </Link>
        )}
      </div>
      {!patSet && (
        <p className="m-0 mt-[24px] max-w-[46ch] text-[13px] leading-[1.5] text-neutral-700">
          Public repositories work without a token, but at much lower GitHub rate limits. A token
          with <span className="cg-mono">contents:read</span> is required for private ones.
        </p>
      )}
    </div>
  );
}
