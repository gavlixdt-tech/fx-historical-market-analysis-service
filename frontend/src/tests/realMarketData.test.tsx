import { vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { RealMarketDataWorkspace } from "@/features/RealMarketDataWorkspace";
import { envelope, dataSourceData } from "./fixtures";

const originalFetch = global.fetch;

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("real market data workspace", () => {
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("renders a backend-reported connected state", async () => {
    global.fetch = vi.fn((input: RequestInfo | URL) =>
      Promise.resolve(
        String(input).includes("/data-source")
          ? jsonResponse(envelope(dataSourceData))
          : String(input).includes("/historical-data/providers")
            ? jsonResponse(
                envelope({
                  status: "available",
                  providers: [
                    {
                      provider_id: "provider-live",
                      provider_type: "real",
                      configured: true,
                      connection_status: "available",
                      historical_candles_supported: true,
                    },
                  ],
                  limitations: [
                    "Provider assertion does not verify original publication timestamps.",
                  ],
                }),
              )
          : jsonResponse({ error: { code: "HTTP_404", message: "not found" } }, 404),
      ),
    ) as unknown as typeof global.fetch;

    render(<RealMarketDataWorkspace />);

    await waitFor(() => {
      expect(screen.getByTestId("data-source-state")).toHaveTextContent(
        "connected",
      );
    });
    expect(screen.getByText("Authentication")).toBeInTheDocument();
    expect(screen.getAllByText("verified").length).toBeGreaterThan(0);
    expect(screen.getByText("Real provider")).toBeInTheDocument();
    expect(screen.getAllByText("available").length).toBeGreaterThan(0);
    await waitFor(() => {
      expect(screen.getByTestId("historical-provider")).toHaveTextContent(
        "provider-live (real)",
      );
    });
  });
});
