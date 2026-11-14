"""Expose saved live measurements without touching the in-flight process/store."""

import copy

import pandas as pd
import pytest

from factory.api.live_evidence import recover_evaluations
from factory.api.schemas import EvalView
from factory.api.views import display_evaluations, leaderboard_row, variant_steps
from factory.evals.common import annualised_sharpe
from factory.evals.decay import decay_eval


def saved_row():
    dates = pd.bdate_range("2020-01-02", periods=80)
    daily = pd.Series([0.003, -0.002, 0.001, -0.001] * 10 + [-0.003, 0.001] * 20, index=dates)
    is_daily, oos_daily = daily.iloc[:40], daily.iloc[40:]
    return (
        {
            "variant": "A",
            "status": "RUNNING",
            "frequency": "1day",
            "evals_passed": 0,
            "reached_eval_2": True,
            "code": "retained",
            "activity": {"IS": {"total_bars": 40}, "OOS": {"total_bars": 40}},
            "equity_boundaries": {
                "is_end": str(dates[39].tz_localize("America/New_York")),
                "oos_end": str(dates[-1].tz_localize("America/New_York")),
            },
            "equity": {
                "dates": dates.strftime("%Y-%m-%d").tolist(),
                "net": (1 + daily).cumprod().tolist(),
                "is_end": str(dates[39].date()),
                "oos_end": str(dates[-1].date()),
            },
            "cost_sharpes": {
                "IS": {"0": 0.4, "2": 0.3, "5": annualised_sharpe(is_daily), "10": 0.1},
                "OOS": {"5": annualised_sharpe(oos_daily)},
            },
        },
        is_daily,
        oos_daily,
    )


def test_recovery_is_read_only_and_uses_exact_saved_costs_and_daily_equity():
    row, is_daily, oos_daily = saved_row()
    before = copy.deepcopy(row)
    evidence = recover_evaluations(row)
    assert set(evidence) == {1, 2, 4}
    assert evidence[1]["result"]["passed"] is True
    assert "cuts" not in evidence[1]["result"]["metrics"]
    assert evidence[2]["result"]["metrics"]["sharpe_by_bps"] == row["cost_sharpes"]["IS"]
    actual = evidence[4]["result"]
    expected = decay_eval(is_daily, oos_daily).to_dict()
    assert actual["passed"] == expected["passed"]
    for key, value in expected["metrics"].items():
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            assert actual["metrics"][key] == pytest.approx(value, abs=1e-10)
        else:
            assert actual["metrics"][key] == value
    assert row == before
    detail = display_evaluations(row, {"status": "RUNNING"}, [])
    assert {item["number"] for item in detail} == {1, 2, 4}
    assert all(
        item["metrics"]["evidence_source"] == "recovered_from_saved_evidence" for item in detail
    )
    for item in detail:
        EvalView.model_validate(
            {"n": item["number"], **{key: item[key] for key in ("name", "passed", "metrics")}}
        )
    assert leaderboard_row(row)["evals_passed"] == sum(item["passed"] for item in detail)
    assert display_evaluations(row, {"status": "FAILED"}, []) == []


def test_negative_base_establishes_failed_sensitivity_without_inventing_jitters():
    row, *_ = saved_row()
    row["cost_sharpes"]["IS"]["5"] = -0.05
    evidence = recover_evaluations(row)
    assert evidence[3]["result"]["passed"] is False
    assert evidence[3]["result"]["metrics"]["base_sharpe"] == -0.05
    assert "jitters" not in evidence[3]["result"]["metrics"]
    assert 4 not in evidence  # contradictory saved Sharpe/equity must not be reconstructed


@pytest.mark.parametrize(
    "change", ["minute", "missing", "downsampled", "zero", "duplicate", "boundary"]
)
def test_incomplete_or_incompatible_equity_never_produces_decay(change):
    row, *_ = saved_row()
    if change == "minute":
        row["frequency"] = "1min"
    if change == "missing":
        row["equity"] = None
    if change == "downsampled":
        row["equity"]["dates"] = row["equity"]["dates"][::2]
        row["equity"]["net"] = row["equity"]["net"][::2]
    if change == "zero":
        row["equity"]["net"][5] = 0
    if change == "duplicate":
        row["equity"]["dates"][1] = row["equity"]["dates"][0]
    if change == "boundary":
        row["equity"]["is_end"] = "1999-01-01"
    assert 4 not in recover_evaluations(row)


def test_live_steps_expose_known_results_and_only_eval5_waits_for_other_lane():
    row, *_ = saved_row()
    steps = variant_steps(
        row,
        {"status": "RUNNING"},
        [],
        [],
        [],
        None,
        siblings=[row, {"variant": "C", "status": "RUNNING"}],
    )
    by_n = {s["number"]: s for s in steps if s["kind"] == "eval"}
    assert by_n[1]["state"] == "pass"
    assert by_n[4]["state"] == "failed"
    assert "OOS Sharpe" in " ".join(by_n[4]["details"])
    assert "saved" in " ".join(by_n[4]["details"]).lower()
    assert by_n[3]["state"] == "recorded"
    assert by_n[5]["state"] == "awaiting_judgment"
    assert "C" in " ".join(by_n[5]["details"])


def test_exact_recorded_result_beats_recovery_and_true_per_eval_start_is_running():
    row, *_ = saved_row()
    recorded = [
        {
            "number": 2,
            "name": "friction",
            "passed": False,
            "metrics": {"pass_bps": 5, "sharpe_by_bps": {"5": -9.0}},
        }
    ]
    assert (
        next(
            item
            for item in display_evaluations(row, {"status": "RUNNING"}, recorded)
            if item["number"] == 2
        )
        == recorded[0]
    )
    steps = variant_steps(row, {"status": "RUNNING"}, [], recorded, [], None)
    assert "-9.000" in " ".join(next(s for s in steps if s["number"] == 2)["details"])
    fresh = {"variant": "C", "status": "RUNNING", "code": "code"}
    events = [
        {
            "stage": "eval",
            "status": "started",
            "variant": "C",
            "message": "Eval 3 started",
            "data": {"eval": 3},
        }
    ]
    steps = variant_steps(fresh, {"status": "RUNNING"}, events, [], [], None)
    assert next(s for s in steps if s["number"] == 3)["state"] == "running"
    assert next(s for s in steps if s["number"] == 4)["state"] == "pending"
