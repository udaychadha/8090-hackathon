"""Thread-safe SQLite records and a replayable JSONL event mirror."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

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
        text = json.dumps(value, allow_nan=False, default=str)
        for name, secret in os.environ.items():
            if secret and ("KEY" in name or "TOKEN" in name or "SECRET" in name):
                text = text.replace(secret, "[REDACTED]")
        return json.loads(text)

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
        temporary = path.with_suffix(".jsonl.tmp")
        with temporary.open("w") as stream:
            for seq, payload in self.db.execute("SELECT seq,payload FROM events ORDER BY seq"):
                stream.write(json.dumps({**json.loads(payload), "seq": seq}) + "\n")
        temporary.replace(path)

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

    def close(self):
        self.db.close()


def usage_record(completion):
    return {key: value for key, value in asdict(completion).items() if key != "text"}
