/**
 * Synthetic response fixtures for frontend tests.
 *
 * These are hand-built shapes that mirror the backend contract. They are NOT
 * real market data and contain no market values.
 */

export const meta = {
  api_version: "v1",
  request_id: "fx-synthetic-fixture-request",
  timestamp_utc: "2024-01-04T00:00:00Z",
};

export const versionData = {
  service: "fx-historical-market-analysis-service",
  application_version: "0.1.0",
  api_version: "v1",
  environment: "testing",
  service_mode: "research-simulation",
};

export const liveData = {
  status: "healthy",
  service: "fx-historical-market-analysis-service",
  mode: "research-simulation",
  check: "liveness",
};

export const readyData = {
  status: "healthy",
  service: "fx-historical-market-analysis-service",
  mode: "research-simulation",
  check: "readiness",
  dependencies: [
    {
      name: "fx-market-data-service",
      healthy: false,
      detail: "Upstream integration is not configured.",
    },
  ],
};

export const statusData = {
  service_id: "fx-historical-market-analysis-service",
  application_version: "0.1.0",
  api_version: "v1",
  environment: "testing",
  service_mode: "research-simulation",
  operational_state: "operational",
  uptime_seconds: 12.5,
  capabilities: [
    {
      name: "service_health",
      implemented: true,
      detail: "Liveness, readiness, status and version endpoints.",
    },
    {
      name: "historical_statistics",
      implemented: true,
      detail: "Descriptive statistics over historical observations.",
    },
    {
      name: "pattern_discovery",
      implemented: true,
      detail: "Historical pattern and relationship identification.",
    },
  ],
  dependencies: [
    { name: "fx-market-data-service", healthy: false, state: "unconfigured" },
  ],
  upstream_integration: {
    service: "fx-market-data-service",
    state: "unconfigured",
    base_url_configured: false,
    credential_configured: false,
    base_url: null,
    last_checked_at: null,
    last_check_succeeded: null,
    last_check_message: null,
    contract_status: "verified",
    latency_ms: null,
  },
  timestamp_utc: "2024-01-04T00:00:00Z",
};

export function envelope(data: unknown) {
  return { data, meta, errors: [] };
}

export const dataSourceData = {
  configuration: {
    base_url_configured: true,
    credential_configured: true,
  },
  connectivity: {
    state: "connected",
    message: "Upstream reachable",
    latency_ms: 12,
    checked_at: "2024-01-04T00:00:00Z",
  },
  contract_status: "verified",
};
