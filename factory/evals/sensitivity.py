"""Eval 3 — sensitivity. One-at-a-time parameter jitter, in sample at base cost."""

from __future__ import annotations

import math

import pandas as pd

from factory.contract import ContractViolation
from factory.engine import BacktestError, backtest
from factory.evals import config
from factory.evals.common import EvalResult, StrategyRunner
from factory.sandbox import StrategyExecutionError


def jitter_value(value, fraction: float):
    """Ints are rounded half away from zero and always move by at least 1."""
    if type(value) is int:
        step = max(1, math.floor(abs(value) * abs(fraction) + 0.5))
        return value + (step if fraction > 0 else -step)
    return value * (1 + fraction)


def jittered_params(params: dict) -> list[dict]:
    """One entry per distinct jitter: {"param", "fraction", "value", "params"}.

    Numeric means int or float (bool is not numeric). Only the first
    SENSITIVITY_MAX_PARAMS numeric entries, in PARAMS order, are jittered.
    """
    numeric = [key for key, value in params.items() if type(value) in (int, float)]
    jitters = []
    for key in numeric[: config.SENSITIVITY_MAX_PARAMS]:
        seen = {params[key]}
        for fraction in config.SENSITIVITY_JITTERS:
            value = jitter_value(params[key], fraction)
            if value in seen:  # e.g. a float 0.0, or small ints where 10% and 20% coincide
                continue
            seen.add(value)
            jitters.append(
                {
                    "param": key,
                    "fraction": fraction,
                    "value": value,
                    "params": {**params, key: value},
                }
            )
    return jitters


def sensitivity_verdict(base_sharpe: float | None, jittered: list[float | None]) -> dict:
    """Pure pass rule. An undefined or non-positive base Sharpe cannot pass:
    "50% of a negative number" would otherwise reward getting worse."""
    worst = None
    if jittered and all(value is not None for value in jittered):
        worst = min(jittered)
    base_ok = base_sharpe is not None and base_sharpe > 0
    if not jittered:
        passed, ratio = base_ok, None
    else:
        ratio = worst / base_sharpe if base_ok and worst is not None else None
        passed = ratio is not None and ratio >= config.SENSITIVITY_MIN_RATIO
    return {"passed": passed, "worst_sharpe": worst, "worst_ratio": ratio}


def sensitivity_eval(
    run: StrategyRunner,
    bars: dict[str, pd.DataFrame],
    params: dict,
    frequency: str,
    base_sharpe: float | None,
) -> EvalResult:
    rows = []
    for jitter in jittered_params(params):
        row = {key: jitter[key] for key in ("param", "fraction", "value")}
        try:
            weights = run(bars, jitter["params"])
            row["sharpe"] = backtest(
                bars, weights, frequency=frequency, round_trip_bps=config.BASE_COST_BPS
            ).metrics.sharpe
        except (ContractViolation, StrategyExecutionError, BacktestError) as error:
            # A strategy that breaks under a 10–20% nudge is fragile, not robust.
            row["sharpe"] = None
            row["error"] = f"{type(error).__name__}: {error}"
        rows.append(row)
    verdict = sensitivity_verdict(base_sharpe, [row["sharpe"] for row in rows])
    return EvalResult(
        3,
        "sensitivity",
        verdict["passed"],
        {
            "base_sharpe": base_sharpe,
            "worst_sharpe": verdict["worst_sharpe"],
            "worst_ratio": verdict["worst_ratio"],
            "min_ratio": config.SENSITIVITY_MIN_RATIO,
            "cost_bps": config.BASE_COST_BPS,
            "jitters": rows,
            "numeric_params_not_jittered": [
                key for key, value in params.items() if type(value) in (int, float)
            ][config.SENSITIVITY_MAX_PARAMS :],
        },
    )
