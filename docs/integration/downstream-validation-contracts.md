# Downstream forecasting and validation contracts

Service 2 owns historical dataset preparation and its own research
calculations. It does not own statistical forecasting, backtesting, or
independent walk-forward validation.

| Service | Audited capability | Service 2 handoff | Result |
|---|---|---|---|
| 21 `fx-statistical-forecast-service` | Zero-return benchmark exists; fitted statistical model selection and robustness operations are not implemented (`501`) | No dataset handoff; no compatible immutable manifest/availability contract | BLOCKED |
| 49 `fx-backtesting-service` | Evaluates submitted historical forecasts against chronological observations | No dataset-reference or source-lineage handoff | NOT_IMPLEMENTED |
| 50 `fx-walk-forward-validation-service` | Owns expanding/rolling forecast folds and holdout validation | No compatible immutable dataset and selection-cutoff handoff | NOT_IMPLEMENTED |

No Service 2 replay predictions are represented as independent external
forecasts. A future adapter must preserve instrument, timeframe, price basis,
observation and availability timestamps, stable source-record identity,
dataset fingerprint, missing-data policy, and limitations; the downstream
service must retain ownership of its evaluation calculation.

No compatibility should be inferred from similar endpoint names or
documentation. An accepted versioned payload schema and an end-to-end test
are prerequisites to implementation.
