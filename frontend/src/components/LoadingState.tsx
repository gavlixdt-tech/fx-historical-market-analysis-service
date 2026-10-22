interface LoadingStateProps {
  label?: string;
}

/** Rendered while a backend request is in flight. */
export function LoadingState({ label = "Loading…" }: LoadingStateProps) {
  return (
    <div className="loading-state" role="status" aria-live="polite">
      <span className="loading-state__spinner" aria-hidden="true" />
      <span className="loading-state__label">{label}</span>
    </div>
  );
}
