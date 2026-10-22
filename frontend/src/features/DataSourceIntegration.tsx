import { DataRow } from "@/components/DataRow";
import { EmptyState } from "@/components/EmptyState";
import { Panel } from "@/components/Panel";
import { StatusBadge, type BadgeTone } from "@/components/StatusBadge";
import type { UpstreamIntegrationStatus } from "@/schemas/api";

interface DataSourceIntegrationProps {
  upstream: UpstreamIntegrationStatus | null;
  isLoading: boolean;
}

/**
 * Maps the upstream state vocabulary onto a badge tone.
 *
 * Each state is distinct on purpose: an unconfigured integration must never
 * look the same as a verified one.
 */
function toneForState(state: UpstreamIntegrationStatus["state"]): BadgeTone {
  switch (state) {
    case "connected":
      return "ok";
    case "unavailable":
    case "auth_failed":
      return "error";
    case "unverified":
      return "warn";
    case "unconfigured":
    default:
      return "neutral";
  }
}

function labelForState(state: UpstreamIntegrationStatus["state"]): string {
  switch (state) {
    case "connected":
      return "connected";
    case "unavailable":
      return "unavailable";
    case "auth_failed":
      return "authentication failed";
    case "unverified":
      return "configured, not yet verified";
    case "unconfigured":
    default:
      return "not configured";
  }
}

/**
 * Data Source Integration panel.
 *
 * Shows the configured upstream service identity and its real connection
 * state. Credentials are never displayed: only a boolean indicating whether
 * one is configured.
 */
export function DataSourceIntegration({
  upstream,
  isLoading,
}: DataSourceIntegrationProps) {
  return (
    <Panel
      title="Data Source Integration"
      subtitle="Upstream market-data service configured for this deployment."
    >
      {isLoading && !upstream ? <p className="muted">Loading integration status…</p> : null}

      {!isLoading && !upstream ? (
        <EmptyState
          title="No integration status"
          message="The backend did not report an upstream integration state."
        />
      ) : null}

      {upstream ? (
        <>
          <div className="integration-head">
            <p className="integration-head__service" data-testid="upstream-service">
              {upstream.service}
            </p>
            <StatusBadge
              tone={toneForState(upstream.state)}
              label={labelForState(upstream.state)}
            />
          </div>

          <dl className="data-list">
            <DataRow
              label="Base URL configured"
              value={upstream.base_url_configured ? "Yes" : "No"}
              testId="upstream-base-url-configured"
            />
            <DataRow
              label="Credential configured"
              value={upstream.credential_configured ? "Yes" : "No"}
              testId="upstream-credential-configured"
            />
            <DataRow
              label="Base URL"
              value={
                upstream.base_url ? (
                  <code data-testid="upstream-base-url">{upstream.base_url}</code>
                ) : (
                  "Not configured"
                )
              }
            />
            <DataRow
              label="Contract status"
              value={
                <span data-testid="upstream-contract-status">
                  {upstream.contract_status}
                </span>
              }
            />
            <DataRow
              label="Last check"
              value={upstream.last_checked_at ?? "Never performed"}
              testId="upstream-last-checked"
            />
            <DataRow
              label="Last check outcome"
              value={
                upstream.last_check_succeeded === null ||
                upstream.last_check_succeeded === undefined
                  ? "Not yet verified"
                  : upstream.last_check_succeeded
                    ? "Succeeded"
                    : "Failed"
              }
              testId="upstream-last-check-outcome"
            />
            <DataRow
              label="Last check message"
              value={upstream.last_check_message ?? "No result recorded"}
            />
            <DataRow
              label="Latency"
              value={
                upstream.latency_ms !== null && upstream.latency_ms !== undefined
                  ? `${upstream.latency_ms} ms`
                  : "Not measured"
              }
            />
          </dl>

          <p className="muted small">
            Credential values are never returned by the backend and are not
            displayed here.
          </p>
        </>
      ) : null}
    </Panel>
  );
}
