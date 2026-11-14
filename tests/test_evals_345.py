import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factory.evals import config
from factory.evals.decay import decay_eval, max_window_share
from factory.evals.deflated import (
    deflated_eval,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    moments,
)
from factory.evals.lookahead import LookaheadBiasError
from factory.evals.runner import evaluate, sandbox_runner
from factory.evals.sensitivity import (
    jitter_value,
    jittered_params,
    sensitivity_eval,
    sensitivity_verdict,
)

FIXTURES = Path(__file__).parent / "fixtures"


def sessions(count, start="2021-01-04"):
    return pd.date_range(start, periods=count, freq="B", tz="America/New_York")


def drift(count, mean=0.001, wiggle=0.0005, start="2021-01-04"):
    """Constant positive drift with a deterministic +/- wiggle so Sharpe is defined."""
    signs = np.where(np.arange(count) % 2 == 0, 1.0, -1.0)
    return pd.Series(mean + wiggle * signs, index=sessions(count, start))


def test_thresholds_are_the_agents_md_values():
    assert config.SENSITIVITY_JITTERS == (-0.20, -0.10, 0.10, 0.20)
    assert (config.SENSITIVITY_MAX_PARAMS, config.SENSITIVITY_MIN_RATIO) == (4, 0.5)
    assert config.DECAY_MIN_RATIO == 0.5
    assert (config.CONCENTRATION_WINDOW_DAYS, config.CONCENTRATION_MAX_SHARE) == (5, 0.60)
    assert (config.DSR_MIN, config.DSR_MIN_TRIALS) == (0.95, 3)


# ---- Eval 3


def test_jitter_values():
    assert [jitter_value(30, f) for f in (-0.2, -0.1, 0.1, 0.2)] == [24, 27, 33, 36]
    assert [jitter_value(3, f) for f in (-0.2, -0.1, 0.1, 0.2)] == [2, 2, 4, 4]  # min change 1
    assert jitter_value(25, 0.1) == 28  # 2.5 rounds half away from zero
    assert jitter_value(2.0, -0.2) == pytest.approx(1.6)


def test_jittered_params_one_at_a_time_numeric_only_max_four():
    params = {"a": 10, "flag": True, "b": 2.0, "name": "x", "c": 3, "zero": 0.0, "d": 5, "e": 7}
    jitters = jittered_params(params)
    assert {j["param"] for j in jitters} == {"a", "b", "c"}  # zero has no distinct jitter; d, e cut
    assert [j["value"] for j in jitters if j["param"] == "a"] == [8, 9, 11, 12]
    assert [j["value"] for j in jitters if j["param"] == "c"] == [2, 4]
    for jitter in jitters:
        changed = {k for k in params if jitter["params"][k] != params[k]}
        assert changed == {jitter["param"]}


def test_sensitivity_verdict_known_answers():
    assert sensitivity_verdict(2.0, [1.5, 1.0, 1.9])["passed"]  # worst is exactly 50%
    assert not sensitivity_verdict(2.0, [1.5, 0.99])["passed"]
    assert not sensitivity_verdict(2.0, [1.5, None])["passed"]  # a broken jitter fails
    assert not sensitivity_verdict(-1.0, [-0.4, -0.3])["passed"]  # negative base cannot pass
    assert not sensitivity_verdict(None, [1.0])["passed"]
    assert sensitivity_verdict(1.0, [])["passed"] and not sensitivity_verdict(0.0, [])["passed"]


def trending_bars(days=300):
    from factory.data import expected_index

    index = expected_index("1day", "2020-01-02", "2024-12-31")[:days]
    steps = np.where(np.arange(days) % 2 == 0, 0.004, -0.002)
    close = 100 * np.exp(np.cumsum(steps))
    return {
        "SPY": pd.DataFrame(
            {"open": close, "high": close, "low": close, "close": close, "volume": 1.0},
            index=index,
        )
    }


def test_sensitivity_eval_runs_each_jitter_and_fails_on_a_cliff():
    bars = trending_bars()

    def smooth(bars, params):
        weight = (params or {"weight": 0.5})["weight"]
        return pd.DataFrame({"SPY": weight}, index=bars["SPY"].index)

    result = sensitivity_eval(smooth, bars, {"weight": 0.5}, "1day", base_sharpe=10.0)
    assert len(result.metrics["jitters"]) == 4
    # Constant long: Sharpe does not depend on size, so the base equals every jitter.
    sharpes = [row["sharpe"] for row in result.metrics["jitters"]]
    assert max(sharpes) - min(sharpes) < 0.05
    assert sensitivity_eval(smooth, bars, {"weight": 0.5}, "1day", sharpes[0]).passed

    def cliff(bars, params):  # only works at exactly lookback == 10
        side = 1.0 if params["lookback"] == 10 else -1.0
        return pd.DataFrame({"SPY": side}, index=bars["SPY"].index)

    result = sensitivity_eval(cliff, bars, {"lookback": 10}, "1day", sharpes[0])
    assert not result.passed and result.metrics["worst_sharpe"] < 0


# ---- Eval 4


def test_constant_positive_drift_passes_decay():
    result = decay_eval(drift(600), drift(200, start="2023-06-01"))
    assert result.passed
    expected = 0.001 / drift(600).std(ddof=1) * math.sqrt(252)
    assert result.metrics["is_sharpe"] == pytest.approx(expected)
    assert result.metrics["oos_max_window_share"] == pytest.approx(0.0055 / 0.2, rel=1e-9)


def test_single_spike_pnl_fails_decay():
    spike = pd.Series(0.0, index=sessions(200, "2023-06-01"))
    spike.iloc[120] = 0.10
    spike.iloc[::7] -= 0.0001  # a little noise; almost all PnL is the one day
    result = decay_eval(drift(600), spike)
    assert result.metrics["oos_max_window_share"] > 0.6
    assert not result.metrics["concentration_ok"] and not result.passed


def test_decay_sharpe_rules():
    assert not decay_eval(drift(600), -drift(200, start="2023-06-01")).passed  # OOS negative
    weak = drift(200, mean=0.0001, start="2023-06-01")  # positive but < 50% of IS Sharpe
    result = decay_eval(drift(600), weak)
    assert 0 < result.metrics["oos_to_is_ratio"] < 0.5 and not result.passed
    assert result.metrics["concentration_ok"]
    flat = pd.Series(0.001, index=sessions(200, "2023-06-01"))  # zero variance: undefined
    assert not decay_eval(drift(600), flat).passed


def test_max_window_share_known_answers():
    series = pd.Series([0.01] * 10, index=sessions(10))
    assert max_window_share(series, 5) == pytest.approx(0.5)
    series.iloc[3] = 0.11  # window sum 0.15 of total 0.20
    assert max_window_share(series, 5) == pytest.approx(0.75)
    assert max_window_share(-series, 5) is None
    assert max_window_share(series.iloc[:4], 5) == 1.0


# ---- Eval 5


def test_dsr_reproduces_the_papers_numerical_example():
    """Bailey & López de Prado (2014), "A numerical example": N=100, V=1/2 annualised,
    T=1250, skew=-3, kurtosis=10, annualised SR 2.5 with 250 observations per year."""
    sr0 = expected_max_sharpe(1 / (2 * 250), 100)
    assert sr0 == pytest.approx(0.1132, abs=5e-5)
    sharpe = 2.5 / math.sqrt(250)
    assert deflated_sharpe_ratio(sharpe, sr0, 1250, -3, 10) == pytest.approx(0.9004, abs=5e-5)
    # "after running only N=46 independent trials ... DSR would have been 0.9505"
    sr0_46 = expected_max_sharpe(1 / (2 * 250), 46)
    assert deflated_sharpe_ratio(sharpe, sr0_46, 1250, -3, 10) == pytest.approx(0.9505, abs=5e-4)
    # "Normal returns (skew 0, kurtosis 3), DSR = 0.9505 after N=88 independent trials"
    sr0_88 = expected_max_sharpe(1 / (2 * 250), 88)
    assert deflated_sharpe_ratio(sharpe, sr0_88, 1250, 0, 3) == pytest.approx(0.9505, abs=5e-4)


def test_dsr_decreases_in_n_and_sr0_increases():
    sharpe, previous_dsr, previous_sr0 = 0.12, 1.0, 0.0
    for trials in (3, 5, 10, 30, 100, 1000):
        sr0 = expected_max_sharpe(0.002, trials)
        dsr = deflated_sharpe_ratio(sharpe, sr0, 500, -0.5, 5)
        assert sr0 > previous_sr0 and dsr < previous_dsr
        previous_dsr, previous_sr0 = dsr, sr0


def test_moments_are_population_skew_and_raw_kurtosis():
    skew, kurtosis = moments(pd.Series([-1.0, 1.0] * 50))
    assert skew == pytest.approx(0) and kurtosis == pytest.approx(1)
    rng = np.random.default_rng(0)
    skew, kurtosis = moments(pd.Series(rng.normal(size=200_000)))
    assert skew == pytest.approx(0, abs=0.03) and kurtosis == pytest.approx(3, abs=0.06)


def test_deflated_eval_uses_trial_count_floor_and_falls_with_more_trials():
    oos = drift(300, mean=0.001, wiggle=0.004)
    few = deflated_eval(oos, [0.05, 0.10])
    assert few.metrics["n_trials"] == 3
    spread = [0.05, 0.10] * 10  # similar spread, many more trials
    many = deflated_eval(oos, spread)
    assert many.metrics["n_trials"] == 20
    assert many.metrics["sr0"] > 0 and many.metrics["dsr"] < 1
    same_v = float(np.var([0.05, 0.10], ddof=1))
    assert (
        deflated_sharpe_ratio(
            few.metrics["daily_sharpe"],
            expected_max_sharpe(same_v, 20),
            300,
            few.metrics["skew"],
            few.metrics["kurtosis"],
        )
        < few.metrics["dsr"]
    )


def test_deflated_eval_fails_closed_when_not_computable():
    oos = drift(300)
    alone = deflated_eval(oos, [0.1])
    assert not alone.passed and "at least 2" in alone.metrics["reason"]
    flat = deflated_eval(pd.Series(0.001, index=sessions(50)), [0.1, 0.2, 0.3])
    assert not flat.passed and flat.metrics["reason"] == "Sharpe undefined"


def test_deflated_eval_pass_and_fail_known_cases():
    strong = drift(500, mean=0.002, wiggle=0.004)  # per-day Sharpe about 0.5
    assert deflated_eval(strong, [0.01, 0.02, 0.03]).passed
    weak = drift(500, mean=0.0001, wiggle=0.004)
    assert not deflated_eval(weak, [0.01, 0.02, 0.03]).passed


# ---- Full pass through the sandbox


def split_bars(symbols, days=500, seed=3):
    rng = np.random.default_rng(seed)
    from factory.data import expected_index

    index = expected_index("1day", "2020-01-02", "2024-12-31")[:days]
    bars = {}
    for symbol in symbols:
        close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.008, days)))
        bars[symbol] = pd.DataFrame(
            {"open": close, "high": close, "low": close, "close": close, "volume": 1.0},
            index=index,
        )
    cut = int(days * 0.75)
    return (
        {s: f.iloc[:cut] for s, f in bars.items()},
        {s: f.iloc[cut:] for s, f in bars.items()},
    )


def test_full_pass_records_all_five_evals_and_first_failure_status():
    is_bars, oos_bars = split_bars(["SPY", "QQQ", "TLT", "GLD"])
    report = evaluate(
        sandbox_runner(FIXTURES / "clean.py"),
        {"lookback": 126, "vol_window": 20},
        "1day",
        is_bars,
        oos_bars,
        trial_sharpes=[0.01, 0.05, 0.03],
    )
    assert sorted(report.results) == [1, 2, 3, 4, 5]
    assert report.results[1].passed
    failed = [number for number in sorted(report.results) if not report.results[number].passed]
    assert report.status == (f"FAILED_EVAL_{failed[0]}" if failed else "VERIFIED")
    assert len(report.oos_daily_returns) == len(oos_bars["SPY"])
    assert len(report.results[3].metrics["jitters"]) == 8
    assert set(report.seconds) == {"eval_1", "eval_2", "eval_3", "eval_4", "eval_5", "total"}
    # OOS weights are warm: the trend signal is live from the first OOS bar.
    assert report.oos_daily_returns.iloc[:5].abs().sum() > 0


def test_full_pass_raises_lookahead_for_rigged():
    is_bars, oos_bars = split_bars(["SPY"])
    with pytest.raises(LookaheadBiasError):
        evaluate(
            sandbox_runner(FIXTURES / "rigged.py"),
            {"period": 2, "miss_weight": 0.5},
            "1day",
            is_bars,
            oos_bars,
        )
