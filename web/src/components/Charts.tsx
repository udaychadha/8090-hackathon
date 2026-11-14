import type { DatasetPreview, Equity } from "../types";
import { Empty } from "./common";
import { formatNumber } from "../evidence";

function line(
  values: number[],
  times: number[],
  x: (v: number) => number,
  y: (v: number) => number,
) {
  return values
    .map(
      (value, index) =>
        `${index ? "L" : "M"}${x(times[index]).toFixed(2)},${y(value).toFixed(2)}`,
    )
    .join(" ");
}
export function EquityChart({ equity }: { equity: Equity | null }) {
  if (!equity || !equity.dates.length)
    return <Empty>No equity curve was recorded for this variant.</Empty>;
  const times = equity.dates.map((d) => Date.parse(d));
  const values = [...equity.gross, ...equity.net];
  const low = Math.min(...values),
    high = Math.max(...values);
  const margin = (high - low) * 0.08 || 0.1;
  const x = (time: number) =>
    60 + ((time - times[0]) / (times[times.length - 1] - times[0] || 1)) * 980;
  const y = (value: number) =>
    320 - ((value - (low - margin)) / (high - low + 2 * margin)) * 270;
  const boundary = x(Date.parse(equity.is_end));
  return (
    <>
      <div className="chart-frame">
        <svg
          className="chart"
          viewBox="0 0 1080 370"
          role="img"
          aria-label="Recorded gross and net equity with the in-sample boundary"
        >
          <title>
            Gross and net equity · IS ends {equity.is_end}, OOS ends{" "}
            {equity.oos_end}
          </title>
          {[0, 0.25, 0.5, 0.75, 1].map((t) => {
            const v = low - margin + t * (high - low + 2 * margin);
            return (
              <g key={t}>
                <line
                  className="gridline"
                  x1="60"
                  x2="1040"
                  y1={y(v)}
                  y2={y(v)}
                />
                <text x="50" y={y(v) + 4} textAnchor="end">
                  {formatNumber(v)}
                </text>
              </g>
            );
          })}
          {boundary >= 60 && boundary <= 1040 && (
            <>
              <line
                className="boundary"
                x1={boundary}
                x2={boundary}
                y1="35"
                y2="320"
              />
              <text
                x={Math.min(1020, Math.max(120, boundary))}
                y="22"
                textAnchor="middle"
              >
                IS ends · {equity.is_end}
              </text>
            </>
          )}
          <path className="line-gross" d={line(equity.gross, times, x, y)} />
          <path className="line-net" d={line(equity.net, times, x, y)} />
          <text x="60" y="352">
            {equity.dates[0]}
          </text>
          <text x="1040" y="352" textAnchor="end">
            {equity.dates.at(-1)}
          </text>
        </svg>
      </div>
      <p className="caption chart-caption">
        Recorded daily equity. Dashed vertical rule: IS/OOS boundary. HOLDOUT
        remains sealed.
      </p>
    </>
  );
}
export function DatasetChart({ preview }: { preview: DatasetPreview }) {
  const rows = preview.rows.filter(
    (row) => typeof row.close === "number" && typeof row.timestamp === "string",
  );
  if (!rows.length)
    return <Empty>No visible price observations returned.</Empty>;
  const times = rows.map((row) => Date.parse(String(row.timestamp))),
    prices = rows.map((row) => Number(row.close)),
    volumes = rows.map((row) => Number(row.volume ?? 0));
  const low = Math.min(...prices),
    high = Math.max(...prices);
  const x = (t: number) =>
    25 + ((t - times[0]) / (times.at(-1)! - times[0] || 1)) * 370;
  const y = (v: number) => 155 - ((v - low) / (high - low || 1)) * 110;
  const maxVol = Math.max(...volumes) || 1;
  const splits = preview.splits as Record<
    string,
    { start?: string; end?: string }
  >;
  const boundary = splits.IS?.end ? x(Date.parse(splits.IS.end)) : null;
  return (
    <div className="chart-frame">
      <svg
        viewBox="0 0 500 250"
        className="chart"
        role="img"
        aria-label={`Visible IS and OOS prices from ${String(rows[0].timestamp).slice(0, 10)} to ${String(rows.at(-1)!.timestamp).slice(0, 10)}, close ${formatNumber(prices[0])} to ${formatNumber(prices.at(-1)!)} USD. HOLDOUT sealed.`}
      >
        <title>
          Visible close prices: {formatNumber(low)}–{formatNumber(high)} USD. No
          holdout observations.
        </title>
        <rect className="holdout" x="410" y="25" width="75" height="165" />
        {boundary != null && boundary >= 25 && boundary <= 395 && (
          <>
            <line
              className="boundary"
              x1={boundary}
              x2={boundary}
              y1="30"
              y2="190"
            />
            <text x={boundary + 5} y="20">
              OOS
            </text>
          </>
        )}
        <text x="25" y="20">
          {String(preview.coverage.split ?? "IS + OOS")}
        </text>
        <text x="447" y="70" textAnchor="middle">
          HOLDOUT
        </text>
        <text x="447" y="92" textAnchor="middle">
          sealed
        </text>
        {volumes.map((v, i) => (
          <rect
            className="volume"
            key={i}
            x={x(times[i])}
            y={190 - (v / maxVol) * 25}
            width="1.3"
            height={(v / maxVol) * 25}
          />
        ))}
        <path className="line-net" d={line(prices, times, x, y)} />
        <text x="25" y="212">
          {String(rows[0].timestamp).slice(0, 10)}
        </text>
        <text x="395" y="212" textAnchor="end">
          {String(rows.at(-1)!.timestamp).slice(0, 10)}
        </text>
        <text x="25" y="237">
          close USD {formatNumber(low)}–{formatNumber(high)} · volume ·{" "}
          {rows.length} points
        </text>
      </svg>
    </div>
  );
}
