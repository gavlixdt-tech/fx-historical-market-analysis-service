import { DataRow } from "@/components/DataRow";
import { EmptyState } from "@/components/EmptyState";
import { ErrorNotice } from "@/components/ErrorNotice";
import { LoadingState } from "@/components/LoadingState";
import { Panel } from "@/components/Panel";
import { StatusBadge, type BadgeTone } from "@/components/StatusBadge";
import type { ApiError } from "@/services/api";
import type {
  ReadyResponseData,
  StatusResponseData,
  VersionResponseData,
} from "@/schemas/api";

interface ServiceOverviewProps {
  status: StatusResponseData | null;
  readiness: ReadyResponseData | null;
  version: VersionResponseData | null;
  isLoading: boolean;
  error: ApiError | null;
  lastRefreshedAt: Date | null;
}

function operationalTone(state: string): BadgeTone {
  if (state === "operational") return "ok";
  if (state === "degraded") return "warn";
  return "error";
}

function readinessTone(status: string): BadgeTone {
  if (status === "healthy") return "ok";
  if (status === "degraded") return "warn";
  return "error";
}

/**
 * Service Overview panel.
 *
 * Reports only what the backend actually returned. Nothing about the
 * connection state is hard-coded or optimistic.
 */
export function ServiceOverview({
  status,
  readiness,
  version,
  isLoading,
  error,
  lastRefreshedAt,
}: ServiceOverviewProps) {
  return (
    <Panel
      title="Service Overview"
      subtitle="Live operational state reported by this service's own backend."
      actions={
        lastRefreshedAt ? (
          <span className="last-refresh" data-testid="last-refresh">
            Last refreshed {lastRefreshedAt.toLocaleTimeString()}
          </span>
        ) : null
      }
    >
      {isLoading && !status ? (
        <LoadingState label="Loading service status…" />
      ) : null}

      {error ? (
        <ErrorNotice
          title="Backend unreachable"
          message={error.message}
          code={error.code}
          requestId={error.requestId}
          testId="overview-error-notice"
        />
      ) : null}

      {!isLoading && !status && !error ? (
        <EmptyState
          title="No status available"
          message="The backend did not return a status payload."
        />
      ) : null}

      {status ? (
        <div className="overview-grid">
          <div className="overview-card">
            <p className="overview-card__label">Service</p>
            <p className="overview-card__value" data-testid="service-name">
              {status.service_id}
            </p>
            <StatusBadge
              tone={operationalTone(status.operational_state)}
              label={status.operational_state}
            />
          </div>

          <div className="overview-card">
            <p className="overview-card__label">Version</p>
            <p className="overview-card__value" data-testid="service-version">
              {version?.application_version ?? status.application_version}
            </p>
            <p className="overview-card__hint">API {status.api_version}</p>
          </div>

          <div className="overview-card">
            <p className="overview-card__label">Readiness</p>
            <p className="overview-card__value">
              {readiness?.status ?? "unknown"}
            </p>
            {readiness ? (
              <StatusBadge
                tone={readinessTone(readiness.status)}
                label={readiness.status}
              />
            ) : (
              <StatusBadge tone="neutral" label="not yet checked" />
            )}
          </div>

          <div className="overview-card">
            <p className="overview-card__label">Environment</p>
            <p className="overview-card__value">{status.environment}</p>
            <p className="overview-card__hint">{status.service_mode}</p>
          </div>

          <div className="overview-card overview-card--wide">
            <p className="overview-card__label">Liveness</p>
            <dl className="data-list">
              <DataRow
                label="Process alive"
                value={readiness ? "Backend responded" : "Unknown"}
              />
              <DataRow
                label="Uptime"
                value={
                  status.uptime_seconds !== null &&
                  status.uptime_seconds !== undefined
                    ? `${Math.round(status.uptime_seconds)}s`
                    : "Not reported"
                }
              />
              <DataRow label="Reported at" value={status.timestamp_utc} />
            </dl>
          </div>
        </div>
      ) : null}
    </Panel>
  );
}
