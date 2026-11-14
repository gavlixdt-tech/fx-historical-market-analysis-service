import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DatasetQualityProvenance } from "@/features/DatasetQualityProvenance";
import { HistoricalCandleChart } from "@/features/HistoricalCandleChart";
import type { HistoricalDatasetResponseData } from "@/schemas/api";

const dataset: HistoricalDatasetResponseData = {
  status: "completed",
  data_source: "upstream_historical",
  synthetic: true,
  instrument: "EUR/USD",
  timeframe: "H1",
  price_basis: "bid",
  provider_id: "test-adapter",
  observations: [
    { timestamp: "2026-01-01T00:00:00Z", open: 1.1, high: 1.12, low: 1.09, close: 1.11, volume: null },
  ],
  quality: { valid: true, accepted_count: 1, rejected_count: 0 },
  provenance: {
    provider_type: "test",
    provenance_status: "synthetic_fixture",
    verified_real_market_data: false,
    real_market_research_accepted: false,
  },
  dataset_fingerprint: "sha256:test-fingerprint",
  partial: false,
};

describe("historical research data views", () => {
  it("clearly labels synthetic datasets and preserves backend provenance", () => {
    render(<DatasetQualityProvenance dataset={dataset} />);
    expect(screen.getByTestId("dataset-quality-provenance")).toBeInTheDocument();
    expect(screen.getByText("synthetic fixture")).toBeInTheDocument();
    expect(screen.getByText(/must not be treated as genuine market evidence/i)).toBeInTheDocument();
    expect(screen.getByText("sha256:test-fingerprint")).toBeInTheDocument();
  });

  it("renders only valid OHLC observations in the historical candle chart", () => {
    render(
      <HistoricalCandleChart
        instrument="EUR/USD"
        timeframe="H1"
        observations={[
          { timestamp: "2026-01-01T00:00:00Z", open: 1.1, high: 1.12, low: 1.09, close: 1.11 },
          { timestamp: "invalid", open: 1.1, high: 1.0, low: 1.09, close: 1.11 },
        ]}
      />,
    );
    expect(screen.getByTestId("historical-candle-chart")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /candlestick chart for EUR\/USD on H1/i })).toBeInTheDocument();
    expect(screen.getByText("2026-01-01T00:00:00Z")).toBeInTheDocument();
  });
});
