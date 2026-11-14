import type { Event, EvalResult, Json } from "./types";
export const formatNumber = (value: number | null | undefined, digits = 2) =>
  value == null || !Number.isFinite(value) ? "—" : value.toFixed(digits);
export const formatDate = (value: string | null | undefined) =>
  value
    ? new Date(value).toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "Not recorded";
export const shortDate = (value: string | null | undefined) =>
  value?.slice(0, 10) ?? "—";
export const human = (value: string) => value.replaceAll("_", " ");
export const checkExpression = (check: {
  metric: string;
  op: string;
  default: number;
  relative_to: string | null;
}) =>
  `${check.metric} ${check.op === ">=" ? "≥" : check.op === "<=" ? "≤" : check.op} ${check.default}${check.relative_to ? ` × ${check.relative_to}` : ""}`;
export const mergeEvents = (previous: Event[], next: Event[]) =>
  Array.from(
    new Map([...previous, ...next].map((event) => [event.seq, event])).values(),
  ).sort((a, b) => a.seq - b.seq);
export const isTerminal = (status: string) =>
  ["COMPLETED", "FAILED", "VOID", "BLOCKED_DATA"].includes(status);
export const laneNames: Record<string, string> = {
  A: "Literal",
  B: "Conservative",
  C: "Regime-filtered",
};
export const laneDescriptions: Record<string, string> = {
  A: "The paper's rules and parameters",
  B: "Same signal, inverse-volatility sizing and turnover damping",
  C: "Same signal with a volatility or trend filter",
};
export const auditSuffix = (audit: boolean) =>
  audit ? "?include_voided=true" : "";

/** Compact descriptions use retained metrics only; they never judge a result. */
export function evalMetricSummary(result: EvalResult): string[] {
  const m = result.metrics;
  const value = (v: Json | undefined) =>
    typeof v === "number"
      ? v !== 0 && Math.abs(v) < 0.0001
        ? v.toExponential(2)
        : formatNumber(v, 3)
      : v == null
        ? "—"
        : String(v);
  const lines: string[] = [];
  if (result.n === 1)
    lines.push(
      `${Array.isArray(m.cuts) ? m.cuts.length : "—"} recorded cuts · tolerance ${value(m.tolerance)}`,
    );
  if (result.n === 2) {
    const costs = m.sharpe_by_bps;
    const sharpe =
      costs && typeof costs === "object" && !Array.isArray(costs)
        ? costs[String(m.pass_bps)]
        : undefined;
    lines.push(
      `Net Sharpe ${value(sharpe)} at ${value(m.pass_bps)} bps · minimum ${value(m.min_sharpe)}`,
    );
    if (m.break_even_note) lines.push(String(m.break_even_note));
  }
  if (result.n === 3) {
    lines.push(
      `Worst Sharpe ${value(m.worst_sharpe)} · base ${value(m.base_sharpe)}`,
    );
    lines.push(
      `Worst / base ${value(m.worst_ratio)} · minimum ${value(m.min_ratio)}`,
    );
  }
  if (result.n === 4) {
    lines.push(
      `OOS Sharpe ${value(m.oos_sharpe)} · must exceed 0 and be ≥ ${value(m.min_ratio)} × IS ${value(m.is_sharpe)}`,
    );
    lines.push(`IS Sharpe ${value(m.is_sharpe)} · must exceed 0`);
    const share = (v: Json | undefined) =>
      v == null ? "not applicable / unavailable" : value(v);
    lines.push(
      `${value(m.window_days)}-day PnL share: IS ${share(m.is_max_window_share)} / OOS ${share(m.oos_max_window_share)} · maximum ${value(m.max_share)}`,
    );
  }
  if (result.n === 5)
    lines.push(
      `DSR ${value(m.dsr)} · minimum ${value(m.min)} · ${value(m.n_trials)} trials${m.trial_scope === "all_runs" ? " across all runs" : ""}`,
    );
  if (m.reason) lines.push(String(m.reason));
  if (m.error) lines.push(String(m.error));
  return lines;
}
