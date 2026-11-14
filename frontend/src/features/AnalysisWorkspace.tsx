import { useEffect, useState, type FormEvent } from "react";

import { EmptyState } from "@/components/EmptyState";
import { ErrorNotice } from "@/components/ErrorNotice";
import { LoadingState } from "@/components/LoadingState";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { api, ApiError, type HistoricalProviderInventory, type ResearchSummaryResponseData } from "@/services/api";
import type { CapabilityStatus } from "@/schemas/api";

interface AnalysisWorkspaceProps {
  capabilities: CapabilityStatus[];
  isLoading: boolean;
}

/**
 * Runs the service's actual retrospective regime/pattern research summary.
 * It does not create a live forecast or trading recommendation.
 */
export function AnalysisWorkspace({ capabilities, isLoading }: AnalysisWorkspaceProps) {
  const [inventory, setInventory] = useState<HistoricalProviderInventory | null>(null);
  const [providerId, setProviderId] = useState("");
  const [instrument, setInstrument] = useState("EUR/USD");
  const [timeframe, setTimeframe] = useState("H1");
  const [priceBasis, setPriceBasis] = useState("bid");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [limit, setLimit] = useState("1000");
  const [loadingProviders, setLoadingProviders] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [result, setResult] = useState<ResearchSummaryResponseData | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoadingProviders(true);
    api.listHistoricalProviders()
      .then((data) => {
        if (!cancelled) {
          setInventory(data);
          if (!providerId) {
            const firstConfigured = data.providers.find((provider) => provider.configured && provider.historical_candles_supported);
            if (firstConfigured) setProviderId(firstConfigured.provider_id);
          }
        }
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof ApiError ? caught : new ApiError("Unable to load historical providers.", 0, "UNEXPECTED", null));
      })
      .finally(() => { if (!cancelled) setLoadingProviders(false); });
    return () => { cancelled = true; };
  }, []);

  async function runResearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const numericLimit = Number(limit);
    if (!providerId || !instrument.trim() || !Number.isInteger(numericLimit) || numericLimit < 1 || numericLimit > 5000) {
      setError(new ApiError("Select a provider, enter an instrument, and use a limit from 1 to 5000.", 0, "VALIDATION_ERROR", null));
      return;
    }
    if (start && end && new Date(start).getTime() > new Date(end).getTime()) {
      setError(new ApiError("Start time must not be later than end time.", 0, "VALIDATION_ERROR", null));
      return;
    }
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const data = await api.runResearchSummary({
        provider_id: providerId,
        instrument: instrument.trim(),
        timeframe,
        price_basis: priceBasis,
        start: start ? new Date(start).toISOString() : null,
        end: end ? new Date(end).toISOString() : null,
        limit: numericLimit,
      });
      setResult(data);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError("Historical research failed.", 0, "UNEXPECTED", null));
    } finally {
      setRunning(false);
    }
  }

  const implemented = capabilities.filter((capability) => capability.implemented);
  const selectedProvider = inventory?.providers.find((provider) => provider.provider_id === providerId);

  return (
    <Panel
      title="Historical Analysis Workspace"
      subtitle="Retrospective regime and pattern research using the backend's validated historical-analysis endpoints. No live forecast or trading action."
    >
      <div data-testid="historical-analysis-workspace">
        {isLoading ? <LoadingState label="Loading service capabilities…" /> : null}
        {implemented.length > 0 ? (
          <ul className="capability-list" data-testid="implemented-capabilities">
            {implemented.map((capability) => (
              <li key={capability.name} className="capability-list__item">
                <div className="capability-list__head">
                  <span className="capability-list__name">{capability.name.replace(/_/g, " ")}</span>
                  <StatusBadge tone="ok" label="available" />
                </div>
                {capability.detail ? <p className="capability-list__detail">{capability.detail}</p> : null}
              </li>
            ))}
          </ul>
        ) : null}

        <form className="replay-form" onSubmit={runResearch}>
          <div className="replay-form__grid">
            <label>
              Historical provider
              <select required value={providerId} onChange={(event) => setProviderId(event.currentTarget.value)} disabled={loadingProviders}>
                <option value="">Select provider explicitly</option>
                {(inventory?.providers ?? []).map((provider) => (
                  <option key={provider.provider_id} value={provider.provider_id} disabled={!provider.configured || !provider.historical_candles_supported}>
                    {provider.provider_id} · {provider.provider_type} · {provider.configured ? "configured" : "not configured"}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Instrument
              <input required minLength={3} maxLength={20} value={instrument} onChange={(event) => setInstrument(event.currentTarget.value)} />
            </label>
            <label>
              Timeframe
              <select value={timeframe} onChange={(event) => setTimeframe(event.currentTarget.value)}>
                {["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"].map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
            <label>
              Price basis
              <select value={priceBasis} onChange={(event) => setPriceBasis(event.currentTarget.value)}>
                <option value="bid">Bid</option><option value="ask">Ask</option><option value="midpoint">Midpoint</option>
              </select>
            </label>
            <label>Start (optional)<input type="datetime-local" value={start} onChange={(event) => setStart(event.currentTarget.value)} /></label>
            <label>End (optional)<input type="datetime-local" value={end} onChange={(event) => setEnd(event.currentTarget.value)} /></label>
            <label>Maximum observations<input type="number" min="1" max="5000" value={limit} onChange={(event) => setLimit(event.currentTarget.value)} /></label>
          </div>
          <p className="muted small">
            {selectedProvider ? `Selected ${selectedProvider.provider_id} (${selectedProvider.provider_type}); the backend still validates provider availability and data quality.` : "Choose a configured provider with historical-candle capability."}
          </p>
          <button className="button" type="submit" disabled={running || loadingProviders || !providerId} data-testid="run-historical-analysis">
            {running ? "Analyzing historical observations…" : "Run historical analysis"}
          </button>
        </form>

        {error ? <ErrorNotice title="Historical analysis unavailable" message={error.message} code={error.code} requestId={error.requestId} testId="analysis-error" /> : null}
        {running ? <LoadingState label="Calculating historical regimes and pattern statistics…" /> : null}
        {result ? (
          <section className="replay-result" data-testid="historical-analysis-result">
            <h3>Research summary</h3>
            <p>{result.narrative}</p>
            <div className="overview-grid">
              <div className="overview-card"><p className="overview-card__label">Observations</p><p className="overview-card__value">{result.observation_count.toLocaleString()}</p></div>
              <div className="overview-card"><p className="overview-card__label">Dominant regime</p><p className="overview-card__value">{result.dominant_regime ?? "Not classified"}</p></div>
              <div className="overview-card"><p className="overview-card__label">Regime share</p><p className="overview-card__value">{result.regime_share === null || result.regime_share === undefined ? "Not reported" : `${(result.regime_share * 100).toFixed(1)}%`}</p></div>
              <div className="overview-card"><p className="overview-card__label">Trend / volatility</p><p className="overview-card__value">{result.trend_state} / {result.volatility_state}</p></div>
              <div className="overview-card"><p className="overview-card__label">Pattern tested</p><p className="overview-card__value">{result.pattern_id ?? "Not estimable"}</p></div>
              <div className="overview-card"><p className="overview-card__label">Pattern significance</p><p className="overview-card__value">{result.pattern_significance ? "Significant under reported test" : "Not established"}</p></div>
            </div>
            <p className="muted small">Confidence: {result.confidence_status}; no calibrated confidence is produced by this analysis. Provenance: {String(result.data_provenance.provenance_status ?? "unknown")}. Fingerprint: {result.dataset_fingerprint ?? "Not reported"}</p>
            <h4>Research notes</h4>
            <ul>{result.recommendations.map((item) => <li key={item}>{item}</li>)}</ul>
            {result.warnings.length ? <><h4>Warnings</h4><ul>{result.warnings.map((item) => <li key={item}>{item}</li>)}</ul></> : null}
            {result.limitations.length ? <><h4>Limitations</h4><ul>{result.limitations.map((item) => <li key={item}>{item}</li>)}</ul></> : null}
          </section>
        ) : !running ? (
          <EmptyState title="No analysis run yet" message="Select a historical provider and run a bounded retrospective analysis. Results will be displayed here only after the backend responds." />
        )}
      </div>
    </Panel>
  );
}
