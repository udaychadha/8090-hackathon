"""Failures before Eval 2 must not poison sibling DSR; all outputs are filtered."""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

from factory import orchestrator
from factory.agents import critic, worker
from factory.agents.records import Records
from factory.agents.test_worker import CLEAN, bars, spec
from factory.contract import parse_strategy
from factory.evals.common import EvalResult, daily_sharpe
from factory.evals.runner import EvalReport
from factory.evaluation import RecordedEvaluation
from factory.llm import Completion, LLMError


@pytest.fixture
def run_fixture(monkeypatch):
    usage = Completion("fixture narrative", "fixture", 10, 5, 0.01, 0.001)
    for role in ("EXTRACTOR", "WORKER", "CRITIC"):
        monkeypatch.setenv(f"{role}_MODEL", "openai:fixture")
    monkeypatch.setattr(orchestrator, "extract", lambda *a, **kw: (spec(), usage))
    monkeypatch.setattr(orchestrator, "load_bars", lambda *a, **kw: bars())
    monkeypatch.setattr(
        orchestrator, "propose_parallel", lambda *a: {v: (CLEAN, usage) for v in "ABC"}
    )
    monkeypatch.setattr(orchestrator, "critique", lambda *a: usage)

    def heal(s, variant, code, is_bars, path, *args):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(code)
        return parse_strategy(code), []

    def evaluate(*args):
        returns = pd.Series([0.01, -0.004, 0.006, 0.002] * 80)
        report = EvalReport(
            {n: EvalResult(n, f"eval{n}", True, {}) for n in range(1, 6)},
            {},
            returns,
            daily_sharpe(returns),
        )
        return RecordedEvaluation(
            report,
            {
                "dates": ["2024-03-11", "2024-03-12"],
                "gross": [1.01, 1.02],
                "net": [1.009, 1.018],
                "is_end": "2024-03-11",
                "oos_end": "2024-03-12",
            },
        )

    monkeypatch.setattr(orchestrator, "validate_and_heal", heal)
    monkeypatch.setattr(orchestrator, "evaluate_file", evaluate)
    return usage, heal, evaluate


@pytest.mark.parametrize("stage", ["repair", "harness", "artifact", "undefined_sharpe"])
def test_failure_scope(run_fixture, monkeypatch, tmp_path, stage):
    _, heal, evaluate = run_fixture

    def failed_heal(s, v, *args):
        if stage == "repair" and v == "A":
            raise LLMError("Repair failed before Eval 2")
        return heal(s, v, *args)

    def failed_evaluate(path, *args):
        result = evaluate()
        if Path(path).stem == "A":
            if stage == "harness":
                raise RuntimeError("Failure after Eval 2 started")
            if stage == "artifact":
                return RecordedEvaluation(result.report, artifact_error="Missing equity")
            if stage == "undefined_sharpe":
                return RecordedEvaluation(
                    EvalReport(result.report.results, {}, pd.Series([0.0] * 320), None)
                )
        return result

    monkeypatch.setattr(orchestrator, "validate_and_heal", failed_heal)
    monkeypatch.setattr(orchestrator, "evaluate_file", failed_evaluate)
    outcome = orchestrator.run_paper("stub.pdf", output_root=tmp_path)
    assert outcome["status"] == ("COMPLETED" if stage == "undefined_sharpe" else "FAILED")
    for row in outcome["variants"][1:]:
        if stage in {"harness", "undefined_sharpe"}:
            assert row["status"] == "FAILED_EVAL_5"
        else:
            assert row["status"] == "VERIFIED"
    if stage == "repair":
        assert outcome["estimated_model_cost_usd"] is None


def test_prompts_cli_records_and_graveyard_redact(run_fixture, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(orchestrator, "load_dotenv", lambda **kw: None)
    usage, _, _ = run_fixture
    sentinel = "fake-secret-sentinel-93bc"
    monkeypatch.setenv("OPENAI_API_KEY", sentinel)
    sample = spec().model_copy(update={"title": "Title " + sentinel})
    monkeypatch.setattr(orchestrator, "extract", lambda *a, **kw: (sample, usage))
    prompts = []

    def complete(role, system, user, **kwargs):
        prompts.append(user)
        return Completion(
            CLEAN if role == "worker" else "Critique " + sentinel, "fixture", 10, 5, 0.01, 0.001
        )

    monkeypatch.setattr(worker, "complete", complete)
    monkeypatch.setattr(critic, "complete", complete)
    monkeypatch.setattr(orchestrator, "propose_parallel", worker.propose_parallel)
    monkeypatch.setattr(orchestrator, "critique", critic.critique)
    monkeypatch.setattr(sys, "argv", ["orchestrator", "stub.pdf", "--output", str(tmp_path)])
    orchestrator.main()
    displayed = capsys.readouterr().out
    assert json.loads(displayed)["status"] == "COMPLETED"
    assert sentinel not in displayed
    assert prompts and all(sentinel not in prompt for prompt in prompts)
    assert sentinel not in (tmp_path / "wiki/graveyard.md").read_text()
    assert sentinel not in (tmp_path / "runs/events.jsonl").read_text()
    records = Records(tmp_path / "runs")
    assert sentinel not in "\n".join(records.db.iterdump())
    records.close()


def test_intraday_worker_receives_real_bar_clock(run_fixture, monkeypatch, tmp_path):
    from factory.data import OHLCV, expected_index

    usage, _, _ = run_fixture
    intraday = spec().model_copy(update={"frequency": "1min"})
    monkeypatch.setattr(orchestrator, "extract", lambda *a, **kw: (intraday, usage))
    frame = pd.DataFrame(
        {c: 100.0 for c in OHLCV}, index=expected_index("1min", "2024-03-11", "2024-03-12")
    )
    monkeypatch.setattr(orchestrator, "load_bars", lambda *a, **kw: {"SPY": frame})
    captured = []

    def propose(spec, schema):
        captured.append(schema)
        return {v: RuntimeError("Stop fixture before generation") for v in "ABC"}

    monkeypatch.setattr(orchestrator, "propose_parallel", propose)
    orchestrator.run_paper("stub.pdf", output_root=tmp_path)
    timing = captured[0]["data_contract"]
    assert "bar START" in timing and "15:59" in timing and "no 16:00 bar" in timing
    assert "next bar's close-to-close return" in timing


def test_inactive_lane_stops_before_evals_without_poisoning_siblings(
    run_fixture, monkeypatch, tmp_path
):
    from factory.contract import InactiveStrategy

    _, heal, evaluate = run_fixture
    evaluated = []

    def inactive(s, variant, *args):
        result = heal(s, variant, *args)
        if variant == "A":
            raise InactiveStrategy({"active_bars": 0, "total_bars": 40, "days_traded": 0})
        return result

    def capture(path, *args):
        evaluated.append(Path(path).stem)
        return evaluate(path, *args)

    monkeypatch.setattr(orchestrator, "validate_and_heal", inactive)
    monkeypatch.setattr(orchestrator, "evaluate_file", capture)
    result = orchestrator.run_paper("stub.pdf", output_root=tmp_path)
    assert evaluated == ["B", "C"]
    a, b, c = result["variants"]
    assert a["status"] == "INACTIVE" and a["evals_passed"] == 0
    assert a["days_traded"] == 0 and a["eval_eligible"] is False
    assert b["status"] == c["status"] == "VERIFIED"
    assert result["status"] == "COMPLETED"
