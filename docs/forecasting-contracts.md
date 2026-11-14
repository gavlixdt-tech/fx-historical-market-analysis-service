# Forecasting contract decisions (eligibility, feature configuration, calibration)

## Eligibility rules

`ForecastingProblemSpec.eligibility_rules` is a list of string rules. Empty list
preserves all observations, as before.

Supported rule type:

- `exclude_index:<zero-based observation index>` (aliases: `<index>`,
  `exclude:<index>`, `exclude_reference_index:<index>`)

Semantics:

- The rule excludes the observation at the given zero-based index in the
  supplied observation sequence from label generation.
- The excluded reference observation receives `status="excluded"` and
  `reason="excluded by documented eligibility rule"`.
- Exclusion is by reference index only. It does not change
  `prediction_horizon`, does not move a label onto a different timestamp, and
  does not use any future observation.
- Multiple rules may overlap; duplicates are collapsed.
- Missing, invalid, or future-horizon-incomplete observations keep their
  existing statuses unless explicitly excluded.
- Bounds are validated against the supplied observation count. Out-of-range
  indices fail deterministically.

Unsupported or malformed rules fail during problem validation and, when bounds
are involved, during label generation.

## `max_features`

`max_features` is an upper bound on the number of point-in-time features used by
models. The service currently constructs a fixed, ordered feature set of 11
features. Therefore:

- values greater than 11 use all 11 features;
- values from 1 to 11 use the first N features in the declared order
  (`FORECAST_FEATURE_NAMES`);
- invalid values outside 1..256 are rejected.

The effective feature set is recorded in experiment `effective_config`,
dataset manifests, and feature-spec responses.

## Calibration

Probability calibration is supported for classification experiments through
multiclass temperature scaling. It is not supported for regression targets;
`calibration=true` on a regression problem is rejected during validation.

When calibration is enabled:

- The chronological validation segment is reserved exclusively for calibration
  and is not used for hyperparameter selection. Ridge logistic uses its declared
  default regularization value in this mode.
- The model and preprocessing pipeline are fitted on the earlier training
  segment only.
- Validation rows are eligible for calibration only when their target outcomes
  have matured strictly before the first test timestamp. Immature validation
  labels are excluded from calibrator fitting.
- The calibrator is fitted on validation probabilities and labels only, then
  applied to test probabilities. Test targets are never passed to the fitting
  routine.
- The default minimum is 10 mature calibration observations per fold and can
  be configured with `calibration_min_samples`.
- The service records the fitted temperature, calibration sample count and
  time range, maximum label-maturity timestamp, test-start timestamp and an
  explicit maturity-order assertion in each fold result.
- Calibration may be unavailable in a fold when the sample is too small or the
  training/calibration segment does not contain all direction classes. The
  response reports the reason; it does not silently claim calibration succeeded.
- The majority-class baseline has no per-observation probability output and is
  marked not applicable.

Classification metrics report multiclass Brier score, log loss and
top-label expected calibration error. Calibration is evaluated on the held-out
test segment; these metrics do not imply predictive value or trading readiness.

## Historical replay context feature cap

The base point-in-time forecasting catalog contains 11 ordered features.
Historical replay may append optional session-context and liquidity-lifecycle
features when those records are supplied and available at the replay decision
time. These optional context features are subject to the same total
`max_features` upper bound: the replay uses base features first, then appends
context features in the declared order until the cap is reached. Missing or
late context values remain unavailable and are handled by the existing replay
preprocessor. The replay response records the effective feature names and
reproducibility configuration. This does not change the 11-feature base
forecasting dataset contract.
