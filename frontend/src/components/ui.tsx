import type { ReactNode } from 'react';

/**
 * The small caps rail label the design uses to open every block — 10.5px,
 * 0.1em tracking, uppercase, quiet ink. Sections are separated by whitespace
 * alone; this label is the only thing that opens one.
 */
export function SectionLabel({ children, tone }: { children: ReactNode; tone?: 'accent-2' }) {
  return (
    <div
      className="mb-[10px] text-[10.5px] tracking-[0.1em] uppercase"
      style={{
        color: tone === 'accent-2' ? 'var(--color-accent-2-700)' : 'var(--color-neutral-600)',
      }}
    >
      {children}
    </div>
  );
}

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
}

/** The design system's `.seg` / `.seg-opt` control, on buttons. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: readonly SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div className="seg w-full" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className="seg-opt flex-1 text-[11.5px]"
          aria-pressed={value === option.value}
          onClick={() => {
            onChange(option.value);
          }}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** A labelled text input. Labels are always real `<label for>` pairs. */
export function Field({
  id,
  label,
  hint,
  children,
}: {
  id: string;
  label: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="field">
      <label htmlFor={id} className="mb-[5px] block text-[12px] text-neutral-700">
        {label}
      </label>
      {children}
      {hint ? <div className="mt-[5px] text-[12px] text-neutral-700">{hint}</div> : null}
    </div>
  );
}

/**
 * An inline message. Only two tones exist, because Broadsheet has only two
 * inks — and §6 reserves the magenta for genuine problems.
 */
export function Notice({ tone, children }: { tone: 'info' | 'problem'; children: ReactNode }) {
  return (
    <p
      className="m-0 border-l-2 py-[5px] pl-[10px] text-[13px] leading-[1.5]"
      style={{
        borderColor: tone === 'problem' ? 'var(--color-accent-2)' : 'var(--color-accent)',
        color: tone === 'problem' ? 'var(--color-accent-2-800)' : 'var(--color-neutral-800)',
      }}
      role={tone === 'problem' ? 'alert' : undefined}
    >
      {children}
    </p>
  );
}
