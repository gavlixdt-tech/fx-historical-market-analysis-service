/**
 * Runtime-validated API response schemas.
 *
 * These mirror the backend contracts exactly:
 *   backend/app/schemas/common.py, health.py, status.py, version.py
 *
 * Every response is validated at runtime so that a contract drift between the
 * backend and the dashboard surfaces as an explicit error rather than as
 * silently `undefined` fields in the UI.
 */

import { z } from "zod";

export const ErrorDetailSchema = z.object({
  code: z.string(),
  message: z.string(),
  request_id: z.string().nullable().optional(),
  details: z.record(z.unknown()).nullable().optional(),
});

export type ErrorDetail = z.infer<typeof ErrorDetailSchema>;

export const ResponseMetaSchema = z.object({
  api_version: z.string(),
  request_id: z.string(),
  timestamp_utc: z.string(),
});

export type ResponseMeta = z.infer<typeof ResponseMetaSchema>;

/** Generic envelope: `data` is validated separately per endpoint. */
export const ApiEnvelopeSchema = z.object({
  data: z.unknown().nullable().optional(),
  meta: ResponseMetaSchema,
  errors: z.array(ErrorDetailSchema),
});

export const HealthResponseDataSchema = z.object({
  status: z.string(),
  service: z.string(),
  mode: z.string(),
  check: z.string(),
});

export type HealthResponseData = z.infer<typeof HealthResponseDataSchema>;

export const DependencyHealthSchema = z.object({
  name: z.string(),
  healthy: z.boolean(),
  detail: z.string().nullable().optional(),
});

export type DependencyHealth = z.infer<typeof DependencyHealthSchema>;

export const ReadyResponseDataSchema = HealthResponseDataSchema.extend({
  dependencies: z.array(DependencyHealthSchema),
});

export type ReadyResponseData = z.infer<typeof ReadyResponseDataSchema>;

export const VersionResponseDataSchema = z.object({
  service: z.string(),
  application_version: z.string(),
  api_version: z.string(),
  environment: z.string(),
  service_mode: z.string(),
});

export type VersionResponseData = z.infer<typeof VersionResponseDataSchema>;

export const CapabilityStatusSchema = z.object({
  name: z.string(),
  implemented: z.boolean(),
  detail: z.string().nullable().optional(),
});

export type CapabilityStatus = z.infer<typeof CapabilityStatusSchema>;

/**
 * Upstream integration states.
 *
 * The vocabulary is explicit so that "not configured" is never rendered as
 * "connected".
 */
export const UPSTREAM_STATES = [
  "unconfigured",
  "unverified",
  "connected",
  "unavailable",
  "auth_failed",
  "contract_mismatch",
  "invalid_response",
  "rate_limited",
] as const;

export const UpstreamIntegrationStatusSchema = z.object({
  service: z.string(),
  state: z.enum(UPSTREAM_STATES),
  base_url_configured: z.boolean(),
  credential_configured: z.boolean(),
  base_url: z.string().nullable().optional(),
  last_checked_at: z.string().nullable().optional(),
  last_check_succeeded: z.boolean().nullable().optional(),
  last_check_message: z.string().nullable().optional(),
  authentication_status: z.string(),
  provider_status: z.string(),
  provider_tested_at: z.string().nullable(),
  contract_status: z.string(),
  latency_ms: z.number().nullable().optional(),
});

export type UpstreamIntegrationStatus = z.infer<
  typeof UpstreamIntegrationStatusSchema
>;

export const StatusResponseDataSchema = z.object({
  service_id: z.string(),
  application_version: z.string(),
  api_version: z.string(),
  environment: z.string(),
  service_mode: z.string(),
  operational_state: z.string(),
  uptime_seconds: z.number().nullable().optional(),
  capabilities: z.array(CapabilityStatusSchema),
  dependencies: z.array(z.record(z.unknown())),
  upstream_integration: UpstreamIntegrationStatusSchema,
  timestamp_utc: z.string(),
});

export type StatusResponseData = z.infer<typeof StatusResponseDataSchema>;

/** Envelope schemas for each concrete endpoint. */
export const LiveEnvelopeSchema = ApiEnvelopeSchema.extend({
  data: HealthResponseDataSchema,
});

export const ReadyEnvelopeSchema = ApiEnvelopeSchema.extend({
  data: ReadyResponseDataSchema,
});

export const VersionEnvelopeSchema = ApiEnvelopeSchema.extend({
  data: VersionResponseDataSchema,
});

export const StatusEnvelopeSchema = ApiEnvelopeSchema.extend({
  data: StatusResponseDataSchema,
});

/** Data source status returned by GET /api/v1/data-source. */
export const DataSourceResponseDataSchema = z.object({
  configuration: z.record(z.unknown()),
  connectivity: z.object({
    state: z.string(),
    message: z.string(),
    latency_ms: z.number().nullable(),
    checked_at: z.string().nullable(),
    authentication_status: z.string(),
    provider_status: z.string(),
    provider_tested_at: z.string().nullable(),
  }),
  contract_status: z.string(),
});

export type DataSourceResponseData = z.infer<typeof DataSourceResponseDataSchema>;

/** Historical dataset returned by POST /api/v1/historical-data/retrieve. */
export const HistoricalDatasetResponseDataSchema = z.object({
  status: z.string(),
  data_source: z.string(),
  synthetic: z.boolean(),
  instrument: z.string(),
  timeframe: z.string(),
  price_basis: z.string(),
  provider_id: z.string(),
  observations: z.array(z.record(z.unknown())),
  quality: z.record(z.unknown()),
  provenance: z.record(z.unknown()),
  dataset_fingerprint: z.string(),
  partial: z.boolean().optional().default(false),
});

export type HistoricalDatasetResponseData = z.infer<
  typeof HistoricalDatasetResponseDataSchema
>;

export const HistoricalProviderInventorySchema = z.object({
  status: z.string(),
  providers: z.array(
    z.object({
      provider_id: z.string(),
      provider_type: z.enum(["real", "test"]),
      configured: z.boolean(),
      connection_status: z.string(),
      historical_candles_supported: z.boolean(),
      connection_test_succeeded: z.boolean().nullable().optional(),
    }),
  ),
  limitations: z.array(z.string()),
});

export type HistoricalProviderInventory = z.infer<
  typeof HistoricalProviderInventorySchema
>;

export const HistoricalProviderInventoryEnvelopeSchema =
  ApiEnvelopeSchema.extend({
    data: HistoricalProviderInventorySchema,
  });

/** Research readiness returned by POST /api/v1/research/readiness. */
export const ResearchReadinessResponseDataSchema = z.object({
  ready: z.boolean(),
  findings: z.array(z.record(z.unknown())),
  experiment_validation: z.record(z.unknown()),
  dataset_quality: z.record(z.unknown()).nullable().optional(),
  readiness_status: z.string().nullable().optional(),
  research_readiness_status: z.string().nullable().optional(),
});

export type ResearchReadinessResponseData = z.infer<
  typeof ResearchReadinessResponseDataSchema
>;

/** Model families returned by GET /api/v1/forecasting/models. */
export const ModelFamiliesResponseDataSchema = z.object({
  families: z.array(z.record(z.unknown())),
});

export type ModelFamiliesResponseData = z.infer<
  typeof ModelFamiliesResponseDataSchema
>;

/** Experiment validation returned by POST /api/v1/forecasting/experiment/validate. */
export const ExperimentValidationResponseDataSchema = z.object({
  valid: z.boolean(),
  errors: z.array(z.string()),
  config: z.record(z.unknown()),
});

export type ExperimentValidationResponseData = z.infer<
  typeof ExperimentValidationResponseDataSchema
>;

/** Experiment run returned by POST /api/v1/forecasting/experiment/run. */
export const ExperimentRunResponseDataSchema = z.object({
  experiment_id: z.string(),
  status: z.string(),
  started_at: z.string(),
  completed_at: z.string(),
  problem: z.record(z.unknown()),
  dataset_fingerprint: z.string(),
  feature_set_version: z.string(),
  target_type: z.string(),
  task_type: z.string(),
  n_observations: z.number(),
  n_folds: z.number(),
  folds: z.array(z.record(z.unknown())),
  models: z.array(z.record(z.unknown())),
  comparison: z.array(z.record(z.unknown())),
  aggregate: z.record(z.unknown()),
  warnings: z.array(z.string()),
  limitations: z.array(z.string()),
  artifact: z.record(z.unknown()),
  data_source: z.string().nullable().optional(),
  synthetic: z.boolean().nullable().optional(),
  data_provenance: z.record(z.unknown()).nullable().optional(),
  random_seed: z.number().nullable().optional(),
  validation_scheme: z.string().nullable().optional(),
  purge: z.boolean().nullable().optional(),
  embargo_periods: z.number().nullable().optional(),
  reproducibility: z.record(z.unknown()).nullable().optional(),
  effective_config: z.record(z.unknown()).nullable().optional(),
  research_readiness_status: z.string().nullable().optional(),
  research_readiness: z.record(z.unknown()).nullable().optional(),
  code_version: z.string().nullable().optional(),
  git_commit: z.string().nullable().optional(),
});

export type ExperimentRunResponseData = z.infer<
  typeof ExperimentRunResponseDataSchema
>;

export const ReplaySessionContextSchema = z.object({
  contract_version: z.literal("fx-session-context/v1"),
  observed_at: z.string().datetime({ offset: true }),
  available_at: z.string().datetime({ offset: true }),
  active_sessions: z.array(z.enum(["wellington", "sydney", "tokyo", "hong_kong", "singapore", "frankfurt", "london", "new_york"])).max(8).default([]),
  active_open_windows: z.array(z.enum(["sydney_open", "tokyo_open", "frankfurt_open", "london_open"])).max(4).default([]),
  active_kill_zones: z.array(z.enum(["ict_asia", "ict_london", "ict_new_york_am", "ict_london_close", "ict_new_york_pm"])).max(5).default([]),
  session_overlap_count: z.number().int().min(0).max(8),
  source_reference: z.string().min(1).max(200),
});

export const ReplayLiquidityLifecycleSchema = z.object({
  contract_version: z.literal("liquidity-sweep-lifecycle/v1"),
  observed_at: z.string().datetime({ offset: true }),
  available_at: z.string().datetime({ offset: true }),
  state: z.enum(["INSUFFICIENT_EVIDENCE_QUALITY", "INSUFFICIENT_PRE_SWEEP_HISTORY", "NOT_REVERSAL_ELIGIBLE", "SWEEP_CONFIRMED_AWAITING_DISPLACEMENT", "DISPLACEMENT_CONFIRMED", "MIDPOINT_REACHED", "MIDPOINT_CONSOLIDATION_CANDIDATE", "INVALIDATED"]),
  expected_direction: z.enum(["bullish", "bearish"]).nullable().optional(),
  source_event_id: z.string().min(1).max(200),
  displacement_confirmed_at: z.string().datetime({ offset: true }).nullable().optional(),
  midpoint_first_reached_at: z.string().datetime({ offset: true }).nullable().optional(),
  consolidation_candidate_at: z.string().datetime({ offset: true }).nullable().optional(),
  invalidated_at: z.string().datetime({ offset: true }).nullable().optional(),
});

export const ReplayObservationSchema = z.object({
  timestamp: z.string().datetime({ offset: true }),
  available_at: z.string().datetime({ offset: true }),
  open: z.number().positive(),
  high: z.number().positive(),
  low: z.number().positive(),
  close: z.number().positive(),
  volume: z.number().nonnegative().nullable().optional(),
  source_record_id: z.string().min(1),
  session_context: ReplaySessionContextSchema.nullable().optional(),
  liquidity_lifecycle: ReplayLiquidityLifecycleSchema.nullable().optional(),
});

export type ReplayObservation = z.infer<typeof ReplayObservationSchema>;

export const HistoricalReplayResponseDataSchema = z.object({
  replay_id: z.string(),
  status: z.string(),
  instrument: z.string(),
  timeframe: z.string(),
  target_type: z.string(),
  dataset_fingerprint: z.string(),
  source_dataset_id: z.string(),
  provenance_status: z.string(),
  synthetic: z.boolean(),
  n_observations: z.number(),
  n_predictions: z.number(),
  validation_mode: z.string(),
  predictions: z.array(
    z.object({
      reference_timestamp: z.string(),
      information_cutoff: z.string(),
      training_information_cutoff: z.string(),
      target_timestamp: z.string(),
      target_available_at: z.string(),
      training_samples: z.number(),
      training_reference_end: z.string(),
      training_target_end: z.string(),
      training_outcomes_available_by_cutoff: z.boolean(),
      regime: z.string(),
      actual: z.number(),
      forecasts: z.record(
        z.object({
          prediction: z.number(),
          class_probabilities: z.record(z.number()),
        }),
      ),
      market_context: z.record(z.unknown()).optional(),
    }),
  ),
  models: z.array(
    z.object({
      model_family: z.string(),
      n_predictions: z.number(),
      primary_metric: z.string(),
      out_of_sample_metrics: z.record(z.unknown()),
      regime_metrics: z.record(z.unknown()),
      declared_holdout: z.record(z.unknown()),
      vs_baseline: z.record(z.unknown()),
    }),
  ),
  robustness: z.record(z.unknown()),
  reproducibility: z.record(z.unknown()),
  warnings: z.array(z.string()),
  limitations: z.array(z.string()),
});

export type HistoricalReplayResponseData = z.infer<
  typeof HistoricalReplayResponseDataSchema
>;

export const SessionLiquidityEventStudyResponseDataSchema = z.object({
  status: z.string(),
  analysis_id: z.string(),
  analysis_cutoff: z.string(),
  input_event_count: z.number(),
  eligible_event_count: z.number(),
  excluded_after_cutoff_count: z.number(),
  first_sweep_session_instance_count: z.number(),
  groups: z.array(z.record(z.unknown())),
  provenance_status: z.string(),
  limitations: z.array(z.string()),
  forecast_eligible: z.boolean(),
});

export type SessionLiquidityEventStudyResponseData = z.infer<
  typeof SessionLiquidityEventStudyResponseDataSchema
>;

export const ResearchSummaryResponseDataSchema = z.object({
  status: z.string(),
  analysis_id: z.string(),
  instrument: z.string().nullable().optional(),
  timeframe: z.string().nullable().optional(),
  observation_count: z.number(),
  dominant_regime: z.string().nullable().optional(),
  regime_share: z.number().nullable().optional(),
  volatility_state: z.string(),
  trend_state: z.string(),
  pattern_id: z.string().nullable().optional(),
  pattern_effect_size: z.number().nullable().optional(),
  pattern_significance: z.boolean(),
  confidence: z.number().nullable().optional(),
  confidence_status: z.string(),
  narrative: z.string(),
  recommendations: z.array(z.string()),
  regime_summary: z.record(z.unknown()).nullable().optional(),
  pattern_summary: z.record(z.unknown()).nullable().optional(),
  historical_interval: z.record(z.string().nullable()),
  dataset_fingerprint: z.string().nullable().optional(),
  data_provenance: z.record(z.unknown()),
  source_quality: z.record(z.unknown()).nullable().optional(),
  warnings: z.array(z.string()),
  limitations: z.array(z.string()),
  duration_ms: z.number(),
});

export type ResearchSummaryResponseData = z.infer<
  typeof ResearchSummaryResponseDataSchema
>;


export const SeasonalityBucketResultSchema = z.object({
  dimension: z.enum(["weekday", "hour_of_day", "month_of_year"]),
  bucket_key: z.string(),
  bucket_label: z.string(),
  observation_count: z.number(),
  sample_status: z.string(),
  mean_return: z.number().nullable(),
  median_return: z.number().nullable(),
  positive_return_rate: z.number().nullable(),
  realized_volatility: z.number().nullable(),
  mean_candle_range_pct: z.number().nullable(),
  mean_return_interval_95_lower: z.number().nullable(),
  mean_return_interval_95_upper: z.number().nullable(),
  difference_from_global_mean: z.number().nullable(),
});

export const SeasonalityAnalysisResponseDataSchema = z.object({
  status: z.string(),
  analysis_id: z.string(),
  instrument: z.string(),
  timeframe: z.string(),
  timezone: z.string(),
  observation_count: z.number(),
  return_observation_count: z.number(),
  excluded_gap_return_count: z.number(),
  excluded_short_interval_return_count: z.number(),
  interval: z.object({ start: z.string().nullable(), end: z.string().nullable() }),
  dataset_fingerprint: z.string(),
  analysis_fingerprint: z.string(),
  effective_config: z.record(z.unknown()),
  methodology: z.record(z.unknown()),
  algorithm_id: z.string(),
  algorithm_version: z.string(),
  global_summary: z.record(z.unknown()),
  buckets: z.array(SeasonalityBucketResultSchema),
  minimum_bucket_samples: z.number(),
  bootstrap: z.object({
    method: z.string(),
    samples: z.number(),
    block_size: z.number(),
    interval: z.string(),
  }),
  insufficient_bucket_count: z.number(),
  data_provenance: z.record(z.unknown()),
  source_quality: z.record(z.unknown()).nullable().optional(),
  forecast_eligible: z.boolean(),
  warnings: z.array(z.string()),
  limitations: z.array(z.string()),
  duration_ms: z.number(),
});

export type SeasonalityAnalysisResponseData = z.infer<
  typeof SeasonalityAnalysisResponseDataSchema
>;

/** Envelope schemas for the new endpoints. */
export const DataSourceEnvelopeSchema = ApiEnvelopeSchema.extend({
  data: DataSourceResponseDataSchema,
});

export const HistoricalDatasetEnvelopeSchema = ApiEnvelopeSchema.extend({
  data: HistoricalDatasetResponseDataSchema,
});

export const ResearchReadinessEnvelopeSchema = ApiEnvelopeSchema.extend({
  data: ResearchReadinessResponseDataSchema,
});

export const ModelFamiliesEnvelopeSchema = ApiEnvelopeSchema.extend({
  data: ModelFamiliesResponseDataSchema,
});

export const ExperimentValidationEnvelopeSchema = ApiEnvelopeSchema.extend({
  data: ExperimentValidationResponseDataSchema,
});

export const ExperimentRunEnvelopeSchema = ApiEnvelopeSchema.extend({
  data: ExperimentRunResponseDataSchema,
});

export const HistoricalReplayEnvelopeSchema = ApiEnvelopeSchema.extend({
  data: HistoricalReplayResponseDataSchema,
});

export const SessionLiquidityEventStudyEnvelopeSchema = ApiEnvelopeSchema.extend({
  data: SessionLiquidityEventStudyResponseDataSchema,
});

export const ResearchSummaryEnvelopeSchema = ApiEnvelopeSchema.extend({
  data: ResearchSummaryResponseDataSchema,
});

export const SeasonalityAnalysisEnvelopeSchema = ApiEnvelopeSchema.extend({
  data: SeasonalityAnalysisResponseDataSchema,
});
