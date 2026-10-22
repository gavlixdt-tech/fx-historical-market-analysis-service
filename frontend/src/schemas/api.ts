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
