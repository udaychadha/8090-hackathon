"""Eval 4 — decay. Out-of-sample Sharpe against in-sample, plus PnL concentration."""

from __future__ import annotations

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


def decay_eval(is_daily: pd.Series, oos_daily: pd.Series) -> EvalResult:
    """Pure function of daily net returns at base cost.

    The concentration rule is applied to IS and OOS separately; either one
    exceeding the cap fails. Undefined share (no positive PnL) fails.
    """
    is_sharpe, oos_sharpe = annualised_sharpe(is_daily), annualised_sharpe(oos_daily)
    sharpe_ok = (
        is_sharpe is not None
        and oos_sharpe is not None
        and oos_sharpe > 0
        and oos_sharpe >= config.DECAY_MIN_RATIO * is_sharpe
    )
    window, cap = config.CONCENTRATION_WINDOW_DAYS, config.CONCENTRATION_MAX_SHARE
    is_share, oos_share = max_window_share(is_daily, window), max_window_share(oos_daily, window)
    concentration_ok = all(share is not None and share <= cap for share in (is_share, oos_share))
    return EvalResult(
        4,
        "decay",
        sharpe_ok and concentration_ok,
        {
            "is_sharpe": is_sharpe,
            "oos_sharpe": oos_sharpe,
            "oos_to_is_ratio": (
                oos_sharpe / is_sharpe if is_sharpe and oos_sharpe is not None else None
            ),
            "min_ratio": config.DECAY_MIN_RATIO,
            "sharpe_ok": sharpe_ok,
            "is_max_window_share": is_share,
            "oos_max_window_share": oos_share,
            "window_days": window,
            "max_share": cap,
            "concentration_ok": concentration_ok,
            "is_days": len(is_daily),
            "oos_days": len(oos_daily),
            "cost_bps": config.BASE_COST_BPS,
        },
    )
