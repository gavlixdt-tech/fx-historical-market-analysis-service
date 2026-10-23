import { useEffect, useState } from "react";

import { api } from "@/services/api";
import type { ExperimentRunResponseData } from "@/schemas/api";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";

interface ModelFamily {
  name: string;
  tier: number;
  task_types: string[];
  description: string;
}

interface ComparisonRow {
  model_family: string;
  aggregate_primary_metric: number;
  baseline_name: string;
  baseline_aggregate_primary: number;
  improvement_vs_baseline: number;
}

export function ForecastingReadiness() {
  const [families, setFamilies] = useState<ModelFamily[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ExperimentRunResponseData | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .listModelFamilies()
      .then((items) => {
        if (cancelled) return;
        setFamilies(items as unknown as ModelFamily[]);
      })
      .catch(() => {
        if (!cancelled) setError("Unable to load model families.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function runDemo() {
    setLoading(true);
    setError(null);
    setResult(null);
    const observations = Array.from({ length: 120 }, (_, i) => {
      const close = 1.0 + 0.001 * i + Math.sin(i / 5) * 0.01;
      return {
        timestamp: new Date(Date.UTC(2024, 0, 1 + i)).toISOString(),
        open: close,
        high: close + 0.005,
        low: close - 0.005,
        close,
        volume: 1000,
      };
    });
    const problem = {
      problem_id: "demo_fx",
      version: "1.0.0",
      instrument_scope: ["EURUSD"],
      input_timeframe: "D1",
      price_basis: "close",
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
      known_limitations: ["Synthetic demo data - not predictive evidence."],
      neutral_threshold: null,
      volatility_window: null,
      max_features: 64,
    };
    const body = {
      observations,
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
      setResult(data);
    } catch (caught) {
      const message =
        caught instanceof Error ? caught.message : "Experiment failed.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  const comparison = (result?.comparison ?? []) as unknown as ComparisonRow[];

  return (
    <Panel
      title="AI Forecast Research & Evaluation"
      subtitle="Historical model benchmarking only. No live prediction or trading."
    >
      <div data-testid="forecast-research-workspace">
        <p className="muted">
          Synthetic demo data is used only for UI demonstration and is not
          predictive evidence.
        </p>
        <div className="capability-list">
          {families.map((f) => (
            <div key={f.name} className="capability-list__item">
              <div className="capability-list__head">
                <span className="capability-list__name">{f.name}</span>
                <StatusBadge tone="ok" label={`tier ${f.tier}`} />
              </div>
              <p className="capability-list__detail">{f.description}</p>
            </div>
          ))}
        </div>
        <button
          type="button"
          className="button"
          onClick={runDemo}
          disabled={loading}
          data-testid="run-experiment"
        >
          {loading ? "Running..." : "Run synthetic demo experiment"}
        </button>
        {error && <p className="error">{error}</p>}
        {result && (
          <div data-testid="experiment-result">
            <p>
              {result.experiment_id} - {result.status} - {result.n_observations}{" "}
              obs / {result.n_folds} folds
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
                {comparison.map((c) => (
                  <tr key={c.model_family}>
                    <td>{c.model_family}</td>
                    <td>{c.aggregate_primary_metric.toFixed(4)}</td>
                    <td>{c.baseline_aggregate_primary.toFixed(4)}</td>
                    <td>{c.improvement_vs_baseline.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {result.warnings.length > 0 && (
              <ul>
                {result.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            )}
            {result.limitations.length > 0 && (
              <ul>
                {result.limitations.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </Panel>
  );
}
