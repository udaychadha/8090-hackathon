"""Migration preserves original evidence and refuses unreviewed mirror conflicts."""

import importlib.util
import json
import sqlite3

import pytest


def legacy_store(root):
    root.mkdir(exist_ok=True)
    db = sqlite3.connect(root / "factory.db")
    for table in (
        "sources",
        "runs",
        "variants",
        "eval_results",
        "heal_attempts",
        "critiques",
        "data_needs",
    ):
        db.execute(
            f"CREATE TABLE {table}(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,payload TEXT NOT NULL)"
        )
    db.execute("CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT,payload TEXT NOT NULL)")
    db.execute(
        "INSERT INTO runs VALUES(?,?,?)",
        ("r", "r", json.dumps({"run_id": "r", "status": "FAILED", "legacy_note": {"keep": 3}})),
    )
    event = {
        "ts": "2026-11-14T06:20:03Z",
        "run_id": "r",
        "stage": "done",
        "variant": None,
        "status": "failed",
        "message": "Run failed",
        "data": {"status": "FAILED"},
    }
    db.execute("INSERT INTO events(payload) VALUES(?)", (json.dumps(event),))
    db.commit()
    db.close()
    (root / "events.jsonl").write_text(json.dumps({"seq": 1, **event}) + "\n")


def test_migration_module_exists():
    assert importlib.util.find_spec("factory.record_migration") is not None


def test_audit_all_rows_and_lines_and_migration_retains_extensions(tmp_path):
    from factory.record_migration import audit, migrate

    root = tmp_path / "runs"
    legacy_store(root)
    before = (root / "factory.db").read_bytes()
    report = audit(root)
    assert (
        report["counts"]["runs"]
        == report["counts"]["events"]
        == report["counts"]["jsonl_lines"]
        == 1
    )
    assert any(x["table"] == "runs" and x["field"] == "legacy_note" for x in report["mismatches"])
    assert (root / "factory.db").read_bytes() == before
    result = migrate(root, report_path=tmp_path / "report.json")
    assert result["migrated"]
    assert (root / result["backup"] / "factory.db").is_file()
    from factory.agents.records import Records

    with Records(root) as records:
        row = records.get("runs", "r")
        assert row["legacy_extensions"]["legacy_note"] == {"keep": 3}
        assert row["created_at"] is None
        assert row["created_at_provenance"]["method"] == "unknown"
        event = records.events()[0]
        assert event["created_at"] == "2026-11-14T06:20:03Z"
        with pytest.raises(ValueError):
            records.put(
                "runs",
                "other",
                "other",
                {"run_id": "other", "status": "RUNNING", "legacy_extensions": {"injected": 1}},
            )
    assert not audit(root)["mismatches"]
    again = migrate(root, report_path=tmp_path / "again.json")
    assert not again["migrated"]


def test_bad_mirror_requires_explicit_reconciliation_and_archives_original(tmp_path):
    from factory.record_migration import MigrationError, migrate

    root = tmp_path / "runs"
    legacy_store(root)
    (root / "events.jsonl").write_text("{broken\n")
    original = (root / "factory.db").read_bytes()
    with pytest.raises(MigrationError):
        migrate(root, report_path=tmp_path / "rejected.json")
    assert (root / "factory.db").read_bytes() == original
    assert (root / "events.jsonl").read_text() == "{broken\n"
    report = json.loads((tmp_path / "rejected.json").read_text())
    assert any(m["table"] == "events.jsonl" for m in report["mismatches"])
    result = migrate(root, report_path=tmp_path / "accepted.json", reconcile_mirror=True)
    assert (root / result["backup"] / "events.jsonl").read_text() == "{broken\n"
    assert json.loads((root / "events.jsonl").read_text())["seq"] == 1


def test_invalid_legacy_state_reports_all_and_does_not_migrate(tmp_path, monkeypatch):
    from factory.record_migration import MigrationError, migrate

    root = tmp_path / "runs"
    legacy_store(root)
    monkeypatch.setenv("OPENAI_API_KEY", "secret-bad-status")
    db = sqlite3.connect(root / "factory.db")
    db.execute(
        "UPDATE runs SET payload=?",
        (json.dumps({"run_id": "r", "status": "secret-bad-status", "cost_complete": "not bool"}),),
    )
    db.commit()
    db.close()
    with pytest.raises(MigrationError):
        migrate(root, report_path=tmp_path / "report.json")
    report = (tmp_path / "report.json").read_text()
    assert "secret-bad-status" not in report
    fields = {x["field"] for x in json.loads(report)["mismatches"]}
    assert {"status", "cost_complete"} <= fields


def test_nested_unknown_fields_preserved_without_replacing_historical_source(tmp_path):
    from factory.agents.test_worker import spec
    from factory.record_migration import migrate

    root = tmp_path / "runs"
    legacy_store(root)
    snapshot = {
        "source_id": spec().paper_id,
        "title": spec().title,
        "source_kind": "paper",
        "spec": spec().model_dump(),
        "provenance": {"version_date": "2018"},
    }
    snapshot["spec"]["hypothesis"] = "Historic hypothesis"
    snapshot["spec"]["legacy_extra"] = {"preserve": [1, "two"]}
    current = json.loads(json.dumps(snapshot))
    current["spec"].pop("legacy_extra")
    current["spec"]["hypothesis"] = "Later hypothesis"
    db = sqlite3.connect(root / "factory.db")
    db.execute(
        "UPDATE runs SET payload=?",
        (json.dumps({"run_id": "r", "status": "FAILED", "source": snapshot}),),
    )
    db.execute("INSERT INTO sources VALUES(?,?,?)", (spec().paper_id, "later", json.dumps(current)))
    db.commit()
    db.close()
    result = migrate(root, report_path=tmp_path / "report.json")
    assert result["migrated"]
    from factory.agents.records import Records

    with Records(root) as store:
        run = store.get("runs", "r")
        assert run["source"]["spec"]["hypothesis"] == "Historic hypothesis"
        assert run["legacy_extensions"]["source.spec.legacy_extra"] == {"preserve": [1, "two"]}
        assert store.get("sources", spec().paper_id)["spec"]["hypothesis"] == "Later hypothesis"
        assert run["source"]["provenance"]["version_date"] == "2018"
    assert any(x["field"] == "source.spec.legacy_extra" for x in result["changes"])


def test_valid_but_different_mirror_is_not_silently_replaced(tmp_path):
    from factory.record_migration import MigrationError, migrate

    root = tmp_path / "runs"
    legacy_store(root)
    line = json.loads((root / "events.jsonl").read_text())
    line["message"] = "Additional evidence only present in mirror"
    (root / "events.jsonl").write_text(json.dumps(line) + "\n")
    with pytest.raises(MigrationError):
        migrate(root, report_path=tmp_path / "report.json")
    assert json.loads((root / "events.jsonl").read_text())["message"] == line["message"]
    report = json.loads((tmp_path / "report.json").read_text())
    assert any(x["kind"] == "mirror_payload_mismatch" for x in report["mismatches"])


def test_committed_migration_with_failed_mirror_can_be_explicitly_recovered(tmp_path, monkeypatch):
    from factory import record_migration as migration

    root = tmp_path / "runs"
    legacy_store(root)
    original_mirror = (root / "events.jsonl").read_bytes()
    real_write = migration.write_mirror

    def fail(*args):
        raise OSError("simulated mirror interruption")

    monkeypatch.setattr(migration, "write_mirror", fail)
    with pytest.raises(OSError):
        migration.migrate(root, report_path=tmp_path / "interrupted.json")
    assert sqlite3.connect(root / "factory.db").execute("PRAGMA user_version").fetchone()[0] == 1
    assert (root / "events.jsonl").read_bytes() == original_mirror
    monkeypatch.setattr(migration, "write_mirror", real_write)
    with pytest.raises(migration.MigrationError):
        migration.migrate(root, report_path=tmp_path / "blocked.json")
    result = migration.migrate(root, report_path=tmp_path / "recovered.json", reconcile_mirror=True)
    assert result["mirror_recovered"]
    assert not migration.audit(root)["mismatches"]
    assert (root / result["backup"] / "events.jsonl").read_bytes() == original_mirror


@pytest.mark.parametrize("bad_source", [["not an object"], 5, "broken"])
def test_malformed_legacy_snapshot_still_produces_complete_report(tmp_path, bad_source):
    from factory.record_migration import MigrationError, migrate

    root = tmp_path / "runs"
    legacy_store(root)
    db = sqlite3.connect(root / "factory.db")
    db.execute(
        "UPDATE runs SET payload=?",
        (json.dumps({"run_id": "r", "status": "FAILED", "source": bad_source}),),
    )
    db.commit()
    db.close()
    before = (root / "factory.db").read_bytes()
    with pytest.raises(MigrationError):
        migrate(root, report_path=tmp_path / "report.json")
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["unresolved"]
    assert len(report["validations"]) == 3
    assert (root / "factory.db").read_bytes() == before


def test_audit_reports_corrupted_boolean_without_crashing(tmp_path):
    from factory.record_migration import audit, migrate

    root = tmp_path / "runs"
    legacy_store(root)
    migrate(root, report_path=tmp_path / "initial.json")
    db = sqlite3.connect(root / "factory.db")
    value = json.loads(db.execute("SELECT payload FROM runs").fetchone()[0])
    value["voided"] = "invalid boolean"
    db.execute("UPDATE runs SET payload=?", (json.dumps(value),))
    db.commit()
    db.close()
    report = audit(root)
    assert any(m["table"] == "runs" and m["field"] == "voided" for m in report["mismatches"])
    assert len(report["validations"]) == 3


def test_out_of_order_mirror_is_reported_and_requires_explicit_reconciliation(tmp_path):
    from factory.record_migration import MigrationError, audit, migrate

    root = tmp_path / "runs"
    legacy_store(root)
    db = sqlite3.connect(root / "factory.db")
    event = json.loads(db.execute("SELECT payload FROM events").fetchone()[0])
    event["message"] = "second event"
    db.execute("INSERT INTO events(payload) VALUES(?)", (json.dumps(event),))
    db.commit()
    db.close()
    first = json.loads((root / "events.jsonl").read_text())
    second = {"seq": 2, **event}
    (root / "events.jsonl").write_text(json.dumps(second) + "\n" + json.dumps(first) + "\n")
    assert any(m["kind"] == "out_of_order_sequence" for m in audit(root)["mismatches"])
    with pytest.raises(MigrationError):
        migrate(root, report_path=tmp_path / "order.json")
