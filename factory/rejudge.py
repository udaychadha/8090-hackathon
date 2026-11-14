"""Owner-authorized Eval 4/5 revision using retained metrics only; no backtests."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from factory.agents.records import Records
from factory.evals.decay import decay_from_metrics
from factory.evals.deflated import deflated_from_metrics
from factory.record_migration import utc_now
from factory.trials import trial_cohort

REVISION = "2026-11-14-eval45-global-v2"
TABLES = ("runs", "variants", "eval_results", "events")


def _snapshot(records):
    return {table: records.list(table, include_voided=True) for table in TABLES}


def _fingerprint(snapshot):
    return hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def _evidence(variant, stored):
    values = {e["number"]: copy.deepcopy(e) for e in variant.get("evals", [])}
    for result in stored:
        if (result["run_id"], result["variant"]) != (variant["run_id"], variant["variant"]):
            continue
        item = {key: copy.deepcopy(result[key]) for key in ("number", "name", "passed", "metrics")}
        if item["number"] in values and values[item["number"]] != item:
            raise ValueError(f"Recorded eval evidence disagrees for {variant['variant_id']}")
        values[item["number"]] = item
    return values


def _verdict(row):
    return {"status": row["status"], "evals_passed": row["evals_passed"]}


def plan_rejudgment(records):
    """Validate all projections and compute a reproducible plan without mutations."""
    snapshot = _snapshot(records)
    if any(r["status"] == "RUNNING" for r in snapshot["runs"]):
        raise ValueError("Cannot rejudge while a research run is running")
    ids, sharpes = trial_cohort(records)
    variants, evaluations, rows = [], [], []
    standalone = {(e["run_id"], e["variant"], e["number"]): e for e in snapshot["eval_results"]}
    originals = {v["variant_id"]: v for v in snapshot["variants"]}
    for run in snapshot["runs"]:
        for nested in run.get("variants", []):
            if nested != originals.get(nested["variant_id"]):
                raise ValueError(f"Run and variant snapshots disagree for {nested['variant_id']}")
    for before in snapshot["variants"]:
        after = copy.deepcopy(before)
        values = _evidence(before, snapshot["eval_results"])
        changed_evals = []
        for number, function in ((4, decay_from_metrics), (5, deflated_from_metrics)):
            if number not in values:
                continue  # Never invent an eval or missing observations.
            old = copy.deepcopy(values[number])
            kwargs = {"trial_variant_ids": ids} if number == 5 else {}
            args = (old["metrics"], sharpes) if number == 5 else (old["metrics"],)
            result = function(*args, **kwargs).to_dict()
            result["metrics"]["judgment_revision"] = REVISION
            # Preserve any extension envelope on the existing evaluation.
            values[number] = {**old, **result}
            if values[number] != old:
                changed_evals.append(number)
            key = (before["run_id"], before["variant"], number)
            persisted = standalone.get(key)
            if persisted is not None:
                updated = {**persisted, **values[number]}
                if updated != persisted:
                    evaluations.append(updated)
        if changed_evals:
            after["evals"] = [values[n] for n in sorted(values)]
            after["judgment_revision"] = REVISION
            if before["status"] != "VOID":
                count = sum(e["passed"] for e in values.values())
                after["evals_passed"] = after["default_evals_passed"] = count
                # An operational stop cannot become successful just by rejudging metrics.
                if before["status"] == "VERIFIED" or before["status"].startswith("FAILED_EVAL_"):
                    failed = [n for n in sorted(values) if not values[n]["passed"]]
                    if not failed and set(values) != set(range(1, 6)):
                        raise ValueError(
                            f"Incomplete evaluation evidence for {before['variant_id']}"
                        )
                    status = f"FAILED_EVAL_{failed[0]}" if failed else "VERIFIED"
                    after["status"] = after["default_status"] = status
            variants.append(after)
        rows.append(
            {
                "variant_id": before["variant_id"],
                "run_id": before["run_id"],
                "source_title": before["source_title"],
                "variant": before["variant"],
                "voided": before["voided"],
                "is_control": before.get("is_control", False),
                "before": _verdict(before),
                "after": _verdict(after),
                "evals_before": [
                    values for values in before.get("evals", []) if values["number"] in (4, 5)
                ],
                "evals_after": [values[n] for n in (4, 5) if n in values],
                "changed_evals": changed_evals,
                "action": "rejudged" if changed_evals else "no recorded evals to change",
            }
        )
    replacement = {v["variant_id"]: v for v in variants}
    runs = []
    for before in snapshot["runs"]:
        after = copy.deepcopy(before)
        after["variants"] = [
            replacement.get(v["variant_id"], v) for v in before.get("variants", [])
        ]
        if after != before:
            runs.append(after)
    return {
        "revision": REVISION,
        "input_fingerprint": _fingerprint(snapshot),
        "trial_variant_ids": ids,
        "trial_sharpes": sharpes,
        "trial_count": len(ids),
        "rows": rows,
        "changed_variants": len(variants),
        "updates": {"variants": variants, "eval_results": evaluations, "runs": runs},
    }


def _backup(records):
    directory = records.root / ("rejudge-backup-" + utc_now().replace(":", "").replace(".", ""))
    directory.mkdir()
    with sqlite3.connect(directory / "factory.db") as target:
        records.db.backup(target)
    for name in ("events.jsonl",):
        path = records.root / name
        if path.exists():
            shutil.copy2(path, directory / name)
    return directory


def apply_rejudgment(records, plan):
    """Back up then atomically update typed projections and append audit events."""
    records._writable()
    if _fingerprint(_snapshot(records)) != plan["input_fingerprint"]:
        raise ValueError("Recorded evidence changed since the rejudgment plan")
    report = {k: copy.deepcopy(v) for k, v in plan.items() if k != "updates"}
    if not plan["changed_variants"]:
        records._mirror()
        return {**report, "backup": None, "applied": False}
    backup = _backup(records)
    report.update(backup=str(backup), applied=True, applied_at=utc_now())
    (backup / "plan.json").write_text(json.dumps(plan, indent=2, allow_nan=False) + "\n")
    with records.lock:
        with records.db:
            records.db.execute("BEGIN IMMEDIATE")
            if _fingerprint(_snapshot(records)) != plan["input_fingerprint"]:
                raise ValueError("Recorded evidence changed before the rejudgment transaction")
            for table in ("eval_results", "variants", "runs"):
                for payload in plan["updates"][table]:
                    value = records._prepared(table, payload["id"], payload["run_id"], payload)
                    records._write(table, payload["id"], value)
            for row in plan["rows"]:
                for result in row["evals_after"]:
                    if result["number"] not in row["changed_evals"]:
                        continue
                    event = records._event_value(
                        row["run_id"],
                        "eval",
                        "passed" if result["passed"] else "failed",
                        f"Eval {result['number']} rejudged from recorded metrics ({REVISION})",
                        variant=row["variant"],
                        data={"eval": result["number"], **result["metrics"]},
                    )
                    records._write("events", event["seq"], event)
        records._mirror()
    (backup / "applied.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def write_report(report, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix(".json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    lines = [
        "# Eval 4/5 recorded-metric rejudgment",
        "",
        f"Revision: `{report['revision']}`. Selected global trials: **{report['trial_count']}**.",
        "No strategy executions, backtests, data downloads or model calls.",
        "",
        "| Variant | Before status | Before passed | After status | After passed |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in report["rows"]:
        before, after = row["before"], row["after"]
        lines.append(
            f"| {row['variant_id']} | {before['status']} | {before['evals_passed']}/5 "
            f"| {after['status']} | {after['evals_passed']}/5 |"
        )
    lines += [
        "",
        "Voided variants remain VOID and excluded. Inactive/bug variants with no",
        "recorded Eval 4/5 remain unevaluated; no missing metric was invented.",
        "",
        "Concentration uses the sum of daily net returns. A positive-total share",
        "can exceed one when other windows lose money; it remains a failure.",
        "Nonpositive/unknown total PnL is not applicable (null), never a pass.",
        "",
        f"Backup: `{report.get('backup') or 'dry run / no changes'}`.",
        "Original event lines are retained; explicit rejudgment events follow them.",
        "",
    ]
    path.with_suffix(".md").write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="runs")
    parser.add_argument("--report", default="report/eval45-rejudgment")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        with Records(args.root, read_only=True) as records:
            report = plan_rejudgment(records)
        report = {k: v for k, v in report.items() if k != "updates"}
    else:
        # The API owns this process lock even while idle. Stop it before applying;
        # this prevents a new submission racing the backed-up global revision.
        with (Path(args.root) / "api-runtime.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SystemExit("Stop the local API before applying a metric rejudgment") from None
            with Records(args.root) as records:
                report = apply_rejudgment(records, plan_rejudgment(records))
    write_report(report, args.report)
    print(
        json.dumps(
            {
                "revision": REVISION,
                "trial_count": report["trial_count"],
                "variants": len(report["rows"]),
                "changed_variants": report["changed_variants"],
                "applied": report.get("applied", False),
                "report": args.report,
            }
        )
    )


if __name__ == "__main__":
    main()
