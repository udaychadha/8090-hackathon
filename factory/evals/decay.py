"""Eval 4 — decay. Out-of-sample Sharpe against in-sample, plus PnL concentration."""

from __future__ import annotations

import math
from collections.abc import Mapping
from numbers import Real

import pandas as pd

from factory.evals import config
from factory.evals.common import EvalResult, annualised_sharpe


def max_window_share(daily: pd.Series, window: int) -> float | None:
    """Largest share of total PnL (sum of daily returns) held by `window`
    consecutive days. None when total PnL is not positive (share undefined)."""
    total = float(daily.sum())
    if total <= 0:
        return None
    if len(daily) <= window:
        return 1.0
    return float(daily.rolling(window).sum().max() / total)


def _finite(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def decay_from_metrics(metrics: Mapping) -> EvalResult:
    """Rejudge retained Eval 4 evidence without returns or strategy execution.

    PnL here means the sum of daily net returns, not compounded equity return.
    A finite historical Sharpe has the sign of that sum (mean / positive std),
    so it establishes the sign when an explicit total was not retained. It
    never establishes an amount. Missing sign/share evidence fails closed.
    Positive-PnL shares can exceed one when other windows lose money; preserve
    those observations, rather than clipping them. The input is not mutated.
    """
    result = dict(metrics)
    is_sharpe, oos_sharpe = metrics.get("is_sharpe"), metrics.get("oos_sharpe")
    sharpe_ok = (
        _finite(is_sharpe)
        and _finite(oos_sharpe)
        and is_sharpe > 0
        and oos_sharpe > 0
        and oos_sharpe >= config.DECAY_MIN_RATIO * is_sharpe
    )
    window, cap = config.CONCENTRATION_WINDOW_DAYS, config.CONCENTRATION_MAX_SHARE
    concentration_ok = True
    for period in ("is", "oos"):
        total = metrics.get(f"{period}_total_pnl")
        # Legacy records have no total; a defined Sharpe proves its sign.
        sign_evidence = total if total is not None else metrics.get(f"{period}_sharpe")
        positive_pnl = _finite(sign_evidence) and sign_evidence > 0
        share = metrics.get(f"{period}_max_window_share")
        if not positive_pnl or not _finite(share):
            share = None
        result[f"{period}_max_window_share"] = share
        concentration_ok = concentration_ok and share is not None and share <= cap
    result.update(
        {
            "oos_to_is_ratio": (
                oos_sharpe / is_sharpe
                if _finite(is_sharpe) and is_sharpe > 0 and _finite(oos_sharpe)
                else None
            ),
            "min_ratio": config.DECAY_MIN_RATIO,
            "sharpe_ok": sharpe_ok,
            "window_days": window,
            "max_share": cap,
            "concentration_ok": concentration_ok,
        }
    )
    return EvalResult(4, "decay", sharpe_ok and concentration_ok, result)


def decay_eval(is_daily: pd.Series, oos_daily: pd.Series) -> EvalResult:
    """Judge daily net returns at base cost, applying concentration per period."""
    window = config.CONCENTRATION_WINDOW_DAYS
    return decay_from_metrics(
        {
            "is_sharpe": annualised_sharpe(is_daily),
            "oos_sharpe": annualised_sharpe(oos_daily),
            "is_total_pnl": float(is_daily.sum()),
            "oos_total_pnl": float(oos_daily.sum()),
            "is_max_window_share": max_window_share(is_daily, window),
            "oos_max_window_share": max_window_share(oos_daily, window),
            "is_days": len(is_daily),
            "oos_days": len(oos_daily),
            "cost_bps": config.BASE_COST_BPS,
        }
    )
