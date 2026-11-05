import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { HistoricalReplayWorkbench } from "@/features/HistoricalReplayWorkbench";

describe("historical replay workbench", () => {
  it("requires a caller-provided dataset instead of generating demo observations", () => {
    render(<HistoricalReplayWorkbench />);

    expect(screen.getByTestId("replay-file")).toBeInTheDocument();
    expect(screen.getByTestId("run-historical-replay")).toBeDisabled();
    expect(screen.queryByText(/run synthetic demo/i)).toBeNull();
  });

  it("loads a bounded JSON dataset with point-in-time fields", async () => {
    const observations = Array.from({ length: 52 }, (_, index) => {
      const timestamp = new Date(Date.UTC(2024, 0, index + 1));
      const availableAt = new Date(timestamp.getTime() + 120_000);
      return {
        timestamp: timestamp.toISOString(),
        available_at: availableAt.toISOString(),
        open: 1.1,
        high: 1.101,
        low: 1.099,
        close: 1.1,
        source_record_id: `source-${index}`,
      };
    });
    const file = new File(
      [JSON.stringify(observations)],
      "historical-records.json",
      { type: "application/json" },
    );
    Object.defineProperty(file, "text", {
      value: vi.fn().mockResolvedValue(JSON.stringify(observations)),
    });
    render(<HistoricalReplayWorkbench />);

    fireEvent.change(screen.getByTestId("replay-file"), {
      target: { files: [file] },
    });

    await waitFor(() => {
      expect(screen.getByTestId("replay-file-status")).toHaveTextContent(
        "historical-records.json: 52 records loaded",
      );
    });
  });
});
