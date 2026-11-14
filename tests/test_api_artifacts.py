"""Evidence registry must not become a filesystem or holdout download service."""

import json

import pytest


def test_gross_diagnostic_reports_and_backups_are_audit_evidence(tmp_path):
    from factory.api.artifacts import ArtifactRegistry

    (tmp_path / "report").mkdir()
    report = tmp_path / "report/gross-diagnostics-backfill.json"
    report.write_text('{"rows": []}')
    backup = tmp_path / "runs/gross-diagnostics-backup-test"
    backup.mkdir(parents=True)
    (backup / "factory.db").write_bytes(b"backup metadata only")
    registry = ArtifactRegistry(tmp_path)
    assert report.relative_to(tmp_path).as_posix() not in {a.name for a in registry.list()}
    entries = {a.name: a for a in registry.list(include_voided=True)}
    assert entries["report/gross-diagnostics-backfill.json"].audit_only
    stored = entries["runs/gross-diagnostics-backup-test/factory.db"]
    assert stored.audit_only and not stored.downloadable


def test_rejudgment_evidence_is_available_only_in_audit_mode(artifact_root):
    from factory.api.artifacts import ArtifactRegistry

    (artifact_root / "report/eval45-rejudgment.md").write_text("r_void_A: VOID → VOID")
    backup = artifact_root / "runs/rejudge-backup-2026-11-14T120000Z"
    backup.mkdir()
    (backup / "plan.json").write_text('{"trial_count":13}')
    (backup / "factory.db").write_bytes(b"snapshot")
    (backup / "secret.txt").write_text("not allowlisted")
    registry = ArtifactRegistry(artifact_root)
    assert not any("rejudge" in item.name for item in registry.list())
    entries = {item.name: item for item in registry.list(include_voided=True)}
    report = entries["report/eval45-rejudgment.md"]
    assert report.audit_only and report.historical
    assert "r_void_A" in registry.view(report.id, include_voided=True).content
    assert entries[f"runs/{backup.name}/plan.json"].audit_only
    assert not entries[f"runs/{backup.name}/factory.db"].downloadable
    assert f"runs/{backup.name}/secret.txt" not in entries


@pytest.fixture
def artifact_root(tmp_path):
    from factory.agents.records import Records

    (tmp_path / "report").mkdir()
    with Records(tmp_path / "runs") as records:
        records.put("runs", "r_live", "r_live", {"run_id": "r_live", "status": "COMPLETED"})
        records.put("runs", "r_void", "r_void", {"run_id": "r_void", "status": "COMPLETED"})
        records.event("r_live", "done", "passed", "Kept")
        records.event("r_void", "done", "passed", "Hidden")
        records.void_run("r_void", "Historical invalidation")
    (tmp_path / "report/wo17-r_live.json").write_text(
        json.dumps({"run_id": "r_live", "key": "SECRET123"})
    )
    (tmp_path / "report/wo17-r_void.json").write_text(json.dumps({"run_id": "r_void"}))
    (tmp_path / "report/wo17-results.json").write_text(
        json.dumps(
            {
                "attempts": [{"run_id": "r_live"}, {"run_id": "r_void"}],
            }
        )
    )
    (tmp_path / "report/wo17-audit-step1.json").write_text(
        json.dumps(
            {
                "files": [],
                "cross_tier_spy_examples": [{"daily_close": 999999}],
            }
        )
    )
    (tmp_path / "runs/secrets.env").write_text("TOP_SECRET=SECRET123")
    return tmp_path


def test_artifact_registry_redacts_and_excludes_void_children(artifact_root, monkeypatch):
    from fastapi import HTTPException

    from factory.api.artifacts import ArtifactRegistry

    monkeypatch.setenv("TEST_API_KEY", "SECRET123")
    registry = ArtifactRegistry(artifact_root)
    names = {x.name: x for x in registry.list()}
    assert "report/wo17-r_live.json" in names
    assert "report/wo17-r_void.json" not in names
    artifact = names["report/wo17-r_live.json"]
    assert "SECRET123" not in registry.view(artifact.id).content
    data, media, filename = registry.download(artifact.id)
    assert b"SECRET123" not in data and media == "application/json"
    assert filename == "wo17-r_live.json"
    void = next(x for x in registry.list(include_voided=True) if x.name.endswith("r_void.json"))
    with pytest.raises(HTTPException) as hidden:
        registry.view(void.id)
    assert hidden.value.status_code == 404
    assert "r_void" in registry.view(void.id, include_voided=True).content


def test_mixed_exports_filter_void_records_and_holdout_examples(artifact_root):
    from factory.api.artifacts import ArtifactRegistry

    registry = ArtifactRegistry(artifact_root)
    entries = {a.name: a for a in registry.list()}
    for name in ["runs/events.jsonl", "report/wo17-results.json"]:
        assert "r_void" not in registry.view(entries[name].id).content
    audit = registry.view(entries["report/wo17-audit-step1.json"].id)
    assert "999999" not in audit.content


def test_nested_migration_audit_hides_void_identifiers_and_preserves_nulls(artifact_root):
    from factory.api.artifacts import ArtifactRegistry

    (artifact_root / "report/wo09-record-audit-before.json").write_text(
        json.dumps(
            {
                "rows": [
                    {"id": "r_void_A", "table": "variants"},
                    {"id": "r_live_A", "unknown": None},
                ],
                "by_id": {"r_void": "hidden", "r_live": "retained"},
                "message": "Audit of r_void is historical",
            }
        )
    )
    registry = ArtifactRegistry(artifact_root)
    entry = next(a for a in registry.list() if a.name.endswith("wo09-record-audit-before.json"))
    content = registry.view(entry.id).content
    assert "r_void" not in content
    assert json.loads(content)["rows"] == [{"id": "r_live_A", "unknown": None}]


def test_registered_binary_and_html_captures_require_explicit_audit(artifact_root):
    from factory.api.artifacts import ArtifactRegistry

    (artifact_root / "report/wo07-real-paper.html").write_text('<script>alert("r_void")</script>')
    (artifact_root / "report/wo07-real-paper.jpg").write_bytes(b"historic-image")
    (artifact_root / "runs/wo07-real-paper.json").write_text('{"run_id":"r_void"}')
    registry = ArtifactRegistry(artifact_root)
    assert not any(a.kind == "historical_capture" for a in registry.list())
    entries = registry.list(run_id="r_void", include_voided=True)
    image = next(a for a in entries if a.name.endswith(".jpg"))
    html = next(a for a in entries if a.name.endswith(".html"))
    assert registry.view(image.id, include_voided=True).content is None
    assert registry.download(image.id, include_voided=True)[0] == b"historic-image"
    _, media, filename = registry.download(html.id, include_voided=True)
    assert media == "text/plain" and filename.endswith(".html.txt")


def test_artifact_read_rechecks_symlink_after_inventory(artifact_root, monkeypatch):
    from fastapi import HTTPException

    from factory.api.artifacts import ArtifactRegistry

    registry = ArtifactRegistry(artifact_root)
    entry = next(a for a in registry.list() if a.name.endswith("r_live.json"))
    original = registry._resolve

    def replace_after_resolve(*args, **kwargs):
        result = original(*args, **kwargs)
        path = result[1]
        path.unlink()
        path.symlink_to(artifact_root / "runs/secrets.env")
        return result

    monkeypatch.setattr(registry, "_resolve", replace_after_resolve)
    with pytest.raises(HTTPException) as denied:
        registry.view(entry.id)
    assert denied.value.status_code == 404


def test_artifacts_deny_database_secrets_arbitrary_path_and_symlink(artifact_root, tmp_path):
    from fastapi import HTTPException

    from factory.api.artifacts import ArtifactRegistry

    (artifact_root / "report/wo17-canary.json").symlink_to(artifact_root / "runs/secrets.env")
    registry = ArtifactRegistry(artifact_root)
    names = {a.name for a in registry.list(include_voided=True)}
    assert "runs/secrets.env" not in names
    assert "report/wo17-canary.json" not in names
    with pytest.raises(HTTPException) as missing:
        registry.view("../../runs/secrets.env")
    assert missing.value.status_code == 404
    database = next(a for a in registry.list() if a.name == "runs/factory.db")
    assert not database.downloadable
    with pytest.raises(HTTPException) as denied:
        registry.download(database.id)
    assert denied.value.status_code == 404


def test_artifact_routes_bound_preview_and_force_safe_attachment(artifact_root):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from factory.api.artifacts import router

    app = FastAPI()
    app.state.root = artifact_root
    app.include_router(router)
    client = TestClient(app)
    rows = client.get("/api/artifacts").json()["artifacts"]
    entry = next(a for a in rows if a["name"].endswith("r_live.json"))
    view = client.get(f"/api/artifacts/{entry['id']}?limit=5").json()
    assert len(view["content"]) == 5 and view["next_offset"] == 5
    response = client.get(f"/api/artifacts/{entry['id']}/download")
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_owned_upload_directory_and_recovery_evidence_are_registered(artifact_root):
    from factory.agents.records import Records
    from factory.api.artifacts import ArtifactRegistry

    directory = artifact_root / "runs/uploads/r_live"
    directory.mkdir(parents=True)
    (directory / "paper.pdf").write_bytes(b"%PDF-1.4 source")
    (directory / "paper.md").write_text("Extracted paper")
    (directory / "paper.spec.json").write_text('{"extraction_status":"pending"}')
    with Records(artifact_root / "runs") as records:
        run = records.get("runs", "r_live")
        run["submission"] = {
            "origin": "api",
            "input_path": "runs/uploads/r_live/paper.pdf",
            "upload_name": "paper.pdf",
            "upload_sha256": "0" * 64,
            "accepted_at": "2026-11-14T00:00:00Z",
        }
        records.put("runs", "r_live", "r_live", run)
    (artifact_root / "runs/events-recovery-test.jsonl").write_text('{"run_id":"r_void"}\n')
    (artifact_root / "runs/events-recovery-test.report.json").write_text('{"reason":"torn mirror"}')
    registry = ArtifactRegistry(artifact_root)
    own = registry.list(run_id="r_live")
    assert {a.name for a in own} >= {
        "runs/uploads/r_live/paper.pdf",
        "runs/uploads/r_live/paper.md",
        "runs/uploads/r_live/paper.spec.json",
    }
    assert not any(a.kind == "event_backup" for a in registry.list())
    archived = {a.name for a in registry.list(include_voided=True) if a.kind == "event_backup"}
    assert archived >= {
        "runs/events-recovery-test.jsonl",
        "runs/events-recovery-test.report.json",
    }


def test_real_migration_reports_do_not_leak_void_ids():
    from pathlib import Path

    from factory.api.artifacts import ArtifactRegistry

    root = Path(__file__).resolve().parents[1]
    if not (root / "report/wo09-record-audit-before.json").exists():
        pytest.skip("Local migration reports unavailable")
    registry = ArtifactRegistry(root)
    for artifact in registry.list():
        if artifact.name.startswith("report/wo09-record-"):
            content = registry.view(artifact.id).content
            assert "r_449ef7fd3ae6" not in content


def test_torn_recovery_mirror_remains_viewable_as_sanitized_audit_text(artifact_root, monkeypatch):
    from factory.api.artifacts import ArtifactRegistry

    monkeypatch.setenv("TEST_API_KEY", "SECRET123")
    (artifact_root / "runs/events-recovery-torn.jsonl").write_text(
        '{"run_id":"r_void","message":"SECRET123"}\n{"torn":'
    )
    registry = ArtifactRegistry(artifact_root)
    artifact = next(
        a
        for a in registry.list(include_voided=True)
        if a.name.endswith("events-recovery-torn.jsonl")
    )
    view = registry.view(artifact.id, include_voided=True)
    assert '"torn":' in view.content and "SECRET123" not in view.content


def test_torn_migration_backup_requires_audit_and_preserves_original_bytes(
    artifact_root, monkeypatch
):
    from fastapi import HTTPException

    from factory.api.artifacts import ArtifactRegistry

    monkeypatch.setenv("TEST_API_KEY", "SECRET123")
    directory = artifact_root / "runs/record-backup-test"
    directory.mkdir()
    original = b'{"run_id":"r_void","message":"SECRET123"}\n{"torn":'
    path = directory / "events.jsonl"
    path.write_bytes(original)
    registry = ArtifactRegistry(artifact_root)
    assert not any(a.name == "runs/record-backup-test/events.jsonl" for a in registry.list())
    artifact = next(
        a
        for a in registry.list(include_voided=True)
        if a.name == "runs/record-backup-test/events.jsonl"
    )
    with pytest.raises(HTTPException) as hidden:
        registry.view(artifact.id)
    assert hidden.value.status_code == 404
    view = registry.view(artifact.id, include_voided=True)
    assert '"torn":' in view.content and "SECRET123" not in view.content
    downloaded, media_type, _ = registry.download(artifact.id, include_voided=True)
    assert b'"torn":' in downloaded and b"SECRET123" not in downloaded
    assert media_type == "text/plain"
    assert path.read_bytes() == original
