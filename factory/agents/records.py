"""Strict typed SQLite records and an evidence-preserving replayable JSONL mirror."""

from __future__ import annotations

import copy
import fcntl
import json
import sqlite3
import threading
from dataclasses import asdict
from pathlib import Path

from pydantic import BaseModel, ValidationError

from factory.record_migration import (
    INDEX_COLUMNS,
    TABLES,
    index_values,
    prepare,
    setup_schema,
    utc_now,
    write_mirror,
)
from factory.record_models import RECORD_MODELS, dump
from factory.redaction import redact


class MigrationRequired(ValueError):
    """Existing legacy evidence requires an explicit backed-up migration."""


def _validated(table, payload):
    """Return canonical evidence without putting rejected input in exceptions."""
    try:
        return dump(RECORD_MODELS[table].model_validate(payload))
    except ValidationError as error:
        details = [
            f"{'.'.join(str(part) for part in item['loc']) or '<record>'}: {item['type']}"
            for item in error.errors(include_input=False, include_context=False, include_url=False)
        ]
        raise ValueError(redact(f"Invalid {table} record: {'; '.join(details)}")) from None


class Records:
    def __init__(self, root="runs", *, read_only=False):
        self.root = Path(root)
        self.read_only = read_only
        if read_only:
            path = self.root / "factory.db"
            if not path.is_file():
                raise FileNotFoundError("Research record store does not exist")
            connection = path.resolve().as_uri() + "?mode=ro"
        else:
            self.root.mkdir(parents=True, exist_ok=True)
            connection = str(self.root / "factory.db")
        self.lock = threading.RLock()
        self.db = sqlite3.connect(connection, uri=read_only, check_same_thread=False)
        tables = {
            r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if tables and version != 1:
            self.db.close()
            raise MigrationRequired(
                "Run factory.record_migration audit and migrate before opening legacy records"
            )
        if not read_only:
            with self.db:
                setup_schema(self.db)
            self._mirror()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def safe(self, value):
        return redact(value)

    def _writable(self):
        if self.read_only:
            raise PermissionError("This record connection is read-only")

    @staticmethod
    def _table(table):
        if table not in RECORD_MODELS:
            raise ValueError("Unknown record table")
        return table

    def _decode(self, table, row):
        if row is None:
            return None
        columns = [r[1] for r in self.db.execute(f"PRAGMA table_info({table})")]
        values = dict(zip(columns, row, strict=True))
        payload = json.loads(values["payload"])
        result = _validated(table, payload)
        key = values["seq"] if table == "events" else values["id"]
        if result["id"] != str(key) or (table == "events" and result["seq"] != key):
            raise ValueError("Persisted record identity mismatch")
        for field, expected in index_values(result).items():
            if values[field] != expected:
                raise ValueError(f"Persisted record index mismatch: {field}")
        return result

    def _raw(self, table, identifier):
        table = self._table(table)
        key = "seq" if table == "events" else "id"
        return self._decode(
            table, self.db.execute(f"SELECT * FROM {table} WHERE {key}=?", (identifier,)).fetchone()
        )

    @staticmethod
    def _extensions(payload, path=""):
        result = {}
        if isinstance(payload, dict):
            for key, value in payload.items():
                nested = f"{path}.{key}".strip(".")
                if key == "legacy_extensions" and value:
                    result[nested] = value
                else:
                    result.update(Records._extensions(value, nested))
        elif isinstance(payload, list):
            for i, value in enumerate(payload):
                result.update(Records._extensions(value, f"{path}.{i}"))
        return result

    def _prepared(self, table, identifier, run_id, payload):
        if isinstance(payload, BaseModel):
            payload = dump(payload)
        previous = self._raw(table, identifier)
        if self._extensions(payload) != self._extensions(previous):
            # An existing extension may not be removed silently either.
            raise ValueError("Legacy extensions are reserved for audited migration")
        value = copy.deepcopy(payload)
        if previous:
            for key in ("created_at", "created_at_provenance"):
                if key in value and value[key] != previous[key]:
                    raise ValueError("Creation metadata is immutable")
                value[key] = previous[key]
        parent = self._raw("runs", run_id)
        if parent and parent["status"] == "VOID" and not value.get("voided"):
            raise ValueError("Cannot write eligible evidence to a void run")
        source_id = (parent or {}).get("source_id")
        if source_id and value.get("source_id") not in (None, source_id):
            raise ValueError("Child source identity differs from its parent run")
        value = prepare(table, identifier, run_id, value, source_id=source_id)
        # Validate before redact: redact intentionally stringifies arbitrary objects,
        # which must never turn an invalid typed input into an accepted record.
        canonical = _validated(table, value)
        return _validated(table, self.safe(canonical))

    def _write(self, table, identifier, value):
        indexes = index_values(value)
        key = "seq" if table == "events" else "id"
        columns = [key, "payload", *indexes]
        # Explicit names preserve the original SQLite columns and support additions.
        placeholders = ",".join("?" for _ in columns)
        updates = ",".join(f"{name}=excluded.{name}" for name in columns if name != key)
        self.db.execute(
            f"INSERT INTO {table}({','.join(columns)}) VALUES({placeholders}) "
            f"ON CONFLICT({key}) DO UPDATE SET {updates}",
            (identifier, json.dumps(value, allow_nan=False), *indexes.values()),
        )

    def put(self, table, identifier, run_id, payload):
        self._writable()
        if table not in TABLES:
            raise ValueError("Unknown record table")
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            value = self._prepared(table, identifier, run_id, payload)
            self._write(table, identifier, value)
        return value

    def _visible(self, payload, include_voided):
        if include_voided:
            return True
        if payload["voided"] or payload.get("status") == "VOID":
            return False
        parent = self._raw("runs", payload["run_id"])
        return not parent or (not parent["voided"] and parent["status"] != "VOID")

    def get(self, table, identifier, *, include_voided=False):
        """Return a validated dictionary or None, excluding void records by default."""
        with self.lock:
            value = self._raw(table, identifier)
            return value if value and self._visible(value, include_voided) else None

    def list(
        self,
        table,
        *,
        run_id=None,
        source_id=None,
        variant=None,
        status=None,
        sort_by=None,
        descending=False,
        include_voided=False,
    ):
        """List canonical typed evidence; explicit audit opt-in includes invalidated rows."""
        table = self._table(table)
        clauses, args = [], []
        for field, value in [
            ("run_id", run_id),
            ("source_id", source_id),
            ("variant", variant),
            ("status", status),
        ]:
            if value is not None:
                clauses.append(f"{field}=?")
                args.append(value)
        key = "seq" if table == "events" else "id"
        order = sort_by or key
        if order not in {*INDEX_COLUMNS, key}:
            raise ValueError("Unsupported record sort field")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        direction = "DESC" if descending else "ASC"
        with self.lock:
            rows = self.db.execute(
                f"SELECT * FROM {table}{where} ORDER BY {order} {direction}, {key} {direction}",
                args,
            ).fetchall()
            values = [self._decode(table, row) for row in rows]
            return [value for value in values if self._visible(value, include_voided)]

    def events(self, run_id=None, *, after_seq=0, include_voided=False):
        return [
            row
            for row in self.list("events", run_id=run_id, include_voided=include_voided)
            if row["seq"] > after_seq
        ]

    def _mirror(self):
        """Preserve a divergent mirror before recovery; never erase sole evidence."""
        self._writable()
        path = self.root / "events.jsonl"
        with (self.root / "events.lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                # Validate all durable event records before touching the mirror.
                events = self.list("events", include_voided=True)
                expected = [json.dumps(event, allow_nan=False) for event in events]
                old = path.read_bytes() if path.exists() else b""
                try:
                    decoded = [json.loads(line) for line in old.splitlines()]
                except (ValueError, UnicodeError):
                    decoded = None
                if decoded == events:
                    return
                # A prefix is the ordinary append-after-commit case, including a
                # missing mirror. Any other difference is archived before repair.
                is_prefix = (
                    decoded is not None
                    and len(decoded) <= len(events)
                    and decoded == events[: len(decoded)]
                )
                if old and not is_prefix:
                    stamp = utc_now().replace(":", "").replace(".", "")
                    archive = self.root / f"events-recovery-{stamp}.jsonl"
                    archive.write_bytes(old)
                    archive.with_suffix(".report.json").write_text(
                        json.dumps(
                            {
                                "reason": (
                                    "Mirror differs from validated SQLite; original bytes archived"
                                ),
                                "archive": archive.name,
                                "sqlite_events": len(events),
                                "created_at": utc_now(),
                            },
                            indent=2,
                        )
                        + "\n"
                    )
                if expected or path.exists():
                    write_mirror(self.db, self.root)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _event_value(self, run_id, stage, status, message, *, variant=None, data=None):
        seq = self.db.execute("SELECT coalesce(max(seq),0)+1 FROM events").fetchone()[0]
        timestamp = utc_now()
        value = {
            "ts": timestamp,
            "run_id": run_id,
            "stage": stage,
            "variant": variant,
            "status": status,
            "message": message,
            "data": {} if data is None else data,
        }
        parent = self._raw("runs", run_id)
        value = prepare(
            "events",
            seq,
            run_id,
            value,
            parent_voided=(parent or {}).get("voided", False),
            source_id=(parent or {}).get("source_id"),
        )
        canonical = _validated("events", value)
        return _validated("events", self.safe(canonical))

    def event(self, run_id, stage, status, message, *, variant=None, data=None):
        self._writable()
        with self.lock:
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                value = self._event_value(
                    run_id, stage, status, message, variant=variant, data=data
                )
                self._write("events", value["seq"], value)
            self._mirror()
        return value

    def void_run(self, run_id, reason):
        """Atomically invalidate parent, all child records and event index flags."""
        self._writable()
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("A nonempty void reason is required")
        reason = self.safe(reason.strip())
        with self.lock:
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                summary = self._raw("runs", run_id)
                if summary is None:
                    raise KeyError(run_id)
                if summary["status"] != "VOID":
                    timestamp = utc_now()
                    # Preserve metrics and text in children; only eligibility metadata changes.
                    for table in sorted(RECORD_MODELS):
                        if table == "runs":
                            continue
                        for row in self.list(table, run_id=run_id, include_voided=True):
                            value = (
                                _void_payload(row, reason, timestamp)
                                if table == "variants"
                                else {**row, "voided": True}
                            )
                            value = _validated(table, value)
                            identifier = value["seq"] if table == "events" else value["id"]
                            self._write(table, identifier, value)
                    summary = _void_payload(summary, reason, timestamp)
                    # Keep historic nested snapshots independently; do not replace a
                    # historical source/variant with its current shared table row.
                    summary["variants"] = [
                        _void_payload(v, reason, timestamp) for v in summary.get("variants", [])
                    ]
                    summary["data_needs"] = [
                        {**v, "voided": True} for v in summary.get("data_needs", [])
                    ]
                    if summary.get("source"):
                        summary["source"] = {**summary["source"], "voided": True}
                    summary = _validated("runs", summary)
                    self._write("runs", run_id, summary)
                    event = self._event_value(
                        run_id,
                        "done",
                        "info",
                        f"Run voided: {reason}",
                        data={"status": "VOID", "reason": reason},
                    )
                    self._write("events", event["seq"], event)
            self._mirror()
            return summary

    def leaderboard(self, *, include_voided=False):
        return [
            v
            for v in self.list("variants", include_voided=include_voided)
            if include_voided or v.get("leaderboard_eligible", True)
        ]

    def trial_variants(self, run_id=None, *, include_voided=False):
        """Global reached trials; eligibility flags cannot erase an attempt."""
        parents = {r["run_id"]: r for r in self.list("runs", include_voided=True)}
        if run_id is not None and run_id not in parents:
            raise KeyError(run_id)
        reached = {
            (v["run_id"], v["variant"])
            for v in self.list("eval_results", run_id=run_id, include_voided=include_voided)
            if v["number"] == 2
        }
        trials = []
        for variant in self.list("variants", run_id=run_id, include_voided=include_voided):
            parent = parents.get(variant["run_id"], {})
            if parent.get("is_control") or variant.get("is_control"):
                continue
            if not include_voided and any(
                item.get("voided") or item.get("status") == "VOID" for item in (parent, variant)
            ):
                continue
            if (
                variant.get("reached_eval_2")
                or (variant["run_id"], variant["variant"]) in reached
                or any(e["number"] == 2 for e in variant.get("evals", []))
            ):
                trials.append(variant)
        return sorted(trials, key=lambda v: v["variant_id"])

    def close(self):
        self.db.close()


def _void_payload(payload, reason, timestamp):
    if payload.get("status") == "VOID":
        return payload
    replacements = {
        "status": "VOID",
        "default_status": "VOID",
        "evals_passed": 0,
        "default_evals_passed": 0,
        "verified_sharpe": None,
        "break_even_bps": None,
    }
    original = {key: payload[key] for key in replacements if key in payload}
    return {
        **payload,
        **{key: value for key, value in replacements.items() if key in payload},
        "status": "VOID",
        "original_result": original,
        "leaderboard_eligible": False,
        "eval_eligible": False,
        "voided": True,
        "void_reason": reason,
        "voided_at": timestamp,
    }


def usage_record(completion):
    from factory.record_models import Usage

    return dump(
        Usage.model_validate(
            {key: value for key, value in asdict(completion).items() if key != "text"}
        )
    )
