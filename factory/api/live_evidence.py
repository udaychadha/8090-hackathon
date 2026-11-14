"""Read-only recovery of live outcomes from an older runner's saved evidence.

Never execute a strategy, mutate records, or manufacture unretained measurements.
The exact result records supersede this explicitly labelled presentation fallback.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from factory.evals import config
from factory.evals.common import annualised_sharpe
from factory.evals.decay import decay_eval
from factory.evals.friction import break_even_bps
from factory.evals.sensitivity import sensitivity_verdict


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _decay(row):
    """Invert complete daily equity, then verify against independently saved Sharpes."""
    if row.get("frequency") != "1day":
        return None  # Intraday split days can straddle IS/OOS; daily equity is insufficient.
    equity, boundaries, activity = (
        row.get(k) or {} for k in ("equity", "equity_boundaries", "activity")
    )
    try:
        dates = pd.DatetimeIndex(equity["dates"])
        values = np.asarray(equity["net"], dtype=float)
        is_end = (
            pd.Timestamp(boundaries["is_end"]).tz_convert("America/New_York").date().isoformat()
        )
        oos_end = (
            pd.Timestamp(boundaries["oos_end"]).tz_convert("America/New_York").date().isoformat()
        )
        if (
            len(dates) != len(values)
            or len(dates) < 4
            or not dates.is_unique
            or not dates.is_monotonic_increasing
            or dates.hasnans
            or dates.tz is not None
            or not np.isfinite(values).all()
            or not (values > 0).all()
            or equity["is_end"] != is_end
            or equity["oos_end"] != oos_end
            or dates[-1].date().isoformat() != oos_end
        ):
            return None
        daily = pd.Series(values / np.concatenate(([1.0], values[:-1])) - 1, index=dates)
        periods = {"IS": daily.loc[:is_end], "OOS": daily.loc[daily.index > pd.Timestamp(is_end)]}
        for period, series in periods.items():
            saved = row["cost_sharpes"][period][f"{config.BASE_COST_BPS:g}"]
            measured = annualised_sharpe(series)
            if (
                len(series) != activity[period]["total_bars"]
                or len(series) < 2
                or not _finite(saved)
                or not _finite(measured)
                or not math.isclose(saved, measured, rel_tol=1e-9, abs_tol=1e-10)
            ):
                return None
        result = decay_eval(periods["IS"], periods["OOS"]).to_dict()
        # Strictly decline a boundary case rather than make a rounding-driven verdict.
        metrics = result["metrics"]
        guards = [
            metrics["is_sharpe"],
            metrics["oos_sharpe"],
            metrics["oos_sharpe"] - config.DECAY_MIN_RATIO * metrics["is_sharpe"],
            metrics["is_total_pnl"],
            metrics["oos_total_pnl"],
        ]
        guards += [
            v - config.CONCENTRATION_MAX_SHARE
            for k in ("is_max_window_share", "oos_max_window_share")
            if (v := metrics[k]) is not None
        ]
        if any(abs(value) < 1e-10 for value in guards):
            return None
        return result
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, OverflowError):
        return None


def recover_evaluations(row):
    """Return result + provenance for facts proved by retained active-run evidence."""
    if row.get("status") != "RUNNING":
        return {}
    evidence = {}
    if row.get("reached_eval_2") is True:
        evidence[1] = {
            "result": {"number": 1, "name": "lookahead", "passed": True, "metrics": {}},
            "details": [
                "Lookahead passed: the runner recorded entry into Eval 2.",
                "Recovered from the recorded milestone. Individual cut details have not been "
                "published by this older runner.",
            ],
        }
    grid = (row.get("cost_sharpes") or {}).get("IS") or {}
    expected = [f"{cost:g}" for cost in config.FRICTION_BPS_GRID]
    if all(key in grid and (grid[key] is None or _finite(grid[key])) for key in expected):
        numeric = {float(key): grid[key] for key in expected}
        base = numeric[config.BASE_COST_BPS]
        bps, note = break_even_bps(numeric, config.FRICTION_MIN_SHARPE)
        evidence[2] = {
            "result": {
                "number": 2,
                "name": "friction",
                "passed": base is not None and base >= config.FRICTION_MIN_SHARPE,
                "metrics": {
                    "sharpe_by_bps": {key: grid[key] for key in expected},
                    "min_sharpe": config.FRICTION_MIN_SHARPE,
                    "pass_bps": config.BASE_COST_BPS,
                    "break_even_bps": bps,
                    "break_even_note": note,
                },
            },
            "provenance": "Recovered from the saved IS cost grid; "
            "original detailed eval record is pending publication.",
        }
        if base is not None and base <= 0:
            evidence[3] = {
                "result": {
                    "number": 3,
                    "name": "sensitivity",
                    "passed": sensitivity_verdict(base, [])["passed"],
                    "metrics": {"base_sharpe": base, "cost_bps": config.BASE_COST_BPS},
                },
                "details": [
                    f"Base IS Sharpe at {config.BASE_COST_BPS:g} bps: {base:.3f}; "
                    "sensitivity requires a positive base.",
                    "Failure follows from the saved base Sharpe. Jitter measurements "
                    "have not been published; none are inferred.",
                ],
            }
    decay = _decay(row)
    if decay is not None:
        evidence[4] = {
            "result": decay,
            "provenance": "Recovered from complete saved daily equity; reconstructed IS/OOS "
            "Sharpes match the saved cost grid. No strategy rerun.",
        }
    return evidence
