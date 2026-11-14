import type { GrossDiagnostics, Json } from "../types";
import { formatNumber } from "../evidence";

const number = (value: Json | undefined) =>
  formatNumber(typeof value === "number" ? value : null);

/** These retained observations never establish an authoritative eval verdict. */
export function GrossDiagnosticsPanel({
  diagnostic,
  status,
  compact = false,
}: {
  diagnostic: GrossDiagnostics | null | undefined;
  status: string;
  compact?: boolean;
}) {
  const sensitivity = diagnostic?.eval_3;
  const decay = diagnostic?.eval_4;
  const state = diagnostic?.state ?? (status === "RUNNING" ? "pending" : null);
  const metrics = (
    <div className="gross-metrics">
      <div>
        <p className="gross-outcome">
          Sensitivity ·{" "}
          {sensitivity
            ? sensitivity.passed
              ? "pass"
              : "failed"
            : "not measured"}
        </p>
        {sensitivity && (
          <p className="mono">
            Base Sharpe {number(sensitivity.metrics.base_sharpe)} · Worst Sharpe{" "}
            {number(sensitivity.metrics.worst_sharpe)} · Worst/base{" "}
            {number(sensitivity.metrics.worst_ratio)}
          </p>
        )}
      </div>
      <div>
        <p className="gross-outcome">
          Decay · {decay ? (decay.passed ? "pass" : "failed") : "not measured"}
        </p>
        {decay && (
          <>
            <p className="mono">
              IS Sharpe {number(decay.metrics.is_sharpe)} · OOS Sharpe{" "}
              {number(decay.metrics.oos_sharpe)} · OOS/IS{" "}
              {number(decay.metrics.oos_to_is_ratio)}
            </p>
            <p className="mono">
              IS 5-day concentration {number(decay.metrics.is_max_window_share)}{" "}
              · OOS 5-day concentration{" "}
              {number(decay.metrics.oos_max_window_share)}
            </p>
          </>
        )}
      </div>
    </div>
  );
  return (
    <section
      aria-label="Gross diagnostics"
      className={`gross-diagnostics ${compact ? "gross-compact" : "card"}`}
    >
      <div className="gross-heading">
        <div className="row between">
          {!compact && <h2>Gross diagnostics</h2>}
          <span className="eyebrow">Diagnostic · 0 bps</span>
        </div>
        {diagnostic?.label && <p className="gross-label">{diagnostic.label}</p>}
        {state !== "complete" && (
          <p className="muted">
            {state === "pending"
              ? "Pending"
              : state === "unavailable"
                ? "Unavailable"
                : "Not recorded"}
          </p>
        )}
        {diagnostic?.reason && <p className="caption">{diagnostic.reason}</p>}
      </div>
      {(sensitivity || decay) && metrics}
      {!compact && (
        <p className="caption">
          Same sensitivity and decay checks at zero trading cost. These
          diagnostics do not change status, evals passed, or VERIFIED
          eligibility. Zero bps removes trading-cost deductions; it does not
          imply free computation or realistically executable returns. — means
          undefined or not measured, not zero.
        </p>
      )}
      {state === "unavailable" && (
        <p className="caption">
          Missing measurements are not evidence of economic failure.
        </p>
      )}
    </section>
  );
}
