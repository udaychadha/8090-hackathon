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
from collections.abc import Sequence
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


def deflated_eval(oos_daily: pd.Series, trial_sharpes: Sequence[float]) -> EvalResult:
    """`trial_sharpes`: per-day OOS Sharpes (base cost) of every variant that reached
    Eval 2 in this factory run, this one included. Jitters are not trials.

    N = max(DSR_MIN_TRIALS, number of trials); V = sample variance of the trial
    Sharpes. If V or the DSR cannot be computed the eval fails; it never passes
    by default.
    """
    trials = [float(value) for value in trial_sharpes if value is not None]
    count = max(config.DSR_MIN_TRIALS, len(trials))
    metrics: dict = {
        "n_trials": count,
        "trial_sharpes_supplied": len(trials),
        "min": config.DSR_MIN,
    }
    sharpe = daily_sharpe(oos_daily)
    metrics.update(daily_sharpe=sharpe, observations=len(oos_daily))
    if sharpe is None:
        return EvalResult(5, "deflated_sharpe", False, {**metrics, "reason": "Sharpe undefined"})
    if len(trials) < 2:
        return EvalResult(
            5,
            "deflated_sharpe",
            False,
            {**metrics, "reason": "variance across trials needs at least 2 trial Sharpes"},
        )
    variance = float(np.var(trials, ddof=1))
    skew, kurtosis = moments(oos_daily)
    benchmark = expected_max_sharpe(variance, count)
    metrics.update(trial_variance=variance, sr0=benchmark, skew=skew, kurtosis=kurtosis)
    try:
        dsr = deflated_sharpe_ratio(sharpe, benchmark, len(oos_daily), skew, kurtosis)
    except ValueError as error:
        return EvalResult(5, "deflated_sharpe", False, {**metrics, "reason": str(error)})
    return EvalResult(5, "deflated_sharpe", dsr >= config.DSR_MIN, {**metrics, "dsr": dsr})
