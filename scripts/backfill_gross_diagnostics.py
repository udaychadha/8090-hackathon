"""Replay retained code for separate zero-cost diagnostics; dry-run unless --apply.

No model calls, repairs, authoritative eval writes, or verdict changes. The
diagnostic batch and matching nested run snapshots are published atomically only
when all parent runs are idle. --wait-running stages replay while runs finish.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import os
import sqlite3
import tempfile
import time
from contextlib import nullcontext
from pathlib import Path

from factory.agents.records import Records, _validated
from factory.record_migration import utc_now
from factory.redaction import redact


def without_diagnostics(value):
    """Canonical original evidence, excluding only the authorized added field."""
    if isinstance(value, dict):
        return {k: without_diagnostics(v) for k, v in value.items() if k != "gross_diagnostics"}
    if isinstance(value, list):
        return [without_diagnostics(v) for v in value]
    return value


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def data_snapshot_fingerprint(data_root):
    """Hash manifest bytes and file identities without reading sealed price rows.

    Dataset manifests retain content digests; tier manifests retain split bounds.
    Parquet size/time/inode guards also detect data replaced without a new manifest.
    This is only a same-process reuse guard, never a persistent replay cache.
    """
    root = Path(data_root).resolve()
    evidence = []
    try:
        for path in sorted(root.rglob("*")):
            if path.name == "manifest.json" or path.name.endswith(".manifest.json"):
                evidence.append(
                    (str(path.relative_to(root)), hashlib.sha256(path.read_bytes()).hexdigest())
                )
            elif path.suffix == ".parquet":
                stat = path.stat()
                evidence.append(
                    (
                        str(path.relative_to(root)),
                        stat.st_dev,
                        stat.st_ino,
                        stat.st_size,
                        stat.st_mtime_ns,
                        stat.st_ctime_ns,
                    )
                )
    except OSError:
        return None
    return _fingerprint({"root": str(root), "files": evidence})


def _raw(records, table, identifier):
    # Validate identity and indexes using Records, but retain the exact field set.
    if records.get(table, identifier, include_voided=True) is None:
        return None
    return json.loads(
        records.db.execute(f"SELECT payload FROM {table} WHERE id=?", (identifier,)).fetchone()[0]
    )


def _backup(records):
    directory = Path(tempfile.mkdtemp(prefix="gross-diagnostics-backup-", dir=records.root))
    with sqlite3.connect(directory / "factory.db") as destination:
        records.db.backup(destination)
    return str(directory)


def _unavailable(reason):
    return {
        "schema_version": "1.0.0",
        "state": "unavailable",
        "cost_bps": 0,
        "eval_3": None,
        "eval_4": None,
        "label": None,
        "reason": reason,
    }


def _compute(variant, *, compute, data_root, timeout):
    from factory.gross_diagnostics import diagnostics_for_status

    code = variant.get("code")
    if not isinstance(code, str) or not code.strip():
        result = _unavailable("No retained strategy code is available.")
    else:
        try:
            if variant.get("params") is not None:
                assignments = [
                    ast.literal_eval(node.value)
                    for node in ast.parse(code).body
                    if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "PARAMS" for t in node.targets)
                ]
                if assignments != [variant["params"]]:
                    return diagnostics_for_status(
                        _unavailable(
                            "Retained parameters disagree with the code's literal PARAMS."
                        ),
                        variant["status"],
                    )
            with tempfile.TemporaryDirectory(prefix="gross-diagnostic-replay-") as folder:
                path = Path(folder) / "retained.py"
                path.write_text(code)
                result = compute(path, data_root=data_root, timeout=timeout)
        except Exception as error:
            # Exception text can contain source code or credentials. Only report its class.
            result = _unavailable(f"Retained strategy replay failed ({type(error).__name__}).")
    return redact(diagnostics_for_status(result, variant["status"]))


def _running_ids(records):
    return [row["run_id"] for row in records.list("runs", status="RUNNING", include_voided=True)]


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _apply_one(records, before, run_before, diagnostics, *, in_transaction=False):
    records._writable()
    with records.lock, nullcontext() if in_transaction else records.db:
        if not in_transaction:
            records.db.execute("BEGIN IMMEDIATE")
        if _running_ids(records):
            return False
        current = _raw(records, "variants", before["id"])
        run = _raw(records, "runs", before["run_id"])
        if current != before or without_diagnostics(run) != without_diagnostics(run_before):
            return False
        if current["status"] == "RUNNING" or (run or {}).get("status") == "RUNNING":
            return False
        for nested in (run or {}).get("variants", []):
            if nested["variant_id"] == before["variant_id"] and any(
                nested.get(key) != current.get(key) for key in ("code", "params", "status")
            ):
                return False
        updated = {**current, "gross_diagnostics": diagnostics}
        _validated("variants", updated)
        if without_diagnostics(updated) != without_diagnostics(before):
            raise ValueError("Non-diagnostic variant evidence changed")
        records._write("variants", before["id"], updated)
        if run is not None:
            updated_run = copy.deepcopy(run)
            for nested in updated_run.get("variants", []):
                if nested["variant_id"] == before["variant_id"]:
                    nested["gross_diagnostics"] = diagnostics
            _validated("runs", updated_run)
            if without_diagnostics(updated_run) != without_diagnostics(run):
                raise ValueError("Non-diagnostic run evidence changed")
            records._write("runs", before["run_id"], updated_run)
        return True


def backfill(
    records,
    *,
    apply=False,
    data_root="data",
    timeout=None,
    retry_unavailable=False,
    variant_ids=None,
    exclude_run_ids=None,
    compute=None,
    on_row=None,
    wait_running=False,
    wait=None,
    wait_pids=None,
    process_alive=None,
):
    """Compute each terminal candidate once; retain audit evidence and resume safely.

    The injectable compute boundary is the slow sandbox replay. It cannot affect
    authoritative evidence: writes below patch only gross_diagnostics.
    """
    if compute is None:
        from factory.gross_diagnostics import compute_diagnostics_file

        compute = compute_diagnostics_file
    if apply:
        records._writable()
        if not wait_running and _running_ids(records):
            raise ValueError("Cannot apply gross diagnostics while any parent run is running")
    wait_pids = list(dict.fromkeys(wait_pids or []))
    if any(type(pid) is not int or pid <= 0 for pid in wait_pids):
        raise ValueError("Wait PIDs must be positive process identifiers")
    process_alive = _pid_alive if process_alive is None else process_alive
    selected = set(variant_ids or [])
    excluded = set(exclude_run_ids or [])
    report = {"created_at": utc_now(), "applied": False, "backup": None, "rows": []}
    replay_cache = {}
    staged = []
    candidates = records.list("variants", include_voided=True)
    if wait_running:
        parent_status = {
            row["run_id"]: row["status"] for row in records.list("runs", include_voided=True)
        }
        candidates.sort(
            key=lambda row: (
                row["status"] == "RUNNING" or parent_status.get(row["run_id"]) == "RUNNING"
            )
        )
    wait = time.sleep if wait is None else wait
    for candidate in candidates:
        identifier = candidate["variant_id"]
        if selected and identifier not in selected:
            continue
        if candidate["run_id"] in excluded:
            continue
        before = _raw(records, "variants", identifier)
        if before is None:
            continue
        run_before = _raw(records, "runs", before["run_id"])
        waiting_started = utc_now()
        while wait_running and (
            before["status"] == "RUNNING" or (run_before or {}).get("status") == "RUNNING"
        ):
            # Waiting only reads durable evidence. Never freeze the API or write a
            # placeholder diagnostic onto a candidate still owned by its pipeline.
            report["waiting"] = {
                "variant_id": identifier,
                "run_id": before["run_id"],
                "state": "pending",
                "status": before["status"],
                "run_status": (run_before or {}).get("status"),
                "started_at": waiting_started,
                "checked_at": utc_now(),
            }
            if on_row is not None:
                on_row(redact(report))
            wait(10)
            before = _raw(records, "variants", identifier)
            if before is None:
                break
            run_before = _raw(records, "runs", before["run_id"])
        report.pop("waiting", None)
        if before is None:
            continue
        code = before.get("code")
        row = {
            "variant_id": identifier,
            "run_id": before["run_id"],
            "status": before["status"],
            "voided": before.get("voided", False),
            "code_sha256": hashlib.sha256(code.encode()).hexdigest() if code is not None else None,
            "started_at": utc_now(),
            "evidence_before_sha256": _fingerprint(without_diagnostics(before)),
            "run_evidence_before_sha256": _fingerprint(without_diagnostics(run_before)),
            "reused_from_variant_id": None,
            "data_snapshot_sha256": None,
        }
        started = time.monotonic()
        existing = before.get("gross_diagnostics") or {}
        if before["status"] == "RUNNING" or (run_before or {}).get("status") == "RUNNING":
            row.update(action="skipped_running", state="pending", diagnostics=existing or None)
        elif existing.get("state") == "complete":
            row.update(action="skipped_complete", state="complete", diagnostics=existing)
        elif existing.get("state") == "unavailable" and not retry_unavailable:
            row.update(action="skipped_unavailable", state="unavailable", diagnostics=existing)
        else:
            from factory.gross_diagnostics import diagnostics_for_status

            snapshot = data_snapshot_fingerprint(data_root)
            row["data_snapshot_sha256"] = snapshot
            cache_key = _fingerprint(
                {
                    "code": code,
                    "params": before.get("params"),
                    "snapshot": snapshot,
                    "timeout": timeout,
                }
            )
            cached = replay_cache.get(cache_key) if snapshot is not None else None
            if cached is not None:
                source_id, result = cached
                diagnostics = diagnostics_for_status(result, before["status"])
                row["reused_from_variant_id"] = source_id
            else:
                diagnostics = _compute(
                    before, compute=compute, data_root=data_root, timeout=timeout
                )
            if snapshot is None or data_snapshot_fingerprint(data_root) != snapshot:
                diagnostics = diagnostics_for_status(
                    _unavailable(
                        "Data snapshot changed or could not be verified during diagnostic replay."
                    ),
                    before["status"],
                )
                row["reused_from_variant_id"] = None
            elif diagnostics["state"] == "complete" and cached is None:
                replay_cache[cache_key] = (
                    identifier,
                    {**copy.deepcopy(diagnostics), "label": None},
                )
            # Validate even dry runs before claiming a usable diagnostic projection.
            _validated("variants", {**before, "gross_diagnostics": diagnostics})
            row.update(action="computed", state=diagnostics["state"], diagnostics=diagnostics)
            if apply:
                row["action"] = "staged"
                staged.append((before, run_before, diagnostics, len(report["rows"])))
        after = _raw(records, "variants", identifier)
        run_after = _raw(records, "runs", before["run_id"])
        row.update(
            finished_at=utc_now(),
            elapsed_seconds=round(time.monotonic() - started, 3),
            evidence_after_sha256=_fingerprint(without_diagnostics(after)),
            run_evidence_after_sha256=_fingerprint(without_diagnostics(run_after)),
        )
        row["non_diagnostic_evidence_unchanged"] = (
            row["evidence_before_sha256"] == row["evidence_after_sha256"]
            and row["run_evidence_before_sha256"] == row["run_evidence_after_sha256"]
        )
        report["rows"].append(redact(row))
        if on_row is not None:
            on_row(redact(report))
    if staged:
        waiting_started = utc_now()
        while True:
            active = _running_ids(records)
            alive_pids = [pid for pid in wait_pids if process_alive(pid)]
            if not active and not alive_pids:
                break
            if active and not wait_running:
                raise ValueError("Cannot apply gross diagnostics while any parent run is running")
            report["waiting"] = {
                "kind": "global_idle",
                "state": "pending",
                "run_ids": active,
                "process_ids": alive_pids,
                "started_at": waiting_started,
                "checked_at": utc_now(),
            }
            if on_row is not None:
                on_row(redact(report))
            wait(10)
        report.pop("waiting", None)
        report["backup"] = _backup(records)
        snapshot = data_snapshot_fingerprint(data_root)
        # One short transaction publishes the whole staged batch only after the
        # global idle check. Older live processes cannot read the new field.
        with records.lock, records.db:
            records.db.execute("BEGIN IMMEDIATE")
            if _running_ids(records):
                raise ValueError("Cannot apply gross diagnostics while any parent run is running")
            if any(process_alive(pid) for pid in wait_pids):
                raise ValueError("Cannot apply gross diagnostics while a guarded process is alive")
            transaction_snapshot = data_snapshot_fingerprint(data_root)
            for before, run_before, diagnostics, index in staged:
                row = report["rows"][index]
                same_data = (
                    snapshot is not None
                    and transaction_snapshot == snapshot == row["data_snapshot_sha256"]
                )
                applied = same_data and _apply_one(
                    records,
                    before,
                    run_before,
                    diagnostics,
                    in_transaction=True,
                )
                row["action"] = "applied" if applied else "conflict"
                if not same_data:
                    row["conflict_reason"] = "Data snapshot changed before deferred application."
                report["applied"] |= applied
        for before, _, _, index in staged:
            row = report["rows"][index]
            row.update(
                applied_at=utc_now() if row["action"] == "applied" else None,
                evidence_after_sha256=_fingerprint(
                    without_diagnostics(_raw(records, "variants", before["id"]))
                ),
                run_evidence_after_sha256=_fingerprint(
                    without_diagnostics(_raw(records, "runs", before["run_id"]))
                ),
            )
            row["non_diagnostic_evidence_unchanged"] = (
                row["evidence_before_sha256"] == row["evidence_after_sha256"]
                and row["run_evidence_before_sha256"] == row["run_evidence_after_sha256"]
            )
        if on_row is not None:
            on_row(redact(report))
    return redact(report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="runs")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--report", default="report/gross-diagnostics-backfill.json")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--retry-unavailable", action="store_true")
    parser.add_argument(
        "--wait-running",
        action="store_true",
        help="Stage terminal rows first, poll active rows, and apply only after global idle.",
    )
    parser.add_argument("--variant-id", action="append")
    parser.add_argument(
        "--wait-pid",
        action="append",
        type=int,
        help="Defer publication until this legacy process exits; repeat for multiple PIDs.",
    )
    parser.add_argument("--exclude-run-id", action="append")
    parser.add_argument("--timeout", type=float, default=None)
    args = parser.parse_args()
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    def save(report):
        # Each completed row survives interruption; no code or raw error text is exported.
        temporary = report_path.with_suffix(report_path.suffix + ".tmp")
        temporary.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        temporary.replace(report_path)

    with Records(args.root, read_only=not args.apply) as records:
        report = backfill(
            records,
            apply=args.apply,
            data_root=args.data_root,
            timeout=args.timeout,
            retry_unavailable=args.retry_unavailable,
            variant_ids=args.variant_id,
            exclude_run_ids=args.exclude_run_id,
            on_row=save,
            wait_running=args.wait_running,
            wait_pids=args.wait_pid,
        )
    save(report)
    print(
        json.dumps(
            {
                "report": str(report_path),
                "rows": len(report["rows"]),
                "applied": report["applied"],
                "backup": report["backup"],
            }
        )
    )


if __name__ == "__main__":
    main()
