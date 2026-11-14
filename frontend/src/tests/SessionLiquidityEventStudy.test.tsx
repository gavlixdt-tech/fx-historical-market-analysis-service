import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SessionLiquidityEventStudy } from "@/features/SessionLiquidityEventStudy";

describe("SessionLiquidityEventStudy upload validation", () => {
  it("rejects files larger than the configured API request budget", async () => {
    render(<SessionLiquidityEventStudy />);
    const file = new File(["x".repeat(900_001)], "oversized-events.json", {
      type: "application/json",
    });

    fireEvent.change(screen.getByTestId("event-study-file"), {
      target: { files: [file] },
    });

    expect(await screen.findByTestId("event-study-error")).toHaveTextContent(
      /exceeds 900 KB/i,
    );
  });

  it("rejects a cutoff timestamp without an explicit timezone", async () => {
    render(<SessionLiquidityEventStudy />);
    const file = new File(
      [JSON.stringify({ analysis_cutoff: "2026-11-14T09:00:00", events: [{}] })],
      "naive-cutoff.json",
      { type: "application/json" },
    );
    Object.defineProperty(file, "text", {
      value: async () =>
        JSON.stringify({ analysis_cutoff: "2026-11-14T09:00:00", events: [{}] }),
    });

    fireEvent.change(screen.getByTestId("event-study-file"), {
      target: { files: [file] },
    });

    expect(await screen.findByTestId("event-study-error")).toHaveTextContent(
      /timezone-aware ISO-8601/i,
    );
  });
});
