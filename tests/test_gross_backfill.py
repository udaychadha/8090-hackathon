"""Historical gross diagnostics must never rewrite authoritative evidence."""

import copy
import json
import sqlite3
from pathlib import Path

import pytest

from factory.agents.records import Records


def fixture_store(root, status="FAILED_EVAL_2", run_status="COMPLETED"):
    records = Records(root)
    records.put("runs", "r_test", "r_test", {"status": run_status})
    evaluation = {"number": 2, "name": "friction", "passed": False, "metrics": {}}
    variant = records.put(
        "variants",
        "r_test_A",
        "r_test",
        {
            "variant_id": "r_test_A",
            "variant": "A",
            "source_id": "p_test",
            "source_title": "Retained experiment",
            "source_kind": "described",
            "test_type": "original",
            "frequency": "1day",
            "status": status,
            "default_status": status,
            "evals_passed": 0,
            "default_evals_passed": 0,
            "evals": [evaluation],
            "reached_eval_2": True,
            "code": 'PARAMS = {"lookback": 60}\n# exact retained candidate\n',
            "params": {"lookback": 60},
            "critique": "Original postmortem",
        },
    )
    records.put("eval_results", "r_test_A_2", "r_test", {"variant": "A", **evaluation})
    run = records.get("runs", "r_test")
    records.put("runs", "r_test", "r_test", {**run, "variants": [variant]})
    return records


def raw(records, table, identifier):
    return json.loads(
        records.db.execute(f"SELECT payload FROM {table} WHERE id=?", (identifier,)).fetchone()[0]
    )


def complete(path, **kwargs):
    assert Path(path).read_text() == 'PARAMS = {"lookback": 60}\n# exact retained candidate\n'
    return {
        "schema_version": "1.0.0",
        "state": "complete",
        "cost_bps": 0,
        "eval_3": {"number": 3, "name": "sensitivity", "passed": True, "metrics": {"cost_bps": 0}},
        "eval_4": {"number": 4, "name": "decay", "passed": False, "metrics": {"cost_bps": 0}},
        "label": None,
        "reason": None,
    }


def test_backfill_preserves_raw_evidence_and_nested_snapshot(tmp_path):
    from scripts.backfill_gross_diagnostics import backfill

    with fixture_store(tmp_path / "runs") as records:
        before = raw(records, "variants", "r_test_A")
        run_before = raw(records, "runs", "r_test")
        eval_before = raw(records, "eval_results", "r_test_A_2")
        report = backfill(records, apply=True, compute=complete)
        after = raw(records, "variants", "r_test_A")
        diagnostics = after.pop("gross_diagnostics")
        assert after == before
        run_after = raw(records, "runs", "r_test")
        assert run_after["variants"][0].pop("gross_diagnostics") == diagnostics
        assert run_after == run_before
        assert diagnostics["label"] == "no signal before costs"
        assert raw(records, "eval_results", "r_test_A_2") == eval_before
        assert report["rows"][0]["non_diagnostic_evidence_unchanged"] is True
        with sqlite3.connect(Path(report["backup"]) / "factory.db") as backup:
            assert (
                json.loads(backup.execute("SELECT payload FROM variants").fetchone()[0]) == before
            )


def test_dry_run_never_writes_and_complete_rows_resume(tmp_path):
    from scripts.backfill_gross_diagnostics import backfill

    with fixture_store(tmp_path / "runs") as records:
        before = raw(records, "variants", "r_test_A")
        assert backfill(records, compute=complete)["applied"] is False
        assert raw(records, "variants", "r_test_A") == before
        backfill(records, apply=True, compute=complete)
        report = backfill(
            records, apply=True, compute=lambda *a, **kw: pytest.fail("Repeated replay")
        )
        assert report["rows"][0]["action"] == "skipped_complete"


@pytest.mark.parametrize(
    "variant_status,run_status",
    [
        ("RUNNING", "COMPLETED"),
        ("FAILED_EVAL_2", "RUNNING"),
    ],
)
def test_active_evidence_is_skipped(tmp_path, variant_status, run_status):
    from scripts.backfill_gross_diagnostics import backfill

    with fixture_store(tmp_path / "runs", variant_status, run_status) as records:
        report = backfill(records, compute=lambda *a, **kw: pytest.fail("Active replay"))
        assert report["rows"][0]["action"] == "skipped_running"
        assert "gross_diagnostics" not in raw(records, "variants", "r_test_A")


def test_changed_evidence_refuses_write_after_replay(tmp_path):
    from scripts.backfill_gross_diagnostics import backfill

    with fixture_store(tmp_path / "runs") as records:

        def concurrent_edit(path, **kwargs):
            with Records(records.root) as writer:
                variant = writer.get("variants", "r_test_A")
                writer.put(
                    "variants", "r_test_A", "r_test", {**variant, "params": {"lookback": 99}}
                )
            return complete(path, **kwargs)

        report = backfill(records, apply=True, compute=concurrent_edit)
        assert report["rows"][0]["action"] == "conflict"
        assert raw(records, "variants", "r_test_A")["params"] == {"lookback": 99}
        assert "gross_diagnostics" not in raw(records, "variants", "r_test_A")
        assert "gross_diagnostics" not in raw(records, "runs", "r_test")["variants"][0]


def test_unavailable_is_redacted_resumable_and_retryable(tmp_path, monkeypatch):
    from scripts.backfill_gross_diagnostics import backfill

    monkeypatch.setenv("OPENAI_API_KEY", "secret-test-key")
    with fixture_store(tmp_path / "runs", "BUG_UNRESOLVED") as records:

        def broken(*a, **kw):
            raise ValueError("secret-test-key strategy failed")

        report = backfill(records, apply=True, compute=broken)
        assert "secret-test-key" not in json.dumps(report)
        assert raw(records, "variants", "r_test_A")["gross_diagnostics"]["state"] == "unavailable"
        report = backfill(
            records, compute=lambda *a, **kw: pytest.fail("Repeated unavailable replay")
        )
        assert report["rows"][0]["action"] == "skipped_unavailable"
        report = backfill(records, apply=True, retry_unavailable=True, compute=complete)
        assert report["rows"][0]["state"] == "complete"


def test_void_and_inactive_rows_replay_without_rejudgment(tmp_path):
    from scripts.backfill_gross_diagnostics import backfill

    with fixture_store(tmp_path / "runs", "INACTIVE") as records:
        backfill(records, apply=True, compute=complete)
        assert records.get("variants", "r_test_A")["status"] == "INACTIVE"
        records.void_run("r_test", "Audited invalidation")
        before = copy.deepcopy(raw(records, "variants", "r_test_A"))
        before.pop("gross_diagnostics")
        # Simulate a pre-diagnostics VOID record.
        with records.db:
            records.db.execute(
                "UPDATE variants SET payload=? WHERE id='r_test_A'", (json.dumps(before),)
            )
        report = backfill(records, apply=True, compute=complete)
        assert report["rows"][0]["action"] == "applied"
        after = raw(records, "variants", "r_test_A")
        after.pop("gross_diagnostics")
        assert after == before


def test_default_replay_missing_code_and_data_never_calls_models(tmp_path, monkeypatch):
    from factory import llm
    from scripts.backfill_gross_diagnostics import backfill

    monkeypatch.setattr(llm, "complete", lambda *a, **kw: pytest.fail("Model call during replay"))
    with fixture_store(tmp_path / "runs", "BUG_UNRESOLVED") as records:
        variant = records.get("variants", "r_test_A")
        records.put("variants", "r_test_A", "r_test", {**variant, "code": None})
        report = backfill(records, apply=True)
        assert report["rows"][0]["state"] == "unavailable"
        assert report["rows"][0]["diagnostics"]["eval_3"] is None
        records.put("variants", "r_test_A", "r_test", variant)
        report = backfill(records, apply=True, data_root=tmp_path / "missing-data")
        assert report["rows"][0]["state"] == "unavailable"
        assert report["rows"][0]["diagnostics"]["eval_4"] is None


def test_mismatched_stored_parameters_are_not_silently_replayed(tmp_path):
    from scripts.backfill_gross_diagnostics import backfill

    with fixture_store(tmp_path / "runs") as records:
        variant = records.get("variants", "r_test_A")
        records.put("variants", "r_test_A", "r_test", {**variant, "params": {"lookback": 90}})
        report = backfill(records, compute=lambda *a, **kw: pytest.fail("Mismatched replay"))
        assert report["rows"][0]["state"] == "unavailable"
        assert "parameters" in report["rows"][0]["diagnostics"]["reason"].lower()


def test_concurrent_nested_evidence_edit_is_not_overwritten(tmp_path):
    from scripts.backfill_gross_diagnostics import backfill

    with fixture_store(tmp_path / "runs") as records:

        def concurrent_edit(path, **kwargs):
            with Records(records.root) as writer:
                run = writer.get("runs", "r_test")
                run["variants"][0]["critique"] = "Concurrent evidence update"
                writer.put("runs", "r_test", "r_test", run)
            return complete(path, **kwargs)

        report = backfill(records, apply=True, compute=concurrent_edit)
        assert report["rows"][0]["action"] == "conflict"
        assert "gross_diagnostics" not in raw(records, "variants", "r_test_A")
        assert (
            raw(records, "runs", "r_test")["variants"][0]["critique"]
            == "Concurrent evidence update"
        )


def duplicate_candidate(records, run_id):
    variant = records.get("variants", "r_test_A", include_voided=True)
    records.put("runs", run_id, run_id, {"status": "COMPLETED"})
    variant = {**variant, "id": run_id + "_A", "variant_id": run_id + "_A", "run_id": run_id}
    variant.pop("gross_diagnostics", None)
    variant = records.put("variants", run_id + "_A", run_id, variant)
    run = records.get("runs", run_id)
    records.put("runs", run_id, run_id, {**run, "variants": [variant]})


def test_identical_candidates_reuse_only_same_invocation_and_relabel(tmp_path):
    from scripts.backfill_gross_diagnostics import backfill

    with fixture_store(tmp_path / "runs") as records:
        duplicate_candidate(records, "z_duplicate")
        records.void_run("z_duplicate", "Same retained code, invalidated harness")
        calls = []

        def once(path, **kwargs):
            calls.append(path)
            assert len(calls) == 1, "Identical retained code was executed twice"
            return complete(path, **kwargs)

        report = backfill(records, apply=True, data_root=tmp_path / "data", compute=once)
        assert report["rows"][0]["diagnostics"]["label"] == "no signal before costs"
        assert report["rows"][1]["diagnostics"]["label"] is None
        assert report["rows"][1]["reused_from_variant_id"] == "r_test_A"
        assert raw(records, "variants", "z_duplicate_A")["status"] == "VOID"
        duplicate_candidate(records, "zz_later")
        calls.clear()
        next_report = backfill(records, apply=True, data_root=tmp_path / "data", compute=once)
        assert len(calls) == 1
        assert next_report["rows"][-1]["reused_from_variant_id"] is None


@pytest.mark.parametrize("changed_file", ["manifest.json", "SPY.manifest.json", "SPY.parquet"])
def test_changed_data_snapshot_prevents_cached_reuse(tmp_path, changed_file):
    from scripts.backfill_gross_diagnostics import backfill

    data_root = tmp_path / "data"
    tier = data_root / "1day"
    tier.mkdir(parents=True)
    path = tier / changed_file
    path.write_bytes(b"original")
    with fixture_store(tmp_path / "runs") as records:
        duplicate_candidate(records, "z_duplicate")
        calls = []

        def replay(path, **kwargs):
            calls.append(path)
            return complete(path, **kwargs)

        def mutate_data(report):
            if len(report["rows"]) == 1:
                path.write_bytes(b"changed contents")

        report = backfill(records, data_root=data_root, compute=replay, on_row=mutate_data)
        assert len(calls) == 2
        assert report["rows"][1]["reused_from_variant_id"] is None
        assert (
            report["rows"][0]["data_snapshot_sha256"] != report["rows"][1]["data_snapshot_sha256"]
        )


def test_data_change_during_replay_is_unavailable_not_cached(tmp_path):
    from scripts.backfill_gross_diagnostics import backfill

    data_root = tmp_path / "data"
    data_root.mkdir()
    manifest = data_root / "manifest.json"
    manifest.write_text("old")
    with fixture_store(tmp_path / "runs") as records:

        def changing_replay(path, **kwargs):
            manifest.write_text("changed")
            return complete(path, **kwargs)

        report = backfill(records, data_root=data_root, compute=changing_replay)
        assert report["rows"][0]["state"] == "unavailable"
        assert "changed" in report["rows"][0]["diagnostics"]["reason"].lower()


def finish_candidate(records, run_id, *, code=None, params=None):
    row = records.get("variants", run_id + "_A")
    row.update(status="FAILED_EVAL_2", default_status="FAILED_EVAL_2")
    if code is not None:
        row["code"] = code
    if params is not None:
        row["params"] = params
    row = records.put("variants", run_id + "_A", run_id, row)
    run = records.get("runs", run_id)
    records.put("runs", run_id, run_id, {**run, "status": "COMPLETED", "variants": [row]})


def test_wait_running_processes_terminal_first_then_reuses_after_completion(tmp_path):
    from scripts.backfill_gross_diagnostics import backfill

    with fixture_store(tmp_path / "runs", "RUNNING", "RUNNING") as records:
        duplicate_candidate(records, "z_prior")
        finish_candidate(records, "z_prior")
        records.void_run("z_prior", "Invalidated prior harness attempt")
        observed = []
        waits = []

        def wait(seconds):
            waits.append(seconds)
            assert observed == ["z_prior_A"]
            assert "gross_diagnostics" not in raw(records, "variants", "z_prior_A")
            assert raw(records, "variants", "r_test_A")["status"] == "RUNNING"
            assert "gross_diagnostics" not in raw(records, "variants", "r_test_A")
            finish_candidate(records, "r_test")

        def progress(report):
            if report["rows"]:
                observed[:] = [row["variant_id"] for row in report["rows"]]

        replayed = []

        def replay(path, **kwargs):
            replayed.append(path)
            return complete(path, **kwargs)

        report = backfill(
            records,
            apply=True,
            data_root=tmp_path / "data",
            compute=replay,
            wait_running=True,
            wait=wait,
            on_row=progress,
        )
        assert waits == [10]
        assert len(replayed) == 1
        assert [row["variant_id"] for row in report["rows"]] == ["z_prior_A", "r_test_A"]
        assert report["rows"][1]["reused_from_variant_id"] == "z_prior_A"
        assert report["rows"][1]["diagnostics"]["label"] == "no signal before costs"
        assert "waiting" not in report
        assert all(row["non_diagnostic_evidence_unchanged"] for row in report["rows"])


def test_wait_running_rereads_changed_code_and_params(tmp_path):
    from scripts.backfill_gross_diagnostics import backfill

    data_root = tmp_path / "data"
    old_code = 'PARAMS = {"lookback": 60}\n# exact retained candidate\n'
    new_code = 'PARAMS = {"lookback": 90}\n# terminal retained candidate\n'
    with fixture_store(tmp_path / "runs", "RUNNING", "RUNNING") as records:
        duplicate_candidate(records, "z_prior")
        finish_candidate(records, "z_prior")
        observed_code = []
        waiting_progress = []
        result_path = tmp_path / "original.py"
        result_path.write_text(old_code)

        def replay(path, **kwargs):
            observed_code.append(Path(path).read_text())
            return complete(result_path)

        def wait(seconds):
            assert seconds == 10
            finish_candidate(records, "r_test", code=new_code, params={"lookback": 90})

        def progress(report):
            if report.get("waiting"):
                waiting_progress.append(copy.deepcopy(report["waiting"]))

        report = backfill(
            records,
            data_root=data_root,
            compute=replay,
            wait_running=True,
            wait=wait,
            on_row=progress,
        )
        assert observed_code == [old_code, new_code]
        assert report["rows"][1]["reused_from_variant_id"] is None
        assert report["rows"][1]["status"] == "FAILED_EVAL_2"
        assert waiting_progress[0]["variant_id"] == "r_test_A"
        assert waiting_progress[0]["state"] == "pending"
        assert "gross_diagnostics" not in raw(records, "variants", "r_test_A")


def test_apply_refuses_unrelated_active_parent_before_computing(tmp_path):
    from scripts.backfill_gross_diagnostics import backfill

    with fixture_store(tmp_path / "runs") as records:
        records.put("runs", "unrelated", "unrelated", {"status": "RUNNING"})
        with pytest.raises(ValueError, match="running"):
            backfill(
                records, apply=True, compute=lambda *a, **kw: pytest.fail("Active-store replay")
            )
        assert "gross_diagnostics" not in raw(records, "variants", "r_test_A")
        assert backfill(records, compute=complete)["rows"][0]["state"] == "complete"


def test_wait_mode_stages_terminal_result_until_unrelated_parent_is_idle(tmp_path):
    from scripts.backfill_gross_diagnostics import backfill

    with fixture_store(tmp_path / "runs") as records:
        records.put("runs", "unrelated", "unrelated", {"status": "RUNNING"})
        computed = []
        progress = []

        def replay(path, **kwargs):
            computed.append(True)
            return complete(path, **kwargs)

        def wait(seconds):
            assert computed == [True]
            assert "gross_diagnostics" not in raw(records, "variants", "r_test_A")
            assert "gross_diagnostics" not in raw(records, "runs", "r_test")["variants"][0]
            run = records.get("runs", "unrelated")
            records.put("runs", "unrelated", "unrelated", {**run, "status": "COMPLETED"})

        report = backfill(
            records,
            apply=True,
            wait_running=True,
            wait=wait,
            compute=replay,
            data_root=tmp_path / "data",
            on_row=lambda value: progress.append(copy.deepcopy(value)),
        )
        assert report["rows"][0]["action"] == "applied"
        assert any(value.get("waiting", {}).get("kind") == "global_idle" for value in progress)
        assert raw(records, "variants", "r_test_A")["gross_diagnostics"]["state"] == "complete"


def test_deferred_apply_checks_data_snapshot_again_after_wait(tmp_path):
    from scripts.backfill_gross_diagnostics import backfill

    data_root = tmp_path / "data"
    data_root.mkdir()
    manifest = data_root / "manifest.json"
    manifest.write_text("original")
    with fixture_store(tmp_path / "runs") as records:
        records.put("runs", "unrelated", "unrelated", {"status": "RUNNING"})

        def wait(seconds):
            manifest.write_text("new data")
            run = records.get("runs", "unrelated")
            records.put("runs", "unrelated", "unrelated", {**run, "status": "COMPLETED"})

        report = backfill(
            records, apply=True, wait_running=True, wait=wait, compute=complete, data_root=data_root
        )
        assert report["rows"][0]["action"] == "conflict"
        assert "gross_diagnostics" not in raw(records, "variants", "r_test_A")


def test_wait_pid_holds_publication_after_terminal_run_until_process_exits(tmp_path):
    from scripts.backfill_gross_diagnostics import backfill

    with fixture_store(tmp_path / "runs") as records:
        computed = []
        alive = {65120: True}
        waits = []

        def replay(path, **kwargs):
            computed.append(True)
            return complete(path, **kwargs)

        def wait(seconds):
            waits.append(seconds)
            assert computed == [True]
            assert records.get("runs", "r_test")["status"] == "COMPLETED"
            assert "gross_diagnostics" not in raw(records, "variants", "r_test_A")
            alive[65120] = False

        report = backfill(
            records,
            apply=True,
            wait_running=True,
            wait_pids=[65120],
            process_alive=lambda pid: alive[pid],
            wait=wait,
            compute=replay,
            data_root=tmp_path / "data",
        )
        assert waits == [10]
        assert report["rows"][0]["action"] == "applied"


@pytest.mark.parametrize(
    "outcome,expected", [(None, True), (PermissionError, True), (ProcessLookupError, False)]
)
def test_process_guard_handles_alive_permission_denied_and_missing(monkeypatch, outcome, expected):
    from scripts import backfill_gross_diagnostics as module

    def kill(pid, signal):
        assert pid == 65120 and signal == 0
        if outcome:
            raise outcome()

    monkeypatch.setattr(module.os, "kill", kill)
    assert module._pid_alive(65120) is expected


def test_data_snapshot_is_checked_inside_write_transaction(tmp_path, monkeypatch):
    from scripts import backfill_gross_diagnostics as module

    data_root = tmp_path / "data"
    data_root.mkdir()
    manifest = data_root / "manifest.json"
    manifest.write_text("original")
    with fixture_store(tmp_path / "runs") as records:
        original = module._running_ids

        def checked_running(store):
            if store.db.in_transaction:
                manifest.write_text("changed after transaction begins")
            return original(store)

        monkeypatch.setattr(module, "_running_ids", checked_running)
        report = module.backfill(records, apply=True, compute=complete, data_root=data_root)
        assert report["rows"][0]["action"] == "conflict"
        assert "gross_diagnostics" not in raw(records, "variants", "r_test_A")
