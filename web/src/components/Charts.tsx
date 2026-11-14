import type { DatasetPreview, Equity } from "../types";
import { Empty } from "./common";
import { InteractiveChart } from "./InteractiveChart";
import type { ChartPoint } from "./InteractiveChart";

const number = (v: number, digits = 4) =>
  v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
const signed = (v: number, digits = 4) =>
  `${v < 0 ? "−" : v > 0 ? "+" : ""}${number(Math.abs(v), digits)}`;
function change(value: number, base: number | undefined) {
  if (base == null || base === 0) return "Unavailable";
  return `${signed(value - base)} (${signed((value / base - 1) * 100, 2)}%)`;
}
export function EquityChart({
  equity,
  title = "Equity",
}: {
  equity: Equity | null;
  title?: string;
}) {
  if (!equity || !equity.dates.length)
    return <Empty>No equity curve was recorded for this variant.</Empty>;
  if (
    equity.gross.length !== equity.dates.length ||
    equity.net.length !== equity.dates.length ||
    equity.dates.some(
      (d, i) =>
        !Number.isFinite(Date.parse(d)) ||
        !Number.isFinite(equity.gross[i]) ||
        !Number.isFinite(equity.net[i]),
    )
  )
    return <Empty>The recorded equity curve is incomplete.</Empty>;
  const points: ChartPoint[] = equity.dates.map((date, i) => ({
    time: Date.parse(date),
    date: date.slice(0, 10),
    label: date.slice(0, 10),
    values: [equity.gross[i], equity.net[i]],
    details: [
      ["Gross · index", number(equity.gross[i])],
      ["Net · index", number(equity.net[i])],
      ["Net from first point", change(equity.net[i], equity.net[0])],
      ["Net Δ previous point", change(equity.net[i], equity.net[i - 1])],
      ["Gross − net · index", number(equity.gross[i] - equity.net[i])],
    ],
  }));
  return (
    <InteractiveChart
      key={`${title}:${equity.dates[0]}:${equity.dates.at(-1)}`}
      model={{
        title,
        kind: "equity",
        points,
        primary: 1,
        series: [
          { label: "gross", className: "line-gross" },
          { label: "net of 5 bps", className: "line-net" },
        ],
        isEnd: equity.is_end,
        caption:
          "Recorded daily equity indices, not account dollars. Dashed rule: IS/OOS boundary. HOLDOUT remains sealed.",
      }}
    />
  );
}
export function DatasetChart({
  preview,
  title = "Dataset price",
}: {
  preview: DatasetPreview;
  title?: string;
}) {
  const rows = preview.rows.filter(
    (row) =>
      typeof row.close === "number" &&
      Number.isFinite(row.close) &&
      typeof row.timestamp === "string" &&
      Number.isFinite(Date.parse(row.timestamp)),
  );
  if (!rows.length)
    return <Empty>No visible price observations returned.</Empty>;
  const points: ChartPoint[] = rows.map((row, i) => ({
    time: Date.parse(String(row.timestamp)),
    date: String(row.timestamp).slice(0, 10),
    label: new Date(String(row.timestamp))
      .toISOString()
      .replace("T", " ")
      .replace(".000Z", " UTC"),
    values: [Number(row.close)],
    volume:
      typeof row.volume === "number" && Number.isFinite(row.volume)
        ? row.volume
        : undefined,
    details: [
      ["Close · USD", number(Number(row.close))],
      ["From first shown", change(Number(row.close), Number(rows[0].close))],
      [
        "Previous shown Δ",
        change(Number(row.close), i ? Number(rows[i - 1].close) : undefined),
      ],
      [
        "Volume",
        typeof row.volume === "number" && Number.isFinite(row.volume)
          ? `${number(row.volume, 0)} shares`
          : "Unavailable",
      ],
      [
        "Bar",
        row.is_filled === true
          ? "Locally filled"
          : row.is_filled === false
            ? "Provider observation"
            : "Provenance unavailable",
      ],
    ],
  }));
  const splits = preview.splits as Record<string, { end?: string }>;
  return (
    <InteractiveChart
      key={`${preview.dataset_id}:${preview.coverage.split}:${points[0].time}:${points.at(-1)!.time}`}
      model={{
        title,
        kind: "dataset",
        points,
        primary: 0,
        series: [{ label: "close · USD", className: "line-net" }],
        isEnd: splits.IS?.end ?? null,
        caption: `${preview.downsampled ? "Downsampled" : "Retained"} preview · ${points.length.toLocaleString()} observations. Deltas compare shown points. UTC bar labels. Volume in shares. HOLDOUT remains sealed.`,
      }}
    />
  );
}
