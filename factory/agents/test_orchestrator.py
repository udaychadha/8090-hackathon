"""Offline integration: real records/IS bug checks, stubbed paper/models/eval telemetry."""

import json

import pandas as pd

from factory import orchestrator
from factory.agents import worker
from factory.agents.records import TABLES, Records
from factory.agents.test_worker import CLEAN, LEAK, bars, spec
from factory.evals.common import EvalResult
from factory.evals.runner import EvalReport
from factory.evaluation import RecordedEvaluation
from factory.llm import Completion


def test_run_records_all_stages_without_metric_healing(tmp_path, monkeypatch):
    usage = Completion("postmortem", "test", 10, 5, 0.01, 0.001)
    for role in ("EXTRACTOR", "WORKER", "CRITIC"):
        monkeypatch.setenv(f"{role}_MODEL", "openai:test")
    monkeypatch.setattr(orchestrator, "extract", lambda *a, **kw: (spec(), usage))
    splits = []

    def load(*a, **kw):
        splits.append(kw["split"])
        return bars()

    monkeypatch.setattr(orchestrator, "load_bars", load)

    def proposals(spec, schema):
        assert "not guaranteed available at the regular-session close" in schema["data_contract"]
        return {"A": (LEAK, usage), "B": (CLEAN, usage), "C": (CLEAN, usage)}

    monkeypatch.setattr(orchestrator, "propose_parallel", proposals)
    repairs = []

    def repair(*args):
        repairs.append(args)
        return Completion(CLEAN, "test", 10, 5, 0.01, 0.001)

    monkeypatch.setattr(worker, "complete", repair)

    def evaluate(*a):
        returns = pd.Series([0.01, -0.02, 0.005] * 30)
        return RecordedEvaluation(
            EvalReport(
                {
                    n: EvalResult(n, f"eval{n}", n == 1, {"reason": "fixture failure"})
                    for n in range(1, 6)
                },
                {},
                returns,
                0.01,
            ),
            equity={
                "dates": ["2020-01-01"],
                "gross": [1.01],
                "net": [1.009],
                "is_end": "2020-01-01",
                "oos_end": "2020-01-01",
            },
        )

    monkeypatch.setattr(orchestrator, "evaluate_file", evaluate)
    monkeypatch.setattr(orchestrator, "critique", lambda *a: usage)
    result = orchestrator.run_paper("stub.pdf", output_root=tmp_path)
    assert result["status"] == "COMPLETED"
    assert len(repairs) == 1  # No repair for any metrics failure.
    assert set(splits) == {"IS"} and "HOLDOUT" not in splits
    assert all(row["status"] == "FAILED_EVAL_2" for row in result["variants"])
    assert all(len(row["evals"]) == 5 for row in result["variants"])
    assert all(row["equity"]["net"] == [1.009] for row in result["variants"])
    assert all(row["notes"] for row in result["variants"])
    assert result["estimated_model_cost_usd"] == 0.008
    records = Records(tmp_path / "runs")
    for table in TABLES:
        assert records.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0
    assert records.db.execute("SELECT COUNT(*) FROM eval_results").fetchone()[0] == 15
    saved_rows = records.db.execute("SELECT payload FROM variants").fetchall()
    assert all(json.loads(row[0])["equity"]["gross"] == [1.01] for row in saved_rows)
    records.close()
    events = [
        json.loads(line) for line in (tmp_path / "runs/events.jsonl").read_text().splitlines()
    ]
    assert all(
        set(e) == {"seq", "ts", "run_id", "stage", "variant", "status", "message", "data"}
        for e in events
    )
    assert (tmp_path / "wiki/graveyard.md").read_text().count("postmortem") == 3


def test_missing_config_is_recorded_not_success(tmp_path, monkeypatch):
    monkeypatch.delenv("EXTRACTOR_MODEL", raising=False)
    result = orchestrator.run_paper("missing.pdf", output_root=tmp_path)
    assert result["status"] == "FAILED"
    assert result["estimated_model_cost_usd"] is None
    assert result["error_type"] == "LLMError"


def test_records_redact_and_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-example-key")
    records = Records(tmp_path)
    records.event("r", "worker", "failed", "secret-example-key")
    records.close()
    (tmp_path / "events.jsonl").write_text("torn mirror")
    records = Records(tmp_path)
    text = (tmp_path / "events.jsonl").read_text()
    assert "secret-example-key" not in text
    assert json.loads(text)["message"] == "[REDACTED]"
    records.close()


def test_all_provider_failures_fail_run(tmp_path, monkeypatch):
    usage = Completion("postmortem", "test", 1, 1, 0, 0.001)
    for role in ("EXTRACTOR", "WORKER", "CRITIC"):
        monkeypatch.setenv(f"{role}_MODEL", "openai:test")
    monkeypatch.setattr(orchestrator, "extract", lambda *a, **kw: (spec(), usage))
    monkeypatch.setattr(orchestrator, "load_bars", lambda *a, **kw: bars())
    monkeypatch.setattr(
        orchestrator,
        "propose_parallel",
        lambda *a: {variant: RuntimeError("provider unavailable") for variant in "ABC"},
    )
    monkeypatch.setattr(orchestrator, "critique", lambda *a: usage)
    result = orchestrator.run_paper("stub.pdf", output_root=tmp_path)
    assert result["status"] == "FAILED"
    assert result["estimated_model_cost_usd"] is None
    events = [
        json.loads(line) for line in (tmp_path / "runs/events.jsonl").read_text().splitlines()
    ]
    assert events[-1]["stage"] == "done" and events[-1]["status"] == "failed"
