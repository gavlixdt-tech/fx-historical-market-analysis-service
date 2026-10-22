import type { ReactNode } from "react";

export type BadgeTone = "ok" | "warn" | "error" | "neutral" | "info";

interface StatusBadgeProps {
  tone: BadgeTone;
  label: string;
  detail?: ReactNode;
}

/**
 * A small, accessible status pill.
 *
 * The tone is conveyed by text as well as colour so that the dashboard
 * remains usable for colour-blind operators and in monochrome terminals.
 */
export function StatusBadge({ tone, label, detail }: StatusBadgeProps) {
  return (
    <span className={`badge badge--${tone}`} data-testid={`badge-${tone}`}>
      <span className="badge__dot" aria-hidden="true" />
      <span className="badge__label">{label}</span>
      {detail ? <span className="badge__detail">{detail}</span> : null}
    </span>
  );
}
