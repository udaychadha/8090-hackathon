"""Read-only, paginated Alpaca ingestion. Run with --help for commands."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import io
import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from dotenv import load_dotenv

from factory.data import (
    DAILY_ETFS,
    DAILY_LIMITATION,
    INTRADAY_UNIVERSE,
    OHLCV,
    DataError,
    clean_bars,
    expected_index,
    split_boundaries,
    validate_symbol,
    validate_tier_manifest,
)
from factory.data_contract import validate_price_bars
from factory.data_contract.errors import fail
from factory.data_contract.storage import manifest_path, read_dataset, read_metadata, write_dataset

DATA_URL = "https://data.alpaca.markets/v2/stocks/bars"
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NORMALIZER_VERSION = 1


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def atomic_parquet(path: Path, frame: pd.DataFrame, **context) -> None:
    write_dataset(
        path, frame, kind="price_bars", source=DATA_URL, feed="sip", adjustment="all", **context
    )


def event(root: Path, kind: str, **fields) -> None:
    payload = {"time": datetime.now(ZoneInfo("UTC")).isoformat(), "event": kind, **fields}
    with (root / "ingest.jsonl").open("a") as output:
        output.write(json.dumps(payload, allow_nan=False) + "\n")


class AlpacaBars:
    """SDK-validated parameters, explicit HTTP pages, one shared rate limiter.

    We use our own page loop because the SDK auto-pagination hides individual
    requests from a caller's rate limiter. This client has no trading methods.
    """

    def __init__(
        self, key: str, secret: str, *, session=None, sleep=time.sleep, clock=time.monotonic
    ):
        if not key or not secret:
            raise DataError(
                "Set APCA_API_KEY_ID and APCA_API_SECRET_KEY in .env or the environment"
            )
        self.session = session or requests.Session()
        self.session.headers.update({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
        self.sleep, self.clock = sleep, clock
        self.next_request = 0.0
        self.requests = 0

    def _page(self, params: dict) -> dict:
        for attempt in range(6):
            self.sleep(max(0.0, self.next_request - self.clock()))
            self.next_request = self.clock() + 0.31  # less than 200 requests/minute
            self.requests += 1
            try:
                response = self.session.get(DATA_URL, params=params, timeout=(10, 60))
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 5:
                    raise DataError("Alpaca connection failed after six attempts") from None
                self.sleep(min(2**attempt, 60))
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 5:
                    raise DataError(f"Alpaca HTTP {response.status_code} after six attempts")
                try:
                    delay = float(response.headers.get("Retry-After", 2**attempt))
                except ValueError:
                    delay = 2**attempt
                self.sleep(min(max(delay, 0), 60))
                continue
            if response.status_code >= 400:
                # Do not dump request headers or credentials in a traceback/log.
                raise DataError(
                    f"Alpaca HTTP {response.status_code}; check credentials, SIP entitlement, "
                    "symbols and date bounds. No alternate feed will be substituted."
                )
            payload = response.json()
            if not isinstance(payload, dict) or "bars" not in payload:
                raise DataError("Alpaca response has no bars mapping")
            return payload
        raise AssertionError("unreachable")

    def fetch(self, symbol: str, frequency: str, start: str, through: str) -> pd.DataFrame:
        raw = self._fetch_raw(symbol, frequency, start, through)
        clean, stats = clean_bars(raw, frequency, start, through)
        validate_price_bars(
            clean,
            dataset=f"alpaca/{frequency}/{symbol}",
            frequency=frequency,
            start=start,
            through=through,
        )
        clean.attrs["ingest_stats"] = stats
        return clean

    def _fetch_raw(self, symbol: str, frequency: str, start: str, through: str) -> pd.DataFrame:
        validate_symbol(symbol)
        begin = pd.Timestamp(start, tz="America/New_York")
        end = pd.Timestamp(through, tz="America/New_York") + pd.DateOffset(days=1)
        request = StockBarsRequest(
            symbol_or_symbols=[symbol],
            timeframe=TimeFrame.Minute if frequency == "1min" else TimeFrame.Day,
            start=begin.to_pydatetime(),
            end=(end - pd.Timedelta(microseconds=1)).to_pydatetime(),
            limit=10_000,
            feed=DataFeed.SIP,
            adjustment=Adjustment.ALL,
        )
        params = request.to_request_fields()
        params.update(
            timeframe=str(request.timeframe),
            feed=request.feed.value,
            adjustment=request.adjustment.value,
            sort="asc",
        )
        rows, seen_tokens = [], set()
        while True:
            page = self._page(params)
            mapping = page["bars"] or {}
            if set(mapping) - {symbol}:
                raise DataError("Alpaca returned an unrequested symbol")
            rows.extend(mapping.get(symbol, []))
            token = page.get("next_page_token")
            if not token:
                break
            if token in seen_tokens:
                raise DataError("Alpaca repeated a pagination token")
            seen_tokens.add(token)
            params["page_token"] = token
        if not rows:
            return pd.DataFrame(
                columns=OHLCV, index=pd.DatetimeIndex([], tz="UTC", name="timestamp")
            )
        frame = pd.DataFrame(rows).rename(
            columns={
                "t": "timestamp",
                "o": "open",
                "h": "high",
                "l": "low",
                "c": "close",
                "v": "volume",
            }
        )
        frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
        return frame.set_index("timestamp")[OHLCV]


def read_universe(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str)
    frame = frame.rename(columns={"Symbol": "symbol", "Security": "name"})
    if "symbol" not in frame:
        raise DataError("S&P 500 CSV needs a symbol or Symbol column")
    # Alpaca uses dots (BRK.B, BF.B), not the hyphens used by some vendors.
    frame["symbol"] = frame.symbol.str.strip().str.upper().str.replace("-", ".", regex=False)
    for symbol in frame.symbol:
        validate_symbol(symbol)
    if frame.symbol.duplicated().any() or not 450 <= len(frame) <= 550:
        raise DataError("S&P 500 snapshot must contain 450–550 unique share-class symbols")
    return frame


def sp500_universe(root: Path, supplied: Path | None = None) -> list[str]:
    snapshot = root / "sp500.csv"
    if supplied:
        frame = read_universe(supplied)
        source = "owner-supplied CSV"
    elif snapshot.exists():
        return read_universe(snapshot).symbol.tolist()
    else:
        response = requests.get(
            SP500_URL, headers={"User-Agent": "FinancialModelsArena/0.1"}, timeout=30
        )
        response.raise_for_status()
        tables = pd.read_html(io.StringIO(response.text), attrs={"id": "constituents"})
        if len(tables) != 1:
            raise DataError(
                "Could not identify the S&P 500 constituents table; provide --sp500-csv"
            )
        temporary = root / "sp500.download.csv"
        tables[0].to_csv(temporary, index=False)
        try:
            frame = read_universe(temporary)
        finally:
            temporary.unlink(missing_ok=True)
        source = SP500_URL
    frame.to_csv(snapshot, index=False)
    atomic_json(
        root / "sp500.source.json",
        {
            "source": source,
            "retrieved_at": datetime.now(ZoneInfo("UTC")).isoformat(),
            "symbols": len(frame),
            "limitation": DAILY_LIMITATION,
        },
    )
    return frame.symbol.tolist()


def daily_universe(root: Path, supplied: Path | None = None) -> list[str]:
    """S&P 500 constituents followed by the daily-tier ETFs."""
    constituents = sp500_universe(root, supplied)
    return constituents + [symbol for symbol in DAILY_ETFS if symbol not in constituents]


def month_ranges(start: str, through: str):
    left, final = pd.Timestamp(start), pd.Timestamp(through)
    while left <= final:
        right = min(left + pd.offsets.MonthEnd(0), final)
        yield left.date().isoformat(), right.date().isoformat()
        left = right + pd.Timedelta(days=1)


def _validate_stats(stats, frame, frequency, start, through, *, dataset):
    """Reconcile retained-data counts; check consistency of unavailable raw counts."""
    if not isinstance(stats, dict):
        fail(dataset, "ingest_stats.shape", detail="Expected a statistics object")
    expected_rows = len(expected_index(frequency, start, through))
    filled_rows = int(frame.is_filled.sum())
    facts = {
        "expected_rows": expected_rows,
        "observed_rows": len(frame) - filled_rows,
        "filled_rows": filled_rows,
        "missing_rows": expected_rows - len(frame),
        "rows": len(frame),
    }
    for key in (*facts, "source_rows", "off_session_rows"):
        if type(stats.get(key)) is not int or stats[key] < 0:
            fail(dataset, f"ingest_stats.{key}", detail="Expected a nonnegative integer")
        if key in facts and stats[key] != facts[key]:
            fail(dataset, f"ingest_stats.{key}", detail=f"Expected {facts[key]}")
    if stats["source_rows"] - stats["off_session_rows"] != facts["observed_rows"]:
        fail(dataset, "ingest_stats.source_rows", detail="Source/off-session counts disagree")
    if (
        type(stats.get("fill_rate")) not in (int, float)
        or stats["fill_rate"] != filled_rows / expected_rows
    ):
        fail(dataset, "ingest_stats.fill_rate", detail="Fill rate differs from validated bars")
    return stats


def ingest_symbol(
    client, root: Path, frequency: str, symbol: str, start: str, through: str
) -> dict:
    request = {
        "symbol": symbol,
        "frequency": frequency,
        "start": start,
        "through": through,
        "feed": "sip",
        "adjustment": "all",
        "normalizer_version": NORMALIZER_VERSION,
    }
    request_id = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()[:16]
    destination = root / frequency / f"{symbol}.parquet"
    metadata_path = root / "metadata" / frequency / f"{symbol}.json"
    if destination.exists() and metadata_path.exists():
        metadata = read_metadata(metadata_path)
        if metadata.get("request_id") == request_id:
            frame = read_dataset(
                destination,
                expected={
                    "kind": "price_bars",
                    "frequency": frequency,
                    "start": start,
                    "through": through,
                    "feed": "sip",
                    "adjustment": "all",
                },
            )
            _validate_stats(metadata, frame, frequency, start, through, dataset=str(metadata_path))
            for key, value in request.items():
                if metadata.get(key) != value:
                    fail(str(metadata_path), f"manifest.{key}", detail="Request metadata differs")
            for key, value in {
                "first_timestamp": frame.index[0].isoformat(),
                "last_timestamp": frame.index[-1].isoformat(),
            }.items():
                if metadata.get(key) != value:
                    fail(str(metadata_path), f"manifest.{key}", detail="Stored bounds differ")
            return metadata
    staging = root / ".staging" / frequency / symbol / request_id
    staging.mkdir(parents=True, exist_ok=True)
    chunks, stats, frames = [], [], []
    ranges = month_ranges(start, through) if frequency == "1min" else [(start, through)]
    for left, right in ranges:
        path = staging / f"{left}_{right}.parquet"
        stat_path = path.with_suffix(".json")
        if not (path.exists() and stat_path.exists()):
            raw = client.fetch(symbol, frequency, left, right)
            if "ingest_stats" in raw.attrs:
                clean, stat = raw, raw.attrs["ingest_stats"]
            else:
                clean, stat = clean_bars(raw, frequency, left, right)
            validate_price_bars(
                clean, dataset=str(path), frequency=frequency, start=left, through=right
            )
            _validate_stats(stat, clean, frequency, left, right, dataset=str(stat_path))
            atomic_parquet(path, clean, frequency=frequency, start=left, through=right)
            atomic_json(stat_path, stat)
            event(
                root,
                "chunk_written",
                symbol=symbol,
                frequency=frequency,
                start=left,
                through=right,
                **stat,
            )
        chunks.append(path)
        chunk = read_dataset(
            path,
            expected={
                "kind": "price_bars",
                "frequency": frequency,
                "start": left,
                "through": right,
                "source": DATA_URL,
                "feed": request["feed"],
                "adjustment": request["adjustment"],
            },
        )
        stats.append(
            _validate_stats(
                read_metadata(stat_path), chunk, frequency, left, right, dataset=str(stat_path)
            )
        )
        frames.append(chunk)
    frame = pd.concat(frames).sort_index()
    if frame.empty:
        raise DataError(
            f"No bars returned for {symbol} ({frequency}); refusing an empty final file"
        )
    if not frame.index.is_unique:
        raise DataError(f"Overlapping chunks for {symbol}")
    totals = {
        key: sum(stat[key] for stat in stats)
        for key in (
            "source_rows",
            "off_session_rows",
            "expected_rows",
            "observed_rows",
            "filled_rows",
            "missing_rows",
            "rows",
        )
    }
    metadata = {
        **request,
        **totals,
        "request_id": request_id,
        "first_timestamp": frame.index[0].isoformat(),
        "last_timestamp": frame.index[-1].isoformat(),
        "fill_rate": totals["filled_rows"] / totals["expected_rows"],
        "written_at": datetime.now(ZoneInfo("UTC")).isoformat(),
    }
    atomic_parquet(
        destination,
        frame,
        frequency=frequency,
        start=start,
        through=through,
        created_at=metadata["written_at"],
    )
    atomic_json(metadata_path, metadata)
    event(root, "symbol_complete", **metadata)
    # Completed symbol files are the resume checkpoint; remove duplicate chunks.
    for path in chunks:
        path.unlink()
        path.with_suffix(".json").unlink()
        manifest_path(path).unlink()
    return metadata


def ingest_tier(client, root, frequency, symbols, start, through):
    manifest_path = root / frequency / "manifest.json"
    manifest = {
        "frequency": frequency,
        "symbols": symbols,
        "start": start,
        "through": through,
        "feed": "sip",
        "adjustment": "all",
        "normalizer_version": NORMALIZER_VERSION,
        "splits": split_boundaries(expected_index(frequency, start, through)),
        "complete": False,
    }
    validate_tier_manifest(manifest, frequency, dataset=str(manifest_path))
    if manifest_path.exists():
        previous = validate_tier_manifest(
            read_metadata(manifest_path), frequency, dataset=str(manifest_path)
        )
        stable = (
            "frequency",
            "symbols",
            "start",
            "through",
            "feed",
            "adjustment",
            "normalizer_version",
        )
        # Appending symbols to an otherwise identical snapshot is a resume, not a new one.
        appended = previous.get("symbols") == symbols[: len(previous.get("symbols", []))]
        if any(previous.get(key) != manifest[key] for key in stable if key != "symbols") or (
            not appended
        ):
            raise DataError("Existing tier uses a different snapshot. Select a new --data-root.")
    atomic_json(manifest_path, manifest)
    failed = []
    for number, symbol in enumerate(symbols, 1):
        try:
            metadata = ingest_symbol(client, root, frequency, symbol, start, through)
            print(
                f"{frequency} {number}/{len(symbols)} {symbol}: {metadata['rows']:,} rows; "
                f"{metadata['first_timestamp']} → {metadata['last_timestamp']}; "
                f"filled {metadata['fill_rate']:.4%}; missing {metadata['missing_rows']:,}",
                flush=True,
            )
        except (DataError, requests.RequestException) as error:
            failed.append(symbol)
            event(root, "symbol_failed", symbol=symbol, frequency=frequency, error=str(error))
            print(f"{frequency} {symbol}: FAILED: {error}", flush=True)
            # Authentication/entitlement failure should not trigger hundreds more requests.
            if "HTTP 401" in str(error) or "HTTP 403" in str(error):
                break
    manifest["complete"] = not failed
    manifest["failed_symbols"] = failed
    atomic_json(manifest_path, manifest)
    if failed:
        raise DataError(f"{frequency} incomplete: {', '.join(failed)}; rerun to resume")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=["all", "1min", "1day"], default="all")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument(
        "--through",
        type=date.fromisoformat,
        help="Last included date, default yesterday in America/Los_Angeles",
    )
    parser.add_argument("--start", type=date.fromisoformat, help="Override start for a smoke test")
    parser.add_argument(
        "--symbols", nargs="+", help="Subset smoke test; use a separate --data-root"
    )
    parser.add_argument(
        "--sp500-csv", type=Path, help="Owner-supplied current constituent snapshot"
    )
    args = parser.parse_args(argv)
    load_dotenv(args.env_file, override=False)
    today = datetime.now(ZoneInfo("America/Los_Angeles")).date()
    through = args.through or today - timedelta(days=1)
    if through >= today:
        parser.error("--through must be yesterday or earlier")
    if args.start and args.start > through:
        parser.error("--start is after --through")
    root = args.data_root
    root.mkdir(parents=True, exist_ok=True)
    try:
        client = AlpacaBars(
            os.environ.get("APCA_API_KEY_ID", ""), os.environ.get("APCA_API_SECRET_KEY", "")
        )
        with (root / ".ingest.lock").open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DataError("Another ingestion is already writing to this data root") from None
            for frequency in ["1min", "1day"] if args.tier == "all" else [args.tier]:
                default_start = (
                    (pd.Timestamp(through) - pd.DateOffset(years=3)).date()
                    if frequency == "1min"
                    else date(2016, 1, 1)
                )
                start = args.start or default_start
                symbols = args.symbols or (
                    INTRADAY_UNIVERSE
                    if frequency == "1min"
                    else daily_universe(root, args.sp500_csv)
                )
                if len(symbols) != len(set(symbols)):
                    raise DataError("Symbols must be unique")
                for symbol in symbols:
                    validate_symbol(symbol)
                ingest_tier(
                    client, root, frequency, symbols, start.isoformat(), through.isoformat()
                )
        print(
            f"Ingestion complete ({client.requests} HTTP requests). "
            "Run python -m factory.audit_data."
        )
        return 0
    except (DataError, requests.RequestException) as error:
        print(f"Ingestion blocked: {error}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
