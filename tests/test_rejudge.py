"""A recorded-metric revision is atomic, lossless, auditable and repeatable."""

import json
import sqlite3

import pytest

from factory.agents.records import Records


def fixture_store(root):
    records = Records(root)
    for run_id, own, control in [
        ("one", 0.05, False),
        ("two", -0.5, False),
        ("control", 20.0, True),
        ("void", 30.0, False),
    ]:
        records.put(
            "runs", run_id, run_id, {"run_id": run_id, "status": "COMPLETED", "is_control": control}
        )
        evaluations = [dict(number=n, name=f"eval{n}", passed=True, metrics={}) for n in (1, 2, 3)]
        evaluations += [
            dict(
                number=4,
                name="decay",
                passed=True,
                metrics={
                    "is_sharpe": -1.0,
                    "oos_sharpe": 0.8,
                    "sharpe_ok": True,
                    "is_max_window_share": 0.2,
                    "oos_max_window_share": 0.2,
                    "concentration_ok": True,
                },
            ),
            dict(
                number=5,
                name="deflated_sharpe",
                passed=True,
                metrics={
                    "daily_sharpe": own,
                    "observations": 300,
                    "skew": 0.0,
                    "kurtosis": 3.0,
                    "dsr": 1.0,
                    "n_trials": 3,
                    "trial_variance": 0.0,
                    "sr0": 0.0,
                },
            ),
        ]
        variant = records.put(
            "variants",
            f"{run_id}_A",
            run_id,
            {
                "variant_id": f"{run_id}_A",
                "run_id": run_id,
                "variant": "A",
                "source_id": "p_test",
                "source_title": "Recorded evidence fixture",
                "source_kind": "paper",
                "test_type": "transfer",
                "frequency": "1day",
                "status": "VERIFIED",
                "evals_passed": 5,
                "default_status": "VERIFIED",
                "default_evals_passed": 5,
                "evals": evaluations,
                "code": "retained code",
            },
        )
        for result in evaluations:
            records.put(
                "eval_results", f"{run_id}_A_{result['number']}", run_id, {"variant": "A", **result}
            )
        run = records.get("runs", run_id)
        run["variants"] = [variant]
        records.put("runs", run_id, run_id, run)
    records.void_run("void", "Prior invalidation")
    return records


def test_recorded_only_rejudge_updates_all_projections_and_preserves_original(
    tmp_path, monkeypatch
):
    from factory import data, engine, rejudge

    def prohibited(*a, **kw):
        pytest.fail("Rejudgment must not load bars or run backtests")

    monkeypatch.setattr(engine, "backtest", prohibited)
    monkeypatch.setattr(data, "load_bars", prohibited)
    with fixture_store(tmp_path / "runs") as records:
        before = records.list("variants", include_voided=True)
        plan = rejudge.plan_rejudgment(records)
        assert plan["trial_variant_ids"] == ["one_A", "two_A"]
        report = rejudge.apply_rejudgment(records, plan)
        assert len(report["rows"]) == 4
        after = records.get("variants", "one_A")
        assert after["status"] == "FAILED_EVAL_4" and after["evals_passed"] == 3
        assert after["default_status"] == after["status"]
        assert after["code"] == "retained code"
        assert records.get("runs", "one")["variants"] == [after]
        for result in records.list("eval_results", run_id="one"):
            embedded = next(e for e in after["evals"] if e["number"] == result["number"])
            assert embedded == {k: result[k] for k in ("number", "name", "passed", "metrics")}
        void = records.get("variants", "void_A", include_voided=True)
        assert void["status"] == "VOID" and void["evals_passed"] == 0
        assert (
            void["original_result"]
            == next(v for v in before if v["variant_id"] == "void_A")["original_result"]
        )
        with sqlite3.connect(report["backup"] + "/factory.db") as db:
            saved = json.loads(
                db.execute("SELECT payload FROM variants WHERE id=?", ("one_A",)).fetchone()[0]
            )
        assert saved == next(v for v in before if v["variant_id"] == "one_A")
        events = records.events(include_voided=True)
        second = rejudge.apply_rejudgment(records, rejudge.plan_rejudgment(records))
        assert second["changed_variants"] == 0
        assert records.events(include_voided=True) == events


def test_failed_write_rolls_back_all_evals_snapshots_and_events(tmp_path):
    from factory import rejudge

    with fixture_store(tmp_path / "runs") as records:
        plan = rejudge.plan_rejudgment(records)
        before = {
            t: records.list(t, include_voided=True)
            for t in ("runs", "variants", "eval_results", "events")
        }
        records.db.execute(
            "CREATE TRIGGER reject_revision BEFORE UPDATE ON variants "
            "WHEN NEW.id='two_A' BEGIN SELECT RAISE(ABORT,'injected'); END"
        )
        records.db.commit()
        with pytest.raises(sqlite3.IntegrityError, match="injected"):
            rejudge.apply_rejudgment(records, plan)
        assert {t: records.list(t, include_voided=True) for t in before} == before


def test_disagreeing_recorded_metrics_are_rejected_and_not_silently_chosen(tmp_path):
    from factory import rejudge

    with fixture_store(tmp_path / "runs") as records:
        result = records.get("eval_results", "one_A_4")
        result["metrics"]["is_sharpe"] = 2.0
        records.put("eval_results", result["id"], "one", result)
        with pytest.raises(ValueError, match="disagree"):
            rejudge.plan_rejudgment(records)


def test_stale_plan_and_running_research_are_rejected(tmp_path):
    from factory import rejudge

    with fixture_store(tmp_path / "runs") as records:
        plan = rejudge.plan_rejudgment(records)
        variant = records.get("variants", "one_A")
        variant["notes"] = ["New evidence"]
        records.put("variants", "one_A", "one", variant)
        with pytest.raises(ValueError, match="changed"):
            rejudge.apply_rejudgment(records, plan)
        run = records.get("runs", "one")
        run["status"] = "RUNNING"
        records.put("runs", "one", "one", run)
        with pytest.raises(ValueError, match="running"):
            rejudge.plan_rejudgment(records)
