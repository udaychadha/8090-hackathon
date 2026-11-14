"""Validate legacy data and add manifests, without fetching or rewriting prices."""

import argparse
import json
from pathlib import Path

import pandas as pd

from factory.data_contract.storage import attach_manifest, read_dataset


def migrate(root="data"):
    root = Path(root)
    results = []
    for base in (root, root / "smoke"):
        for frequency in ("1min", "1day"):
            for path in sorted((base / frequency).glob("*.parquet")):
                meta = json.loads(
                    (base / "metadata" / frequency / (path.stem + ".json")).read_text()
                )
                frame = pd.read_parquet(path)
                entry = attach_manifest(
                    path,
                    frame,
                    kind="price_bars",
                    frequency=frequency,
                    start=meta["start"],
                    through=meta["through"],
                    source="https://data.alpaca.markets/v2/stocks/bars",
                    feed=meta["feed"],
                    adjustment=meta["adjustment"],
                    created_at=meta["written_at"],
                )
                results.append(
                    {"path": str(path), "rows": entry["row_count"], "sha256": entry["sha256"]}
                )
                if len(results) % 25 == 0:
                    print(f"Validated {len(results)} datasets", flush=True)
    return results


def verify_all(root="data"):
    results = []
    for path in sorted(Path(root).rglob("*.parquet")):
        frame = read_dataset(path)
        results.append({"path": str(path), "rows": len(frame)})
        if len(results) % 25 == 0:
            print(f"Checked {len(results)} datasets", flush=True)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="data")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--report")
    args = parser.parse_args()
    rows = verify_all(args.root) if args.check else migrate(args.root)
    if args.report:
        Path(args.report).write_text(json.dumps(rows, indent=2) + "\n")
    print(f"Validated {len(rows)} datasets / {sum(r['rows'] for r in rows):,} rows")
