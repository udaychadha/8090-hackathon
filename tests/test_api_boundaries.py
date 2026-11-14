"""Read APIs must not mutate evidence or expose credentials."""

import json
from pathlib import Path

import pytest

from factory.agents.records import Records


def test_readonly_store_never_repairs_or_writes(tmp_path):
    with Records(tmp_path) as records:
        records.put("runs", "r", "r", {"run_id": "r", "status": "FAILED"})
        records.event("r", "done", "failed", "Recorded failure")
    (tmp_path / "events.jsonl").write_text("torn mirror\n")
    original = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    with Records(tmp_path, read_only=True) as records:
        assert records.get("runs", "r")["status"] == "FAILED"
        assert len(records.events("r")) == 1
        with pytest.raises(PermissionError):
            records.event("r", "done", "info", "Forbidden write")
        with pytest.raises(PermissionError):
            records.put("runs", "new", "new", {"run_id": "new", "status": "RUNNING"})
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == original


def test_readonly_missing_store_does_not_create_directories(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(FileNotFoundError):
        Records(missing, read_only=True)
    assert not missing.exists()


def test_response_sanitizer_handles_urls_and_nested_secrets(monkeypatch):
    from factory.api.common import sanitize

    monkeypatch.setenv("OPENAI_API_KEY", "configured-secret")
    value = {
        "title": "configured-secret",
        "nested": {"api_key": "older-key"},
        "url": "https://user:pass@example.org/paper?rlkey=capability&dl=1",
        "narrative": "See https://example.org/file?access_token=hidden&version=2.",
        "input_tokens": 123,
        "key": "BASE_COST_BPS",
    }
    result = sanitize(value)
    encoded = json.dumps(result)
    assert all(
        secret not in encoded
        for secret in [
            "configured-secret",
            "older-key",
            "user:pass",
            "capability",
            "hidden",
        ]
    )
    assert result["input_tokens"] == 123
    assert result["key"] == "BASE_COST_BPS"
    assert "dl=1" in result["url"]


def test_api_submission_keeps_only_safe_relative_input_paths(tmp_path):
    with Records(tmp_path) as records:
        submission = {
            "origin": "api",
            "upload_name": "paper.pdf",
            "upload_sha256": "a" * 64,
            "accepted_at": "2026-11-14T11:00:00Z",
            "input_path": "/etc/passwd",
        }
        with pytest.raises(ValueError):
            records.put(
                "runs", "r", "r", {"run_id": "r", "status": "RUNNING", "submission": submission}
            )
        submission["input_path"] = "runs/uploads/r/paper.pdf"
        row = records.put(
            "runs", "r", "r", {"run_id": "r", "status": "RUNNING", "submission": submission}
        )
        assert row["submission"]["input_path"] == "runs/uploads/r/paper.pdf"
        assert Path(row["submission"]["input_path"]).is_absolute() is False
