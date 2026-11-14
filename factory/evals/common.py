"""Shared result type and the single Sharpe formula used on daily returns."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

import pandas as pd

# run(bars, params) -> validated target weights. The harness binds this to the
# sandbox; unit tests may bind it to an in-process function.
StrategyRunner = Callable[[dict[str, pd.DataFrame], dict | None], pd.DataFrame]


STD_FLOOR = 1e-12  # numerical guard, not a pass threshold


class EvalError(RuntimeError):
    """The harness (not the strategy) could not evaluate. Never a pass."""


@dataclass(frozen=True)
class EvalResult:
    number: int
    name: str
    passed: bool
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def daily_sharpe(daily: pd.Series) -> float | None:
    """Per-day (not annualised) Sharpe; None when undefined."""
    if len(daily) < 2:
        return None
    std = float(daily.std(ddof=1))
    # A constant series has a rounding-noise std (~1e-19), not exactly zero.
    return float(daily.mean() / std) if std > STD_FLOOR else None


def annualised_sharpe(daily: pd.Series) -> float | None:
    """mean / std * sqrt(252) — the same formula as engine.performance_metrics."""
    per_day = daily_sharpe(daily)
    return None if per_day is None else per_day * math.sqrt(252)
