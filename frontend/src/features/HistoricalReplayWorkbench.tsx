import { useState, type ChangeEvent, type FormEvent } from "react";

import { Panel } from "@/components/Panel";
import {
  api,
  type HistoricalReplayResponseData,
} from "@/services/api";
import {
  ReplayObservationSchema,
  type ReplayObservation,
} from "@/schemas/api";

const MINIMUM_OBSERVATIONS = 52;
const MAXIMUM_OBSERVATIONS = 2000;
const MAXIMUM_UPLOAD_BYTES = 900_000;

export function HistoricalReplayWorkbench() {
  const [observations, setObservations] = useState<ReplayObservation[]>([]);
  const [fileName, setFileName] = useState("");
  const [instrument, setInstrument] = useState("EURUSD");
  const [timeframe, setTimeframe] = useState("D1");
  const [sourceDatasetId, setSourceDatasetId] = useState("");
  const [targetType, setTargetType] = useState<"future_return" | "direction">(
    "future_return",
  );
  const [modelFamily, setModelFamily] = useState("ridge_regression");
  const [result, setResult] = useState<HistoricalReplayResponseData | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function loadFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    setError(null);
    setResult(null);
    if (!file) return;
    try {
      if (file.size > MAXIMUM_UPLOAD_BYTES) {
        throw new Error("Replay file exceeds 900 KB. Split the data into smaller chronological datasets before upload.");
      }
      const parsed: unknown = JSON.parse(await file.text());
      const rows = ReplayObservationSchema.array()
        .min(MINIMUM_OBSERVATIONS)
        .max(MAXIMUM_OBSERVATIONS)
        .parse(parsed);
      setObservations(rows);
      setFileName(file.name);
    } catch (caught) {
      setObservations([]);
      setFileName("");
      setError(
        caught instanceof Error
          ? `Could not load a valid replay dataset: ${caught.message}`
          : "Could not load a valid replay dataset.",
      );
    }
  }

  async function runReplay(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await api.runHistoricalReplay({
        instrument,
        timeframe,
        price_basis: "close",
        source_dataset_id: sourceDatasetId,
        synthetic: false,
        observations,
        problem: {
          problem_id: `historical-replay-${instrument.toLowerCase()}`,
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
        },
        lookback: 20,
        min_train_samples: 30,
        validation_mode: "expanding",
        embargo_periods: 0,
        model_families: [modelFamily],
        random_seed: 42,
      });
      setResult(data);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Replay failed.");
    } finally {
      setLoading(false);
    }
  }

  const selectedModel = result?.models.find(
    (model) => model.model_family === modelFamily,
  );
  const metric = selectedModel?.out_of_sample_metrics;

  return (
    <Panel
      title="Historical Replay & Robustness"
      subtitle="Chronological point-in-time research replay. No trade simulation or broker dependency."
    >
      <div data-testid="historical-replay-workbench">
        <p className="muted">
          Upload actual observations with the time each record became
          available. The engine does not create sample market data. Submitted
          source identity and availability timestamps are recorded but cannot
          be independently verified here.
        </p>
        <form className="replay-form" onSubmit={runReplay}>
          <label>
            Historical replay JSON
            <input
              type="file"
              accept=".json,application/json"
              onChange={loadFile}
              data-testid="replay-file"
            />
          </label>
          <p className="muted" data-testid="replay-file-status">
            {fileName
              ? `${fileName}: ${observations.length} records loaded`
              : `Provide ${MINIMUM_OBSERVATIONS}-${MAXIMUM_OBSERVATIONS} actual records.`}
          </p>
          <div className="replay-form__grid">
            <label>
              Instrument
              <input
                required
                minLength={3}
                maxLength={20}
                value={instrument}
                onChange={(event) => setInstrument(event.currentTarget.value)}
              />
            </label>
            <label>
              Timeframe
              <select
                value={timeframe}
                onChange={(event) => setTimeframe(event.currentTarget.value)}
              >
                {["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"].map(
                  (value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ),
                )}
              </select>
            </label>
            <label>
              Source dataset ID
              <input
                required
                value={sourceDatasetId}
                onChange={(event) =>
                  setSourceDatasetId(event.currentTarget.value)
                }
              />
            </label>
            <label>
              Prediction target
              <select
                value={targetType}
                onChange={(event) => {
                  const nextTarget =
                    event.currentTarget.value === "direction"
                      ? "direction"
                      : "future_return";
                  setTargetType(nextTarget);
                  setModelFamily(
                    nextTarget === "direction"
                      ? "ridge_logistic"
                      : "ridge_regression",
                  );
                }}
              >
                <option value="future_return">Next-period return</option>
                <option value="direction">Next-period direction</option>
              </select>
            </label>
            <label>
              Research model
              <select
                value={modelFamily}
                onChange={(event) => setModelFamily(event.currentTarget.value)}
              >
                {(targetType === "direction"
                  ? ["ridge_logistic", "random_forest", "histogram_gradient_boosting"]
                  : [
                      "ridge_regression",
                      "random_forest",
                      "histogram_gradient_boosting",
                    ]
                ).map((value) => (
                  <option key={value} value={value}>
                    {value.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <button
            className="button"
            type="submit"
            disabled={
              loading ||
              observations.length < MINIMUM_OBSERVATIONS ||
              sourceDatasetId.trim().length === 0
            }
            data-testid="run-historical-replay"
          >
            {loading ? "Replaying chronologically..." : "Run historical replay"}
          </button>
        </form>

        {error ? (
          <p className="error" role="alert" data-testid="replay-error">
            {error}
          </p>
        ) : null}
        {result ? (
          <section className="replay-result" data-testid="replay-result">
            <h3>Replay report</h3>
            <p>
              {result.replay_id} · {result.instrument} {result.timeframe} ·{" "}
              {result.n_predictions} out-of-sample predictions
            </p>
            <p>
              Provenance: {result.provenance_status}; dataset fingerprint:{" "}
              <code>{result.dataset_fingerprint}</code>
            </p>
            <p data-testid="replay-primary-metrics">
              Primary metrics: {JSON.stringify(metric ?? {})}
            </p>
            <h4>Point-in-time session and liquidity context</h4>
            <p className="muted small">
              Context is caller-supplied and remains unverified. Each field is only eligible at forecast origins where its own available_at is no later than the information cutoff.
            </p>
            <pre data-testid="replay-market-context">
              {JSON.stringify(
                result.predictions.slice(0, 25).map((prediction) => ({
                  reference_timestamp: prediction.reference_timestamp,
                  information_cutoff: prediction.information_cutoff,
                  market_context: prediction.market_context ?? {
                    status: "not supplied in this replay response",
                  },
                })),
                null,
                2,
              )}
            </pre>
            <h4>Robustness diagnostics</h4>
            <pre>{JSON.stringify(result.robustness, null, 2)}</pre>
            <h4>Limitations</h4>
            <ul>
              {result.limitations.map((limitation) => (
                <li key={limitation}>{limitation}</li>
              ))}
            </ul>
            {result.warnings.length > 0 ? (
              <>
                <h4>Warnings</h4>
                <ul>
                  {result.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </>
            ) : null}
          </section>
        ) : null}
      </div>
    </Panel>
  );
}
