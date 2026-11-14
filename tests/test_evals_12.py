from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factory.contract import read_strategy
from factory.data import load_bars
from factory.evals import config
from factory.evals.friction import break_even_bps, friction_eval
from factory.evals.lookahead import LookaheadBiasError, first_difference, lookahead_eval
from factory.evals.runner import sandbox_runner

FIXTURES = Path(__file__).parent / "fixtures"
DATA = Path(__file__).parent.parent / "data"
needs_data = pytest.mark.skipif(
    not (DATA / "1day" / "SPY.parquet").exists(), reason="daily tier with ETFs not ingested"
)


def synthetic_bars(symbols, days=400, seed=7, vol=0.003):
    rng = np.random.default_rng(seed)
    index = pd.date_range("2020-01-02T05:00:00Z", periods=days, freq="B", name="timestamp")
    bars = {}
    for symbol in symbols:
        close = 100 * np.exp(np.cumsum(rng.normal(0, vol, days)))
        bars[symbol] = pd.DataFrame(
            {"open": close, "high": close, "low": close, "close": close, "volume": 1000.0},
            index=index,
        )
    return bars


def test_thresholds_are_the_agents_md_values():
    assert config.LOOKAHEAD_CUT_FRACTIONS == (0.30, 0.45, 0.60, 0.75, 0.90)
    assert config.LOOKAHEAD_TOLERANCE == 1e-9
    assert config.FRICTION_BPS_GRID == (0.0, 2.0, 5.0, 10.0)
    assert (config.FRICTION_MIN_SHARPE, config.BASE_COST_BPS) == (0.5, 5.0)


def test_first_difference_treats_nan_as_equal_and_respects_tolerance():
    index = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")
    full = pd.DataFrame({"A": [0.1, np.nan, 0.3], "B": [0.0, 0.2, 0.5]}, index=index)
    same = full.iloc[:2].copy()
    same.iloc[0, 0] += 5e-10
    assert first_difference(full, same, 1e-9) is None
    changed = full.iloc[:2].copy()
    changed.iloc[1, 1] = 0.25
    stamp, symbol, was, now = first_difference(full, changed, 1e-9)
    assert (stamp, symbol, was, now) == (index[1], "B", 0.2, 0.25)
    one_nan = full.iloc[:2].copy()
    one_nan.iloc[0, 0] = np.nan
    assert first_difference(full, one_nan, 1e-9)[:2] == (index[0], "A")


def test_rigged_fails_lookahead_naming_timestamp_and_symbol():
    bars = synthetic_bars(["SPY"])
    with pytest.raises(LookaheadBiasError) as error:
        lookahead_eval(sandbox_runner(FIXTURES / "rigged.py"), bars)
    index = bars["SPY"].index
    # The first cut keeps 30% of bars; the leak shows on the last bar kept.
    assert error.value.timestamp == index[int(len(index) * 0.30) - 1]
    assert error.value.symbol == "SPY"
    assert error.value.cut_fraction == 0.30
    assert error.value.timestamp.isoformat() in str(error.value) and "SPY" in str(error.value)


def test_leak_removed_passes_lookahead_then_fails_friction():
    bars = synthetic_bars(["SPY"])
    result, weights = lookahead_eval(sandbox_runner(FIXTURES / "rigged_fixed.py"), bars)
    assert result.passed and len(result.metrics["cuts"]) == 5
    friction = friction_eval(bars, weights, "1day")
    assert not friction.passed
    sharpes = friction.metrics["sharpe_by_bps"]
    assert sharpes["0"] > sharpes["2"] > sharpes["5"] > sharpes["10"]
    assert friction.metrics["average_daily_turnover"] == pytest.approx(2.0, abs=0.01)


def test_clean_passes_lookahead_on_synthetic_bars():
    bars = synthetic_bars(read_strategy(FIXTURES / "clean.py").universe)
    result, weights = lookahead_eval(sandbox_runner(FIXTURES / "clean.py"), bars)
    assert result.passed
    assert weights.abs().sum(axis=1).max() <= 1 + 1e-12


def test_break_even_interpolation_and_edges():
    bps, note = break_even_bps({0.0: 1.5, 2.0: 1.0, 5.0: 0.25, 10.0: -1.0}, 0.5)
    assert bps == pytest.approx(2 + (1.0 - 0.5) / (1.0 - 0.25) * 3) and note == "interpolated"
    assert break_even_bps({0.0: 0.4, 2.0: 0.1, 5.0: 0.0, 10.0: -1.0}, 0.5)[0] is None
    assert break_even_bps({0.0: 3.0, 2.0: 2.0, 5.0: 1.0, 10.0: 0.6}, 0.5) == (
        None,
        "above 0.5 through 10 bps",
    )
    assert break_even_bps({0.0: 1.0, 2.0: None, 5.0: 0.0, 10.0: -1.0}, 0.5)[0] is None


def test_friction_passes_a_cheap_steady_earner():
    bars = synthetic_bars(["SPY"], vol=0.0)
    index = bars["SPY"].index
    steps = np.where(np.arange(len(index)) % 2 == 0, 0.004, -0.002)  # drifts up, with noise
    close = 100 * np.exp(np.cumsum(steps))
    for field in ("open", "high", "low", "close"):
        bars["SPY"][field] = close
    weights = pd.DataFrame({"SPY": 1.0}, index=index)
    result = friction_eval(bars, weights, "1day")
    assert result.passed and result.metrics["break_even_note"] == "above 0.5 through 10 bps"


def etf_daily_is(symbols):
    return load_bars(DATA, "1day", list(symbols), split="IS")


@needs_data
def test_real_data_fixture_acceptance():
    """WO-03 acceptance on real IS data (daily tier, 2016 onward)."""
    rigged = etf_daily_is(["SPY"])
    with pytest.raises(LookaheadBiasError) as error:
        lookahead_eval(sandbox_runner(FIXTURES / "rigged.py"), rigged)
    assert error.value.symbol == "SPY" and error.value.timestamp in rigged["SPY"].index
    result, weights = lookahead_eval(sandbox_runner(FIXTURES / "rigged_fixed.py"), rigged)
    assert result.passed
    assert not friction_eval(rigged, weights, "1day").passed
    bars = etf_daily_is(read_strategy(FIXTURES / "clean.py").universe)
    result, weights = lookahead_eval(sandbox_runner(FIXTURES / "clean.py"), bars)
    assert result.passed
    # clean's Eval 2 outcome is recorded in work-orders/WO-03.md, not asserted here.
    friction_eval(bars, weights, "1day")
