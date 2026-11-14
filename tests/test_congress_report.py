"""The final proof permits diagnostics only; original research evidence stays fixed."""

import hashlib
import json
import sqlite3

import pytest


def test_historical_proof_allows_only_authorized_diagnostic_addition(tmp_path):
    from scripts.report_congress_results import verify_historical_records

    (tmp_path / "report").mkdir()
    (tmp_path / "runs").mkdir()
    original = {"id": "v", "status": "FAILED_EVAL_2", "evals_passed": 1}
    canonical = hashlib.sha256(json.dumps(original, sort_keys=True).encode()).hexdigest()
    baseline = {
        "original_payload_bytes_verified": True,
        "canonical": {"variants": {"v": canonical}},
    }
    (tmp_path / "report/wo12-pre-diagnostics-baseline.json").write_text(json.dumps(baseline))
    with sqlite3.connect(tmp_path / "runs/factory.db") as db:
        db.execute("CREATE TABLE variants (id TEXT, payload TEXT)")
        augmented = {**original, "gross_diagnostics": {"state": "unavailable"}}
        db.execute("INSERT INTO variants VALUES (?,?)", ("v", json.dumps(augmented)))
    assert verify_historical_records(tmp_path) == {"variants": 1}
    with sqlite3.connect(tmp_path / "runs/factory.db") as db:
        db.execute("UPDATE variants SET payload=?", (json.dumps({**augmented, "evals_passed": 2}),))
    with pytest.raises(AssertionError, match="variants"):
        verify_historical_records(tmp_path)
