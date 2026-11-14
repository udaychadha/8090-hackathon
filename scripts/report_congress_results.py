"""Render stored Congress acceptance evidence, without any backtest or model call."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path


def verify_historical_records(root):
    """The owner authorized only separate gross fields on historical evidence."""
    from scripts.backfill_gross_diagnostics import without_diagnostics

    baseline = json.loads((root / "report/wo12-pre-diagnostics-baseline.json").read_text())
    if baseline.get("original_payload_bytes_verified") is not True:
        raise AssertionError("Original payload bytes were not verified before diagnostic changes")
    unchanged = {}
    with sqlite3.connect(root / "runs/factory.db") as db:
        for table, original in baseline["canonical"].items():
            identity = "seq" if table == "events" else "id"
            current = {
                str(key): hashlib.sha256(
                    json.dumps(
                        without_diagnostics(json.loads(payload)), sort_keys=True, allow_nan=False
                    ).encode()
                ).hexdigest()
                for key, payload in db.execute(f"SELECT {identity},payload FROM {table}")
            }
            if any(current.get(key) != digest for key, digest in original.items()):
                raise AssertionError(f"Historical {table} changed beyond gross diagnostics")
            unchanged[table] = len(original)
    return unchanged


def main():
    root = Path(__file__).resolve().parents[1]
    runs = json.loads((root / "report/wo12-runs.json").read_text())
    experiments = ("congress_all", "congress_committee", "control")
    if any(name not in runs or runs[name]["status"] == "RUNNING" for name in experiments):
        raise ValueError("Both Congress experiments and the control must finish before reporting")
    audit = json.loads((root / "report/wo12-source-audit.json").read_text())
    committee = json.loads((root / "report/wo12-committee-audit.json").read_text())
    unchanged = verify_historical_records(root)
    with sqlite3.connect(root / "runs/factory.db") as db:
        gross = {
            key: json.loads(payload).get("gross_diagnostics")
            for key, payload in db.execute("SELECT id,payload FROM variants")
        }
    lines = [
        "# WO-12 — Congress experiments",
        "",
        "Both specifications were frozen before results. The source is unverified; "
        "today's index membership and GICS classifications introduce survivorship and "
        "classification limitations. The chronological IS/OOS price splits are unchanged; "
        "HOLDOUT was not used.",
        "",
        f"Canonical event rows: {audit['eligible']['rows']:,}. "
        f"Daily-symbol overlap: {audit['daily_overlap']['rows']:,} rows. "
        "The audit separates source-classified stocks from supported symbol spellings.",
        "",
        f"Dated committee snapshots produced {committee['qualifying_purchase_count']} "
        "qualifying purchases. Every committee result is **short sample: not a verdict**. "
        "Unknown dates and publication times were not inferred.",
        "",
        "## Status and activity",
        "",
        "| Experiment | Variant | Status | Evals passed | IS active days |",
        "|---|---|---|---:|---:|",
    ]
    labels = {
        "congress_all": "All Congress",
        "congress_committee": "Committee Congress",
        "control": "Buy-and-hold SPY control",
    }
    for name in experiments:
        for row in runs[name]["variants"]:
            days = row["days_traded"] if row["days_traded"] is not None else "not recorded"
            lines.append(
                f"| {labels[name]} | {row['variant']} | {row['status']} | "
                f"{row['evals_passed']}/5 | {days} |"
            )
    lines += [
        "",
        "INACTIVE is the existing pre-performance activity gate; no return metric "
        "or five-eval pass is invented for a strategy that never trades.",
    ]
    for split in ("IS", "OOS"):
        lines += [
            "",
            f"## {split} annualized Sharpe by round-trip cost",
            "",
            "| Experiment | Variant | 0 bps | 2 bps | 5 bps | 10 bps |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for name in experiments:
            for row in runs[name]["variants"]:
                values = (row.get("cost_sharpes") or {}).get(split, {})
                numbers = [
                    "not available" if values.get(cost) is None else f"{values[cost]:.4f}"
                    for cost in ("0", "2", "5", "10")
                ]
                lines.append(f"| {labels[name]} | {row['variant']} | " + " | ".join(numbers) + " |")
    lines += [
        "",
        "## Gross diagnostics — zero bps, no verdict authority",
        "",
        "| Experiment | Variant | Diagnostic label | Sensitivity | "
        "Gross base / worst Sharpe | Decay | Gross IS / OOS Sharpe |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in experiments:
        for row in runs[name]["variants"]:
            diagnostic = gross.get(row["variant_id"]) or {}
            sensitivity, decay = diagnostic.get("eval_3"), diagnostic.get("eval_4")

            def outcome(result):
                return (
                    "not measured" if result is None else "pass" if result["passed"] else "failed"
                )

            def pair(result, first, second):
                values = (result or {}).get("metrics", {})
                return " / ".join(
                    "not available" if values.get(key) is None else f"{values[key]:.4f}"
                    for key in (first, second)
                )

            lines.append(
                f"| {labels[name]} | {row['variant']} | "
                f"{diagnostic.get('label') or 'not applicable'} | "
                f"{outcome(sensitivity)} | {pair(sensitivity, 'base_sharpe', 'worst_sharpe')} | "
                f"{outcome(decay)} | {pair(decay, 'is_sharpe', 'oos_sharpe')} |"
            )
    lines += [
        "",
        "Diagnostic passes do not change any status, eval count, or VERIFIED eligibility. "
        "Undefined or unavailable measurements are not zeros. Full jitter and concentration "
        "evidence is retained separately in the database and proof JSON.",
    ]
    attempts = [runs[name] for name in experiments] + runs.get("invalid_attempts", [])
    complete_cost = all(item.get("cost_complete") for item in attempts)
    cost = sum(item["estimated_model_cost_usd"] for item in attempts) if complete_cost else None
    seconds = sum(item["wall_seconds"] for item in attempts)
    lines += [
        "",
        "## Time, cost and audit",
        "",
        f"Summed measured execution time: {seconds:.1f} seconds. "
        "This includes the invalidated harness attempt and control, excluding development.",
        f"Total recorded model cost: {'unknown' if cost is None else f'${cost:.6f}'}. "
        "Invalidated attempts remain included in cost accounting.",
        "",
    ]
    for name in experiments:
        item = runs[name]
        lines.append(
            f"- {labels[name]}: `{item['run_id']}`, {item['wall_seconds']:.1f}s, "
            f"model cost {item['estimated_model_cost_usd']} USD."
        )
    for item in runs.get("invalid_attempts", []):
        lines.append(
            f"- VOID `{item['run_id']}`: {item['void_reason']} "
            "Exact retained candidates were reused; no measured strategy was regenerated."
        )
    lines += [
        "",
        "The SPY control is explicitly marked `is_control` and excluded from Eval 5. "
        "All pre-WO-12 rows were verified byte-for-byte before diagnostics were added. "
        "Their original evidence remains unchanged; only the owner-requested separate "
        "gross diagnostic fields may have been added.",
        "",
        "Sources: [Congress audit](wo12-source-audit.md), "
        "[committee audit](wo12-committee-audit.md). Raw data and PDFs are not committed.",
    ]
    (root / "report/wo12-results.md").write_text("\n".join(lines) + "\n")
    proof = {
        "historical_rows_unchanged": unchanged,
        "runs": runs,
        "gross_diagnostics": {
            row["variant_id"]: gross.get(row["variant_id"])
            for name in experiments
            for row in runs[name]["variants"]
        },
        "source_commit": audit["commit"],
        "source_rows": audit["eligible"]["rows"],
        "committee_qualifying_purchases": committee["qualifying_purchase_count"],
        "total_model_cost_usd": cost,
        "summed_execution_seconds": seconds,
        "config_sha256": hashlib.sha256(
            (root / "factory/evals/config.py").read_bytes()
        ).hexdigest(),
        "frozen_specs_sha256": {
            name: hashlib.sha256((root / f"specs/{name}.json").read_bytes()).hexdigest()
            for name in experiments
            if name != "control"
        },
    }
    (root / "report/wo12-proof.json").write_text(
        json.dumps(proof, indent=2, allow_nan=False) + "\n"
    )
    print(
        json.dumps(
            {
                "reports": ["report/wo12-results.md", "report/wo12-proof.json"],
                "summed_execution_seconds": seconds,
                "model_cost_usd": cost,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
