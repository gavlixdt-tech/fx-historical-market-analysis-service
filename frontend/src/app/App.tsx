import { ForecastingReadiness } from "@/features/ForecastingReadiness";
import { SessionLiquidityEventStudy } from "@/features/SessionLiquidityEventStudy";
import { SeasonalityWorkspace } from "@/features/SeasonalityWorkspace";
import { HistoricalReplayWorkbench } from "@/features/HistoricalReplayWorkbench";
import { ProviderHistoricalReplayWorkbench } from "@/features/ProviderHistoricalReplayWorkbench";
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

      <nav className="app-nav" aria-label="Dashboard sections">
        <a href="#overview">Overview</a>
        <a href="#analysis">Historical analysis</a>
        <a href="#seasonality">Calendar seasonality</a>
        <a href="#forecasting">Forecast research</a>
        <a href="#provider-replay">Provider replay</a>
        <a href="#replay">Uploaded replay</a>
        <a href="#event-study">Session / liquidity study</a>
        <a href="#market-data">Market data</a>
        <a href="#integrations">Integrations</a>
        <a href="#diagnostics">Diagnostics</a>
      </nav>

      <main className="app-main">
        <section id="overview"><ServiceOverview
          status={status}
          readiness={readiness}
          version={version}
          isLoading={isLoading}
          error={error}
          lastRefreshedAt={lastRefreshedAt}
        /></section>

        <section id="analysis"><AnalysisWorkspace
          capabilities={status?.capabilities ?? []}
          isLoading={isLoading}
        /></section>

        <section id="seasonality"><SeasonalityWorkspace /></section>

        <section id="forecasting"><ForecastingReadiness /></section>

        <section id="provider-replay"><ProviderHistoricalReplayWorkbench /></section>

        <section id="replay"><HistoricalReplayWorkbench /></section>

        <section id="event-study"><SessionLiquidityEventStudy /></section>

        <section id="market-data"><RealMarketDataWorkspace /></section>

        <section id="integrations"><DataSourceIntegration
          upstream={status?.upstream_integration ?? null}
          isLoading={isLoading}
        /></section>

        <section id="diagnostics"><OperationalDiagnostics
          readiness={readiness}
          error={error}
          isLoading={isLoading}
          lastRefreshedAt={lastRefreshedAt}
        /></section>
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
