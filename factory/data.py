"""Market-data hygiene and explicit, chronological partition access.

Only trusted ingestion/audit code reads a whole tier. Strategy callers must
select IS or OOS; HOLDOUT requires an explicit opt-in reserved for WO-09.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

import exchange_calendars as xcals
import numpy as np
import pandas as pd

from factory.data_contract.errors import DataError, fail
from factory.data_contract.generated import SPEC

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
        SPEC["calendar"]["name"],
        start=pd.Timestamp(start) - pd.Timedelta(days=7),
        end=pd.Timestamp(through) + pd.Timedelta(days=7),
    )
    return calendar.schedule.loc[start:through, ["open", "close"]].copy()


@lru_cache(maxsize=32)
def expected_index(frequency: Frequency, start: str, through: str) -> pd.DatetimeIndex:
    validate_frequency(frequency)
    schedule = session_schedule(start, through)
    if frequency == "1day":
        index = schedule.index.tz_localize(SPEC["calendar"]["timezone"]).tz_convert("UTC")
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
        sessions = expected.tz_convert(SPEC["calendar"]["timezone"]).normalize()
        previous_close = frame.close.groupby(sessions).ffill(limit=SPEC["calendar"]["fill_limit"])
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
    first = int(len(index) * SPEC["splits"]["IS"])
    second = int(len(index) * (SPEC["splits"]["IS"] + SPEC["splits"]["OOS"]))
    # Inclusive bounds are convenient for Parquet predicate pushdown.
    return {
        name: {"start": index[left].isoformat(), "end": index[right - 1].isoformat()}
        for name, left, right in (
            ("IS", 0, first),
            ("OOS", first, second),
            ("HOLDOUT", second, len(index)),
        )
    }


def validate_tier_manifest(manifest, frequency, *, dataset):
    """Validate every tier field before trusting completion or partition bounds."""
    from factory.data_contract.storage import validate_request_metadata

    if not isinstance(manifest, dict):
        fail(dataset, "manifest.shape", detail="Expected a metadata object")
    validate_request_metadata(manifest, kind="price_bars", dataset=dataset)
    if manifest["frequency"] != frequency:
        fail(dataset, "manifest.frequency", detail=f"Expected {frequency}")
    if type(manifest.get("complete")) is not bool:
        fail(dataset, "manifest.complete", detail="Completion must be a boolean")
    symbols = manifest.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        fail(dataset, "manifest.symbols", detail="Expected a nonempty symbol list")
    pattern = SPEC["ontology"]["Instrument"]["fields"]["symbol"]["pattern"]
    if any(not isinstance(symbol, str) or not re.fullmatch(pattern, symbol) for symbol in symbols):
        fail(dataset, "manifest.symbols", detail="Invalid symbol")
    if len(set(symbols)) != len(symbols):
        fail(dataset, "manifest.symbols", detail="Symbols must be unique")
    if "normalizer_version" in manifest and (
        type(manifest["normalizer_version"]) is not int or manifest["normalizer_version"] < 1
    ):
        fail(dataset, "manifest.normalizer_version", detail="Expected a positive integer")
    failed = manifest.get("failed_symbols", [])
    if (
        not isinstance(failed, list)
        or any(not isinstance(symbol, str) or symbol not in symbols for symbol in failed)
        or len(set(failed)) != len(failed)
        or (manifest["complete"] and failed)
    ):
        fail(dataset, "manifest.failed_symbols", detail="Failed symbols contradict tier state")
    try:
        expected_splits = split_boundaries(
            expected_index(frequency, manifest["start"], manifest["through"])
        )
    except (ValueError, TypeError) as error:
        fail(dataset, "split_interval", detail=f"Invalid tier grid: {type(error).__name__}")
    if manifest.get("splits") != expected_splits:
        fail(dataset, "split_interval", detail="Tier splits differ from contract")
    return manifest


def load_bars(
    root: Path | str,
    frequency: Frequency,
    symbols: list[str],
    *,
    split: Literal["IS", "OOS", "HOLDOUT"],
    allow_holdout: bool = False,
) -> dict[str, pd.DataFrame]:
    """Validate the complete stored dataset, then expose only the requested partition."""
    from factory.data_contract.sessions import add_session_columns
    from factory.data_contract.storage import read_dataset, read_metadata

    root = Path(root)
    validate_frequency(frequency)
    if split not in ("IS", "OOS", "HOLDOUT"):
        raise DataError(f"Unknown split: {split}")
    if split == "HOLDOUT" and not allow_holdout:
        raise DataError("HOLDOUT is sealed until WO-09")
    tier_path = root / frequency / "manifest.json"
    manifest = validate_tier_manifest(read_metadata(tier_path), frequency, dataset=str(tier_path))
    if not manifest["complete"]:
        fail(str(tier_path), "manifest.complete", detail="Tier ingestion is incomplete")
    bounds = manifest["splits"][split]
    if not symbols or len(symbols) != len(set(symbols)):
        raise DataError("Universe must be nonempty and unique")
    result = {}
    for symbol in symbols:
        validate_symbol(symbol)
        if symbol not in manifest["symbols"]:
            raise DataError(f"{symbol} is not in the {frequency} universe")
        path = root / frequency / f"{symbol}.parquet"
        frame = read_dataset(
            path,
            expected={
                "kind": "price_bars",
                "frequency": frequency,
                **{key: manifest[key] for key in ("start", "through", "feed", "adjustment")},
            },
        )
        frame = frame.loc[pd.Timestamp(bounds["start"]) : pd.Timestamp(bounds["end"])].copy()
        if frame.empty:
            raise DataError(f"No {split} data for {symbol}")
        frame = add_session_columns(frame, frequency)
        frame.attrs["split"] = split
        result[symbol] = frame
    return result


def wide_frames(bars: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Align by timestamp without filling missing values or crossing sessions."""
    return {
        column: pd.concat(
            {symbol: frame[column] for symbol, frame in bars.items()}, axis=1
        ).sort_index()
        for column in OHLCV
    }
