import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HistoricalReplayWorkbench } from "@/features/HistoricalReplayWorkbench";

describe("HistoricalReplayWorkbench upload limits", () => {
  it("rejects files larger than the configured API request budget", async () => {
    render(<HistoricalReplayWorkbench />);
    const file = new File(["x".repeat(900_001)], "oversized-replay.json", {
      type: "application/json",
    });

    fireEvent.change(screen.getByTestId("replay-file"), {
      target: { files: [file] },
    });

    expect(await screen.findByTestId("replay-error")).toHaveTextContent(
      /exceeds 900 KB/i,
    );
  });
});
