"""Record chart artifacts from the exact strategy executions used by the evals.

The evaluation implementation and thresholds remain in factory.evals. This
adapter observes its base runs without adding strategy executions or exposing
OOS data to model workers. Each slice starts flat, as in the reference harness.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from factory.contract import activity_summary, read_strategy
from factory.data import load_bars
from factory.engine import backtest, daily_compound
from factory.evals import config
from factory.evals.runner import EvalReport, evaluate, sandbox_runner


@dataclass(frozen=True)
class RecordedEvaluation:
    report: EvalReport
    equity: dict | None = None
    boundaries: dict | None = None
    artifact_error: str | None = None
    activity: dict | None = None


def evaluate_file(path, data_root="data", *, timeout=60.0) -> RecordedEvaluation:
    definition = read_strategy(path)
    symbols = list(definition.universe)
    is_bars = load_bars(data_root, definition.frequency, symbols, split="IS")
    oos_bars = load_bars(data_root, definition.frequency, symbols, split="OOS")
    run = sandbox_runner(path, timeout=timeout)
    captured = {}

    def record_run(bars, params=None):
        weights = run(bars, params)
        if params is None:
            if bars is is_bars:
                captured["IS"] = weights.copy()
            elif all(
                bars[symbol].index.equals(is_bars[symbol].index.append(oos_bars[symbol].index))
                for symbol in symbols
            ):
                captured["joined"] = weights.copy()
        return weights

    report = evaluate(record_run, definition.params, definition.frequency, is_bars, oos_bars)
    try:
        is_weights = captured["IS"]
        oos_weights = captured["joined"].loc[lambda w: w.index > is_weights.index[-1]]
        results = [
            backtest(
                bars, weights, frequency=definition.frequency, round_trip_bps=config.BASE_COST_BPS
            )
            for bars, weights in ((is_bars, is_weights), (oos_bars, oos_weights))
        ]
        # Fail visibly if chart accounting ever drifts from the evaluated returns.
        pd.testing.assert_series_equal(results[1].daily_returns, report.oos_daily_returns)
        curves = {}
        for label, field in (("gross", "gross_bar_returns"), ("net", "net_bar_returns")):
            # An intraday split can fall within one session. Compound the joined
            # bar returns before daily aggregation so dates remain unique.
            daily = daily_compound(pd.concat([getattr(result, field) for result in results]))
            curves[label] = (1 + daily).cumprod()
        boundaries = {"is_end": is_weights.index[-1], "oos_end": oos_weights.index[-1]}
        equity = {
            "dates": [str(date.date()) for date in curves["net"].index],
            "gross": curves["gross"].tolist(),
            "net": curves["net"].tolist(),
            **{
                key: str(value.tz_convert("America/New_York").date())
                for key, value in boundaries.items()
            },
        }
        return RecordedEvaluation(
            report,
            equity,
            {key: value.isoformat() for key, value in boundaries.items()},
            activity={
                split: {
                    "active_bars": int(result.executed.ne(0).any(axis=1).sum()),
                    "total_bars": len(result.executed),
                    "days_traded": activity_summary(weights)["days_traded"],
                    "target_active_bars": activity_summary(weights)["active_bars"],
                }
                for split, result, weights in zip(
                    ("IS", "OOS"), results, (is_weights, oos_weights), strict=True
                )
            },
        )
    except Exception:
        # A missing chart is an operational failure, not a missing sibling trial:
        # retain this valid report for DSR accounting and diagnose the artifact.
        return RecordedEvaluation(report, artifact_error="Equity artifact could not be recorded")
