/**
 * Tests for the typed API client.
 *
 * These assert that the client validates responses at runtime, normalises
 * failures, and never attempts to reach the upstream market-data service.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, NetworkError, ValidationError } from "@/services/api";
import { envelope, liveData, statusData, versionData } from "./fixtures";

const originalFetch = global.fetch;

function mockFetch(
  handler: (url: string, init?: RequestInit) => Response | Promise<Response>,
) {
  const spy = vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
    Promise.resolve(handler(String(input), init)),
  );
  global.fetch = spy as unknown as typeof global.fetch;
  return spy;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "X-Request-ID": "fx-synthetic-fixture-request",
    },
  });
}

describe("api client", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("requests only this service's own backend paths", async () => {
    const spy = mockFetch(() => jsonResponse(envelope(liveData)));

    await api.getLive();

    expect(spy).toHaveBeenCalledTimes(1);
    const requestedUrl = String(spy.mock.calls[0][0]);
    expect(requestedUrl).toContain("/api/v1/health/live");
    // The browser must never call the upstream market-data service directly.
    expect(requestedUrl).not.toContain("market-data/history");
    expect(requestedUrl).not.toContain("market-data/providers");
  });

  it("returns the validated payload on success", async () => {
    mockFetch(() => jsonResponse(envelope(versionData)));

    const version = await api.getVersion();

    expect(version.service).toBe("fx-historical-market-analysis-service");
    expect(version.service_mode).toBe("research-simulation");
  });

  it("raises a validation error for a malformed payload", async () => {
    mockFetch(() => jsonResponse({ data: { unexpected: true }, meta: {} }));

    await expect(api.getStatus()).rejects.toBeInstanceOf(ValidationError);
  });

  it("raises a validation error when the envelope meta is missing", async () => {
    mockFetch(() => jsonResponse({ data: statusData }));

    await expect(api.getStatus()).rejects.toBeInstanceOf(ValidationError);
  });

  it("raises an ApiError carrying the backend error code and request id", async () => {
    mockFetch(() =>
      jsonResponse(
        {
          error: {
            code: "SVR_UNAVAILABLE",
            message: "The service is temporarily unavailable.",
            request_id: "fx-error-request",
          },
        },
        503,
      ),
    );

    await expect(api.getStatus()).rejects.toMatchObject({
      name: "ApiError",
      status: 503,
      code: "SVR_UNAVAILABLE",
      requestId: "fx-error-request",
    });
  });

  it("raises a network error when the backend is unreachable", async () => {
    global.fetch = vi.fn(() =>
      Promise.reject(new TypeError("Failed to fetch")),
    ) as unknown as typeof global.fetch;

    await expect(api.getLive()).rejects.toBeInstanceOf(NetworkError);
  });

  it("surfaces the correlation id from the response headers", async () => {
    mockFetch(() => jsonResponse(envelope(liveData)));

    const result = await api.getLive();

    expect(result.status).toBe("healthy");
  });

  it("does not send any credential headers", async () => {
    const spy = mockFetch(() => jsonResponse(envelope(liveData)));

    await api.getLive();

    const init = spy.mock.calls[0][1] as RequestInit | undefined;
    const headers = (init?.headers ?? {}) as Record<string, string>;
    expect(headers["X-API-Key"]).toBeUndefined();
    expect(headers["Authorization"]).toBeUndefined();
  });
});
