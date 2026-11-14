"""WO-01 acceptance: inventory, fill rates, wide-frame timing and NVDA split.

This trusted data-hygiene utility never imports or evaluates strategy code.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from factory.data import DAILY_LIMITATION, INTRADAY_UNIVERSE, OHLCV, DataError, wide_frames
from factory.ingest_alpaca import atomic_json, daily_universe, event


def check_nvda_split(root: Path, frequency: str) -> dict:
    frame = pd.read_parquet(
        root / frequency / "NVDA.parquet",
        filters=[
            ("timestamp", ">=", pd.Timestamp("2024-06-07", tz="UTC")),
            ("timestamp", "<", pd.Timestamp("2024-06-11", tz="UTC")),
        ],
    )
    local_dates = frame.index.tz_convert("America/New_York").strftime("%Y-%m-%d")
    before, after = frame.loc[local_dates == "2024-06-07"], frame.loc[local_dates == "2024-06-10"]
    if before.empty or after.empty:
        raise DataError(f"{frequency}: NVDA June 7/10 2024 bars missing")
    ratio = float(after.open.iloc[0] / before.close.iloc[-1])
    # A broad integrity check for the ten-for-one split, not a trading threshold.
    return {
        "frequency": frequency,
        "prior_close": float(before.close.iloc[-1]),
        "next_open": float(after.open.iloc[0]),
        "price_ratio": ratio,
        "passed": 0.5 < ratio < 1.5,
        "description": "June 7 close → June 10 open; reject a split-sized discontinuity",
    }


def audit(root: Path, *, benchmark: bool = True) -> dict:
    report = {"passed": False, "symbols": [], "errors": [], "split_checks": []}
    for frequency in ("1min", "1day"):
        try:
            universe = INTRADAY_UNIVERSE if frequency == "1min" else daily_universe(root)
            manifest = json.loads((root / frequency / "manifest.json").read_text())
            if not manifest.get("complete") or set(manifest["symbols"]) != set(universe):
                raise DataError(f"{frequency}: incomplete or nonstandard universe")
            if frequency == "1day" and manifest["start"] != "2016-01-01":
                raise DataError("Daily tier does not start in 2016")
            if frequency == "1min" and pd.Timestamp(manifest["start"]) != (
                pd.Timestamp(manifest["through"]) - pd.DateOffset(years=3)
            ):
                raise DataError("Intraday tier does not cover the requested three years")
            if manifest["feed"] != "sip" or manifest["adjustment"] != "all":
                raise DataError(f"{frequency}: expected SIP, adjustment=all")
            for symbol in universe:
                path = root / frequency / f"{symbol}.parquet"
                meta = json.loads((root / "metadata" / frequency / f"{symbol}.json").read_text())
                rows = pq.ParquetFile(path).metadata.num_rows
                if rows == 0 or rows != meta["rows"]:
                    raise DataError(f"{frequency}/{symbol}: empty file or metadata row mismatch")
                if any(
                    meta[key] != manifest[key]
                    for key in ("start", "through", "feed", "adjustment", "normalizer_version")
                ):
                    raise DataError(f"{frequency}/{symbol}: snapshot metadata mismatch")
                report["symbols"].append({"symbol": symbol, "frequency": frequency, **meta})
                print(
                    f"{frequency:4} {symbol:6} rows={rows:9,} "
                    f"{meta['first_timestamp']} → {meta['last_timestamp']} "
                    f"fill={meta['fill_rate']:.4%} missing={meta['missing_rows']:,}"
                )
            check = check_nvda_split(root, frequency)
            report["split_checks"].append(check)
            if not check["passed"]:
                report["errors"].append(f"{frequency}: NVDA split discontinuity")
            print(
                f"{frequency} NVDA split ratio: {check['price_ratio']:.6f}; pass={check['passed']}"
            )
        except (OSError, ValueError, KeyError) as error:
            report["errors"].append(str(error))
    if benchmark and all(
        (root / "1min" / f"{symbol}.parquet").exists() for symbol in INTRADAY_UNIVERSE
    ):
        started = time.perf_counter()
        bars = {
            symbol: pd.read_parquet(root / "1min" / f"{symbol}.parquet", columns=OHLCV)
            for symbol in INTRADAY_UNIVERSE
        }
        frames = wide_frames(bars)
        result = {
            "seconds": time.perf_counter() - started,
            "symbols": len(bars),
            "timestamps": len(frames["close"]),
            "fields": list(frames),
            "wide_bytes": int(
                sum(frame.memory_usage(deep=True).sum() for frame in frames.values())
            ),
        }
        report["wide_load"] = result
        event(root, "wide_load_benchmark", **result)
        print(f"Wide load: {len(bars)} symbols, five OHLCV frames, {result['seconds']:.3f}s")
    else:
        report["errors"].append("Full 50-symbol intraday wide-load benchmark not run")
    report["passed"] = not report["errors"]
    print(DAILY_LIMITATION)
    root.mkdir(parents=True, exist_ok=True)
    atomic_json(root / "audit.json", report)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument(
        "--skip-benchmark", action="store_true", help="Inventory only; not acceptance"
    )
    args = parser.parse_args(argv)
    result = audit(args.data_root, benchmark=not args.skip_benchmark)
    for error in result["errors"]:
        print(f"INCOMPLETE: {error}")
    print(f"WO-01 acceptance: {'PASS' if result['passed'] else 'NOT YET PASSED'}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
