"""Computation progress must never masquerade as published eval outcomes."""

import copy
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from factory import orchestrator
from factory.agents.records import Records
from factory.agents.test_worker import CLEAN, bars, spec
from factory.api.app import create_app
from factory.api.views import leaderboard_row, variant_steps
from factory.contract import parse_strategy
from factory.evals.common import EvalResult
from factory.evals.runner import EvalReport
from factory.evaluation import RecordedEvaluation
from factory.llm import Completion

COMPLETED = "Variant computation complete; awaiting final judgment"
ACTIVITY = {
    period: {"active_bars": 5, "total_bars": 20, "days_traded": 5} for period in ("IS", "OOS")
}
BOUNDARIES = {"is_end": "2024-01-10T05:00:00Z", "oos_end": "2024-02-10T05:00:00Z"}


def row(complete=False):
    value = orchestrator._row(spec(), "r_progress", "A")
    value["code"] = CLEAN
    if complete:
        value.update(activity=copy.deepcopy(ACTIVITY), equity_boundaries=BOUNDARIES.copy())
    return value


def event(message="Running all five evals", status="started", variant="A"):
    return {"stage": "eval", "status": status, "variant": variant, "message": message, "data": {}}


def eval_steps(value, *, events=None, run_status="RUNNING", evals=None):
    return [
        step
        for step in variant_steps(
            value, {"status": run_status}, events or [], evals or [], [], None
        )
        if step["kind"] == "eval"
    ]


def test_legacy_completed_artifacts_show_judgment_wait_without_changing_verdict():
    value = row(complete=True)
    steps = eval_steps(value, events=[event()])
    assert {step["state"] for step in steps} == {"awaiting_judgment"}
    assert all("Computation complete; awaiting final judgment" in step["details"] for step in steps)
    projected = leaderboard_row(value)
    assert projected["summary"] == "Computation complete; awaiting final judgment."
    assert projected["status"] == "RUNNING" and projected["evals_passed"] == 0


def test_generic_harness_start_means_unpublished_results_not_five_running_checks():
    steps = eval_steps(row(), events=[event()])
    assert {step["state"] for step in steps} == {"awaiting_results"}
    assert all(
        step["details"] == ["Harness active; individual outcomes not yet published."]
        for step in steps
    )
    assert {step["state"] for step in eval_steps(row())} == {"pending"}


@pytest.mark.parametrize(
    "partial",
    [
        {"activity": ACTIVITY},
        {"equity_boundaries": BOUNDARIES},
        {"activity": {"IS": ACTIVITY["IS"]}, "equity_boundaries": BOUNDARIES},
        {"activity": ACTIVITY, "equity_boundaries": {"is_end": BOUNDARIES["is_end"]}},
    ],
)
def test_partial_artifacts_do_not_prove_computation_complete(partial):
    value = {**row(), **partial}
    assert {step["state"] for step in eval_steps(value, events=[event()])} == {"awaiting_results"}
    assert "Computation complete" not in leaderboard_row(value)["summary"]


def test_explicit_completion_event_is_lane_scoped_and_does_not_publish_outcomes():
    completion = event(COMPLETED, "info")
    steps = eval_steps(row(), events=[completion])
    assert {step["state"] for step in steps} == {"awaiting_judgment"}
    assert {
        step["state"] for step in eval_steps(row(), events=[{**completion, "variant": "B"}])
    } == {"pending"}


@pytest.mark.parametrize(
    "status, run_status", [("RUNNING", "FAILED"), ("BUG_UNRESOLVED", "RUNNING"), ("VOID", "VOID")]
)
def test_terminal_failure_and_recorded_outcomes_override_waiting(status, run_status):
    value = {**row(complete=True), "status": status}
    recorded = [
        {"number": 1, "name": "lookahead", "passed": True, "metrics": {}},
        {"number": 2, "name": "friction", "passed": False, "metrics": {}},
    ]
    steps = eval_steps(
        value, run_status=run_status, events=[event(), event(COMPLETED, "info")], evals=recorded
    )
    assert [step["state"] for step in steps] == ["pass", "failed", "not_run", "not_run", "not_run"]


def test_http_progress_distinguishes_finished_lanes_from_queued_lane(tmp_path):
    with Records(tmp_path / "runs") as records:
        records.put("runs", "r_progress", "r_progress", {"status": "RUNNING"})
        for lane in "ABC":
            value = {
                **row(complete=lane == "A"),
                "variant": lane,
                "variant_id": f"r_progress_{lane}",
            }
            records.put("variants", value["variant_id"], "r_progress", value)
            if lane in "AB":
                records.event(
                    "r_progress", "eval", "started", "Running all five evals", variant=lane
                )
            if lane == "B":
                records.event("r_progress", "eval", "info", COMPLETED, variant=lane)
    with TestClient(create_app(tmp_path)) as client:
        result = client.get("/api/runs/r_progress")
        assert result.status_code == 200
        variants = result.json()["variants"]
        assert result.json()["status"] == "RUNNING"
        for value in variants[:2]:
            assert value["summary"] == "Computation complete; awaiting final judgment."
            assert {s["state"] for s in value["steps"] if s["kind"] == "eval"} == {
                "awaiting_judgment"
            }
            assert value["status"] == "RUNNING" and value["evals_passed"] == 0
        assert {s["state"] for s in variants[2]["steps"] if s["kind"] == "eval"} == {"pending"}
        for route in ("/api/leaderboard", "/api/variants/r_progress_B"):
            payload = client.get(route).json()
            selected = (
                next(v for v in payload["rows"] if v["variant"] == "B")
                if "rows" in payload
                else payload
            )
            assert selected["summary"] == "Computation complete; awaiting final judgment."
        with Records(tmp_path / "runs") as records:
            run = records.get("runs", "r_progress")
            records.put("runs", "r_progress", "r_progress", {**run, "status": "FAILED"})
        failed = client.get("/api/runs/r_progress").json()
        assert all("awaiting" not in value["summary"] for value in failed["variants"])
        assert all(
            s["state"] == "not_run"
            for value in failed["variants"]
            for s in value["steps"]
            if s["kind"] == "eval"
        )


def test_pipeline_emits_one_neutral_completion_after_evaluation_before_next_lane(
    tmp_path, monkeypatch
):
    usage = Completion("fixture", "fixture", 1, 1, 0, 0.001)
    for role in ("EXTRACTOR", "WORKER", "CRITIC"):
        monkeypatch.setenv(f"{role}_MODEL", "openai:fixture")
    monkeypatch.setattr(orchestrator, "extract", lambda *a, **kw: (spec(), usage))
    monkeypatch.setattr(orchestrator, "load_bars", lambda *a, **kw: bars())
    monkeypatch.setattr(
        orchestrator, "propose_parallel", lambda *a: {v: (CLEAN, usage) for v in "ABC"}
    )
    monkeypatch.setattr(orchestrator, "critique", lambda *a: usage)

    def heal(s, lane, code, is_bars, path, *args):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(code)
        return parse_strategy(code), []

    monkeypatch.setattr(orchestrator, "validate_and_heal", heal)
    evaluated = []

    def evaluate(path, *args, on_eval2_started=None):
        with Records(tmp_path / "runs", read_only=True) as records:
            completed = [e for e in records.events("r_progress") if e["message"] == COMPLETED]
            assert [e["variant"] for e in completed] == evaluated
            assert all(e["status"] == "info" and e["data"] == {} for e in completed)
        evaluated.append(Path(path).stem)
        on_eval2_started()
        returns = pd.Series([0.01, -0.004, 0.006, 0.002] * 80)
        return RecordedEvaluation(
            EvalReport(
                {n: EvalResult(n, f"eval{n}", True, {}) for n in range(1, 6)}, {}, returns, 0.5
            )
        )

    monkeypatch.setattr(orchestrator, "evaluate_file", evaluate)
    result = orchestrator.run_paper("fixture.pdf", output_root=tmp_path, run_id="r_progress")
    assert result["status"] == "COMPLETED"
    with Records(tmp_path / "runs", read_only=True) as records:
        completed = [e for e in records.events("r_progress") if e["message"] == COMPLETED]
        assert [e["variant"] for e in completed] == list("ABC")
