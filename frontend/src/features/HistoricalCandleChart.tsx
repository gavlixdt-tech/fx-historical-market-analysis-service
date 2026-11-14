import { Panel } from "@/components/Panel";

interface HistoricalCandleChartProps {
  observations: Record<string, unknown>[];
  instrument: string;
  timeframe: string;
}

interface Candle {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

function toCandle(value: Record<string, unknown>): Candle | null {
  const { timestamp, open, high, low, close } = value;
  if (
    typeof timestamp !== "string" ||
    ![open, high, low, close].every((item) => typeof item === "number" && Number.isFinite(item))
  ) return null;
  const candle = { timestamp, open: open as number, high: high as number, low: low as number, close: close as number };
  if (candle.low <= 0 || candle.high < Math.max(candle.open, candle.close, candle.low) || candle.low > Math.min(candle.open, candle.close)) return null;
  return candle;
}

/** A dependency-free, read-only OHLC chart for the bounded retrieved dataset. */
export function HistoricalCandleChart({ observations, instrument, timeframe }: HistoricalCandleChartProps) {
  const candles = observations.map(toCandle).filter((item): item is Candle => item !== null);
  const visible = candles.slice(-120);
  if (visible.length === 0) {
    return <Panel title="Historical candles" subtitle="OHLC visualization"><p className="muted">No valid OHLC observations are available to chart.</p></Panel>;
  }

  const width = 960;
  const height = 300;
  const padding = { top: 18, right: 18, bottom: 28, left: 18 };
  const min = Math.min(...visible.map((candle) => candle.low));
  const max = Math.max(...visible.map((candle) => candle.high));
  const range = Math.max(max - min, Math.abs(max) * 0.000001, 0.00000001);
  const plotHeight = height - padding.top - padding.bottom;
  const plotWidth = width - padding.left - padding.right;
  const xStep = plotWidth / visible.length;
  const bodyWidth = Math.max(2, Math.min(9, xStep * 0.62));
  const y = (price: number) => padding.top + ((max - price) / range) * plotHeight;

  return (
    <Panel title={`Historical candles · ${instrument} · ${timeframe}`} subtitle={`Latest ${visible.length} of ${candles.length} valid OHLC observations. Read-only source data.`}>
      <div data-testid="historical-candle-chart">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Candlestick chart for ${instrument} on ${timeframe}`} width="100%" height="auto">
          {[0, 0.25, 0.5, 0.75, 1].map((fraction) => {
            const yy = padding.top + fraction * plotHeight;
            return <line key={fraction} x1={padding.left} x2={width - padding.right} y1={yy} y2={yy} stroke="var(--border)" strokeDasharray="3 5" />;
          })}
          {visible.map((candle, index) => {
            const x = padding.left + index * xStep + xStep / 2;
            const rising = candle.close >= candle.open;
            const color = rising ? "var(--ok)" : "var(--error)";
            const top = y(Math.max(candle.open, candle.close));
            const bottom = y(Math.min(candle.open, candle.close));
            const bodyHeight = Math.max(1.5, bottom - top);
            return (
              <g key={candle.timestamp}>
                <line x1={x} x2={x} y1={y(candle.high)} y2={y(candle.low)} stroke={color} strokeWidth="1.2" />
                <rect x={x - bodyWidth / 2} y={top} width={bodyWidth} height={bodyHeight} fill={color} opacity="0.9" />
              </g>
            );
          })}
        </svg>
        <div className="muted small">Green: close ≥ open · Red: close below open · Prices are plotted from the returned OHLC values without interpolation.</div>
        <div style={{ overflowX: "auto", marginTop: "14px" }}>
          <table>
            <thead><tr><th>Timestamp</th><th>Open</th><th>High</th><th>Low</th><th>Close</th></tr></thead>
            <tbody>
              {visible.slice(-30).reverse().map((candle) => (
                <tr key={candle.timestamp}>
                  <td>{candle.timestamp}</td><td>{candle.open}</td><td>{candle.high}</td><td>{candle.low}</td><td>{candle.close}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </Panel>
  );
}
