import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  listHistoricalProviders: vi.fn(),
  runSeasonalityAnalysis: vi.fn(),
}));

vi.mock("@/services/api", () => ({
  api: {
    listHistoricalProviders: mocks.listHistoricalProviders,
    runSeasonalityAnalysis: mocks.runSeasonalityAnalysis,
  },
  ApiError: class ApiError extends Error {
    status: number;
    code: string;
    requestId: string | null;
    constructor(message: string, status: number, code: string, requestId: string | null) {
      super(message);
      this.status = status;
      this.code = code;
      this.requestId = requestId;
    }
  },
}));

import { SeasonalityWorkspace } from "@/features/SeasonalityWorkspace";

const providerInventory = {
  status: "available",
  providers: [
    {
      provider_id: "fixture-provider",
      provider_type: "test",
      configured: true,
      connection_status: "connected",
      historical_candles_supported: true,
      connection_test_succeeded: true,
    },
  ],
  limitations: [],
};

const seasonalityResult = {
  status: "completed_with_warnings",
  analysis_id: "analysis-123",
  instrument: "EUR/USD",
  timeframe: "H1",
  timezone: "Africa/Nairobi",
  observation_count: 120,
  return_observation_count: 119,
  excluded_gap_return_count: 0,
  excluded_short_interval_return_count: 0,
  interval: { start: "2026-01-01T00:00:00Z", end: "2026-01-05T23:00:00Z" },
  dataset_fingerprint: "fingerprint-123",
  analysis_fingerprint: "analysis-fingerprint-123",
  effective_config: { maximum_gap_multiple: 1.5 },
  methodology: {
    return_definition: "Simple close-to-close return.",
    realized_volatility: "Sample standard deviation; not annualized.",
  },
  algorithm_id: "calendar_seasonality_research",
  algorithm_version: "1.0.0",
  global_summary: {
    return_observation_count: 119,
    excluded_gap_return_count: 0,
    mean_return: 0.0002,
    median_return: 0.0001,
    realized_volatility: 0.001,
    positive_return_rate: 0.55,
    mean_candle_range_pct: 0.002,
  },
  buckets: [
    {
      dimension: "weekday",
      bucket_key: "0",
      bucket_label: "Monday",
      observation_count: 20,
      sample_status: "descriptive_sample",
      mean_return: 0.0003,
      median_return: 0.0002,
      positive_return_rate: 0.6,
      realized_volatility: 0.001,
      mean_candle_range_pct: 0.002,
      mean_return_interval_95_lower: 0.0001,
      mean_return_interval_95_upper: 0.0005,
      difference_from_global_mean: 0.0001,
    },
  ],
  minimum_bucket_samples: 20,
  maximum_gap_multiple: 1.5,
  bootstrap: {
    method: "circular moving-block bootstrap within each calendar bucket",
    samples: 300,
    block_size: 5,
    interval: "descriptive 95% interval for the bucket mean",
  },
  insufficient_bucket_count: 30,
  data_provenance: { provenance_status: "synthetic_fixture" },
  source_quality: null,
  forecast_eligible: false,
  warnings: ["Some buckets have insufficient samples."],
  limitations: ["Descriptive research only."],
  duration_ms: 12.5,
};

describe("SeasonalityWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listHistoricalProviders.mockResolvedValue(providerInventory);
    mocks.runSeasonalityAnalysis.mockResolvedValue(seasonalityResult);
  });

  it("loads a provider and renders API-backed seasonality results", async () => {
    const user = userEvent.setup();
    render(<SeasonalityWorkspace />);

    await waitFor(() => {
      expect(screen.getByLabelText("Historical provider")).toHaveValue("fixture-provider");
    });

    await user.selectOptions(screen.getByLabelText("Calendar timezone"), "Africa/Nairobi");
    await user.click(screen.getByTestId("run-seasonality"));

    await waitFor(() => {
      expect(mocks.runSeasonalityAnalysis).toHaveBeenCalledWith(
        expect.objectContaining({
          provider_id: "fixture-provider",
          instrument: "EUR/USD",
          timeframe: "H1",
          timezone: "Africa/Nairobi",
          bucket_types: ["weekday", "hour_of_day", "month_of_year"],
          minimum_bucket_samples: 20,
          maximum_gap_multiple: 1.5,
        }),
      );
    });

    expect(await screen.findByTestId("seasonality-result")).toBeInTheDocument();
    expect(screen.getByText(/Monday/)).toBeInTheDocument();
    expect(screen.getByText("descriptive only")).toBeInTheDocument();
    expect(screen.getByText(/synthetic_fixture/)).toBeInTheDocument();
  });

  it("does not run when every calendar dimension is deselected", async () => {
    const user = userEvent.setup();
    render(<SeasonalityWorkspace />);

    await user.click(screen.getByLabelText("Day of week"));
    await user.click(screen.getByLabelText("Hour of day"));
    await user.click(screen.getByLabelText("Month of year"));

    expect(screen.getByTestId("run-seasonality")).toBeDisabled();
    expect(mocks.runSeasonalityAnalysis).not.toHaveBeenCalled();
  });
});
