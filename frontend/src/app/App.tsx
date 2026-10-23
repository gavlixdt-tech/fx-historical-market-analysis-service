import { ForecastingReadiness } from "@/features/ForecastingReadiness";
import { RealMarketDataWorkspace } from "@/features/RealMarketDataWorkspace";
import { AnalysisWorkspace } from "@/features/AnalysisWorkspace";
import { DataSourceIntegration } from "@/features/DataSourceIntegration";
import { OperationalDiagnostics } from "@/features/OperationalDiagnostics";
import { ServiceOverview } from "@/features/ServiceOverview";
import { StatusBadge } from "@/components/StatusBadge";
import { useServiceStatus } from "./useServiceStatus";

/**
 * Application shell for the Historical Market Analysis Service dashboard.
 *
 * The dashboard is strictly read-only. It exposes no trading controls, no
 * order placement, and no buy/sell guidance.
 */
export default function App() {
  const {
    status,
    readiness,
    version,
    isLoading,
    error,
    lastRefreshedAt,
    refresh,
  } = useServiceStatus();

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header__identity">
          <h1 className="app-header__title">
            Historical Market Analysis Service
          </h1>
          <p className="app-header__subtitle">
            Read-only operational dashboard &middot; research / simulation mode
          </p>
        </div>
        <div className="app-header__actions">
          <StatusBadge
            tone={error ? "error" : isLoading ? "neutral" : "ok"}
            label={error ? "backend unreachable" : isLoading ? "connecting" : "connected"}
          />
          <button
            type="button"
            className="button"
            onClick={refresh}
            disabled={isLoading}
            data-testid="refresh-button"
          >
            Refresh
          </button>
        </div>
      </header>

      <main className="app-main">
        <ServiceOverview
          status={status}
          readiness={readiness}
          version={version}
          isLoading={isLoading}
          error={error}
          lastRefreshedAt={lastRefreshedAt}
        />

        <AnalysisWorkspace
          capabilities={status?.capabilities ?? []}
          isLoading={isLoading}
        />

        <ForecastingReadiness />

        <RealMarketDataWorkspace />

        <DataSourceIntegration
          upstream={status?.upstream_integration ?? null}
          isLoading={isLoading}
        />

        <OperationalDiagnostics
          readiness={readiness}
          error={error}
          isLoading={isLoading}
          lastRefreshedAt={lastRefreshedAt}
        />
      </main>

      <footer className="app-footer">
        <p>
          Historical analysis engine available &mdash; research/simulation mode.
          No trading signals or execution capabilities.
        </p>
      </footer>
    </div>
  );
}
