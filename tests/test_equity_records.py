"""Chart accounting agrees with the real eval harness for daily and intraday splits."""

import numpy as np
import pandas as pd
import pytest

from factory import evaluation
from factory.agents.test_worker import CLEAN
from factory.engine import backtest, daily_compound
from factory.evals import config


@pytest.mark.parametrize("frequency", ["1day", "1min"])
def test_recorded_equity_matches_evaluated_slices(tmp_path, monkeypatch, frequency):
    if frequency == "1day":
        index = pd.date_range("2020-01-02 16:00", periods=250, freq="B", tz="UTC")
        cut = 150
    else:
        sessions = pd.date_range("2020-01-02 14:30", periods=25, freq="B", tz="UTC")
        chunks = [pd.date_range(day, periods=20, freq="min") for day in sessions]
        index = chunks[0].append(chunks[1:])
        cut = 251  # Deliberately split one session between IS and OOS.
    close = 100 * np.cumprod(1 + 0.001 + 0.002 * np.sin(np.arange(len(index))))
    frame = pd.DataFrame(
        {name: close for name in ("open", "high", "low", "close", "volume")}, index=index
    )
    is_bars, oos_bars = {"SPY": frame.iloc[:cut]}, {"SPY": frame.iloc[cut:]}
    splits, calls = [], []

    def load(*args, split):
        splits.append(split)
        assert split in {"IS", "OOS"}
        return is_bars if split == "IS" else oos_bars

    def run(bars, params=None):
        calls.append((len(bars["SPY"]), params))
        return pd.DataFrame(
            (params or {"weight": 0.25})["weight"], index=bars["SPY"].index, columns=["SPY"]
        )

    path = tmp_path / "strategy.py"
    path.write_text(CLEAN.replace('"1day"', f'"{frequency}"'))
    monkeypatch.setattr(evaluation, "load_bars", load)
    monkeypatch.setattr(evaluation, "sandbox_runner", lambda *a, **kw: run)
    result = evaluation.evaluate_file(path)
    assert result.artifact_error is None
    assert set(result.report.results) == {1, 2, 3, 4, 5}
    assert splits == ["IS", "OOS"]
    assert len(calls) == 11  # 6 lookahead, 4 jitters, 1 warmed OOS. No chart rerun.
    bases = [
        backtest(
            bars,
            pd.DataFrame(0.25, index=bars["SPY"].index, columns=["SPY"]),
            frequency=frequency,
            round_trip_bps=config.BASE_COST_BPS,
        )
        for bars in (is_bars, oos_bars)
    ]
    pd.testing.assert_series_equal(bases[1].daily_returns, result.report.oos_daily_returns)
    for label, field in (("gross", "gross_bar_returns"), ("net", "net_bar_returns")):
        expected = (1 + daily_compound(pd.concat([getattr(b, field) for b in bases]))).cumprod()
        np.testing.assert_allclose(result.equity[label], expected)
    assert len(set(result.equity["dates"])) == len(result.equity["dates"])
    assert result.equity["gross"][-1] > result.equity["net"][-1]
    assert result.activity["IS"]["active_bars"] == cut - 1
    assert result.activity["OOS"]["active_bars"] == len(index) - cut - 1
    assert result.boundaries["is_end"] == index[cut - 1].isoformat()
    assert result.boundaries["oos_end"] == index[-1].isoformat()
    assert result.equity["is_end"] == str(index[cut - 1].tz_convert("America/New_York").date())


def test_artifact_failure_preserves_the_valid_trial(tmp_path, monkeypatch):
    # A recording problem must not discard already-computed trial statistics.
    from factory.agents.test_worker import bars
    from factory.evals.common import EvalResult
    from factory.evals.runner import EvalReport

    report = EvalReport({1: EvalResult(1, "lookahead", True, {})}, {}, pd.Series([0.01]), 0.5)
    path = tmp_path / "strategy.py"
    path.write_text(CLEAN)
    monkeypatch.setattr(evaluation, "load_bars", lambda *a, **kw: bars())
    monkeypatch.setattr(evaluation, "evaluate", lambda *a: report)
    result = evaluation.evaluate_file(path)
    assert result.report is report
    assert result.equity is None and result.artifact_error
