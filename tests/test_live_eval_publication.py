"""Each finished deterministic eval is durable before later computation starts."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factory import evaluation, orchestrator
from factory.agents.records import Records
from factory.agents.test_worker import CLEAN, bars, spec
from factory.contract import parse_strategy
from factory.evals import runner
from factory.llm import Completion


def market():
    index = pd.date_range("2020-01-02 16:00", periods=250, freq="B", tz="UTC")
    close = 100 * np.cumprod(1 + 0.001 + 0.002 * np.sin(np.arange(len(index))))
    frame = pd.DataFrame(
        {name: close for name in ("open", "high", "low", "close", "volume")}, index=index
    )
    return {"SPY": frame.iloc[:150]}, {"SPY": frame.iloc[150:]}


def adapter_fixture(tmp_path, monkeypatch, *, fail_oos=False):
    is_bars, oos_bars = market()
    calls = []

    def run(data, params=None):
        calls.append((len(data["SPY"]), params))
        if fail_oos and len(data["SPY"]) == 250:
            raise RuntimeError("OOS execution failed")
        return pd.DataFrame(
            (params or {"weight": 0.25})["weight"], index=data["SPY"].index, columns=["SPY"]
        )

    path = tmp_path / "candidate.py"
    path.write_text(CLEAN)
    monkeypatch.setattr(
        evaluation, "load_bars", lambda *a, split, **kw: is_bars if split == "IS" else oos_bars
    )
    monkeypatch.setattr(evaluation, "sandbox_runner", lambda *a, **kw: run)
    return path, is_bars, oos_bars, run, calls


def test_observer_reports_exact_results_in_order_without_extra_execution(tmp_path, monkeypatch):
    path, is_bars, oos_bars, run, calls = adapter_fixture(tmp_path, monkeypatch)
    expected = runner.evaluate(run, {"weight": 0.25}, "1day", is_bars, oos_bars)
    expected_calls = calls.copy()
    calls.clear()
    events = []
    original_functions = {
        name: getattr(runner, name)
        for name in ("lookahead_eval", "friction_eval", "sensitivity_eval", "decay_eval")
    }

    def observe(number, status, message, result):
        events.append((number, status, result))
        if number == 4 and status == "started":
            assert not any(length == 250 for length, _ in calls)

    with evaluation.evaluation_progress(observe):
        recorded = evaluation.evaluate_file(path)
    assert len(calls) == 11
    assert calls == expected_calls
    assert recorded.report.results == expected.results
    assert [(n, s) for n, s, result in events if s != "info"] == [
        pair
        for number in (1, 2, 3, 4)
        for pair in [
            (number, "started"),
            (number, "passed" if expected.results[number].passed else "failed"),
        ]
    ]
    assert {n: result for n, _, result in events if result is not None} == {
        n: expected.results[n] for n in (1, 2, 3, 4)
    }
    assert len([item for item in events if item[0] == 3 and item[1] == "info"]) == 8
    assert all(getattr(runner, name) is function for name, function in original_functions.items())


def test_observer_scope_resets_after_exception_and_never_reports_unfinished_eval(
    tmp_path, monkeypatch
):
    path, *_ = adapter_fixture(tmp_path, monkeypatch, fail_oos=True)
    results = []
    with (
        pytest.raises(RuntimeError),
        evaluation.evaluation_progress(
            lambda number, status, message, result: results.append(number) if result else None
        ),
    ):
        evaluation.evaluate_file(path)
    assert results == [1, 2, 3]
    path, *_ = adapter_fixture(tmp_path, monkeypatch)
    evaluation.evaluate_file(path)
    assert results == [1, 2, 3]


def setup_pipeline(tmp_path, monkeypatch):
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


def test_completed_results_are_durable_before_next_eval_and_survive_later_failure(
    tmp_path, monkeypatch
):
    setup_pipeline(tmp_path, monkeypatch)
    _, is_bars, oos_bars, _, _ = adapter_fixture(tmp_path, monkeypatch)
    observations = []

    def sandbox(path, **kwargs):
        lane = Path(path).stem

        def run(data, params=None):
            with Records(tmp_path / "runs", read_only=True) as records:
                values = records.list("eval_results", run_id="r_live", variant=lane)
                numbers = {item["number"] for item in values}
                if params is not None:
                    assert numbers == {1, 2}
                    row = records.get("variants", f"r_live_{lane}")
                    assert row["status"] == "RUNNING"
                    assert row["evals_passed"] == sum(item["passed"] for item in values)
                if len(data["SPY"]) == 250:
                    assert numbers == {1, 2, 3}
                    observations.append(lane)
                    if lane == "A":
                        raise RuntimeError("Later execution failure")
                if lane == "B" and data is is_bars and params is None:
                    assert {
                        e["number"]
                        for e in records.list("eval_results", run_id="r_live", variant="A")
                    } == {1, 2, 3}
            return pd.DataFrame(
                (params or {"weight": 0.25})["weight"], index=data["SPY"].index, columns=["SPY"]
            )

        return run

    monkeypatch.setattr(evaluation, "sandbox_runner", sandbox)
    result = orchestrator.run_paper("fixture.pdf", output_root=tmp_path, run_id="r_live")
    assert observations == list("ABC")
    assert result["status"] == "FAILED"
    with Records(tmp_path / "runs", read_only=True) as records:
        a = records.get("variants", "r_live_A")
        assert a["status"] == "BUG_UNRESOLVED"
        assert {e["number"] for e in a["evals"]} == {1, 2, 3}
        for lane in "BC":
            events = records.events("r_live")
            completions = [
                e
                for e in events
                if e["variant"] == lane
                and e["stage"] == "eval"
                and e["status"] in {"passed", "failed"}
                and e["data"].get("eval")
            ]
            assert [e["data"]["eval"] for e in completions] == [1, 2, 3, 4, 5]
        waiting = [
            e
            for e in events
            if e["variant"] == "B" and e["data"].get("eval") == 5 and e["status"] == "info"
        ]
        assert waiting and "cohort" in waiting[0]["message"]


def test_published_metrics_are_redacted_without_making_final_evidence_conflict(
    tmp_path, monkeypatch
):
    from factory.evals.common import EvalResult

    setup_pipeline(tmp_path, monkeypatch)
    adapter_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "secret-jitter-value")
    original = runner.sensitivity_eval

    def with_sensitive_reason(*args, **kwargs):
        result = original(*args, **kwargs)
        return EvalResult(
            result.number,
            result.name,
            result.passed,
            {**result.metrics, "reason": "error includes secret-jitter-value"},
        )

    monkeypatch.setattr(runner, "sensitivity_eval", with_sensitive_reason)
    result = orchestrator.run_paper("fixture.pdf", output_root=tmp_path, run_id="r_safe")
    assert result["status"] == "COMPLETED"
    with Records(tmp_path / "runs", read_only=True) as records:
        assert "secret-jitter-value" not in str(records.list("eval_results"))
        assert "secret-jitter-value" not in str(records.events("r_safe"))
        assert all(len(row["evals"]) == 5 for row in records.list("variants"))
