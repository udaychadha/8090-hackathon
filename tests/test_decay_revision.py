import pandas as pd
import pytest

from factory.evals import decay


def test_negative_is_cannot_pass_sharpe_check_with_positive_oos():
    result = decay.decay_eval(pd.Series([-0.002, -0.001] * 30), pd.Series([0.002, 0.001] * 30))
    assert result.metrics["sharpe_ok"] is False
    assert result.metrics["oos_to_is_ratio"] is None
    assert not result.passed


@pytest.mark.parametrize("daily", [[-0.01, 0.01] * 10, [-0.02, 0.01] * 10])
def test_nonpositive_pnl_has_no_concentration_share(daily):
    result = decay.decay_eval(pd.Series(daily), pd.Series([0.002, 0.001] * 30))
    assert result.metrics["is_total_pnl"] <= 0
    assert result.metrics["is_max_window_share"] is None
    assert result.metrics["concentration_ok"] is False
    assert not result.passed


def test_positive_pnl_concentration_above_one_is_preserved():
    daily = pd.Series([0.01] * 5 + [-0.009] * 5)
    assert decay.max_window_share(daily, 5) == pytest.approx(10.0)


def test_recorded_metrics_rejudge_requires_positive_is_and_preserves_evidence():
    metrics = {
        "is_sharpe": -0.7,
        "oos_sharpe": 0.04,
        "is_max_window_share": 1.5,
        "oos_max_window_share": 4.7,
        "sharpe_ok": True,
        "concentration_ok": True,
    }
    result = decay.decay_from_metrics(metrics)
    assert not result.passed
    assert result.metrics["sharpe_ok"] is False
    assert result.metrics["is_max_window_share"] is None
    assert result.metrics["oos_max_window_share"] == 4.7
    assert "is_total_pnl" not in result.metrics  # sign is known, amount is not
    assert metrics["sharpe_ok"] is True  # original evidence is not mutated


@pytest.mark.parametrize("total", [0.0, -0.1])
def test_explicit_nonpositive_pnl_invalidates_recorded_share(total):
    result = decay.decay_from_metrics(
        {
            "is_sharpe": 1.0,
            "oos_sharpe": 1.0,
            "is_total_pnl": total,
            "oos_total_pnl": 0.2,
            "is_max_window_share": 1.5,
            "oos_max_window_share": 0.2,
        }
    )
    assert result.metrics["is_max_window_share"] is None
    assert result.metrics["concentration_ok"] is False
    assert not result.passed


@pytest.mark.parametrize("missing", ["is_sharpe", "oos_sharpe", "is_max_window_share"])
def test_missing_recorded_evidence_fails_closed(missing):
    metrics = {
        "is_sharpe": 1.0,
        "oos_sharpe": 0.5,
        "is_max_window_share": 0.3,
        "oos_max_window_share": 0.6,
    }
    del metrics[missing]
    assert not decay.decay_from_metrics(metrics).passed


def test_complete_legacy_metrics_pass_at_unchanged_boundaries():
    result = decay.decay_from_metrics(
        {
            "is_sharpe": 1.0,
            "oos_sharpe": 0.5,
            "is_max_window_share": 0.3,
            "oos_max_window_share": 0.6,
        }
    )
    assert result.passed


@pytest.mark.parametrize("value", [float("inf"), float("nan")])
def test_nonfinite_recorded_sharpe_fails_closed(value):
    result = decay.decay_from_metrics(
        {
            "is_sharpe": 1.0,
            "oos_sharpe": value,
            "is_max_window_share": 0.3,
            "oos_max_window_share": 0.3,
        }
    )
    assert not result.passed
