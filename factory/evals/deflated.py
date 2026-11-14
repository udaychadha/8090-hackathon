"""Eval 5 — Deflated Sharpe Ratio.

Bailey & López de Prado (2014), "The Deflated Sharpe Ratio: Correcting for
Selection Bias, Backtest Overfitting and Non-Normality", checked against the
paper text:

    Eq. 1 / 2:  SR0 = sqrt(V[{SR_n}]) * ((1 - g) Zinv[1 - 1/N] + g Zinv[1 - 1/(N e)])
    Eq. 2:      DSR = Z[ (SR - SR0) sqrt(T - 1) / sqrt(1 - g3 SR + (g4 - 1)/4 SR^2) ]

SR is the selected strategy's estimated, non-annualised Sharpe (it, not SR0,
appears in the denominator); T is the sample length; g3, g4 are the skewness
and (non-excess, Normal = 3) kurtosis of its returns; V is the variance of the
trials' Sharpe estimates in the same per-period units; N is the number of
independent trials; g is the Euler–Mascheroni constant.

Caveats the paper states: Eq. 1 is an approximation for N >> 1 (we use it down
to N = 3), and N means *independent* trials (variants of one paper are
correlated, so counting them all is conservative).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from statistics import NormalDist

import numpy as np
import pandas as pd

from factory.evals import config
from factory.evals.common import EvalResult, daily_sharpe

EULER_MASCHERONI = 0.5772156649015329
NORMAL = NormalDist()


def expected_max_sharpe(variance: float, trials: int) -> float:
    """SR0: expected maximum of `trials` Sharpe estimates under a true Sharpe of zero."""
    if trials < 2 or not math.isfinite(variance) or variance < 0:
        raise ValueError("Need at least 2 trials and a finite, nonnegative variance")
    return math.sqrt(variance) * (
        (1 - EULER_MASCHERONI) * NORMAL.inv_cdf(1 - 1 / trials)
        + EULER_MASCHERONI * NORMAL.inv_cdf(1 - 1 / (trials * math.e))
    )


def deflated_sharpe_ratio(
    sharpe: float, benchmark: float, observations: int, skew: float, kurtosis: float
) -> float:
    """PSR at threshold `benchmark` (= SR0). Sharpe values are per period, kurtosis non-excess."""
    spread = 1 - skew * sharpe + (kurtosis - 1) / 4 * sharpe**2
    if observations < 2 or not spread > 0:
        raise ValueError("DSR undefined: need T >= 2 and a positive variance term")
    return NORMAL.cdf((sharpe - benchmark) * math.sqrt(observations - 1) / math.sqrt(spread))


def moments(daily: pd.Series) -> tuple[float, float]:
    """Population skewness and non-excess kurtosis."""
    values = daily.to_numpy(dtype=float)
    centred = values - values.mean()
    variance = float(np.mean(centred**2))
    return float(np.mean(centred**3) / variance**1.5), float(np.mean(centred**4) / variance**2)


def deflated_from_metrics(
    recorded: Mapping,
    trial_sharpes: Sequence[float | None],
    *,
    trial_variant_ids: Sequence[str] | None = None,
) -> EvalResult:
    """Judge retained sufficient statistics against one explicit trial population.

    Missing trial Sharpes still count toward N and fail the entire adjustment
    closed. N retains the configured floor; variance uses every selected trial,
    never a smaller complete-case subset. No returns or backtests are required.
    """
    trials = list(trial_sharpes)
    if trial_variant_ids is not None and (
        len(trial_variant_ids) != len(trials) or len(set(trial_variant_ids)) != len(trials)
    ):
        raise ValueError("Trial identities must be unique and match the trial values")
    finite = [v for v in trials if v is not None and math.isfinite(v)]
    metrics = dict(recorded)
    metrics.pop("reason", None)
    metrics.update(
        n_trials=max(config.DSR_MIN_TRIALS, len(trials)),
        trial_count=len(trials),
        trial_sharpes_supplied=len(finite),
        trial_scope="all_runs" if trial_variant_ids is not None else "supplied",
        min=config.DSR_MIN,
        trial_variance=None,
        sr0=None,
        dsr=None,
    )
    if trial_variant_ids is not None:
        metrics["trial_variant_ids"] = list(trial_variant_ids)
    else:
        metrics.pop("trial_variant_ids", None)

    def failed(reason):
        return EvalResult(5, "deflated_sharpe", False, {**metrics, "reason": reason})

    if len(finite) != len(trials):
        return failed("Incomplete trial accounting: undefined trial Sharpe in selected population")
    if len(trials) < 2:
        return failed("variance across trials needs at least 2 trial Sharpes")
    variance = float(np.var(trials, ddof=1))
    if not math.isfinite(variance):
        return failed("Variance across recorded trial Sharpes is undefined")
    benchmark = expected_max_sharpe(variance, metrics["n_trials"])
    metrics.update(trial_variance=variance, sr0=benchmark)
    sharpe = metrics.get("daily_sharpe")
    if sharpe is None or not math.isfinite(sharpe):
        return failed("Sharpe undefined")
    observations = metrics.get("observations")
    skew, kurtosis = metrics.get("skew"), metrics.get("kurtosis")
    if (
        not isinstance(observations, int)
        or observations < 2
        or any(v is None or not math.isfinite(v) for v in (skew, kurtosis))
    ):
        return failed("Incomplete recorded return moments or observation count")
    try:
        dsr = deflated_sharpe_ratio(sharpe, benchmark, observations, skew, kurtosis)
    except (ValueError, OverflowError) as error:
        return failed(str(error))
    metrics["dsr"] = dsr
    return EvalResult(5, "deflated_sharpe", dsr >= config.DSR_MIN, metrics)


def deflated_eval(
    oos_daily: pd.Series,
    trial_sharpes: Sequence[float | None],
    *,
    trial_variant_ids: Sequence[str] | None = None,
) -> EvalResult:
    """Score OOS returns using the selected global population's per-day Sharpes.

    The orchestrator supplies all nonvoid, noncontrol variants across retained
    runs that reached Eval 2, including this candidate. Jitters are not trials.
    """
    sharpe = daily_sharpe(oos_daily)
    metrics = {"daily_sharpe": sharpe, "observations": len(oos_daily)}
    if sharpe is not None:
        skew, kurtosis = moments(oos_daily)
        metrics.update(skew=skew, kurtosis=kurtosis)
    return deflated_from_metrics(metrics, trial_sharpes, trial_variant_ids=trial_variant_ids)
