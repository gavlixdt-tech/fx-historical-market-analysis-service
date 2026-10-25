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

Calibration is explicitly not implemented in the current evaluation path.
`calibration=true` is rejected deterministically because the existing
walk-forward pipeline has no independent chronological calibration segment:
validation data are already used for model/hyperparameter selection, and test
targets must not be used for fitting. A future implementation should add a
dedicated calibration segment or an out-of-fold procedure that fits calibrators
without using final test targets.