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
          : jsonResponse({ error: { code: "HTTP_404", message: "not found" } }, 404),
      ),
    ) as unknown as typeof global.fetch;

    render(<RealMarketDataWorkspace />);

    await waitFor(() => {
      expect(screen.getByTestId("data-source-state")).toHaveTextContent(
        "connected",
      );
    });
  });
});
