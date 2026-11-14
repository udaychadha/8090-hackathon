"""Global-trial DSR rejudgment uses retained sufficient statistics, never backtests."""

import copy

import numpy as np
import pandas as pd
import pytest

from factory.evals import deflated


def test_undefined_trial_is_counted_and_fails_closed():
    daily = pd.Series([0.01, -0.002, 0.005, 0.003] * 40)
    result = deflated.deflated_eval(daily, [0.1, 0.2, None, 0.3])
    assert result.metrics["n_trials"] == 4
    assert result.metrics["trial_count"] == 4
    assert result.metrics["trial_sharpes_supplied"] == 3
    assert not result.passed
    assert result.metrics.get("dsr") is None


def test_recorded_statistics_reproduce_dsr_for_same_complete_population():
    daily = pd.Series([0.01, -0.002, 0.005, 0.003] * 40)
    original = deflated.deflated_eval(daily, [0.1, 0.2, 0.3])
    saved = copy.deepcopy(original.metrics)
    result = deflated.deflated_from_metrics(saved, [0.1, 0.2, 0.3])
    assert result.passed == original.passed
    assert result.metrics == original.metrics
    assert saved == original.metrics


def test_rejudge_replaces_sibling_variance_with_full_population_variance():
    metrics = {
        "daily_sharpe": 0.04,
        "observations": 400,
        "skew": -0.1,
        "kurtosis": 3.5,
        "dsr": 1.0,
        "trial_variance": 0.0,
        "reason": "old failure",
    }
    trials = [0.05, 0.06, 0.07, -0.2, 0.3, -0.15]
    ids = [f"r_{i}_A" for i in range(len(trials))]
    result = deflated.deflated_from_metrics(metrics, trials, trial_variant_ids=ids)
    variance = float(np.var(trials, ddof=1))
    benchmark = deflated.expected_max_sharpe(variance, 6)
    assert result.metrics["trial_variance"] == pytest.approx(variance)
    assert result.metrics["sr0"] == pytest.approx(benchmark)
    assert result.metrics["dsr"] == pytest.approx(
        deflated.deflated_sharpe_ratio(0.04, benchmark, 400, -0.1, 3.5)
    )
    assert result.metrics["trial_variant_ids"] == ids
    assert result.metrics["trial_scope"] == "all_runs"
    assert "reason" not in result.metrics
    assert metrics["reason"] == "old failure"


def test_missing_recorded_moments_never_reuse_a_stale_pass():
    result = deflated.deflated_from_metrics(
        {"daily_sharpe": 0.2, "observations": 300, "dsr": 1.0}, [0.1, 0.2, 0.3]
    )
    assert not result.passed
    assert result.metrics["dsr"] is None
    assert "recorded" in result.metrics["reason"]


def test_cohort_identity_must_match_values_and_be_unique():
    with pytest.raises(ValueError, match="identit"):
        deflated.deflated_from_metrics({}, [0.1, 0.2], trial_variant_ids=["same", "same"])
