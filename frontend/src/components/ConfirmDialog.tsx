import { useEffect, useRef, type ReactNode } from 'react';

/**
 * The design system's `.dialog` over its backdrop, at the top elevation.
 * Focus moves into the dialog on open and Escape dismisses it.
 */
export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return undefined;
    confirmRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCancel();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center p-4"
      style={{ background: 'color-mix(in srgb, var(--color-neutral-900) 50%, transparent)' }}
      onClick={onCancel}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="flex w-[min(440px,100%)] flex-col gap-3 rounded-lg p-4"
        style={{ background: 'var(--color-surface)', boxShadow: 'var(--shadow-lg)' }}
        onClick={(event) => {
          event.stopPropagation();
        }}
      >
        <h2 className="font-heading m-0 text-[20px]">{title}</h2>
        <div className="text-[14px] leading-[1.5] opacity-85">{body}</div>
        <div className="mt-2 flex justify-end gap-2">
          <button type="button" className="btn btn-secondary text-[13px]" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            ref={confirmRef}
            className="btn btn-primary text-[13px]"
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
