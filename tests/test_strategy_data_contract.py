import json
from pathlib import Path

import pandas as pd
import pytest

from factory.agents import worker
from factory.agents.records import Records
from factory.agents.test_worker import CLEAN, bars, spec
from factory.contract import ContractViolation
from factory.data import OHLCV, expected_index
from factory.data_contract.sessions import add_session_columns
from factory.llm import Completion
from factory.sandbox import run_strategy


def test_session_columns_and_fill_flag_survive_sandbox(tmp_path):
    index = expected_index("1min", "2024-03-11", "2024-03-11")
    frame = pd.DataFrame({**{c: 100.0 for c in OHLCV}, "is_filled": False}, index=index)
    frame.loc[index[0], "is_filled"] = True
    source = Path("tests/fixtures/session_canary.py").read_text()
    path = tmp_path / "canary.py"
    path.write_text(source)
    weights = run_strategy(path, {"SPY": frame})
    assert weights.loc["2024-03-11T13:59Z", "SPY"] == 1
    assert weights.loc["2024-03-11T19:29Z", "SPY"] == 0
    assert weights.SPY.sum() == 330
    path.write_text(source.replace("active.astype(float)", "(~frame.is_filled).astype(float)"))
    weights = run_strategy(path, {"SPY": frame})
    assert weights.iloc[0, 0] == 0 and weights.iloc[1, 0] == 1


@pytest.mark.parametrize("mutation", ["assign", "delete"])
def test_derived_fields_are_read_only(tmp_path, five_bars, valid_source, mutation):
    frame = add_session_columns(five_bars["SPY"], "1day")
    action = (
        'bars["SPY"]["minutes_since_open"] = 1'
        if mutation == "assign"
        else 'bars["SPY"] = bars["SPY"].drop(columns=["is_last_bar"])'
    )
    source = valid_source.replace("    return", f"    {action}\n    return")
    path = tmp_path / "mutates.py"
    path.write_text(source)
    with pytest.raises(ContractViolation, match="read-only"):
        run_strategy(path, {"SPY": frame})


def test_inactive_weights_are_repaired_without_performance_feedback(tmp_path, monkeypatch):
    calls = []

    def repair(role, system, user):
        calls.append(json.loads(user))
        return Completion(CLEAN, "fixture", 1, 1, 0, 0)

    monkeypatch.setattr(worker, "complete", repair)
    records = Records(tmp_path / "runs")
    try:
        result, usage = worker.validate_and_heal(
            spec(), "A", CLEAN.replace("0.25", "0.0"), bars(), tmp_path / "A.py", records, "test"
        )
        assert result is not None and len(usage) == 1
        assert calls[0]["error"] == "strategy never trades; check session-time logic"
        assert calls[0]["data_context"]["split"] == "IS"
        assert len(calls[0]["data_context"]["example_rows"]) == 3
        assert not any(k in calls[0] for k in ["sharpe", "evals", "oos", "holdout", "returns"])
    finally:
        records.close()


def test_unresolved_inactivity_keeps_status(tmp_path, monkeypatch):
    from factory.contract import InactiveStrategy

    zero = CLEAN.replace("0.25", "0.0")
    monkeypatch.setattr(worker, "complete", lambda *a: Completion(zero, "fixture", 1, 1, 0, 0))
    records = Records(tmp_path / "runs")
    try:
        with pytest.raises(InactiveStrategy) as error:
            worker.validate_and_heal(spec(), "A", zero, bars(), tmp_path / "A.py", records, "test")
        assert error.value.activity["days_traded"] == 0
        assert len(error.value.usages) == 3 and error.value.status == "INACTIVE"
    finally:
        records.close()
