"""Read-only evidence audit and explicit, backed-up forward record migration.

Run ``python -m factory.record_migration audit --root runs --report audit.json``.
Migration refuses unresolved records and mirror conflicts unless the operator
explicitly requests mirror reconciliation. SQLite and the original JSONL are
both archived before any change. No eval or metric is recalculated.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from factory.record_models import RECORD_MODELS, SCHEMA_VERSION, dump
from factory.redaction import redact

TABLES = set(RECORD_MODELS) - {"events"}
INDEX_COLUMNS = {
    "run_id": "TEXT",
    "source_id": "TEXT",
    "variant": "TEXT",
    "status": "TEXT",
    "created_at": "TEXT",
    "voided": "INTEGER NOT NULL DEFAULT 0",
}


class MigrationError(ValueError):
    """Migration could not safely proceed; inspect the supplied audit report."""


def utc_now():
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def issue(table, identifier, field, kind, *, action=None):
    # Locations can contain untrusted keys; redact them as well as messages.
    result = {"table": table, "id": str(identifier), "field": field, "kind": kind}
    if action:
        result["action"] = action
    return redact(result)


def validation_issues(table, identifier, payload):
    try:
        RECORD_MODELS[table].model_validate(payload)
    except ValidationError as error:
        return [
            issue(table, identifier, ".".join(str(p) for p in e["loc"]), e["type"])
            for e in error.errors(include_input=False, include_context=False, include_url=False)
        ]
    return []


def index_values(payload):
    values = {name: payload.get(name) for name in INDEX_COLUMNS}
    voided = payload.get("voided", False)
    values["voided"] = int(voided) if isinstance(voided, bool) else voided
    return values


def setup_schema(db):
    """Add transport indexes without replacing legacy id/run_id/payload columns."""
    for table in sorted(TABLES):
        db.execute(
            f"CREATE TABLE IF NOT EXISTS {table} "
            "(id TEXT PRIMARY KEY, run_id TEXT NOT NULL, payload TEXT NOT NULL)"
        )
    db.execute(
        "CREATE TABLE IF NOT EXISTS events "
        "(seq INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL)"
    )
    for table in sorted(RECORD_MODELS):
        existing = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
        for name, definition in INDEX_COLUMNS.items():
            if name not in existing:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
            db.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_{name} ON {table}({name})")
    db.execute("PRAGMA user_version=1")


def prepare(
    table,
    identifier,
    run_id,
    payload,
    *,
    timestamp=None,
    legacy=False,
    parent_voided=False,
    source_id=None,
):
    """Add only storage envelope facts. Caller validates payload before storage.

    Migration sets unknown creation times to null. New writes use wall clock;
    updates supply existing envelope values rather than inventing a new creation.
    """
    value = copy.deepcopy(payload)
    if not isinstance(value, dict):
        raise ValueError("Record must be an object")
    expected = {"id": str(identifier), "run_id": run_id}
    if table == "sources":
        expected["source_id"] = str(identifier)
    if table == "variants":
        expected["variant_id"] = str(identifier)
    if table == "events":
        expected["seq"] = int(identifier)
    for key, item in expected.items():
        if key in value and value[key] != item:
            raise ValueError(f"Record identity mismatch: {key}")
        value[key] = item
    value.setdefault("schema_version", SCHEMA_VERSION)
    if table == "runs" and value.get("source"):
        source_id = value["source"]["source_id"]
    if source_id is not None:
        if value.get("source_id") is None:
            value["source_id"] = source_id
    else:
        value.setdefault("source_id", None)
    if table == "events":
        value.setdefault("created_at", value.get("ts"))
        value.setdefault(
            "created_at_provenance", {"method": "event_timestamp", "event_seq": int(identifier)}
        )
    else:
        value.setdefault("created_at", None if legacy else (timestamp or utc_now()))
        value.setdefault(
            "created_at_provenance", {"method": "unknown" if legacy else "write_clock"}
        )
    value.setdefault("voided", parent_voided or value.get("status") == "VOID")
    if table == "variants":
        value.setdefault("profile", "default")
        value.setdefault("default_status", value.get("status"))
        value.setdefault("default_evals_passed", value.get("evals_passed"))
    if table == "runs":
        if value.get("source"):
            item = value["source"]
            # Historic embedded source is a snapshot of THIS run, never the latest row.
            value["source"] = prepare(
                "sources",
                item["source_id"],
                run_id,
                item,
                timestamp=timestamp,
                legacy=legacy,
                parent_voided=value["voided"],
            )
        for key, child_table, identity in [
            ("variants", "variants", "variant_id"),
            ("data_needs", "data_needs", "id"),
        ]:
            if key in value:
                value[key] = [
                    prepare(
                        child_table,
                        item[identity],
                        run_id,
                        item,
                        timestamp=timestamp,
                        legacy=legacy,
                        parent_voided=value["voided"],
                        source_id=source_id,
                    )
                    for item in value[key]
                ]
    return value


def _read(db):
    all_rows, errors = {}, []
    existing = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in sorted(RECORD_MODELS):
        all_rows[table] = []
        if table not in existing:
            errors.append(issue(table, "*", "", "missing_table"))
            continue
        db.row_factory = sqlite3.Row
        for raw in db.execute(f"SELECT * FROM {table}"):
            row = dict(raw)
            identifier = row.get("id", row.get("seq"))
            try:
                row["decoded"] = json.loads(row["payload"])
            except (ValueError, TypeError):
                errors.append(issue(table, identifier, "", "invalid_json"))
                row["decoded"] = None
            all_rows[table].append(row)
    return all_rows, errors


def _mirror_audit(root, rows):
    path = root / "events.jsonl"
    expected = {
        r["seq"]: {**r["decoded"], "seq": r["seq"]}
        for r in rows["events"]
        if isinstance(r["decoded"], dict)
    }
    errors, validations, seen = [], [], set()
    previous_seq = 0
    if not path.exists():
        if expected:
            errors.append(issue("events.jsonl", "*", "", "missing_mirror"))
        return errors, validations
    # Read bytes per line: a single undecodable line must not hide other evidence.
    for number, raw in enumerate(path.read_bytes().splitlines(), 1):
        line_errors = []
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError
        except (ValueError, UnicodeError):
            line_errors.append(issue("events.jsonl", number, "", "invalid_json"))
        else:
            seq = value.get("seq")
            if type(seq) is not int:
                line_errors.append(issue("events.jsonl", number, "seq", "invalid_sequence"))
            else:
                if seq <= previous_seq:
                    line_errors.append(
                        issue("events.jsonl", number, "seq", "out_of_order_sequence")
                    )
                previous_seq = seq
                if seq in seen:
                    line_errors.append(issue("events.jsonl", number, "seq", "duplicate_sequence"))
                seen.add(seq)
                if seq not in expected:
                    line_errors.append(issue("events.jsonl", number, "seq", "mirror_only_event"))
                elif value != expected[seq]:
                    line_errors.append(issue("events.jsonl", number, "", "mirror_payload_mismatch"))
            line_errors.extend(
                {**item, "table": "events.jsonl", "id": str(number)}
                for item in validation_issues("events", number, value)
            )
        errors.extend(line_errors)
        validations.append(
            {
                "table": "events.jsonl",
                "id": str(number),
                "valid": not line_errors,
                "mismatch_count": len(line_errors),
            }
        )
    for seq in sorted(set(expected) - seen):
        errors.append(issue("events.jsonl", seq, "seq", "missing_event"))
    return errors, validations


def _audit(root, db, rows, initial_errors):
    mismatches = list(initial_errors)
    validations = []
    counts = {table: len(items) for table, items in rows.items()}
    canonical = db.execute("PRAGMA user_version").fetchone()[0] == 1
    for table, items in rows.items():
        for row in items:
            identifier = row.get("id", row.get("seq"))
            payload = row["decoded"]
            found = []
            if isinstance(payload, dict):
                found = validation_issues(table, identifier, payload)
                if table == "events":
                    expected = {"id": str(identifier), "seq": identifier}
                else:
                    expected = {"id": identifier, "run_id": row["run_id"]}
                for field, expected_value in expected.items():
                    if field in payload and payload[field] != expected_value:
                        found.append(issue(table, identifier, field, "identity_mismatch"))
                if canonical:
                    for field, expected_value in index_values(payload).items():
                        if row.get(field) != expected_value:
                            found.append(issue(table, identifier, field, "index_mismatch"))
            elif payload is not None:
                found = [issue(table, identifier, "", "not_object")]
            else:
                found = [issue(table, identifier, "", "invalid_json")]
            mismatches.extend(found)
            validations.append(
                {
                    "table": table,
                    "id": str(identifier),
                    "valid": not found,
                    "mismatch_count": len(found),
                }
            )
    mirror_errors, mirror_validations = _mirror_audit(root, rows)
    mismatches.extend(mirror_errors)
    validations.extend(mirror_validations)
    counts["jsonl_lines"] = len(mirror_validations)
    return {
        "schema_version": SCHEMA_VERSION,
        "counts": counts,
        "mismatches": mismatches,
        "validations": validations,
        "migrated": False,
    }


def audit(root="runs"):
    """Validate EVERY row and JSONL line without opening a writable database."""
    root = Path(root)
    with sqlite3.connect(f"file:{(root / 'factory.db').resolve()}?mode=ro", uri=True) as db:
        rows, errors = _read(db)
        return _audit(root, db, rows, errors)


def _retain_unknown(table, identifier, value, changes):
    """Move each unrecognized field into explicit root extensions; never drop it."""
    while True:
        try:
            RECORD_MODELS[table].model_validate(value)
            return value
        except ValidationError as error:
            extras = [
                e
                for e in error.errors(include_input=False, include_context=False, include_url=False)
                if e["type"] == "extra_forbidden"
            ]
            if not extras:
                return value  # Caller reports every unresolved error before refusing migration.
            moved = False
            for extra in extras:
                path = extra["loc"]
                target = value
                try:
                    for part in path[:-1]:
                        target = target[part]
                    key = ".".join(str(part) for part in path)
                    extensions = value.setdefault("legacy_extensions", {})
                    if key in extensions:
                        raise MigrationError("Legacy extension collision; manual review required")
                    extensions[key] = target.pop(path[-1])
                except (KeyError, TypeError, IndexError):
                    continue
                changes.append(
                    issue(
                        table,
                        identifier,
                        key,
                        "extra_forbidden",
                        action=f"retained as legacy_extensions.{key}",
                    )
                )
                moved = True
            if not moved:
                return value


def _changes(before, after, table, identifier, path=""):
    changes = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in after.keys() - before.keys():
            changes.append(
                issue(
                    table,
                    identifier,
                    f"{path}.{key}".strip("."),
                    "added",
                    action="storage metadata; no strategy evidence recomputed",
                )
            )
        for key in before.keys() - after.keys():
            changes.append(
                issue(
                    table,
                    identifier,
                    f"{path}.{key}".strip("."),
                    "relocated",
                    action="retained in legacy_extensions",
                )
            )
        for key in before.keys() & after.keys():
            changes.extend(
                _changes(before[key], after[key], table, identifier, f"{path}.{key}".strip("."))
            )
    elif isinstance(before, list) and isinstance(after, list):
        for i, (left, right) in enumerate(zip(before, after, strict=True)):
            changes.extend(_changes(left, right, table, identifier, f"{path}.{i}"))
    elif before != after:
        changes.append(
            issue(table, identifier, path, "changed", action="explicit forward migration")
        )
    return changes


def _write_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(redact(report), indent=2, allow_nan=False) + "\n")


def write_mirror(db, root):
    path = Path(root) / "events.jsonl"
    temporary = path.with_suffix(".jsonl.tmp")
    with temporary.open("w") as stream:
        for seq, encoded in db.execute("SELECT seq,payload FROM events ORDER BY seq"):
            payload = json.loads(encoded)
            RECORD_MODELS["events"].model_validate(payload)
            if payload["seq"] != seq or payload["id"] != str(seq):
                raise ValueError("Event identity mismatch in SQLite")
            stream.write(json.dumps(payload, allow_nan=False) + "\n")
    temporary.replace(path)


def _backup(root, report):
    backup = root / ("record-backup-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"))
    backup.mkdir()
    # Backup from a separate read connection: backup() on our active write
    # transaction would block. BEGIN IMMEDIATE already excludes other writers.
    with sqlite3.connect(f"file:{(root / 'factory.db').resolve()}?mode=ro", uri=True) as source:
        with sqlite3.connect(backup / "factory.db") as target:
            source.backup(target)
    if (root / "events.jsonl").exists():
        shutil.copy2(root / "events.jsonl", backup / "events.jsonl")
    report["backup"] = backup.name
    report["backup_sha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in backup.iterdir() if p.is_file()
    }
    _write_report(backup / "audit.json", report)
    return backup


def migrate(root="runs", *, report_path, reconcile_mirror=False):
    """Explicit operator action. Validate the entire plan before backing up/writing."""
    root = Path(root)
    db = sqlite3.connect(root / "factory.db")
    try:
        db.execute("BEGIN IMMEDIATE")  # One stable snapshot and no concurrent record writes.
        rows, initial_errors = _read(db)
        report = _audit(root, db, rows, initial_errors)
        _write_report(report_path, report)
        if db.execute("PRAGMA user_version").fetchone()[0] == 1:
            _write_report(report_path, report)
            if not report["mismatches"]:
                return report
            if (
                any(m["table"] != "events.jsonl" for m in report["mismatches"])
                or not reconcile_mirror
            ):
                raise MigrationError("Canonical store has mismatches; review audit report")
            # The DB is already canonical (e.g. a previous commit succeeded but
            # JSONL replacement failed). Explicit approval repairs only the mirror.
            report["mirror_reconciliation_requested"] = True
            _backup(root, report)
            db.row_factory = None
            write_mirror(db, root)
            db.commit()
            report["mirror_recovered"] = True
            report["post_migration"] = audit(root)
            _write_report(report_path, report)
            return report
        changes, planned, unresolved = [], {}, []
        runs = {r["id"]: r["decoded"] for r in rows["runs"] if isinstance(r["decoded"], dict)}
        for table, items in rows.items():
            planned[table] = []
            for row in items:
                identifier = row.get("id", row.get("seq"))
                original = row["decoded"]
                if not isinstance(original, dict):
                    unresolved.append(issue(table, identifier, "", "invalid_record"))
                    continue
                run_id = original.get("run_id") if table == "events" else row["run_id"]
                if not isinstance(run_id, str) or not run_id:
                    unresolved.append(issue(table, identifier, "run_id", "invalid_identity"))
                    continue
                parent = runs.get(run_id, {})
                source = parent.get("source")
                source_id = source.get("source_id") if isinstance(source, dict) else None
                try:
                    candidate = prepare(
                        table,
                        identifier,
                        run_id,
                        original,
                        legacy=True,
                        parent_voided=parent.get("status") == "VOID",
                        source_id=source_id,
                    )
                except (ValueError, TypeError, KeyError):
                    unresolved.append(
                        issue(table, identifier, "", "identity_or_structure_mismatch")
                    )
                    continue
                try:
                    candidate = _retain_unknown(table, identifier, candidate, changes)
                except MigrationError:
                    unresolved.append(
                        issue(table, identifier, "legacy_extensions", "extension_collision")
                    )
                    continue
                problems = validation_issues(table, identifier, candidate)
                unresolved.extend(problems)
                if not problems:
                    canonical = dump(RECORD_MODELS[table].model_validate(candidate))
                    changes.extend(_changes(original, canonical, table, identifier))
                    planned[table].append((identifier, canonical))
        report["changes"] = changes
        report["unresolved"] = unresolved
        mirror_conflicts = [
            m
            for m in report["mismatches"]
            if m["table"] == "events.jsonl"
            and m["kind"]
            in {
                "invalid_json",
                "invalid_sequence",
                "duplicate_sequence",
                "mirror_only_event",
                "mirror_payload_mismatch",
                "missing_mirror",
                "missing_event",
                "out_of_order_sequence",
            }
        ]
        report["mirror_reconciliation_requested"] = reconcile_mirror
        _write_report(report_path, report)
        if unresolved or initial_errors or (mirror_conflicts and not reconcile_mirror):
            raise MigrationError("Unresolved record or mirror mismatches; review audit report")
        _backup(root, report)
        setup_schema(db)
        for table, entries in planned.items():
            for identifier, value in entries:
                indexes = index_values(value)
                assignments = ",".join(f"{key}=?" for key in indexes)
                key = "seq" if table == "events" else "id"
                db.execute(
                    f"UPDATE {table} SET payload=?,{assignments} WHERE {key}=?",
                    (json.dumps(value, allow_nan=False), *indexes.values(), identifier),
                )
        db.commit()
        report["migrated"] = True
        _write_report(report_path, report)  # Commit is durable even if mirror write fails.
        db.row_factory = None
        write_mirror(db, root)
        report["post_migration"] = audit(root)
        _write_report(report_path, report)
        return report
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["audit", "migrate"])
    parser.add_argument("--root", default="runs")
    parser.add_argument("--report", required=True)
    parser.add_argument("--reconcile-mirror", action="store_true")
    args = parser.parse_args()
    if args.action == "audit":
        result = audit(args.root)
        _write_report(args.report, result)
    else:
        result = migrate(args.root, report_path=args.report, reconcile_mirror=args.reconcile_mirror)
    print(
        json.dumps(
            {
                "counts": result["counts"],
                "mismatches": len(result["mismatches"]),
                "migrated": result["migrated"],
                "report": args.report,
            }
        )
    )


if __name__ == "__main__":
    main()
