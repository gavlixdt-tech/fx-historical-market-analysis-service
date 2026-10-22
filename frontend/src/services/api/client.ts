/**
 * Typed API client for fx-historical-market-analysis-service.
 *
 * Design constraints:
 * - The dashboard talks ONLY to its own backend. It never calls the upstream
 *   market-data service directly; cross-service access is server-side.
 * - Every response is validated at runtime against a Zod schema.
 * - Every failure is normalised into a typed error so the UI can render an
 *   accurate state instead of a generic failure.
 * - Correlation IDs are echoed back so the operator can quote them.
 */

import { z } from "zod";

import {
  LiveEnvelopeSchema,
  ReadyEnvelopeSchema,
  StatusEnvelopeSchema,
  VersionEnvelopeSchema,
  type ErrorDetail,
  type ReadyResponseData,
  type StatusResponseData,
  type VersionResponseData,
} from "@/schemas/api";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "/api/v1").replace(
  /\/$/,
  "",
);

const DEFAULT_TIMEOUT_MS = Number(
  import.meta.env.VITE_API_TIMEOUT_MS || 8000,
);

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly details: ErrorDetail | null;

  constructor(
    message: string,
    status: number,
    code: string,
    requestId: string | null,
    details: ErrorDetail | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.details = details;
  }
}

export class NetworkError extends ApiError {
  constructor(message: string) {
    super(message, 0, "NETWORK_UNAVAILABLE", null);
    this.name = "NetworkError";
  }
}

export class TimeoutError extends ApiError {
  constructor(timeoutMs: number) {
    super(
      `The request exceeded the ${timeoutMs}ms timeout.`,
      0,
      "REQUEST_TIMEOUT",
      null,
    );
    this.name = "TimeoutError";
  }
}

export class ValidationError extends ApiError {
  constructor(message: string, requestId: string | null) {
    super(message, 0, "RESPONSE_SCHEMA_INVALID", requestId);
    this.name = "ValidationError";
  }
}

export interface RequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
}

async function request<S extends z.ZodTypeAny>(
  path: string,
  schema: S,
  options: RequestOptions = {},
): Promise<z.infer<S>> {
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const controller = new AbortController();
  const timeoutHandle = window.setTimeout(() => controller.abort(), timeoutMs);

  if (options.signal) {
    if (options.signal.aborted) {
      window.clearTimeout(timeoutHandle);
      throw new NetworkError("The request was cancelled.");
    }
    options.signal.addEventListener("abort", () => controller.abort(), {
      once: true,
    });
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
  } catch (error) {
    window.clearTimeout(timeoutHandle);
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new TimeoutError(timeoutMs);
    }
    throw new NetworkError(
      "The backend could not be reached. The service may be unavailable.",
    );
  } finally {
    window.clearTimeout(timeoutHandle);
  }

  const requestId = response.headers.get("X-Request-ID");

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new NetworkError(
      "The backend returned a response that could not be parsed.",
    );
  }

  if (!response.ok) {
    const errorBody = payload as { error?: ErrorDetail };
    const detail = errorBody?.error ?? null;
    throw new ApiError(
      detail?.message ?? `Request failed with status ${response.status}.`,
      response.status,
      detail?.code ?? `HTTP_${response.status}`,
      detail?.request_id ?? requestId,
      detail,
    );
  }

  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    throw new ValidationError(
      "The backend response did not match the expected contract.",
      requestId,
    );
  }
  return parsed.data;
}

export const api = {
  getLive: (options?: RequestOptions) =>
    request("/health/live", LiveEnvelopeSchema, options).then((r) => r.data),

  getReady: (options?: RequestOptions) =>
    request("/health/ready", ReadyEnvelopeSchema, options).then((r) => r.data),

  getStatus: (options?: RequestOptions) =>
    request("/status", StatusEnvelopeSchema, options).then((r) => r.data),

  getVersion: (options?: RequestOptions) =>
    request("/version", VersionEnvelopeSchema, options).then((r) => r.data),
};

export type { ErrorDetail, ReadyResponseData, StatusResponseData, VersionResponseData };
