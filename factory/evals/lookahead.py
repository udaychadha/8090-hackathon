"""Eval 1 — lookahead. Weights up to a cut must not change when the future is removed."""

from __future__ import annotations

import numpy as np
import pandas as pd

from factory.data import EventBars
from factory.evals import config
from factory.evals.common import EvalError, EvalResult, StrategyRunner


class LookaheadBiasError(Exception):
    """Bug-class failure: a weight at `timestamp` for `symbol` depended on later bars."""

    def __init__(self, timestamp, symbol, cut_fraction, full_value, truncated_value):
        self.timestamp = pd.Timestamp(timestamp)
        self.symbol = symbol
        self.cut_fraction = cut_fraction
        self.full_value = full_value
        self.truncated_value = truncated_value
        super().__init__(
            f"Lookahead bias: weight for {symbol} at {self.timestamp.isoformat()} is "
            f"{full_value!r} with the full sample but {truncated_value!r} when data after the "
            f"{cut_fraction:.0%} cut is removed"
        )


def union_index(bars: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
    index = None
    for frame in bars.values():
        index = frame.index if index is None else index.union(frame.index)
    return index.sort_values()


def truncate_bars(bars: dict[str, pd.DataFrame], last: pd.Timestamp) -> dict[str, pd.DataFrame]:
    cut = {symbol: frame.loc[:last] for symbol, frame in bars.items()}
    empty = [symbol for symbol, frame in cut.items() if frame.empty]
    if empty and not isinstance(bars, EventBars):
        raise EvalError(f"No bars before the lookahead cut {last.isoformat()} for {empty}")
    if len(empty) == len(cut):
        raise EvalError(f"No observed bars before the lookahead cut {last.isoformat()}")
    return EventBars(cut) if isinstance(bars, EventBars) else cut


def first_difference(full: pd.DataFrame, truncated: pd.DataFrame, tolerance: float):
    """First (timestamp, symbol, full, truncated) that differs, else None. NaN == NaN."""
    reference = full.loc[truncated.index, truncated.columns]
    a, b = reference.to_numpy(dtype=float), truncated.to_numpy(dtype=float)
    both_nan = np.isnan(a) & np.isnan(b)
    with np.errstate(invalid="ignore"):
        same = np.abs(a - b) <= tolerance
    bad = ~(same | both_nan)
    if not bad.any():
        return None
    row, column = np.argwhere(bad)[0]  # row-major: earliest timestamp, then symbol
    return (
        truncated.index[row],
        truncated.columns[column],
        float(a[row, column]),
        float(b[row, column]),
    )


def lookahead_eval(
    run: StrategyRunner, bars: dict[str, pd.DataFrame]
) -> tuple[EvalResult, pd.DataFrame]:
    """Returns (result, full-sample weights). Raises LookaheadBiasError on failure."""
    index = union_index(bars)
    full = run(bars, None)
    cuts = []
    for fraction in config.LOOKAHEAD_CUT_FRACTIONS:
        count = int(len(index) * fraction)
        if not 0 < count < len(index):
            raise EvalError(f"Sample too short for a {fraction:.0%} lookahead cut")
        last = index[count - 1]
        truncated = run(truncate_bars(bars, last), None)
        difference = first_difference(full, truncated, config.LOOKAHEAD_TOLERANCE)
        if difference is not None:
            timestamp, symbol, full_value, truncated_value = difference
            raise LookaheadBiasError(timestamp, symbol, fraction, full_value, truncated_value)
        cuts.append({"fraction": fraction, "bars": count, "last_timestamp": last.isoformat()})
    return (
        EvalResult(1, "lookahead", True, {"tolerance": config.LOOKAHEAD_TOLERANCE, "cuts": cuts}),
        full,
    )
