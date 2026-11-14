"""Offline WO-06 tests using real sandbox and Eval 1, with mocked generation."""

import json
import threading

import pandas as pd
import pytest

from factory.agents import worker
from factory.agents.records import Records
from factory.agents.test_extractor import response
from factory.contract import StrategySpec
from factory.data import expected_index
from factory.llm import Completion

CLEAN = """import pandas as pd
FREQUENCY = "1day"
UNIVERSE = ["SPY"]
PARAMS = {"weight": 0.25}
def generate_signals(bars, params):
    return pd.DataFrame(params["weight"], index=bars["SPY"].index, columns=UNIVERSE)
"""
LEAK = """import pandas as pd
FREQUENCY = "1day"
UNIVERSE = ["SPY"]
PARAMS = {"weight": 0.25}
def generate_signals(bars, params):
    close = bars["SPY"]["close"]
    signal = (close.shift(-1) > close).astype(float).fillna(0) * params["weight"]
    return pd.DataFrame({"SPY": signal}, index=close.index)
"""


def spec():
    return StrategySpec.model_validate_json(response().text)


def bars():
    index = expected_index("1day", "2020-01-02", "2020-04-30")[:40]
    close = pd.Series(range(100, 140), index=index, dtype=float)
    return {"SPY": pd.DataFrame({k: close for k in ["open", "high", "low", "close", "volume"]})}


def test_parallel(monkeypatch):
    barrier = threading.Barrier(3, timeout=5)

    def fake(*args):
        barrier.wait()
        return Completion(CLEAN, "openai:test", 1, 1, 0, 0)

    monkeypatch.setattr(worker, "complete", fake)
    results = worker.propose_parallel(spec(), {"columns": ["close"]})
    assert set(results) == {"A", "B", "C"}
    assert all(isinstance(value, tuple) for value in results.values())


def test_real_lookahead_repaired_and_recorded(tmp_path, monkeypatch):
    calls = []

    def repair(role, system, payload):
        calls.append(json.loads(payload))
        return Completion(CLEAN, "openai:test", 1, 1, 0, 0)

    monkeypatch.setattr(worker, "complete", repair)
    records = Records(tmp_path / "runs")
    definition, usages = worker.validate_and_heal(
        spec(), "A", LEAK, bars(), tmp_path / "A.py", records, "run_test"
    )
    assert definition is not None and len(usages) == len(calls) == 1
    assert "SPY" in calls[0]["error"]
    assert "oos" not in calls[0] and "holdout" not in calls[0]
    rows = records.db.execute("SELECT payload FROM heal_attempts").fetchall()
    assert len(rows) == 1 and json.loads(rows[0][0])["fixed"]
    events = [
        json.loads(line) for line in (tmp_path / "runs/events.jsonl").read_text().splitlines()
    ]
    assert any(e["stage"] == "eval" and e["status"] == "failed" for e in events)
    assert any(e["stage"] == "heal" and e["status"] == "passed" for e in events)
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    records.close()


def test_repair_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "complete", lambda *args: Completion("bad", "test", 1, 1, 0, 0))
    records = Records(tmp_path / "runs")
    definition, usage = worker.validate_and_heal(
        spec(), "A", "bad", bars(), tmp_path / "A.py", records, "r_limit"
    )
    assert definition is None and len(usage) == 3
    assert records.db.execute("SELECT COUNT(*) FROM heal_attempts").fetchone()[0] == 3
    records.close()


def test_failed_repair_records_failure_and_prior_usage(tmp_path, monkeypatch):
    completed = Completion("bad", "test", 10, 5, 0.01, 0.001)
    calls = 0

    def repair(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            return completed
        raise RuntimeError("provider error text must stay private")

    monkeypatch.setattr(worker, "complete", repair)
    records = Records(tmp_path / "runs")
    with pytest.raises(worker.RepairFailure) as caught:
        worker.validate_and_heal(spec(), "A", "bad", bars(), tmp_path / "A.py", records, "r")
    assert caught.value.usages == [completed]
    rows = [
        json.loads(row[0])
        for row in records.db.execute("SELECT payload FROM heal_attempts ORDER BY id")
    ]
    assert len(rows) == 2 and all(not row["fixed"] for row in rows)
    assert rows[1]["result_error"] == "Repair provider failed"
    events = [
        json.loads(line) for line in (tmp_path / "runs/events.jsonl").read_text().splitlines()
    ]
    assert events[-1]["stage"] == "heal" and events[-1]["status"] == "failed"
    assert "provider error text" not in str(rows) + str(events)
    records.close()
