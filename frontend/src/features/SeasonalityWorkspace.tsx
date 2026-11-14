import { useEffect, useState, type FormEvent } from "react";

import { EmptyState } from "@/components/EmptyState";
import { ErrorNotice } from "@/components/ErrorNotice";
import { LoadingState } from "@/components/LoadingState";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import {
  api,
  ApiError,
  type HistoricalProviderInventory,
  type SeasonalityAnalysisResponseData,
} from "@/services/api";

type BucketType = "weekday" | "hour_of_day" | "month_of_year";

const BUCKET_OPTIONS: { value: BucketType; label: string }[] = [
  { value: "weekday", label: "Day of week" },
  { value: "hour_of_day", label: "Hour of day" },
  { value: "month_of_year", label: "Month of year" },
];

const TIMEZONES = [
  "UTC",
  "Africa/Nairobi",
  "Europe/London",
  "America/New_York",
  "Asia/Tokyo",
  "Australia/Sydney",
];

function percentageOrLabel(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value)
    ? `${(value * 100).toFixed(2)}%`
    : "Not estimable";
}

/** Descriptive calendar seasonality research; never a trading signal. */
export function SeasonalityWorkspace() {
  const [inventory, setInventory] = useState<HistoricalProviderInventory | null>(null);
  const [providerId, setProviderId] = useState("");
  const [instrument, setInstrument] = useState("EUR/USD");
  const [timeframe, setTimeframe] = useState("H1");
  const [priceBasis, setPriceBasis] = useState("bid");
  const [timezone, setTimezone] = useState("UTC");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [limit, setLimit] = useState("2000");
  const [minimumSamples, setMinimumSamples] = useState("20");
  const [maximumGapMultiple, setMaximumGapMultiple] = useState("1.5");
  const [bucketTypes, setBucketTypes] = useState<BucketType[]>([
    "weekday",
    "hour_of_day",
    "month_of_year",
  ]);
  const [loadingProviders, setLoadingProviders] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [result, setResult] = useState<SeasonalityAnalysisResponseData | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoadingProviders(true);
    api.listHistoricalProviders()
      .then((data) => {
        if (cancelled) return;
        setInventory(data);
        const firstConfigured = data.providers.find(
          (provider) => provider.configured && provider.historical_candles_supported,
        );
        if (firstConfigured) setProviderId(firstConfigured.provider_id);
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(
            caught instanceof ApiError
              ? caught
              : new ApiError("Unable to load historical providers.", 0, "UNEXPECTED", null),
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingProviders(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function toggleBucket(value: BucketType, checked: boolean) {
    setBucketTypes((current) => {
      if (checked) return current.includes(value) ? current : [...current, value];
      return current.filter((item) => item !== value);
    });
  }

  async function runSeasonality(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const numericLimit = Number(limit);
    const numericMinimum = Number(minimumSamples);
    const numericGapMultiple = Number(maximumGapMultiple);
    if (!providerId || !instrument.trim()) {
      setError(new ApiError("Select a historical provider and instrument.", 0, "VALIDATION_ERROR", null));
      return;
    }
    if (!Number.isInteger(numericLimit) || numericLimit < 20 || numericLimit > 5000) {
      setError(new ApiError("Observation limit must be between 20 and 5000.", 0, "VALIDATION_ERROR", null));
      return;
    }
    if (!Number.isFinite(numericGapMultiple) || numericGapMultiple < 1 || numericGapMultiple > 4) {
      setError(new ApiError("Maximum candle-gap multiple must be between 1 and 4.", 0, "VALIDATION_ERROR", null));
      return;
    }
    if (!Number.isInteger(numericMinimum) || numericMinimum < 5 || numericMinimum > 500) {
      setError(new ApiError("Minimum bucket sample must be between 5 and 500.", 0, "VALIDATION_ERROR", null));
      return;
    }
    if (bucketTypes.length === 0) {
      setError(new ApiError("Select at least one calendar dimension.", 0, "VALIDATION_ERROR", null));
      return;
    }
    if (start && !Number.isFinite(Date.parse(start))) {
      setError(new ApiError("Start time is invalid.", 0, "VALIDATION_ERROR", null));
      return;
    }
    if (end && !Number.isFinite(Date.parse(end))) {
      setError(new ApiError("End time is invalid.", 0, "VALIDATION_ERROR", null));
      return;
    }
    if (start && end && Date.parse(start) >= Date.parse(end)) {
      setError(new ApiError("Start time must be earlier than end time.", 0, "VALIDATION_ERROR", null));
      return;
    }

    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const data = await api.runSeasonalityAnalysis({
        provider_id: providerId,
        instrument: instrument.trim(),
        timeframe,
        price_basis: priceBasis,
        start: start ? new Date(start).toISOString() : null,
        end: end ? new Date(end).toISOString() : null,
        limit: numericLimit,
        timezone,
        bucket_types: bucketTypes,
        minimum_bucket_samples: numericMinimum,
        bootstrap_samples: 300,
        block_size: 5,
        seed: 42,
        maximum_gap_multiple: numericGapMultiple,
      });
      setResult(data);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError("Calendar seasonality analysis failed.", 0, "UNEXPECTED", null),
      );
    } finally {
      setRunning(false);
    }
  }

  const selectedProvider = inventory?.providers.find((provider) => provider.provider_id === providerId);

  return (
    <Panel
      title="Calendar Seasonality Research"
      subtitle="Historical return and volatility distributions by weekday, hour and month, with explicit timezone and missing-interval handling."
    >
      <div data-testid="seasonality-workspace">
        <p className="not-implemented-banner">
          Descriptive historical research only. These distributions are not forecasts, calibrated probabilities, entry signals, or trading recommendations. Provider identity and original historical publication times remain subject to the upstream provenance contract.
        </p>
        <form className="replay-form" onSubmit={runSeasonality}>
          <div className="replay-form__grid">
            <label>
              Historical provider
              <select
                required
                value={providerId}
                onChange={(event) => setProviderId(event.currentTarget.value)}
                disabled={loadingProviders}
              >
                <option value="">Select provider explicitly</option>
                {(inventory?.providers ?? []).map((provider) => (
                  <option
                    key={provider.provider_id}
                    value={provider.provider_id}
                    disabled={!provider.configured || !provider.historical_candles_supported}
                  >
                    {provider.provider_id} · {provider.provider_type} · {provider.configured ? "configured" : "not configured"}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Instrument
              <input
                required
                minLength={3}
                maxLength={20}
                value={instrument}
                onChange={(event) => setInstrument(event.currentTarget.value.toUpperCase())}
              />
            </label>
            <label>
              Timeframe
              <select value={timeframe} onChange={(event) => setTimeframe(event.currentTarget.value)}>
                {["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"].map((value) => (
                  <option key={value} value={value}>{value}</option>
                ))}
              </select>
            </label>
            <label>
              Price basis
              <select value={priceBasis} onChange={(event) => setPriceBasis(event.currentTarget.value)}>
                <option value="bid">Bid</option>
                <option value="ask">Ask</option>
                <option value="midpoint">Midpoint</option>
              </select>
            </label>
            <label>
              Calendar timezone
              <select value={timezone} onChange={(event) => setTimezone(event.currentTarget.value)}>
                {TIMEZONES.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
            <label>
              Maximum observations
              <input type="number" min="20" max="5000" value={limit} onChange={(event) => setLimit(event.currentTarget.value)} />
            </label>
            <label>
              Minimum samples per bucket
              <input type="number" min="5" max="500" value={minimumSamples} onChange={(event) => setMinimumSamples(event.currentTarget.value)} />
            </label>
            <label>
              Maximum candle-gap multiple
              <input type="number" min="1" max="4" step="0.1" value={maximumGapMultiple} onChange={(event) => setMaximumGapMultiple(event.currentTarget.value)} />
            </label>
            <label>Start (local browser time)<input type="datetime-local" value={start} onChange={(event) => setStart(event.currentTarget.value)} /></label>
            <label>End (local browser time)<input type="datetime-local" value={end} onChange={(event) => setEnd(event.currentTarget.value)} /></label>
          </div>
          <fieldset>
            <legend>Calendar dimensions</legend>
            <div className="capability-list">
              {BUCKET_OPTIONS.map((option) => (
                <label key={option.value} className="capability-list__item">
                  <input
                    type="checkbox"
                    checked={bucketTypes.includes(option.value)}
                    onChange={(event) => toggleBucket(option.value, event.currentTarget.checked)}
                  />
                  {option.label}
                </label>
              ))}
            </div>
          </fieldset>
          <p className="muted small">
            {selectedProvider
              ? `Selected ${selectedProvider.provider_id} (${selectedProvider.provider_type}); the backend still validates provider availability and source quality.`
              : "Choose a configured provider with historical-candle capability."}
          </p>
          <button
            className="button"
            type="submit"
            disabled={running || loadingProviders || !providerId || bucketTypes.length === 0}
            data-testid="run-seasonality"
          >
            {running ? "Analyzing calendar distributions…" : "Run seasonality research"}
          </button>
        </form>

        {error ? <ErrorNotice title="Seasonality analysis unavailable" message={error.message} code={error.code} requestId={error.requestId} testId="seasonality-error" /> : null}
        {running ? <LoadingState label="Grouping contiguous historical returns and estimating descriptive intervals…" /> : null}
        {result ? (
          <section className="replay-result" data-testid="seasonality-result">
            <div className="integration-head">
              <p className="integration-head__service">{result.instrument ?? "Instrument"} · {result.timeframe} · {result.timezone}</p>
              <StatusBadge tone="warn" label="descriptive only" />
            </div>
            <p className="muted small">
              {result.observation_count.toLocaleString()} observations · {result.return_observation_count.toLocaleString()} valid returns · {result.excluded_gap_return_count.toLocaleString()} long-gap exclusions · {result.excluded_short_interval_return_count.toLocaleString()} short-interval exclusions
            </p>
            <p className="muted small">Dataset fingerprint: <code>{result.dataset_fingerprint}</code></p>
            <p className="muted small">Analysis fingerprint: <code>{result.analysis_fingerprint}</code></p>
            <p className="muted small">Accepted interval: 0.9× to {String(result.effective_config.maximum_gap_multiple)}× {result.timeframe}</p>
            <div className="overview-grid">
              <div className="overview-card"><p className="overview-card__label">Mean return</p><p className="overview-card__value">{percentageOrLabel(result.global_summary.mean_return)}</p></div>
              <div className="overview-card"><p className="overview-card__label">Median return</p><p className="overview-card__value">{percentageOrLabel(result.global_summary.median_return)}</p></div>
              <div className="overview-card"><p className="overview-card__label">Return standard deviation (not annualized)</p><p className="overview-card__value">{percentageOrLabel(result.global_summary.realized_volatility)}</p></div>
              <div className="overview-card"><p className="overview-card__label">Positive returns</p><p className="overview-card__value">{percentageOrLabel(result.global_summary.positive_return_rate)}</p></div>
              <div className="overview-card"><p className="overview-card__label">Average candle range</p><p className="overview-card__value">{percentageOrLabel(result.global_summary.mean_candle_range_pct)}</p></div>
            </div>
            {BUCKET_OPTIONS.filter((option) => bucketTypes.includes(option.value)).map((option) => (
              <section key={option.value}>
                <h3 className="section-subtitle">{option.label}</h3>
                <div className="data-list">
                  {result.buckets.filter((bucket) => bucket.dimension === option.value).map((bucket) => (
                    <div className="data-row" key={`${bucket.dimension}-${bucket.bucket_key}`}>
                      <dt className="data-row__label">
                        {bucket.bucket_label} · n={bucket.observation_count} · {bucket.sample_status.replace(/_/g, " ")}
                      </dt>
                      <dd className="data-row__value">
                        Mean {percentageOrLabel(bucket.mean_return)} · Median {percentageOrLabel(bucket.median_return)} · Positive {percentageOrLabel(bucket.positive_return_rate)} · Volatility {percentageOrLabel(bucket.realized_volatility)} · Mean range {percentageOrLabel(bucket.mean_candle_range_pct)} · Δ vs global {percentageOrLabel(bucket.difference_from_global_mean)} · 95% interval {percentageOrLabel(bucket.mean_return_interval_95_lower)} to {percentageOrLabel(bucket.mean_return_interval_95_upper)}
                      </dd>
                    </div>
                  ))}
                </div>
              </section>
            ))}
            <p className="muted small">Methodology: {String(result.methodology.return_definition)} {String(result.methodology.realized_volatility)}</p>
            <p className="muted small">Bootstrap: {String(result.bootstrap.method)} · {result.bootstrap.samples} resamples · block size {result.bootstrap.block_size}. Intervals are descriptive, not significance tests.</p>
            <p className="muted small">Provenance: {String(result.data_provenance.provenance_status ?? "unknown")} · Forecast eligible: no.</p>
            {result.warnings.length ? <><h3 className="section-subtitle">Warnings</h3><ul>{result.warnings.map((item) => <li key={item}>{item}</li>)}</ul></> : null}
            <h3 className="section-subtitle">Limitations</h3>
            <ul>{result.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
          </section>
        ) : !running ? (
          <EmptyState title="No seasonality analysis yet" message="Select a historical provider and calendar dimensions, then run a bounded descriptive analysis." />
        ) : null}
      </div>
    </Panel>
  );
}
