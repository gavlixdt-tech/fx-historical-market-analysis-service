/**
 * Dashboard rendering tests.
 *
 * These cover the loading, empty, unavailable, and error states required of
 * the dashboard, and assert that no fabricated analytical content appears.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import App from "@/app/App";
import { envelope, liveData, readyData, statusData, versionData } from "./fixtures";

const originalFetch = global.fetch;

function mockFetch(handler: (url: string) => Response) {
  global.fetch = vi.fn((input: RequestInfo | URL) =>
    Promise.resolve(handler(String(input))),
  ) as unknown as typeof global.fetch;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function successHandler(url: string): Response {
  if (url.includes("/health/live")) return jsonResponse(envelope(liveData));
  if (url.includes("/health/ready")) return jsonResponse(envelope(readyData));
  if (url.includes("/status")) return jsonResponse(envelope(statusData));
  if (url.includes("/version")) return jsonResponse(envelope(versionData));
  return jsonResponse({ error: { code: "HTTP_404", message: "not found" } }, 404);
}

describe("dashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("shows a loading state while the backend is being contacted", () => {
    global.fetch = vi.fn(() => new Promise(() => {})) as unknown as typeof global.fetch;

    render(<App />);

    expect(screen.getAllByText(/loading/i).length).toBeGreaterThan(0);
  });

  it("renders the service overview once the backend responds", async () => {
    mockFetch(successHandler);

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("service-name")).toHaveTextContent(
        "fx-historical-market-analysis-service",
      );
    });
    expect(screen.getByTestId("service-version")).toHaveTextContent("0.1.0");
  });

  it("shows the upstream service identity and its unconfigured state", async () => {
    mockFetch(successHandler);

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("upstream-service")).toHaveTextContent(
        "fx-market-data-service",
      );
    });
    expect(screen.getByTestId("upstream-base-url-configured")).toHaveTextContent(
      "No",
    );
    expect(screen.getByTestId("upstream-credential-configured")).toHaveTextContent(
      "No",
    );
    expect(screen.getByTestId("upstream-last-check-outcome")).toHaveTextContent(
      "Not yet verified",
    );
  });

  it("states explicitly that the analysis engine is not implemented", async () => {
    mockFetch(successHandler);

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("analysis-not-implemented")).toBeInTheDocument();
    });
    expect(
      screen.getByText(/has not been implemented/i),
    ).toBeInTheDocument();
  });

  it("lists deferred analytical capabilities as deferred", async () => {
    mockFetch(successHandler);

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("deferred-capabilities")).toBeInTheDocument();
    });
    expect(screen.getByText(/historical statistics/i)).toBeInTheDocument();
  });

  it("presents no fabricated market statistics or analysis scores", async () => {
    mockFetch(successHandler);

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("analysis-not-implemented")).toBeInTheDocument();
    });

    const body = document.body.textContent ?? "";
    expect(body).not.toMatch(/\bvolatility\b/i);
    expect(body).not.toMatch(/\bcorrelation coefficient\b/i);
    expect(body).not.toMatch(/\bconfidence score\b/i);
    expect(body).not.toMatch(/\bsignal\b/i);
  });

  it("exposes no trading controls", async () => {
    mockFetch(successHandler);

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("service-name")).toBeInTheDocument();
    });

    const body = document.body.textContent ?? "";
    expect(body).not.toMatch(/\bbuy\b/i);
    expect(body).not.toMatch(/\bsell\b/i);
    expect(body).not.toMatch(/\border/i);
    expect(screen.queryByRole("button", { name: /buy|sell|place order/i })).toBeNull();
  });

  it("renders an error notice with the correlation id when the backend fails", async () => {
    mockFetch(() =>
      jsonResponse(
        {
          error: {
            code: "SVR_INTERNAL",
            message: "An internal server error occurred.",
            request_id: "fx-error-request",
          },
        },
        500,
      ),
    );

    render(<App />);

    await waitFor(() => {
      expect(screen.getAllByTestId(/error-notice/).length).toBeGreaterThan(0);
    });
    expect(screen.getByTestId("overview-error-notice-request-id")).toHaveTextContent(
      "fx-error-request",
    );
  });

  it("renders an unavailable notice when the backend cannot be reached", async () => {
    global.fetch = vi.fn(() =>
      Promise.reject(new TypeError("Failed to fetch")),
    ) as unknown as typeof global.fetch;

    render(<App />);

    await waitFor(() => {
      expect(screen.getAllByTestId(/error-notice/).length).toBeGreaterThan(0);
    });
    expect(
      screen.getByTestId("overview-error-notice"),
    ).toHaveTextContent(/backend unreachable/i);
  });

  it("shows the last refresh time after a successful load", async () => {
    mockFetch(successHandler);

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("last-refresh")).toBeInTheDocument();
    });
  });

  it("renders the dependency list in diagnostics", async () => {
    mockFetch(successHandler);

    render(<App />);

    await waitFor(() => {
      expect(
        screen.getByTestId("dependency-fx-market-data-service"),
      ).toBeInTheDocument();
    });
  });
});
