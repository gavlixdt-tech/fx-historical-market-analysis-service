import { EmptyState } from "@/components/EmptyState";
import { ErrorNotice } from "@/components/ErrorNotice";
import { LoadingState } from "@/components/LoadingState";
import { Panel } from "@/components/Panel";
import type { ApiError } from "@/services/api";
import type { ReadyResponseData } from "@/schemas/api";

interface OperationalDiagnosticsProps {
  readiness: ReadyResponseData | null;
  error: ApiError | null;
  isLoading: boolean;
  lastRefreshedAt: Date | null;
}

/**
 * Operational Diagnostics panel.
 *
 * Surfaces safe diagnostics only: dependency names, their health, the
 * correlation ID of the failing request, and the last refresh time.
 */
export function OperationalDiagnostics({
  readiness,
  error,
  isLoading,
  lastRefreshedAt,
}: OperationalDiagnosticsProps) {
  return (
    <Panel
      title="Operational Diagnostics"
      subtitle="Safe diagnostics for operators. No credentials or stack traces."
    >
      {isLoading && !readiness ? (
        <LoadingState label="Running diagnostics…" />
      ) : null}

      {error ? (
        <ErrorNotice
          title="Request failed"
          message={error.message}
          code={error.code}
          requestId={error.requestId}
          testId="diagnostics-error-notice"
        />
      ) : null}

      {!isLoading && !readiness && !error ? (
        <EmptyState
          title="No diagnostics available"
          message="The backend did not return a readiness payload."
        />
      ) : null}

      {readiness ? (
        <div className="diagnostics">
          <h3 className="section-subtitle">Dependencies</h3>
          {readiness.dependencies.length === 0 ? (
            <EmptyState
              title="No dependencies reported"
              message="The service reported no dependency health information."
            />
          ) : (
            <ul className="dependency-list">
              {readiness.dependencies.map((dependency) => (
                <li
                  key={dependency.name}
                  className="dependency-list__item"
                  data-testid={`dependency-${dependency.name}`}
                >
                  <span className="dependency-list__name">
                    {dependency.name}
                  </span>
                  <span
                    className={
                      dependency.healthy
                        ? "dependency-list__state dependency-list__state--ok"
                        : "dependency-list__state dependency-list__state--error"
                    }
                  >
                    {dependency.healthy ? "healthy" : "unhealthy"}
                  </span>
                  {dependency.detail ? (
                    <span className="dependency-list__detail">
                      {dependency.detail}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          )}

          <dl className="data-list">
            <div className="data-row">
              <dt className="data-row__label">Last refresh</dt>
              <dd className="data-row__value" data-testid="diagnostics-last-refresh">
                {lastRefreshedAt
                  ? lastRefreshedAt.toLocaleTimeString()
                  : "Not yet refreshed"}
              </dd>
            </div>
            <div className="data-row">
              <dt className="data-row__label">Readiness check</dt>
              <dd className="data-row__value">{readiness.check}</dd>
            </div>
          </dl>
        </div>
      ) : null}
    </Panel>
  );
}
