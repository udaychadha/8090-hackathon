"""Thread-safe SQLite records and a replayable JSONL event mirror."""

from __future__ import annotations

import fcntl
import json
import sqlite3
import threading
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from factory.redaction import redact

TABLES = {"sources", "runs", "variants", "eval_results", "heal_attempts", "critiques", "data_needs"}
STAGES = {"intake", "extract", "data", "worker", "heal", "eval", "critic", "done"}


class Records:
    def __init__(self, root="runs"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / "factory.db", check_same_thread=False)
        for table in sorted(TABLES):
            self.db.execute(
                f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, "
                "run_id TEXT NOT NULL, payload TEXT NOT NULL)"
            )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS events "
            "(seq INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL)"
        )
        self.db.commit()
        # SQLite is authoritative; repair a missing/torn mirror after interruption.
        self._mirror()

    def safe(self, value):
        return redact(value)

    def put(self, table, identifier, run_id, payload):
        if table not in TABLES:
            raise ValueError("Unknown record table")
        with self.lock:
            self.db.execute(
                f"INSERT OR REPLACE INTO {table} VALUES (?, ?, ?)",
                (identifier, run_id, json.dumps(self.safe(payload))),
            )
            self.db.commit()

    def _mirror(self):
        path = self.root / "events.jsonl"
        # Serialize snapshots across separate runs/processes, not just this instance.
        with (self.root / "events.lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                temporary = path.with_suffix(".jsonl.tmp")
                with temporary.open("w") as stream:
                    for seq, payload in self.db.execute(
                        "SELECT seq,payload FROM events ORDER BY seq"
                    ):
                        stream.write(json.dumps({**json.loads(payload), "seq": seq}) + "\n")
                temporary.replace(path)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def event(self, run_id, stage, status, message, *, variant=None, data=None):
        if stage not in STAGES or status not in {"started", "passed", "failed", "info"}:
            raise ValueError("Invalid event stage or status")
        if variant not in {None, "A", "B", "C"}:
            raise ValueError("Invalid variant")
        payload = self.safe(
            {
                "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "run_id": run_id,
                "stage": stage,
                "variant": variant,
                "status": status,
                "message": message,
                "data": data or {},
            }
        )
        with self.lock:
            self.db.execute("INSERT INTO events(payload) VALUES (?)", (json.dumps(payload),))
            self.db.commit()
            self._mirror()

    def void_run(self, run_id, reason):
        """Invalidate a run without deleting its research evidence.

        The state change and audit event commit together. JSONL is mirrored only
        after commit; retrying this method repairs a failed mirror without adding
        another event or replacing the original reason.
        """
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("A nonempty void reason is required")
        reason = self.safe(reason.strip())
        with self.lock:
            with self.db:
                # Also serialize invalidation through other Records instances.
                self.db.execute("BEGIN IMMEDIATE")
                row = self.db.execute("SELECT payload FROM runs WHERE id = ?", (run_id,)).fetchone()
                if row is None:
                    raise KeyError(run_id)
                summary = json.loads(row[0])
                if summary.get("status") != "VOID":
                    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                    variants = {}
                    for identifier, encoded in self.db.execute(
                        "SELECT id, payload FROM variants WHERE run_id = ? ORDER BY id",
                        (run_id,),
                    ).fetchall():
                        variant = _void_payload(json.loads(encoded), reason, timestamp)
                        variants[identifier] = variant
                        self.db.execute(
                            "UPDATE variants SET payload = ? WHERE id = ?",
                            (json.dumps(variant), identifier),
                        )
                    summary = _void_payload(summary, reason, timestamp)
                    # Retain summary-only evidence if an interrupted run did not
                    # persist its variant table; otherwise use the canonical row.
                    summary_rows = summary.get("variants", [])
                    summary["variants"] = [
                        variants.pop(item.get("variant_id"), None)
                        or _void_payload(item, reason, timestamp)
                        for item in summary_rows
                    ] + list(variants.values())
                    self.db.execute(
                        "UPDATE runs SET payload = ? WHERE id = ?",
                        (json.dumps(summary), run_id),
                    )
                    event = {
                        "ts": timestamp,
                        "run_id": run_id,
                        "stage": "done",
                        "variant": None,
                        "status": "info",
                        "message": f"Run voided: {reason}",
                        "data": {"status": "VOID", "reason": reason},
                    }
                    self.db.execute("INSERT INTO events(payload) VALUES (?)", (json.dumps(event),))
            self._mirror()
            return summary

    def leaderboard(self):
        """Return eligible variant payloads, excluding invalidated parent runs."""
        with self.lock:
            rows = self.db.execute(
                "SELECT variants.payload, runs.payload FROM variants "
                "JOIN runs ON runs.id = variants.run_id ORDER BY variants.id"
            ).fetchall()
        return [
            variant
            for encoded, parent in rows
            if _eligible((variant := json.loads(encoded)), "leaderboard_eligible")
            and _eligible(json.loads(parent), "leaderboard_eligible")
        ]

    def trial_variants(self, run_id):
        """Return eligible siblings that reached Eval 2, including failed trials.

        Legacy rows need no eligibility flag. Persisted eval_results are evidence
        even when a variant's embedded eval list was not yet written.
        """
        with self.lock:
            parent = self.db.execute("SELECT payload FROM runs WHERE id = ?", (run_id,)).fetchone()
            if parent is None:
                raise KeyError(run_id)
            if not _eligible(json.loads(parent[0]), "eval_eligible"):
                return []
            rows = self.db.execute(
                "SELECT payload FROM variants WHERE run_id = ? ORDER BY id", (run_id,)
            ).fetchall()
            results = [
                json.loads(row[0])
                for row in self.db.execute(
                    "SELECT payload FROM eval_results WHERE run_id = ?", (run_id,)
                )
            ]
        reached = {result.get("variant") for result in results if _eval_two(result)}
        return [
            variant
            for (encoded,) in rows
            if _eligible((variant := json.loads(encoded)), "eval_eligible")
            and (
                variant.get("variant") in reached
                or any(_eval_two(result) for result in variant.get("evals", []))
            )
        ]

    def close(self):
        self.db.close()


def _eligible(payload, flag):
    return payload.get("status") != "VOID" and payload.get(flag, True) is True


def _eval_two(result):
    return result.get("number", result.get("n")) == 2


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
        "void_reason": reason,
        "voided_at": timestamp,
    }


def usage_record(completion):
    return {key: value for key, value in asdict(completion).items() if key != "text"}
