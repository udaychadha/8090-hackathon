"""Eval 2 — friction. Net Sharpe across a cost grid, in sample."""

from __future__ import annotations

import pandas as pd

from factory.engine import backtest
from factory.evals import config
from factory.evals.common import EvalResult


def break_even_bps(sharpes: dict[float, float | None], threshold: float):
    """Linear interpolation of the cost where Sharpe crosses `threshold`.

    Returns (bps, note). bps is None when the strategy is already below the
    threshold at the cheapest grid point, or still above it at the dearest.
    """
    grid = sorted(sharpes)
    values = [sharpes[bps] for bps in grid]
    if any(value is None for value in values):
        return None, "sharpe undefined"
    if values[0] < threshold:
        return None, f"below {threshold} at {grid[0]:g} bps"
    for left, right, high, low in zip(grid, grid[1:], values, values[1:], strict=False):
        if high >= threshold > low:
            return left + (high - threshold) / (high - low) * (right - left), "interpolated"
    return None, f"above {threshold} through {grid[-1]:g} bps"


def friction_eval(
    bars: dict[str, pd.DataFrame], weights: pd.DataFrame, frequency: str
) -> EvalResult:
    results = {
        bps: backtest(bars, weights, frequency=frequency, round_trip_bps=bps)
        for bps in config.FRICTION_BPS_GRID
    }
    sharpes = {bps: result.metrics.sharpe for bps, result in results.items()}
    at_base = sharpes[config.BASE_COST_BPS]
    bps, note = break_even_bps(sharpes, config.FRICTION_MIN_SHARPE)
    base = results[config.BASE_COST_BPS].metrics
    return EvalResult(
        2,
        "friction",
        at_base is not None and at_base >= config.FRICTION_MIN_SHARPE,
        {
            "sharpe_by_bps": {f"{bps:g}": value for bps, value in sharpes.items()},
            "min_sharpe": config.FRICTION_MIN_SHARPE,
            "pass_bps": config.BASE_COST_BPS,
            "break_even_bps": bps,
            "break_even_note": note,
            "annualized_return": base.annualized_return,
            "max_drawdown": base.max_drawdown,
            "average_daily_turnover": base.average_daily_turnover,
            "trading_days": base.trading_days,
        },
    )
