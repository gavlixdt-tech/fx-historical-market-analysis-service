interface EmptyStateProps {
  title: string;
  message: string;
  tone?: "neutral" | "warn";
}

/** Rendered when a request succeeded but returned nothing to display. */
export function EmptyState({ title, message, tone = "neutral" }: EmptyStateProps) {
  return (
    <div className={`empty-state empty-state--${tone}`} role="status">
      <p className="empty-state__title">{title}</p>
      <p className="empty-state__message">{message}</p>
    </div>
  );
}
