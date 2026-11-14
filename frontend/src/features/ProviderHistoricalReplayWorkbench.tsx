import { useEffect, useState, type FormEvent } from "react";

import { EmptyState } from "@/components/EmptyState";
import { ErrorNotice } from "@/components/ErrorNotice";
import { LoadingState } from "@/components/LoadingState";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { api, ApiError, type HistoricalProviderInventory, type HistoricalReplayResponseData } from "@/services/api";

/**
 * Runs the server-side Service 1 -> optional Service 61 -> Service 2 replay
 * path. Provider/source authenticity and historical publication time remain
 * explicitly unverified by the upstream contract.
 */
export function ProviderHistoricalReplayWorkbench() {
  const [inventory, setInventory] = useState<HistoricalProviderInventory | null>(null);
  const [providerId, setProviderId] = useState("");
  const [instrument, setInstrument] = useState("EUR/USD");
  const [timeframe, setTimeframe] = useState("H1");
  const [priceBasis, setPriceBasis] = useState("bid");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [sourceDatasetId, setSourceDatasetId] = useState("");
  const [limit, setLimit] = useState("2000");
  const [targetType, setTargetType] = useState<"future_return" | "direction">("future_return");
  const [modelFamily, setModelFamily] = useState("ridge_regression");
  const [loadingProviders, setLoadingProviders] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [result, setResult] = useState<HistoricalReplayResponseData | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoadingProviders(true);
    api.listHistoricalProviders()
      .then((data) => {
        if (cancelled) return;
        setInventory(data);
        const firstReal = data.providers.find((provider) =>
          provider.provider_type === "real" &&
          provider.configured &&
          provider.historical_candles_supported,
        );
        if (firstReal) setProviderId(firstReal.provider_id);
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof ApiError ? caught : new ApiError("Unable to load provider inventory.", 0, "UNEXPECTED", null));
      })
      .finally(() => { if (!cancelled) setLoadingProviders(false); });
    return () => { cancelled = true; };
  }, []);

  async function runReplay(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const numericLimit = Number(limit);
    if (!providerId || !sourceDatasetId.trim() || !instrument.trim()) {
      setError(new ApiError("Provider, canonical instrument, and source dataset ID are required.", 0, "VALIDATION_ERROR", null));
      return;
    }
    if (!start || !end || !Number.isFinite(Date.parse(start)) || !Number.isFinite(Date.parse(end)) || Date.parse(start) >= Date.parse(end)) {
      setError(new ApiError("Enter a valid start and end time, with start earlier than end.", 0, "VALIDATION_ERROR", null));
      return;
    }
    if (!Number.isInteger(numericLimit) || numericLimit < 53 || numericLimit > 2000) {
      setError(new ApiError("Replay limit must be between 53 and 2000 for the current lookback/training/horizon settings.", 0, "VALIDATION_ERROR", null));
      return;
    }

    setRunning(true);
    setError(null);
    setResult(null);
    const problem = {
      problem_id: `provider-replay-${instrument.toLowerCase().replace("/", "-")}`,
      version: "1.0.0",
      instrument_scope: [instrument],
      input_timeframe: timeframe,
      price_basis: "close",
      feature_availability_policy: "point_in_time",
      prediction_reference: "observation_close",
      prediction_horizon: 1,
      target_type: targetType,
      target_units: targetType === "direction" ? "class" : "fraction",
      eligibility_rules: [],
      label_generation_method: "exact_future_observation",
      missing_observation_policy: "drop_row",
      required_historical_coverage: 20,
      evaluation_protocol: "chronological_holdout",
      known_limitations: [],
      neutral_threshold: targetType === "direction" ? 0.0005 : null,
      volatility_window: null,
      max_features: 64,
    };
    try {
      const data = await api.runHistoricalReplayFromMarketData({
        instrument,
        timeframe,
        price_basis: priceBasis,
        provider_id: providerId,
        source_dataset_id: sourceDatasetId,
        start: new Date(start).toISOString(),
        end: new Date(end).toISOString(),
        limit: numericLimit,
        problem,
        lookback: 20,
        min_train_samples: 30,
        validation_mode: "expanding",
        embargo_periods: 1,
        model_families: [modelFamily],
        random_seed: 42,
      });
      setResult(data);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError("Provider-sourced replay failed.", 0, "UNEXPECTED", null));
    } finally {
      setRunning(false);
    }
  }

  const eligibleProviders = (inventory?.providers ?? []).filter((provider) =>
    provider.provider_type === "real" && provider.configured && provider.historical_candles_supported,
  );
  const dataSource = result?.reproducibility.data_source;
  const sessionIntegration = dataSource && typeof dataSource === "object"
    ? (dataSource as Record<string, unknown>).session_context_integration
    : null;

  return (
    <Panel
      title="Provider-Sourced Historical Replay"
      subtitle="Server-side historical retrieval through Service 1 and optional point-in-time session context through Service 61."
    >
      <div data-testid="provider-historical-replay">
        <p className="not-implemented-banner">
          This path uses the configured real-provider integration; it is not a live feed. Provider identity is provider-asserted, historical availability uses an explicit close-plus-lag assumption, and session context is only attached when the configured Feature Engineering contract validates.
        </p>
        {eligibleProviders.length === 0 && !loadingProviders ? (
          <EmptyState title="No eligible real historical provider" message="Configure and connection-test a real provider in Service 1. Test adapters are deliberately excluded from provider-sourced replay." />
        ) : null}
        <form className="replay-form" onSubmit={runReplay}>
          <div className="replay-form__grid">
            <label>
              Real historical provider
              <select required value={providerId} onChange={(event) => setProviderId(event.currentTarget.value)} disabled={loadingProviders || eligibleProviders.length === 0}>
                <option value="">Select provider</option>
                {eligibleProviders.map((provider) => <option key={provider.provider_id} value={provider.provider_id}>{provider.provider_id}</option>)}
              </select>
            </label>
            <label>Canonical instrument<input required value={instrument} onChange={(event) => setInstrument(event.currentTarget.value.toUpperCase())} placeholder="EUR/USD" /></label>
            <label>
              Timeframe
              <select value={timeframe} onChange={(event) => setTimeframe(event.currentTarget.value)}>
                {["M1", "M5", "M15", "M30", "H1", "H4", "D1"].map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
            <label>
              Price basis
              <select value={priceBasis} onChange={(event) => setPriceBasis(event.currentTarget.value)}>
                <option value="bid">Bid</option><option value="ask">Ask</option><option value="midpoint">Midpoint</option>
              </select>
            </label>
            <label>Start (local browser time)<input type="datetime-local" required value={start} onChange={(event) => setStart(event.currentTarget.value)} /></label>
            <label>End (local browser time)<input type="datetime-local" required value={end} onChange={(event) => setEnd(event.currentTarget.value)} /></label>
            <label>Source dataset ID<input required value={sourceDatasetId} onChange={(event) => setSourceDatasetId(event.currentTarget.value)} placeholder="A stable dataset label" /></label>
            <label>Maximum candles<input type="number" min="53" max="2000" value={limit} onChange={(event) => setLimit(event.currentTarget.value)} /></label>
            <label>
              Forecast research target
              <select value={targetType} onChange={(event) => {
                const next = event.currentTarget.value === "direction" ? "direction" : "future_return";
                setTargetType(next);
                setModelFamily(next === "direction" ? "ridge_logistic" : "ridge_regression");
              }}>
                <option value="future_return">Future return</option><option value="direction">Direction</option>
              </select>
            </label>
            <label>
              Research model
              <select value={modelFamily} onChange={(event) => setModelFamily(event.currentTarget.value)}>
                {(targetType === "direction" ? ["ridge_logistic", "random_forest", "histogram_gradient_boosting"] : ["ridge_regression", "random_forest", "histogram_gradient_boosting"]).map((value) => <option key={value} value={value}>{value.replace(/_/g, " ")}</option>)}
              </select>
            </label>
          </div>
          <button className="button" type="submit" disabled={running || loadingProviders || eligibleProviders.length === 0} data-testid="run-provider-replay">
            {running ? "Retrieving and replaying historical candles…" : "Run provider-sourced replay"}
          </button>
        </form>
        {error ? <ErrorNotice title="Provider-sourced replay unavailable" message={error.message} code={error.code} requestId={error.requestId} testId="provider-replay-error" /> : null}
        {running ? <LoadingState label="Fetching validated historical candles and evaluating chronological origins…" /> : null}
        {result ? (
          <section className="replay-result" data-testid="provider-replay-result">
            <div className="integration-head">
              <p className="integration-head__service">{result.instrument} · {result.timeframe}</p>
              <StatusBadge tone="warn" label="provider asserted / availability assumed" />
            </div>
            <p>{result.replay_id} · {result.n_observations} candles · {result.n_predictions} predictions</p>
            <p className="muted small">Dataset fingerprint: <code>{result.dataset_fingerprint}</code></p>
            <p className="muted small">Session context integration: {JSON.stringify(sessionIntegration ?? { state: "not reported" })}</p>
            <h4>Reproducibility and source record</h4>
            <pre>{JSON.stringify(dataSource ?? {}, null, 2)}</pre>
            <h4>Point-in-time session and liquidity context</h4>
            <pre>{JSON.stringify(result.predictions.slice(0, 25).map((prediction) => ({
              reference_timestamp: prediction.reference_timestamp,
              information_cutoff: prediction.information_cutoff,
              market_context: prediction.market_context ?? null,
            })), null, 2)}</pre>
            <h4>Model and robustness results</h4>
            <pre>{JSON.stringify(result.models, null, 2)}</pre>
            <pre>{JSON.stringify(result.robustness, null, 2)}</pre>
            {result.warnings.length ? <><h4>Warnings</h4><ul>{result.warnings.map((item) => <li key={item}>{item}</li>)}</ul></> : null}
            {result.limitations.length ? <><h4>Limitations</h4><ul>{result.limitations.map((item) => <li key={item}>{item}</li>)}</ul></> : null}
            <p className="muted small">Historical research only. This result is not a live prediction, trading signal, calibrated probability, or instruction to enter a position.</p>
          </section>
        ) : null}
      </div>
    </Panel>
  );
}
