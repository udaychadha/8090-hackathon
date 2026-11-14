"""Deterministic close-to-close accounting; all performance statistics are daily."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from factory.contract import validate_bars, validate_weights
from factory.data import DAILY_LIMITATION, Frequency, validate_frequency


class BacktestError(ValueError):
    """Accounting cannot continue with the supplied data or returns."""


@dataclass(frozen=True)
class Metrics:
    sharpe: float | None
    annualized_return: float | None
    max_drawdown: float
    average_daily_turnover: float
    trading_days: int
    total_return: float


@dataclass(frozen=True)
class BacktestResult:
    executed: pd.DataFrame
    asset_returns: pd.DataFrame
    gross_bar_returns: pd.Series
    turnover: pd.Series
    costs: pd.Series
    net_bar_returns: pd.Series
    daily_gross_returns: pd.Series
    daily_returns: pd.Series
    daily_turnover: pd.Series
    equity: pd.Series
    metrics: Metrics
    round_trip_bps: float
    limitations: tuple[str, ...]


def daily_compound(returns: pd.Series) -> pd.Series:
    """Compound within each New York trading date; do not invent weekend zeros."""
    if not isinstance(returns.index, pd.DatetimeIndex) or returns.index.tz is None:
        raise BacktestError("Returns require timezone-aware timestamps")
    dates = returns.index.tz_convert("America/New_York").normalize()
    daily = (1 + returns).groupby(dates).prod() - 1
    daily.index.name = "session"
    return daily


def performance_metrics(
    daily: pd.Series, daily_turnover: pd.Series, *, bar_equity: pd.Series | None = None
) -> Metrics:
    if daily.empty or not np.isfinite(daily.to_numpy()).all() or (daily < -1).any():
        raise BacktestError("Need nonempty, finite daily returns bounded below by -100%")
    count = len(daily)
    std = float(daily.std(ddof=1)) if count > 1 else 0.0
    # Undefined Sharpe is explicit, never silently presented as a pass or infinity.
    # 1e-12 guard: a constant series has rounding-noise std, which is not a Sharpe.
    sharpe = float(daily.mean() / std * math.sqrt(252)) if std > 1e-12 else None
    equity = (1 + daily).cumprod()
    total = float(equity.iloc[-1] - 1)
    if (daily == -1).any():
        annualized = -1.0
    else:
        exponent = float(np.log1p(daily).sum() * 252 / count)
        annualized = float(np.expm1(exponent)) if exponent < math.log(np.finfo(float).max) else None
    # Include starting capital (1.0), so a loss on day one is a drawdown.
    drawdown_equity = equity if bar_equity is None else bar_equity
    if not np.isfinite(drawdown_equity.to_numpy()).all():
        raise BacktestError("Compounded equity overflowed")
    high_water = drawdown_equity.cummax().clip(lower=1.0)
    drawdown = float((drawdown_equity / high_water - 1).min())
    return Metrics(sharpe, annualized, drawdown, float(daily_turnover.mean()), count, total)


def backtest(
    bars: dict[str, pd.DataFrame],
    target: pd.DataFrame,
    *,
    frequency: Frequency,
    round_trip_bps: float = 5.0,
) -> BacktestResult:
    """Apply exactly one execution lag, charge turnover, then compound to daily.

    Each evaluation slice starts flat; there is no terminal liquidation charge.
    Missing prices are never forward-filled here. Nonzero exposure with an
    unavailable close-to-close return is a data error.
    """
    validate_frequency(frequency)
    if not math.isfinite(round_trip_bps) or round_trip_bps < 0:
        raise BacktestError("Round-trip cost must be finite and nonnegative")
    index = validate_bars(bars)
    target = validate_weights(target, index, list(bars))
    close = pd.concat({symbol: frame.close for symbol, frame in bars.items()}, axis=1).reindex(
        index
    )
    executed = target.shift(1, fill_value=0.0)
    returns = close.pct_change(fill_method=None)
    invalid = returns.isna() & executed.ne(0)
    if invalid.any().any():
        row, column = np.argwhere(invalid.to_numpy())[0]
        raise BacktestError(
            f"Missing close-to-close price for held exposure at {index[row].isoformat()}, "
            f"{close.columns[column]}; repair data before evaluating"
        )
    returns = returns.fillna(0.0)
    gross = (executed * returns).sum(axis=1).rename("gross_return")
    turnover = (executed - executed.shift(1, fill_value=0.0)).abs().sum(axis=1).rename("turnover")
    costs = (turnover * (round_trip_bps / 2) / 10_000).rename("cost")
    net = (gross - costs).rename("net_return")
    if not np.isfinite(net.to_numpy()).all() or (net < -1).any():
        raise BacktestError("A bar lost more than all capital or produced non-finite PnL")
    daily = daily_compound(net).rename("net_return")
    daily_gross = daily_compound(gross).rename("gross_return")
    dates = index.tz_convert("America/New_York").normalize()
    daily_turnover = turnover.groupby(dates).sum()
    daily_turnover.index.name = "session"
    return BacktestResult(
        executed=executed,
        asset_returns=returns,
        gross_bar_returns=gross,
        turnover=turnover,
        costs=costs,
        net_bar_returns=net,
        daily_gross_returns=daily_gross,
        daily_returns=daily,
        daily_turnover=daily_turnover,
        equity=(1 + daily).cumprod().rename("equity"),
        metrics=performance_metrics(daily, daily_turnover, bar_equity=(1 + net).cumprod()),
        round_trip_bps=round_trip_bps,
        limitations=(DAILY_LIMITATION,) if frequency == "1day" else (),
    )
