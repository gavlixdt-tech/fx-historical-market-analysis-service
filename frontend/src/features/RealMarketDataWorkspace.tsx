import { useEffect, useState, type FormEvent } from "react";

import { api, ApiError } from "@/services/api";
import type {
  DataSourceResponseData,
  HistoricalDatasetResponseData,
  HistoricalProviderInventory,
  ResearchReadinessResponseData,
  ExperimentRunResponseData,
} from "@/schemas/api";
import { EmptyState } from "@/components/EmptyState";
import { ErrorNotice } from "@/components/ErrorNotice";
import { LoadingState } from "@/components/LoadingState";
import { Panel } from "@/components/Panel";
import { DatasetQualityProvenance } from "@/features/DatasetQualityProvenance";
export function RealMarketDataWorkspace() {
  const [dataSource, setDataSource] = useState<DataSourceResponseData | null>(null);
  const [dataSourceLoading, setDataSourceLoading] = useState(false);
  const [dataSourceError, setDataSourceError] = useState<ApiError | null>(null);

  const [providerInventory, setProviderInventory] = useState<HistoricalProviderInventory | null>(null);
  const [providerInventoryLoading, setProviderInventoryLoading] = useState(false);
  const [providerInventoryError, setProviderInventoryError] = useState<ApiError | null>(null);
  const [providerId, setProviderId] = useState("");

  const [instrument, setInstrument] = useState("EUR/USD");
  const [timeframe, setTimeframe] = useState("D1");
  const [priceBasis, setPriceBasis] = useState("bid");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [limit, setLimit] = useState("500");

  const [retrieving, setRetrieving] = useState(false);
  const [retrieveError, setRetrieveError] = useState<ApiError | null>(null);
  const [dataset, setDataset] = useState<HistoricalDatasetResponseData | null>(null);

  const [readinessLoading, setReadinessLoading] = useState(false);
  const [readinessError, setReadinessError] = useState<ApiError | null>(null);
  const [readiness, setReadiness] = useState<ResearchReadinessResponseData | null>(null);

  const [experimentLoading, setExperimentLoading] = useState(false);
  const [experimentError, setExperimentError] = useState<ApiError | null>(null);
  const [experiment, setExperiment] = useState<ExperimentRunResponseData | null>(null);

  useEffect(() => {
    void refreshDataSource();
    void refreshProviderInventory();
  }, []);

  async function refreshDataSource() {
    setDataSourceLoading(true);
    setDataSourceError(null);
    try {
      const data = await api.getDataSource();
      setDataSource(data);
    } catch (caught) {
      setDataSourceError(
        caught instanceof ApiError
          ? caught
          : new ApiError("Unable to load data source status.", 0, "UNEXPECTED", null),
      );
    } finally {
      setDataSourceLoading(false);
    }
  }

  async function refreshProviderInventory() {
    setProviderInventoryLoading(true);
    setProviderInventoryError(null);
    try {
      const data = await api.listHistoricalProviders();
      setProviderInventory(data);
    } catch (caught) {
      setProviderInventoryError(
        caught instanceof ApiError
          ? caught
          : new ApiError("Unable to load provider inventory.", 0, "UNEXPECTED", null),
      );
    } finally {
      setProviderInventoryLoading(false);
    }
  }

  function validateForm(): string | null {
    if (!providerId) return "Select a historical provider explicitly.";
    if (!instrument.trim()) return "Instrument is required.";
    const numericLimit = Number(limit);
    if (!Number.isFinite(numericLimit) || numericLimit < 1 || numericLimit > 5000) {
      return "Limit must be between 1 and 5000.";
    }
    if (start && end && new Date(start) > new Date(end)) {
      return "Start date must be before end date.";
    }
    return null;
  }

async function handleRetrieve(event: FormEvent) {
    event.preventDefault();
    const validationError = validateForm();
    if (validationError) {
      setRetrieveError(
        new ApiError(validationError, 0, "VALIDATION_ERROR", null),
      );
      return;
    }
    setRetrieving(true);
    setRetrieveError(null);
    setDataset(null);
    setReadiness(null);
    setExperiment(null);
    try {
      const data = await api.retrieveHistoricalDataset({
        provider_id: providerId,
        instrument: instrument.trim(),
        timeframe,
        start: start ? new Date(start).toISOString() : null,
        end: end ? new Date(end).toISOString() : null,
        price_basis: priceBasis,
        limit: Number(limit),
      });
      setDataset(data);
    } catch (caught) {
      setRetrieveError(
        caught instanceof ApiError
          ? caught
          : new ApiError("Historical data retrieval failed.", 0, "UNEXPECTED", null),
      );
    } finally {
      setRetrieving(false);
    }
  }

  async function handleReadiness() {
    if (!dataset) return;
    setReadinessLoading(true);
    setReadinessError(null);
    setReadiness(null);
    const problem = {
      problem_id: "real_market_research",
      version: "1.0.0",
      instrument_scope: [dataset.instrument],
      input_timeframe: dataset.timeframe,
      price_basis: dataset.price_basis,
      feature_availability_policy: "point_in_time",
      prediction_reference: "observation_close",
      prediction_horizon: 1,
      target_type: "future_return",
      target_units: "fraction",
      eligibility_rules: [],
      label_generation_method: "exact_future_observation",
      missing_observation_policy: "drop_row",
      required_historical_coverage: 20,
      evaluation_protocol: "chronological_holdout",
      known_limitations: [],
      neutral_threshold: null,
      volatility_window: null,
      max_features: 64,
    };
    try {
      const data = await api.assessResearchReadiness({
        instrument: dataset.instrument,
        timeframe: dataset.timeframe,
        start:
          typeof dataset.provenance.requested_start === "string"
            ? dataset.provenance.requested_start
            : null,
        end:
          typeof dataset.provenance.requested_end === "string"
            ? dataset.provenance.requested_end
            : null,
        price_basis: dataset.price_basis,
        provider_id: dataset.provider_id,
        limit: dataset.observations.length,
        problem,
      });
      setReadiness(data);
    } catch (caught) {
      setReadinessError(
        caught instanceof ApiError
          ? caught
          : new ApiError("Research readiness check failed.", 0, "UNEXPECTED", null),
      );
    } finally {
      setReadinessLoading(false);
    }
  }

  async function handleRunExperiment() {
    if (!dataset || !readiness?.ready) return;
    setExperimentLoading(true);
    setExperimentError(null);
    setExperiment(null);
    const problem = {
      problem_id: "real_market_research",
      version: "1.0.0",
      instrument_scope: [dataset.instrument],
      input_timeframe: dataset.timeframe,
      price_basis: dataset.price_basis,
      feature_availability_policy: "point_in_time",
      prediction_reference: "observation_close",
      prediction_horizon: 1,
      target_type: "future_return",
      target_units: "fraction",
      eligibility_rules: [],
      label_generation_method: "exact_future_observation",
      missing_observation_policy: "drop_row",
      required_historical_coverage: 20,
      evaluation_protocol: "chronological_holdout",
      known_limitations: [],
      neutral_threshold: null,
      volatility_window: null,
      max_features: 64,
    };
    const body = {
      observations: dataset.observations,
      instrument: dataset.instrument,
      timeframe: dataset.timeframe,
      price_basis: dataset.price_basis,
      provider_id: dataset.provider_id,
      data_source: "upstream_historical",
      synthetic: dataset.synthetic,
      problem,
      lookback: 20,
      n_folds: 3,
      min_train_samples: 30,
      purge: true,
      embargo_periods: 1,
      model_families: ["ridge_regression", "random_forest"],
      random_seed: 42,
      calibration: false,
    };
    try {
      const data = await api.runExperiment(body);
      setExperiment(data);
    } catch (caught) {
      setExperimentError(
        caught instanceof ApiError
          ? caught
          : new ApiError("Experiment execution failed.", 0, "UNEXPECTED", null),
      );
    } finally {
      setExperimentLoading(false);
    }
  }

  const connectivity = dataSource?.connectivity;
  const configuration = dataSource?.configuration ?? {};
  const selectedProvider = providerInventory?.providers.find(
    (provider) => provider.provider_id === providerId,
  );

  return (
    <Panel
      title="Real Market Data Research"
      subtitle="Backend-mediated historical data and exploratory research, with provider and provenance limitations shown explicitly."
    >
      <section>
        <h3 className="section-subtitle">Data source status</h3>
        <button
          type="button"
          className="button"
          onClick={() => void refreshDataSource()}
          disabled={dataSourceLoading}
          data-testid="refresh-data-source"
        >
          {dataSourceLoading ? "Checking..." : "Refresh status"}
        </button>
        <button
          type="button"
          className="button"
          onClick={() => void refreshProviderInventory()}
          disabled={providerInventoryLoading}
          data-testid="refresh-provider-inventory"
        >
          {providerInventoryLoading ? "Loading providers..." : "Refresh providers"}
        </button>
        {dataSourceLoading && !dataSource ? <LoadingState label="Loading data source status..." /> : null}
        {dataSourceError ? (
          <ErrorNotice
            title="Data source status failed"
            message={dataSourceError.message}
            code={dataSourceError.code}
            requestId={dataSourceError.requestId}
            testId="data-source-error"
          />
        ) : null}
        {dataSource ? (
          <dl className="data-list">
            <dt className="data-row__label">State</dt>
            <dd className="data-row__value" data-testid="data-source-state">
              {String(connectivity?.state ?? "unknown")}
            </dd>
            <dt className="data-row__label">Message</dt>
            <dd className="data-row__value">{String(connectivity?.message ?? "No message")}</dd>
            <dt className="data-row__label">Contract status</dt>
            <dd className="data-row__value">{dataSource.contract_status}</dd>
            <dt className="data-row__label">Authentication</dt>
            <dd className="data-row__value">
              {String(connectivity?.authentication_status ?? "unverified")}
            </dd>
            <dt className="data-row__label">Real provider</dt>
            <dd className="data-row__value">
              {String(connectivity?.provider_status ?? "not_checked")}
            </dd>
            <dt className="data-row__label">Last provider test (UTC)</dt>
            <dd className="data-row__value">
              {String(connectivity?.provider_tested_at ?? "Not verified")}
            </dd>
            <dt className="data-row__label">Base URL configured</dt>
            <dd className="data-row__value">
              {configuration.base_url_configured ? "Yes" : "No"}
            </dd>
            <dt className="data-row__label">Credential configured</dt>
            <dd className="data-row__value">
              {configuration.credential_configured ? "Yes" : "No"}
            </dd>
          </dl>
        ) : null}
        {!dataSourceLoading && !dataSource && !dataSourceError ? (
          <EmptyState title="No data source status" message="Refresh to load backend-reported status." />
        ) : null}
        {providerInventoryError ? (
          <ErrorNotice
            title="Provider inventory unavailable"
            message={providerInventoryError.message}
            code={providerInventoryError.code}
            requestId={providerInventoryError.requestId}
            testId="provider-inventory-error"
          />
        ) : null}
        {providerInventory ? (
          <p data-testid="provider-inventory-status">
            Provider inventory: {providerInventory.status}. A real provider remains
            provider-asserted; source entitlement and historical publication time are
            not independently verified.
          </p>
        ) : null}
      </section>

      <section>
        <h3 className="section-subtitle">Historical data request</h3>
        <form onSubmit={handleRetrieve}>
          <label>
            Provider
            <select
              value={providerId}
              onChange={(event) => setProviderId(event.currentTarget.value)}
              data-testid="historical-provider"
              required
            >
              <option value="">Select a provider</option>
              {(providerInventory?.providers ?? [])
                .filter(
                  (provider) =>
                    provider.historical_candles_supported && provider.configured,
                )
                .map((provider) => (
                  <option key={provider.provider_id} value={provider.provider_id}>
                    {provider.provider_id} ({provider.provider_type}
                    {provider.provider_type === "test" ? " fixture" : ""})
                  </option>
                ))}
            </select>
          </label>
          <label>
            Instrument
            <select
              value={instrument}
              onChange={(e) => setInstrument(e.currentTarget.value)}
              data-testid="historical-instrument"
            >
              {[
                "XAU/USD",
                "EUR/USD",
                "GBP/USD",
                "USD/JPY",
                "USD/CHF",
                "USD/CAD",
                "AUD/USD",
                "NZD/USD",
              ].map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
          </label>
          <label>
            Timeframe
            <select
              value={timeframe}
              onChange={(e) => setTimeframe(e.currentTarget.value)}
              data-testid="historical-timeframe"
            >
              {["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"].map(
                (value) => <option key={value} value={value}>{value}</option>,
              )}
            </select>
          </label>
          <label>
            Price basis
            <select
              value={priceBasis}
              onChange={(e) => setPriceBasis(e.currentTarget.value)}
              data-testid="historical-price-basis"
            >
              {["bid", "ask", "midpoint"].map(
                (value) => <option key={value} value={value}>{value}</option>,
              )}
            </select>
          </label>
          {selectedProvider?.provider_type === "test" ? (
            <p className="muted" data-testid="selected-provider-fixture-warning">
              This explicit test provider returns synthetic fixture data and cannot
              support real-market research.
            </p>
          ) : null}
          {selectedProvider?.provider_type === "real" ? (
            <p className="muted" data-testid="selected-provider-real-limitations">
              Provider selection and connection testing do not prove source entitlement,
              independently authenticated observations, or historical availability.
            </p>
          ) : null}
          <label>
            Start
            <input
              type="datetime-local"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              data-testid="historical-start"
            />
          </label>
          <label>
            End
            <input
              type="datetime-local"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
              data-testid="historical-end"
            />
          </label>
          <label>
            Limit
            <input
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
              data-testid="historical-limit"
            />
          </label>
          <button
            type="submit"
            className="button"
            disabled={retrieving || providerInventoryLoading || !selectedProvider}
            data-testid="retrieve-historical-data"
          >
            {retrieving ? "Retrieving..." : "Retrieve historical data"}
          </button>
        </form>
        {retrieveError ? (
          <ErrorNotice
            title="Historical data retrieval failed"
            message={retrieveError.message}
            code={retrieveError.code}
            requestId={retrieveError.requestId}
            testId="historical-retrieve-error"
          />
        ) : null}
        {retrieving ? <LoadingState label="Retrieving historical dataset..." /> : null}
      </section>

      {dataset ? (
        <DatasetQualityProvenance dataset={dataset} />
        <section>
          <p className="muted">
            Experiments submitted from this workspace receive caller-supplied observations.
            Their provider, original availability time, and source-record lineage are not
            independently verified by the experiment endpoint.
          </p>
          <button
            type="button"
            className="button"
            onClick={() => void handleReadiness()}
            disabled={readinessLoading}
            data-testid="check-readiness"
          >
            {readinessLoading ? "Checking..." : "Validate research readiness"}
          </button>
        </section>
      ) : null}

      {readinessError ? (
        <ErrorNotice
          title="Research readiness failed"
          message={readinessError.message}
          code={readinessError.code}
          requestId={readinessError.requestId}
          testId="readiness-error"
        />
      ) : null}
      {readinessLoading ? <LoadingState label="Validating research readiness..." /> : null}
      {readiness ? (
        <section>
          <h3 className="section-subtitle">Research readiness</h3>
          <p data-testid="readiness-ready">Ready: {readiness.ready ? "Yes" : "No"}</p>
          {readiness.findings.length > 0 ? (
            <ul>
              {readiness.findings.map((finding, index) => (
                <li key={index}>
                  [{String(finding.severity ?? "info")}] {String(finding.message ?? "")}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No readiness findings.</p>
          )}
          <button
            type="button"
            className="button"
            onClick={() => void handleRunExperiment()}
            disabled={!readiness.ready || experimentLoading}
            data-testid="run-real-experiment"
          >
            {experimentLoading ? "Running..." : "Run forecasting experiment"}
          </button>
        </section>
      ) : null}

      {experimentError ? (
        <ErrorNotice
          title="Experiment execution failed"
          message={experimentError.message}
          code={experimentError.code}
          requestId={experimentError.requestId}
          testId="experiment-error"
        />
      ) : null}
      {experimentLoading ? <LoadingState label="Running experiment..." /> : null}
      {experiment ? (
        <section>
          <h3 className="section-subtitle">Experiment results</h3>
          <p data-testid="experiment-status">
            {experiment.experiment_id} - {experiment.status} - {experiment.n_observations} obs /{" "}
            {experiment.n_folds} folds
          </p>
          <p data-testid="experiment-provenance">
            Data source: {experiment.data_source ?? "unknown"}; synthetic:{" "}
            {experiment.synthetic === null || experiment.synthetic === undefined
              ? "unknown"
              : experiment.synthetic
                ? "Yes"
                : "No"}
            ; provenance: {String(experiment.data_provenance?.provenance_status ?? "unknown")}
          </p>
          <table>
            <thead>
              <tr>
                <th>Model</th>
                <th>Metric</th>
                <th>Baseline</th>
                <th>Improvement</th>
              </tr>
            </thead>
            <tbody>
              {experiment.comparison.map((row, index) => (
                <tr key={index}>
                  <td>{String(row.model_family ?? "")}</td>
                  <td>{Number(row.aggregate_primary_metric ?? 0).toFixed(4)}</td>
                  <td>{Number(row.baseline_aggregate_primary ?? 0).toFixed(4)}</td>
                  <td>{Number(row.improvement_vs_baseline ?? 0).toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {experiment.warnings.length > 0 ? (
            <ul>
              {experiment.warnings.map((warning, index) => (
                <li key={index}>{warning}</li>
              ))}
            </ul>
          ) : null}
          {experiment.limitations.length > 0 ? (
            <ul>
              {experiment.limitations.map((limitation, index) => (
                <li key={index}>{limitation}</li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}
    </Panel>
  );
}
