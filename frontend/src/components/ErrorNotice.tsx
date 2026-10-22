interface ErrorNoticeProps {
  title: string;
  message: string;
  requestId?: string | null;
  code?: string | null;
  /** Distinct identifier so multiple notices can coexist on one page. */
  testId?: string;
}

/**
 * Renders a safe error message.
 *
 * Only the message and the correlation identifier are shown. No stack traces,
 * internal hostnames, or credentials are ever rendered.
 */
export function ErrorNotice({
  title,
  message,
  requestId,
  code,
  testId = "error-notice",
}: ErrorNoticeProps) {
  return (
    <div className="error-notice" role="alert" data-testid={testId}>
      <p className="error-notice__title">{title}</p>
      <p className="error-notice__message">{message}</p>
      {(requestId || code) && (
        <dl className="error-notice__meta">
          {code ? (
            <div>
              <dt>Error code</dt>
              <dd>{code}</dd>
            </div>
          ) : null}
          {requestId ? (
            <div>
              <dt>Request ID</dt>
              <dd data-testid={`${testId}-request-id`}>{requestId}</dd>
            </div>
          ) : null}
        </dl>
      )}
    </div>
  );
}
