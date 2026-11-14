"""Zero-cost sensitivity and decay, separate from all authoritative judgments.

Normal evaluation supplies already executed targets. Historical computation may
execute retained code, but never calls a model or runs the five-eval harness.
"""

from __future__ import annotations

from copy import deepcopy

import pandas as pd

from factory.contract import ContractViolation, read_strategy
from factory.data import load_bars
from factory.engine import BacktestError, backtest
from factory.evals import config
from factory.evals.common import EvalResult
from factory.evals.decay import decay_eval
from factory.evals.runner import sandbox_runner
from factory.evals.sensitivity import jittered_params, sensitivity_verdict
from factory.sandbox import StrategyExecutionError


def pending_diagnostics() -> dict:
    return {
        "schema_version": "1.0.0",
        "state": "pending",
        "cost_bps": 0,
        "eval_3": None,
        "eval_4": None,
        "label": None,
        "reason": None,
    }


def unavailable_diagnostics(reason: str) -> dict:
    return {**pending_diagnostics(), "state": "unavailable", "reason": reason}


def diagnostics_for_status(diagnostic: dict | None, status: str) -> dict:
    """Apply a descriptive label only after an authoritative terminal result."""
    if status == "RUNNING":
        return pending_diagnostics()
    result = (
        deepcopy(diagnostic)
        if diagnostic
        else unavailable_diagnostics(
            "Valid strategy targets and required data were not retained for diagnostics."
        )
    )
    if result["state"] == "pending":
        result = unavailable_diagnostics(
            "Valid strategy targets and required data were not available for diagnostics."
        )
    failed = status.startswith("FAILED_EVAL_") or status in {
        "BUG_UNRESOLVED",
        "INACTIVE",
        "BLOCKED_DATA",
        "INSUFFICIENT_SAMPLE",
    }
    signal = result["state"] == "complete" and all(
        result[key] and result[key]["passed"] for key in ("eval_3", "eval_4")
    )
    result["label"] = (
        ("signal before costs" if signal else "no signal before costs") if failed else None
    )
    return result


class JitterCapture:
    """Score each observed jitter immediately, avoiding retained target matrices."""

    def __init__(self, bars, params, frequency):
        self.bars, self.params, self.frequency = bars, params, frequency
        self.expected = jittered_params(params)
        self.rows = []
        self.reason = None

    def observe(self, params, weights=None, error=None):
        # Diagnostic recorder failures cannot change the strategy execution result.
        try:
            jitter = self.expected[len(self.rows)]
            if params != jitter["params"]:
                raise ValueError("Captured jitter order differs from the harness")
            row = {key: jitter[key] for key in ("param", "fraction", "value")}
            if error is not None:
                row.update(sharpe=None, error=f"{type(error).__name__}: jitter execution failed")
            else:
                try:
                    row["sharpe"] = backtest(
                        self.bars, weights, frequency=self.frequency, round_trip_bps=0
                    ).metrics.sharpe
                except (ContractViolation, StrategyExecutionError, BacktestError) as failure:
                    row.update(
                        sharpe=None, error=f"{type(failure).__name__}: jitter accounting failed"
                    )
            self.rows.append(row)
        except Exception as failure:
            self.reason = f"Gross jitter recording unavailable ({type(failure).__name__})."


def diagnostics_from_targets(is_bars, oos_bars, is_weights, oos_weights, capture) -> dict:
    """Apply the existing pass rules to zero-bps returns from the captured targets."""
    if capture.reason:
        return unavailable_diagnostics(capture.reason)
    if len(capture.rows) != len(capture.expected):
        return unavailable_diagnostics("Not all configured parameter jitters were captured.")
    is_result, oos_result = (
        backtest(bars, weights, frequency=capture.frequency, round_trip_bps=0)
        for bars, weights in ((is_bars, is_weights), (oos_bars, oos_weights))
    )
    base = is_result.metrics.sharpe
    verdict = sensitivity_verdict(base, [row["sharpe"] for row in capture.rows])
    sensitivity = EvalResult(
        3,
        "sensitivity",
        verdict["passed"],
        {
            "base_sharpe": base,
            "worst_sharpe": verdict["worst_sharpe"],
            "worst_ratio": verdict["worst_ratio"],
            "min_ratio": config.SENSITIVITY_MIN_RATIO,
            "cost_bps": 0,
            "jitters": capture.rows,
            "numeric_params_not_jittered": [
                key for key, value in capture.params.items() if type(value) in (int, float)
            ][config.SENSITIVITY_MAX_PARAMS :],
        },
    )
    decay = decay_eval(is_result.daily_returns, oos_result.daily_returns).to_dict()
    # decay_eval owns the rule; only its descriptive cost metadata changes here.
    decay["metrics"]["cost_bps"] = 0
    return {
        **pending_diagnostics(),
        "state": "complete",
        "eval_3": sensitivity.to_dict(),
        "eval_4": decay,
    }


def compute_diagnostics_file(path, data_root="data", timeout=None) -> dict:
    """Compute only gross Evals 3/4 from retained code and sealed IS/OOS inputs.

    Embedded PARAMS are authoritative for this calculation. All operational
    failures yield explicit unavailable evidence; exception text is not exported.
    """
    try:
        definition = read_strategy(path)
        timeout = (600 if definition.extra else 60) if timeout is None else timeout
        options = {"allow_empty_symbols": True} if definition.extra else {}
        is_bars, oos_bars = (
            load_bars(
                data_root, definition.frequency, list(definition.universe), split=split, **options
            )
            for split in ("IS", "OOS")
        )
        extra = None
        if definition.extra:
            from factory.event_execution import decision_times
            from factory.events import load_extra

            extra = load_extra(
                data_root,
                definition.extra,
                as_of=decision_times(oos_bars, definition.frequency).max(),
            )
        run = sandbox_runner(path, timeout=timeout, extra=extra)
        is_weights = run(is_bars)
        capture = JitterCapture(is_bars, definition.params, definition.frequency)
        for jitter in capture.expected:
            try:
                weights = run(is_bars, jitter["params"])
            except (ContractViolation, StrategyExecutionError, BacktestError) as error:
                capture.observe(jitter["params"], error=error)
            else:
                capture.observe(jitter["params"], weights)
        joined = type(is_bars)()
        for symbol, frame in is_bars.items():
            other = oos_bars[symbol]
            if not frame.empty and not other.empty and frame.index[-1] >= other.index[0]:
                raise ValueError("OOS must follow IS")
            joined[symbol] = pd.concat([frame, other])
        oos_weights = run(joined).loc[lambda weights: weights.index > is_weights.index[-1]]
        return diagnostics_from_targets(is_bars, oos_bars, is_weights, oos_weights, capture)
    except Exception as error:
        return unavailable_diagnostics(
            f"Retained-code gross computation unavailable ({type(error).__name__})."
        )
