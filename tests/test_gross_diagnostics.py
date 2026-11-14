"""Gross diagnostics explain signal quality without changing authoritative evidence."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from factory import evaluation
from factory.evals.runner import evaluate
from factory.sandbox import StrategyExecutionError


def market():
    index = pd.date_range("2020-01-02 16:00", periods=250, freq="B", tz="UTC")
    close = 100 * np.cumprod(1 + 0.001 + 0.002 * np.sin(np.arange(len(index))))
    frame = pd.DataFrame(
        {name: close for name in ("open", "high", "low", "close", "volume")}, index=index
    )
    return {"SPY": frame.iloc[:150]}, {"SPY": frame.iloc[150:]}


def setup_evaluation(tmp_path, monkeypatch, valid_source, *, fragile=False):
    is_bars, oos_bars = market()
    calls = []

    def run(bars, params=None):
        calls.append((len(bars["SPY"]), params))
        if fragile and params is not None and params["weight"] < 0.25:
            raise StrategyExecutionError("jitter fails")
        return pd.DataFrame(
            (params or {"weight": 0.25})["weight"], index=bars["SPY"].index, columns=["SPY"]
        )

    path = tmp_path / "strategy.py"
    path.write_text(valid_source)
    monkeypatch.setattr(
        evaluation, "load_bars", lambda *a, split, **kw: is_bars if split == "IS" else oos_bars
    )
    monkeypatch.setattr(evaluation, "sandbox_runner", lambda *a, **kw: run)
    return path, is_bars, oos_bars, run, calls


@pytest.mark.parametrize("fragile", [False, True])
def test_captured_diagnostics_do_not_change_evals_or_execute_again(
    tmp_path, monkeypatch, valid_source, fragile
):
    path, is_bars, oos_bars, run, calls = setup_evaluation(
        tmp_path, monkeypatch, valid_source, fragile=fragile
    )
    reference = evaluate(run, {"weight": 0.25}, "1day", is_bars, oos_bars)
    calls.clear()
    recorded = evaluation.evaluate_file(path)
    assert len(calls) == 11
    assert recorded.report.results == reference.results
    pd.testing.assert_series_equal(recorded.report.oos_daily_returns, reference.oos_daily_returns)
    diagnostic = recorded.gross_diagnostics
    assert diagnostic["state"] == "complete"
    assert diagnostic["label"] is None
    assert diagnostic["cost_bps"] == 0
    assert diagnostic["eval_3"]["metrics"]["cost_bps"] == 0
    assert diagnostic["eval_4"]["metrics"]["cost_bps"] == 0
    assert diagnostic["eval_3"]["passed"] is (not fragile)
    assert diagnostic["eval_4"]["passed"] is True
    assert (
        diagnostic["eval_3"]["metrics"]["base_sharpe"] > reference.results[3].metrics["base_sharpe"]
    )
    if fragile:
        assert diagnostic["eval_3"]["metrics"]["worst_sharpe"] is None
        assert sum("error" in row for row in diagnostic["eval_3"]["metrics"]["jitters"]) == 2


def test_diagnostic_failure_preserves_valid_report(tmp_path, monkeypatch, valid_source):
    from factory import gross_diagnostics

    path, is_bars, oos_bars, run, _ = setup_evaluation(tmp_path, monkeypatch, valid_source)
    reference = evaluate(run, {"weight": 0.25}, "1day", is_bars, oos_bars)

    def failed(*args, **kwargs):
        raise RuntimeError("diagnostic recorder failure")

    monkeypatch.setattr(gross_diagnostics, "diagnostics_from_targets", failed)
    recorded = evaluation.evaluate_file(path)
    assert recorded.report.results == reference.results
    assert recorded.artifact_error is None
    assert recorded.gross_diagnostics["state"] == "unavailable"
    assert recorded.gross_diagnostics["reason"]
    assert recorded.gross_diagnostics["eval_3"] is None


def test_missing_observation_is_not_a_measured_failure():
    from factory.gross_diagnostics import diagnostics_for_status, unavailable_diagnostics

    result = diagnostics_for_status(unavailable_diagnostics("No valid targets"), "INACTIVE")
    assert result["state"] == "unavailable"
    assert result["eval_3"] is result["eval_4"] is None
    assert result["reason"] == "No valid targets"


def test_labels_are_deterministic_and_only_for_terminal_failures(
    tmp_path, monkeypatch, valid_source
):
    from factory.gross_diagnostics import diagnostics_for_status

    path, *_ = setup_evaluation(tmp_path, monkeypatch, valid_source)
    measured = evaluation.evaluate_file(path).gross_diagnostics
    original = deepcopy(measured)
    assert diagnostics_for_status(measured, "FAILED_EVAL_2")["label"] == "signal before costs"
    assert diagnostics_for_status(measured, "VERIFIED")["label"] is None
    assert diagnostics_for_status(measured, "RUNNING")["state"] == "pending"
    measured["eval_3"]["passed"] = False
    assert diagnostics_for_status(measured, "FAILED_EVAL_3")["label"] == "no signal before costs"
    assert original["label"] is None


def test_typed_diagnostic_rejects_nonzero_cost_and_swapped_evals(
    tmp_path, monkeypatch, valid_source
):
    from factory.record_models import GrossDiagnostics

    path, *_ = setup_evaluation(tmp_path, monkeypatch, valid_source)
    result = evaluation.evaluate_file(path).gross_diagnostics
    GrossDiagnostics.model_validate(result)
    for corrupted in (
        {**result, "cost_bps": 5},
        {**result, "eval_3": result["eval_4"]},
        {**result, "state": "unavailable"},
        {**result, "eval_3": None},
    ):
        with pytest.raises(ValidationError):
            GrossDiagnostics.model_validate(corrupted)


def test_historical_helper_runs_only_base_jitters_and_warm_oos(tmp_path, monkeypatch, valid_source):
    from factory import gross_diagnostics

    path, is_bars, oos_bars, run, calls = setup_evaluation(tmp_path, monkeypatch, valid_source)
    monkeypatch.setattr(
        gross_diagnostics,
        "load_bars",
        lambda *a, split, **kw: is_bars if split == "IS" else oos_bars,
    )
    monkeypatch.setattr(gross_diagnostics, "sandbox_runner", lambda *a, **kw: run)
    result = gross_diagnostics.compute_diagnostics_file(path)
    assert result["state"] == "complete"
    assert len(calls) == 6
    assert calls[0] == (150, None)
    assert calls[-1] == (250, None)
    assert result["eval_4"]["passed"] is True


@pytest.mark.parametrize("weight", [0.0, -0.25])
def test_undefined_or_negative_gross_returns_cannot_pass(weight):
    from factory.gross_diagnostics import JitterCapture, diagnostics_from_targets

    is_bars, oos_bars = market()
    weights = [
        pd.DataFrame(weight, index=bars["SPY"].index, columns=["SPY"])
        for bars in (is_bars, oos_bars)
    ]
    result = diagnostics_from_targets(
        is_bars, oos_bars, *weights, JitterCapture(is_bars, {}, "1day")
    )
    assert result["state"] == "complete"
    assert result["eval_3"]["passed"] is result["eval_4"]["passed"] is False
    assert result["eval_3"]["metrics"]["jitters"] == []
    assert result["eval_4"]["metrics"]["is_max_window_share"] is None
    assert result["eval_4"]["metrics"]["oos_max_window_share"] is None
    if weight == 0:
        assert result["eval_3"]["metrics"]["base_sharpe"] is None


def test_missing_historical_inputs_return_reason_without_error_text(tmp_path):
    from factory.gross_diagnostics import compute_diagnostics_file

    result = compute_diagnostics_file(tmp_path / "secret-do-not-export.py")
    assert result["state"] == "unavailable"
    assert result["eval_3"] is result["eval_4"] is None
    assert result["reason"]
    assert "secret-do-not-export" not in result["reason"]


@pytest.mark.parametrize("status", ["INACTIVE", "BUG_UNRESOLVED", "BLOCKED_DATA"])
def test_future_terminal_failures_persist_unavailable_diagnostic(tmp_path, status):
    from factory.agents.records import Records
    from factory.agents.test_worker import spec
    from factory.orchestrator import _row, _save_row

    with Records(tmp_path / "runs") as records:
        row = _row(spec(), "r_gross", "A")
        pending = _save_row(records, row)
        assert pending["gross_diagnostics"]["state"] == "pending"
        row["status"] = status
        saved = _save_row(records, row)
        assert saved["status"] == status
        assert saved["evals_passed"] == 0
        assert saved["gross_diagnostics"]["state"] == "unavailable"
        assert saved["gross_diagnostics"]["reason"]
        assert saved["gross_diagnostics"]["eval_3"] is None
        assert records.list("eval_results") == []


def test_typed_diagnostic_rejects_contradictory_signal_label(tmp_path, monkeypatch, valid_source):
    from factory.gross_diagnostics import unavailable_diagnostics
    from factory.record_models import GrossDiagnostics

    path, *_ = setup_evaluation(tmp_path, monkeypatch, valid_source)
    result = evaluation.evaluate_file(path).gross_diagnostics
    result["label"] = "no signal before costs"
    with pytest.raises(ValidationError):
        GrossDiagnostics.model_validate(result)
    result["label"] = "signal before costs"
    result["eval_4"]["passed"] = False
    with pytest.raises(ValidationError):
        GrossDiagnostics.model_validate(result)
    unavailable = unavailable_diagnostics("No inputs")
    unavailable["label"] = "signal before costs"
    with pytest.raises(ValidationError):
        GrossDiagnostics.model_validate(unavailable)


def test_historical_event_diagnostic_keeps_disclosures_causal(tmp_path, monkeypatch, five_bars):
    from factory import events, gross_diagnostics

    path = tmp_path / "event.py"
    path.write_text("""import pandas as pd
FREQUENCY = "1day"
UNIVERSE = ["SPY"]
PARAMS = {"weight": 0.25}
EXTRA = ["trades"]
def generate_signals(bars, params, extra=None):
    index = bars["SPY"].index
    trades = extra["trades"]
    eligible = trades[trades.transaction_date <= index[-1]]
    weight = params["weight"] if len(eligible) else 0
    return pd.DataFrame(weight, index=index, columns=UNIVERSE)
""")
    is_bars = {"SPY": five_bars["SPY"].iloc[:3]}
    oos_bars = {"SPY": five_bars["SPY"].iloc[3:]}
    loaded = []

    def load(*args, split, allow_empty_symbols):
        assert allow_empty_symbols is True
        loaded.append(split)
        return is_bars if split == "IS" else oos_bars

    extra = {
        "trades": pd.DataFrame(
            {
                "available_at": pd.to_datetime(["2024-06-05T13:30:00Z"], utc=True),
                "symbol": pd.Series(["SPY"], dtype="string"),
                "transaction_date": pd.to_datetime(["2000-01-01"], utc=True),
            }
        )
    }
    monkeypatch.setattr(gross_diagnostics, "load_bars", load)
    monkeypatch.setattr(events, "load_extra", lambda *a, **kw: extra)
    result = gross_diagnostics.compute_diagnostics_file(path)
    assert result["state"] == "complete", result
    assert loaded == ["IS", "OOS"]
    assert result["eval_3"]["metrics"]["base_sharpe"] is None
    assert result["eval_4"]["metrics"]["is_total_pnl"] == 0
    assert result["eval_4"]["metrics"]["oos_total_pnl"] == pytest.approx(-0.025)


def test_gross_accounting_does_not_mutate_captured_targets():
    from factory.gross_diagnostics import JitterCapture, diagnostics_from_targets

    is_bars, oos_bars = market()
    targets = [
        pd.DataFrame(0.25, index=bars["SPY"].index, columns=["SPY"]) for bars in (is_bars, oos_bars)
    ]
    before = [target.copy(deep=True) for target in targets]
    diagnostics_from_targets(is_bars, oos_bars, *targets, JitterCapture(is_bars, {}, "1day"))
    for actual, expected in zip(targets, before, strict=True):
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
