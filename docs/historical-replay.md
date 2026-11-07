# Historical Replay and Predictive Robustness

## Purpose and endpoint

`POST /api/v1/historical-replay/run` performs a reconstructed, research-only
rolling-origin replay. At each prediction origin it fits the selected
forecasting model using only training labels whose complete outcome was
available before that origin, then scores the forecast after its target
observation becomes available. The primary evidence is chronological and
separate from any trading or execution simulation.

`POST /api/v1/historical-replay/run-from-market-data` accepts an instrument,
provider, time range, source dataset ID, price basis, forecasting problem, and
replay settings, then fetches the candles from Service 1. It only accepts a
configured real provider with an available connection and historical-candle
capability; test providers, incomplete coverage, rejected/duplicate bars,
truncated responses, and candles with incomplete OHLC or missing close times
are rejected. This is a bounded historical fetch per request, not a streaming
or continuously updated live-prediction endpoint.

Service 1's current candle contract has `open_time`, `close_time`, and
`retrieved_at`, but no original historical publication timestamp. Therefore
the provider-sourced replay requires `UPSTREAM_REPLAY_AVAILABILITY_DELAY_SECONDS`
to be explicitly configured and derives `available_at` as
`close_time + configured delay`. The delay is included in reproducibility
metadata, and the response always marks its status as
`provider_asserted_unverified`. This is an assumption, not verified historical
availability; it cannot establish that the replay had access only to the
information that was actually published at each historical decision time.

The caller-supplied endpoint does not generate market observations, submit
orders, or call other GFX services. Records must include:

```json
{
  "timestamp": "2024-01-02T00:00:00Z",
  "available_at": "2024-01-02T00:02:00Z",
  "open": 1.095,
  "high": 1.097,
  "low": 1.094,
  "close": 1.096,
  "volume": null,
  "source_record_id": "provider-record-123"
}
```

`timestamp` is the observation time; `available_at` is when that exact record
was knowable to a prediction. Both must be timezone-aware. Records must be in
strictly increasing observation-time order and nondecreasing availability
order. Duplicate bars, impossible OHLC values, and availability before the
observation are rejected. Datasets are bounded to 40–2,000 records, and the
request must include enough history for its lookback, training minimum, target
horizon, and embargo. With the workbench defaults, that minimum is 52.

The request also requires an instrument, timeframe, source dataset ID, and
validated forecasting problem. Synthetic data is restricted to
development/testing; the production configuration rejects an explicitly
synthetic replay. Responses label synthetic fixtures and warn against
predictive use. There is no synthetic demo data in the workbench.

## Evaluation protocol

- **Rolling origin:** a forecast is generated at each eligible observation
  using the information cutoff in its `available_at`.
- **Expanding or rolling training history:** expanding is the default;
  rolling mode requires an explicit training-window size.
- **Purging:** a training sample is eligible only when its target's
  `future_index` precedes the current origin and the target record's
  `available_at` is no later than the origin cutoff.
- **Embargo:** an optional number of the most recent otherwise-eligible
  training samples are omitted.
- **Feature construction:** the existing point-in-time feature builder uses
  only the current and preceding observations. Its imputation and
  standardisation are fitted separately on each origin's training sample.
- **Baselines:** zero-return, majority-class, or mean-volatility baseline is
  reported alongside the requested model family.
- **Calibration:** classification forecasts receive out-of-sample, class-wise
  Brier and reliability-bin diagnostics. They are descriptive and are not a
  calibration artifact or probability approval.
- **Regimes:** a transparent 20-observation return/volatility heuristic is
  evaluated using only data available at the origin. These are not outputs
  from the market-regime service and are not calibrated.
- **Selection diagnostics:** a moving-block-bootstrap White's Reality Check
  approximation and a supplementary CSCV Probability of Backtest Overfitting
  diagnostic are reported where sample and model counts permit. They do not
  replace chronological evaluation.

`final_holdout_start` freezes training to labels whose target observations
were available at or before that cutoff, with both training references and
target timestamps strictly before it. This prevents the replay from adapting
the model to outcomes inside the declared holdout and excludes training labels
whose availability was delayed past the cutoff. The response separately
reports pre-holdout model-selection metrics and holds out the final segment
from bootstrap/PBO selection diagnostics. Since the same response returns
holdout outcomes and repeated requests are not restricted, the endpoint still
cannot prove that the declared segment was untouched by the operator.

## Reproducibility and provenance

The report includes a SHA-256 dataset fingerprint over source record IDs,
timestamps, availability timestamps, OHLCV values, and the forecasting
problem. It also records algorithm/feature versions, seed, validation mode,
training-window settings, embargo, model families, and fixed model
hyperparameters. Individual predictions include their information cutoff,
training sample count, target timestamp, target availability, forecast, and
realized target, including a distinct frozen training cutoff for the declared
holdout.

Results and model artifacts are not persisted. Source dataset identity and
availability timestamps are caller assertions; this service does not verify
upstream source signatures, historical revisions, or original model artifacts.
The output is a model-class replay performed now, not a reconstruction of a
forecast that the production platform actually emitted at that historical
time.

## Explicit scope limits

- No live capital, broker intelligence, execution, or transaction costs.
- No historical service-output ingestion or cross-service model ablation.
- No durable experiment registry or immutable artifact store.
- No proof of a genuinely untouched future period, model superiority,
  profitability, or production readiness.
- The provider-sourced route uses assumed publication lag because the producer
  contract has no historical first-available timestamp.
- The replay does not claim that generic market features represent all
  information available to GFX services.
