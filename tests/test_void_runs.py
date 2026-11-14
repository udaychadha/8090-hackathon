"""Invalidated research stays auditable but cannot enter comparisons or trials."""

import json
import sqlite3

import pytest

from factory.agents.records import Records


def payload(records, table, identifier):
    return json.loads(
        records.db.execute(f"SELECT payload FROM {table} WHERE id = ?", (identifier,)).fetchone()[0]
    )


@pytest.fixture
def records(tmp_path):
    store = Records(tmp_path)
    for run_id in ("old", "other"):
        variants = []
        for variant in "ABC":
            row = {
                "variant_id": f"{run_id}_{variant}",
                "run_id": run_id,
                "source_id": "p_test",
                "source_title": "Void evidence fixture",
                "source_kind": "paper",
                "test_type": "transfer",
                "frequency": "1min",
                "variant": variant,
                "status": "FAILED_EVAL_2",
                "evals_passed": 1,
                "default_status": "FAILED_EVAL_2",
                "default_evals_passed": 1,
                "verified_sharpe": 0.2,
                "break_even_bps": 1.4,
                "code": "original strategy",
                "equity": {
                    "dates": ["2020-01-02", "2020-01-03"],
                    "gross": [1.0, 1.02],
                    "net": [1.0, 1.01],
                    "is_end": "2020-01-02",
                    "oos_end": "2020-01-03",
                },
                "evals": [{"number": 1, "name": "lookahead", "passed": True, "metrics": {}}],
            }
            row = store.put("variants", row["variant_id"], run_id, row)
            variants.append(row)
            if variant != "C":
                store.put(
                    "eval_results",
                    f"{run_id}_{variant}_2",
                    run_id,
                    {
                        "variant": variant,
                        "number": 2,
                        "name": "friction",
                        "passed": False,
                        "metrics": {"sharpe_by_bps": {"5": 0.2}},
                    },
                )
        store.put(
            "runs",
            run_id,
            run_id,
            {
                "run_id": run_id,
                "status": "COMPLETED",
                "variants": variants,
            },
        )
    yield store
    store.close()


def test_void_preserves_evidence_and_updates_summary_consistently(records):
    original = payload(records, "variants", "old_A")
    evidence = records.list("eval_results", include_voided=True)
    other = payload(records, "runs", "other")
    result = records.void_run("old", "All candidates were inactive")
    assert result["status"] == "VOID"
    assert result["original_result"]["status"] == "COMPLETED"
    for row in result["variants"]:
        assert row == payload(records, "variants", row["variant_id"])
        assert row["status"] == row["default_status"] == "VOID"
        assert row["leaderboard_eligible"] is False
        assert row["eval_eligible"] is False
        assert row["void_reason"] == "All candidates were inactive"
        assert row["verified_sharpe"] is None
        assert row["evals_passed"] == row["default_evals_passed"] == 0
    row = result["variants"][0]
    for key in (
        "status",
        "default_status",
        "evals_passed",
        "verified_sharpe",
        "break_even_bps",
        "default_evals_passed",
    ):
        assert row["original_result"][key] == original[key]
    for key in ("code", "equity", "evals"):
        assert row[key] == original[key]
    after = records.list("eval_results", include_voided=True)
    assert len(after) == len(evidence)
    for before_row, after_row in zip(evidence, after, strict=True):
        assert {k: v for k, v in after_row.items() if k != "voided"} == {
            k: v for k, v in before_row.items() if k != "voided"
        }
        assert after_row["voided"] == (after_row["run_id"] == "old")
    assert payload(records, "runs", "other") == other


def test_void_is_excluded_from_leaderboard_and_trial_accounting(records):
    assert {row["variant"] for row in records.trial_variants("old")} == {"A", "B"}
    records.void_run("old", "Inactive")
    assert records.trial_variants("old") == []
    assert {row["variant_id"] for row in records.leaderboard()} == {
        "other_A",
        "other_B",
        "other_C",
    }
    assert len(records.trial_variants("other")) == 2


def test_trial_selection_recognizes_embedded_evals_despite_eligibility_flag(records):
    a = payload(records, "variants", "other_A")
    a["eval_eligible"] = False
    records.put("variants", "other_A", "other", a)
    c = payload(records, "variants", "other_C")
    c["evals"] = [{"number": 2, "name": "friction", "passed": False, "metrics": {}}]
    c["evals_passed"] = c["default_evals_passed"] = 0
    records.put("variants", "other_C", "other", c)
    assert {row["variant"] for row in records.trial_variants("other")} == {"A", "B", "C"}


def test_repeat_void_keeps_original_reason_and_only_one_event(records):
    first = records.void_run("old", "Inactive")
    assert records.void_run("old", "A second reason") == first
    events = [json.loads(line) for line in (records.root / "events.jsonl").read_text().splitlines()]
    assert len(events) == 1
    assert events[0]["run_id"] == "old"
    assert events[0]["stage"] == "done"
    assert events[0]["status"] == "info"
    assert events[0]["data"]["status"] == "VOID"


def test_unknown_run_and_blank_reason_fail_without_mutation(records):
    before = records.db.total_changes
    with pytest.raises(KeyError):
        records.void_run("missing", "Inactive")
    with pytest.raises(KeyError):
        records.trial_variants("missing")
    with pytest.raises(ValueError):
        records.void_run("old", "  ")
    assert records.db.total_changes == before


def test_failed_variant_update_rolls_back_run_variants_and_event(records):
    before = payload(records, "runs", "old")
    records.db.execute("""CREATE TRIGGER reject_void BEFORE UPDATE ON variants
        WHEN NEW.id = 'old_B' BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
    records.db.commit()
    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        records.void_run("old", "Inactive")
    assert payload(records, "runs", "old") == before
    assert payload(records, "variants", "old_A")["status"] == "FAILED_EVAL_2"
    assert records.db.execute("SELECT count(*) FROM events").fetchone()[0] == 0


def test_mirror_failure_keeps_audit_and_retry_repairs_without_duplicate(records, monkeypatch):
    mirror = records._mirror

    def broken_mirror():
        raise OSError("disk unavailable")

    monkeypatch.setattr(records, "_mirror", broken_mirror)
    with pytest.raises(OSError, match="disk unavailable"):
        records.void_run("old", "Inactive")
    assert payload(records, "runs", "old")["status"] == "VOID"
    assert records.db.execute("SELECT count(*) FROM events").fetchone()[0] == 1
    monkeypatch.setattr(records, "_mirror", mirror)
    records.void_run("old", "Inactive")
    assert len((records.root / "events.jsonl").read_text().splitlines()) == 1
