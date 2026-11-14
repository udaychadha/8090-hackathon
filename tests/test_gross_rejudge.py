"""Rejudgment refreshes only existing gross labels after authoritative decisions."""

import copy

import pytest

from factory.agents.records import Records
from factory.rejudge import apply_rejudgment, plan_rejudgment


def diagnostic(passed=True, label=None):
    return {
        "schema_version": "1.0.0",
        "state": "complete",
        "cost_bps": 0,
        "eval_3": {
            "number": 3,
            "name": "sensitivity",
            "passed": True,
            "metrics": {"cost_bps": 0, "base_sharpe": 1.2, "worst_sharpe": 0.9},
        },
        "eval_4": {
            "number": 4,
            "name": "decay",
            "passed": passed,
            "metrics": {"cost_bps": 0, "is_sharpe": 1.2, "oos_sharpe": 0.9},
        },
        "label": label,
        "reason": None,
    }


def fixture_store(root, *, before_status, is_sharpe, gross):
    records = Records(root)
    for run_id in ("with_gross", "legacy"):
        records.put("runs", run_id, run_id, {"status": "COMPLETED"})
        evaluations = [
            {"number": n, "name": f"eval{n}", "passed": True, "metrics": {}} for n in (1, 2, 3)
        ] + [
            {
                "number": 4,
                "name": "decay",
                "passed": before_status == "VERIFIED",
                "metrics": {
                    "is_sharpe": is_sharpe,
                    "oos_sharpe": 0.8,
                    "is_max_window_share": 0.2,
                    "oos_max_window_share": 0.2,
                },
            },
            {
                "number": 5,
                "name": "deflated_sharpe",
                "passed": True,
                "metrics": {"daily_sharpe": 0.5, "observations": 300, "skew": 0.0, "kurtosis": 3.0},
            },
        ]
        row = {
            "variant_id": f"{run_id}_A",
            "variant": "A",
            "source_id": "p_test",
            "source_title": "Retained fixture",
            "source_kind": "paper",
            "test_type": "transfer",
            "frequency": "1day",
            "status": before_status,
            "default_status": before_status,
            "evals_passed": sum(e["passed"] for e in evaluations),
            "default_evals_passed": sum(e["passed"] for e in evaluations),
            "evals": evaluations,
            "reached_eval_2": True,
        }
        if run_id == "with_gross":
            row["gross_diagnostics"] = gross
        row = records.put("variants", row["variant_id"], run_id, row)
        for evaluation in evaluations:
            records.put(
                "eval_results",
                f"{run_id}_A_{evaluation['number']}",
                run_id,
                {"variant": "A", **evaluation},
            )
        run = records.get("runs", run_id)
        records.put("runs", run_id, run_id, {**run, "variants": [row]})
    return records


@pytest.mark.parametrize(
    "gross_pass, expected_label",
    [
        (True, "signal before costs"),
        (False, "no signal before costs"),
    ],
)
def test_verified_to_failed_refreshes_existing_label_only(tmp_path, gross_pass, expected_label):
    gross = diagnostic(gross_pass)
    with fixture_store(
        tmp_path / "runs", before_status="VERIFIED", is_sharpe=-1, gross=gross
    ) as records:
        plan = plan_rejudgment(records)
        updated = next(row for row in plan["updates"]["variants"] if row["run_id"] == "with_gross")
        assert updated["status"] == "FAILED_EVAL_4"
        assert updated["gross_diagnostics"]["label"] == expected_label
        assert updated["gross_diagnostics"] == {**gross, "label": expected_label}
        apply_rejudgment(records, plan)
        current = records.get("variants", "with_gross_A")
        legacy = records.get("variants", "legacy_A")
        assert current["status"] == legacy["status"] == "FAILED_EVAL_4"
        assert current["evals_passed"] == legacy["evals_passed"] == 4
        assert current["evals"] == legacy["evals"]
        assert "gross_diagnostics" not in legacy
        assert (
            records.get("runs", "with_gross")["variants"][0]["gross_diagnostics"]
            == current["gross_diagnostics"]
        )


def test_failed_to_verified_clears_label_without_recomputing_gross_metrics(tmp_path):
    gross = diagnostic(label="signal before costs")
    with fixture_store(
        tmp_path / "runs", before_status="FAILED_EVAL_4", is_sharpe=1, gross=gross
    ) as records:
        plan = plan_rejudgment(records)
        updated = next(row for row in plan["updates"]["variants"] if row["run_id"] == "with_gross")
        assert updated["status"] == "VERIFIED"
        assert updated["gross_diagnostics"] == {**gross, "label": None}
        apply_rejudgment(records, plan)
        assert (
            records.get("runs", "with_gross")["variants"][0]["gross_diagnostics"]["label"] is None
        )


@pytest.mark.parametrize("gross", [None, diagnostic()])
def test_void_original_result_and_explicit_null_diagnostic_remain_unchanged(tmp_path, gross):
    with fixture_store(
        tmp_path / "runs", before_status="VERIFIED", is_sharpe=-1, gross=gross
    ) as records:
        records.void_run("with_gross", "Retained audit evidence")
        before = copy.deepcopy(records.get("variants", "with_gross_A", include_voided=True))
        apply_rejudgment(records, plan_rejudgment(records))
        after = records.get("variants", "with_gross_A", include_voided=True)
        assert after["status"] == "VOID"
        assert after["gross_diagnostics"] == before["gross_diagnostics"]
        assert after["original_result"] == before["original_result"]
