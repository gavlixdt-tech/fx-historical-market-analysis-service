import { useEffect, useState, type FormEvent } from "react";

import { api, ApiError } from "@/services/api";
import type {
  DataSourceResponseData,
  HistoricalDatasetResponseData,
  ResearchReadinessResponseData,
  ExperimentRunResponseData,
} from "@/schemas/api";
import { EmptyState } from "@/components/EmptyState";
import { ErrorNotice } from "@/components/ErrorNotice";
import { LoadingState } from "@/components/LoadingState";
import { Panel } from "@/components/Panel";

export function RealMarketDataWorkspace() {
  const [dataSource, setDataSource] = useState<DataSourceResponseData | null>(null);
  const [dataSourceLoading, setDataSourceLoading] = useState(false);
  const [dataSourceError, setDataSourceError] = useState<ApiError | null>(null);

  const [instrument, setInstrument] = useState("EURUSD");
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

  function validateForm(): string | null {
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
        start: (dataset.provenance.requested_start as string | null) ?? null,
        end: (dataset.provenance.requested_end as string | null) ?? null,
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

  const connectivity = (dataSource?.connectivity ?? {}) as Record<string, unknown>;
  const configuration = (dataSource?.configuration ?? {}) as Record<string, unknown>;

  return (
    <Panel
      title="Real Market Data Research"
      subtitle="Verified backend workflow for historical data, quality, readiness and experiments."
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
              {String(connectivity.state ?? "unknown")}
            </dd>
            <dt className="data-row__label">Message</dt>
            <dd className="data-row__value">{String(connectivity.message ?? "No message")}</dd>
            <dt className="data-row__label">Contract status</dt>
            <dd className="data-row__value">{dataSource.contract_status}</dd>
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
      </section>

      <section>
        <h3 className="section-subtitle">Historical data request</h3>
        <form onSubmit={handleRetrieve}>
          <label>
            Instrument
            <input
              value={instrument}
              onChange={(e) => setInstrument(e.target.value)}
              data-testid="historical-instrument"
            />
          </label>
          <label>
            Timeframe
            <input
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value)}
              data-testid="historical-timeframe"
            />
          </label>
          <label>
            Price basis
            <input
              value={priceBasis}
              onChange={(e) => setPriceBasis(e.target.value)}
              data-testid="historical-price-basis"
            />
          </label>
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
            disabled={retrieving}
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
        <section>
          <h3 className="section-subtitle">Dataset quality and provenance</h3>
          <dl className="data-list">
            <dt className="data-row__label">Data source</dt>
            <dd className="data-row__value" data-testid="dataset-data-source">
              {dataset.data_source}
            </dd>
            <dt className="data-row__label">Synthetic</dt>
            <dd className="data-row__value" data-testid="dataset-synthetic">
              {dataset.synthetic ? "Yes" : "No"}
            </dd>
            <dt className="data-row__label">Instrument</dt>
            <dd className="data-row__value">{dataset.instrument}</dd>
            <dt className="data-row__label">Timeframe</dt>
            <dd className="data-row__value">{dataset.timeframe}</dd>
            <dt className="data-row__label">Price basis</dt>
            <dd className="data-row__value">{dataset.price_basis}</dd>
            <dt className="data-row__label">Provider</dt>
            <dd className="data-row__value">{dataset.provider_id}</dd>
            <dt className="data-row__label">Row count</dt>
            <dd className="data-row__value" data-testid="dataset-row-count">
              {dataset.observations.length}
            </dd>
            <dt className="data-row__label">Partial</dt>
            <dd className="data-row__value">{dataset.partial ? "Yes" : "No"}</dd>
            <dt className="data-row__label">Fingerprint</dt>
            <dd className="data-row__value">
              <code>{dataset.dataset_fingerprint}</code>
            </dd>
          </dl>
          <p className="muted small">Quality findings: {JSON.stringify(dataset.quality)}</p>
          <p className="muted small">Provenance: {JSON.stringify(dataset.provenance)}</p>
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
