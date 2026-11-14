"""Market-data hygiene and explicit, chronological partition access.

Only trusted ingestion/audit code reads a whole tier. Strategy callers must
select IS or OOS; HOLDOUT requires an explicit opt-in reserved for WO-09.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

import exchange_calendars as xcals
import numpy as np
import pandas as pd

Frequency = Literal["1min", "1day"]
OHLCV = ["open", "high", "low", "close", "volume"]
INTRADAY_UNIVERSE = (
    "SPY QQQ IWM DIA TLT GLD XLF XLE XLK XLV XLY XLP XLI XLU "
    "KO PEP XOM CVX NVDA AMD JPM BAC V MA HD LOW GS MS UPS FDX "
    "WMT TGT MRK PFE AAPL MSFT AMZN GOOGL META TSLA NFLX AVGO "
    "COST UNH JNJ PG DIS CSCO INTC BA"
).split()
# Daily tier = current S&P 500 constituents plus these ETFs (owner decision,
# 2026-11-13: the WO-03 fixtures need them on the 2016+ sample).
DAILY_ETFS = ["SPY", "QQQ", "TLT", "GLD"]
DAILY_LIMITATION = (
    "The daily universe is today's S&P 500 membership; results carry survivorship bias."
)


class DataError(ValueError):
    """Missing, malformed, or incompatible market data."""


def validate_symbol(symbol: str) -> str:
    if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z][A-Z0-9.]{0,14}", symbol):
        raise DataError(f"Invalid equity symbol: {symbol!r}")
    return symbol


def validate_frequency(frequency: str) -> Frequency:
    if frequency not in ("1min", "1day"):
        raise DataError(f"Unsupported frequency: {frequency!r}")
    return frequency


@lru_cache(maxsize=8)
def session_schedule(start: str, through: str) -> pd.DataFrame:
    # Explicit bounds avoid exchange_calendars' rolling default date coverage.
    calendar = xcals.get_calendar(
        "XNYS",
        start=pd.Timestamp(start) - pd.Timedelta(days=7),
        end=pd.Timestamp(through) + pd.Timedelta(days=7),
    )
    return calendar.schedule.loc[start:through, ["open", "close"]].copy()


def expected_index(frequency: Frequency, start: str, through: str) -> pd.DatetimeIndex:
    validate_frequency(frequency)
    schedule = session_schedule(start, through)
    if frequency == "1day":
        index = schedule.index.tz_localize("America/New_York").tz_convert("UTC")
    else:
        pieces = [
            pd.date_range(row.open, row.close, freq="min", inclusive="left")
            for row in schedule.itertuples()
        ]
        index = pieces[0].append(pieces[1:]) if pieces else pd.DatetimeIndex([], tz="UTC")
    return index.rename("timestamp")


def normalize_bars(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise DataError("Bars require a timezone-aware DatetimeIndex")
    if missing := set(OHLCV) - set(frame.columns):
        raise DataError(f"Missing bar columns: {sorted(missing)}")
    frame = frame[OHLCV].copy()
    frame.index = frame.index.tz_convert("UTC").rename("timestamp")
    if frame.index.hasnans:
        raise DataError("Bar timestamps cannot be NaT")
    duplicates = frame[frame.index.duplicated(keep=False)]
    if not duplicates.empty and (duplicates.groupby(level=0).nunique() > 1).any().any():
        raise DataError("Conflicting duplicate bars")
    frame = frame[~frame.index.duplicated(keep="last")].sort_index().astype(float)
    if not np.isfinite(frame.to_numpy()).all():
        raise DataError("Source bars contain non-finite values")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise DataError("Source prices must be positive")
    if (frame.volume < 0).any():
        raise DataError("Source volume must be nonnegative")
    if (frame.high < frame[["open", "close", "low"]].max(axis=1)).any() or (
        frame.low > frame[["open", "close", "high"]].min(axis=1)
    ).any():
        raise DataError("Inconsistent OHLC prices")
    return frame


def clean_bars(
    raw: pd.DataFrame, frequency: Frequency, start: str, through: str
) -> tuple[pd.DataFrame, dict]:
    """Keep exchange sessions; fill at most five minutes, only within a session.

    Synthetic bars are flat at the previous close with zero volume. Unfillable
    rows stay absent and are counted, never silently interpolated.
    """
    source = normalize_bars(raw)
    expected = expected_index(frequency, start, through)
    frame = source.reindex(expected)
    observed = frame.close.notna()
    filled = pd.Series(False, index=expected)
    if frequency == "1min":
        sessions = expected.tz_convert("America/New_York").normalize()
        previous_close = frame.close.groupby(sessions).ffill(limit=5)
        filled = ~observed & previous_close.notna()
        for column in ("open", "high", "low", "close"):
            frame.loc[filled, column] = previous_close[filled]
        frame.loc[filled, "volume"] = 0.0
    frame["is_filled"] = filled
    frame = frame.loc[frame.close.notna()]
    stats = {
        "source_rows": len(source),
        "off_session_rows": int((~source.index.isin(expected)).sum()),
        "expected_rows": len(expected),
        "observed_rows": int(observed.sum()),
        "filled_rows": int(filled.sum()),
        "missing_rows": int((~observed & ~filled).sum()),
        "rows": len(frame),
        "fill_rate": float(filled.sum() / len(expected)) if len(expected) else 0.0,
    }
    return frame, stats


def split_boundaries(index: pd.DatetimeIndex) -> dict:
    """60/20/20 by the shared tier clock, never separately per symbol."""
    if len(index) < 5 or not index.is_monotonic_increasing or not index.is_unique:
        raise DataError("Splits need at least five ordered, unique timestamps")
    first, second = int(len(index) * 0.6), int(len(index) * 0.8)
    # Inclusive bounds are convenient for Parquet predicate pushdown.
    return {
        name: {"start": index[left].isoformat(), "end": index[right - 1].isoformat()}
        for name, left, right in (
            ("IS", 0, first),
            ("OOS", first, second),
            ("HOLDOUT", second, len(index)),
        )
    }


def load_bars(
    root: Path | str,
    frequency: Frequency,
    symbols: list[str],
    *,
    split: Literal["IS", "OOS", "HOLDOUT"],
    allow_holdout: bool = False,
) -> dict[str, pd.DataFrame]:
    """Load just the requested partition; there is deliberately no ALL option."""
    root = Path(root)
    validate_frequency(frequency)
    if split not in ("IS", "OOS", "HOLDOUT"):
        raise DataError(f"Unknown split: {split}")
    if split == "HOLDOUT" and not allow_holdout:
        raise DataError("HOLDOUT is sealed until WO-09")
    manifest = json.loads((root / frequency / "manifest.json").read_text())
    if not manifest.get("complete"):
        raise DataError(f"{frequency} ingestion is incomplete")
    bounds = manifest["splits"][split]
    if not symbols or len(symbols) != len(set(symbols)):
        raise DataError("Universe must be nonempty and unique")
    result = {}
    for symbol in symbols:
        validate_symbol(symbol)
        if symbol not in manifest["symbols"]:
            raise DataError(f"{symbol} is not in the {frequency} universe")
        path = root / frequency / f"{symbol}.parquet"
        frame = pd.read_parquet(
            path,
            columns=OHLCV,
            filters=[
                ("timestamp", ">=", pd.Timestamp(bounds["start"])),
                ("timestamp", "<=", pd.Timestamp(bounds["end"])),
            ],
        )
        if frame.empty:
            raise DataError(f"No {split} data for {symbol}")
        result[symbol] = normalize_bars(frame)
    return result


def wide_frames(bars: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Align by timestamp without filling missing values or crossing sessions."""
    return {
        column: pd.concat(
            {symbol: frame[column] for symbol, frame in bars.items()}, axis=1
        ).sort_index()
        for column in OHLCV
    }
