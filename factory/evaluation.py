"""Record chart artifacts from the exact strategy executions used by the evals.

The evaluation implementation and thresholds remain in factory.evals. This
adapter observes its base runs without adding strategy executions or exposing
OOS data to model workers. Each slice starts flat, as in the reference harness.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import pandas as pd

from factory import gross_diagnostics
from factory.contract import activity_summary, read_strategy
from factory.data import load_bars
from factory.engine import backtest, daily_compound
from factory.evals import config
from factory.evals.runner import EvalReport, evaluate, sandbox_runner

_PROGRESS = ContextVar("evaluation_progress", default=None)


@contextmanager
def evaluation_progress(observer):
    """Scope a durable progress observer to one caller, never global harness state."""
    token = _PROGRESS.set(observer)
    try:
        yield
    finally:
        _PROGRESS.reset(token)


def _emit_progress(number, status, message, result=None):
    observer = _PROGRESS.get()
    if observer is not None:
        observer(number, status, message, result)


def _eval_started(number):
    _emit_progress(number, "started", f"Eval {number} started")


def _eval_result(result):
    status = "passed" if result.passed else "failed"
    _emit_progress(result.number, status, f"Eval {result.number} {status}", result)


@dataclass(frozen=True)
class RecordedEvaluation:
    report: EvalReport
    equity: dict | None = None
    boundaries: dict | None = None
    artifact_error: str | None = None
    activity: dict | None = None
    cost_sharpes: dict | None = None
    gross_diagnostics: dict | None = None


def evaluate_file(
    path, data_root="data", *, timeout=None, on_eval2_started=None
) -> RecordedEvaluation:
    definition = read_strategy(path)
    timeout = (600 if definition.extra else 60) if timeout is None else timeout
    symbols = list(definition.universe)
    options = {"allow_empty_symbols": True} if definition.extra else {}
    is_bars = load_bars(data_root, definition.frequency, symbols, split="IS", **options)
    oos_bars = load_bars(data_root, definition.frequency, symbols, split="OOS", **options)
    extra = None
    if definition.extra:
        from factory.event_execution import decision_times
        from factory.events import load_extra

        extra = load_extra(
            data_root, definition.extra, as_of=decision_times(oos_bars, definition.frequency).max()
        )
    run = sandbox_runner(path, timeout=timeout, extra=extra)
    captured = {}
    jitter_capture = gross_diagnostics.JitterCapture(
        is_bars, definition.params, definition.frequency
    )

    def record_run(bars, params=None):
        jitter = bars is is_bars and params is not None
        step = len(jitter_capture.rows) + 1
        total = len(jitter_capture.expected)
        if jitter:
            _emit_progress(3, "info", f"Eval 3 parameter jitter {step}/{total} started")
        try:
            weights = run(bars, params)
        except Exception as error:
            if jitter:
                jitter_capture.observe(params, error=error)
                _emit_progress(
                    3, "info", f"Eval 3 parameter jitter {step}/{total} execution failed"
                )
            raise
        if jitter:
            jitter_capture.observe(params, weights)
            _emit_progress(3, "info", f"Eval 3 parameter jitter {step}/{total} execution complete")
        if params is None:
            if bars is is_bars:
                captured["IS"] = weights.copy()
            elif all(
                bars[symbol].index.equals(is_bars[symbol].index.append(oos_bars[symbol].index))
                for symbol in symbols
            ):
                captured["joined"] = weights.copy()
        return weights

    report = evaluate(
        record_run,
        definition.params,
        definition.frequency,
        is_bars,
        oos_bars,
        on_eval2_started=on_eval2_started,
        on_eval_started=_eval_started,
        on_eval_result=_eval_result,
    )
    try:
        diagnostics = gross_diagnostics.diagnostics_from_targets(
            is_bars,
            oos_bars,
            captured["IS"],
            captured["joined"].loc[lambda w: w.index > captured["IS"].index[-1]],
            jitter_capture,
        )
    except Exception as error:
        diagnostics = gross_diagnostics.unavailable_diagnostics(
            f"Gross diagnostics unavailable ({type(error).__name__})."
        )
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
            gross_diagnostics=diagnostics,
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
            cost_sharpes={
                split: {
                    f"{cost:g}": backtest(
                        bars, weights, frequency=definition.frequency, round_trip_bps=cost
                    ).metrics.sharpe
                    for cost in config.FRICTION_BPS_GRID
                }
                for split, bars, weights in (
                    ("IS", is_bars, is_weights),
                    ("OOS", oos_bars, oos_weights),
                )
            },
        )
    except Exception:
        # A missing chart is an operational failure, not a missing sibling trial:
        # retain this valid report for DSR accounting and diagnose the artifact.
        return RecordedEvaluation(
            report,
            artifact_error="Equity artifact could not be recorded",
            gross_diagnostics=diagnostics,
        )
