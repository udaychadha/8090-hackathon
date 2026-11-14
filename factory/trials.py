"""Deterministic global trial identity and daily Sharpe accounting."""

from __future__ import annotations

import math
from collections.abc import Mapping

from factory.agents.records import Records


def trial_cohort(
    records: Records, current: Mapping[str, float | None] | None = None
) -> tuple[list[str], list[float | None]]:
    """Return sorted unique trial IDs and aligned Sharpes, retaining missing values.

    Current reports replace the same retained trial's value, never its identity.
    Distinct trials with identical Sharpes remain distinct observations.
    """
    current = current or {}
    evaluations = {}
    for result in records.list("eval_results"):
        evaluations.setdefault((result["run_id"], result["variant"]), {})[result["number"]] = result
    ids, sharpes = [], []
    for variant in records.trial_variants():
        identifier = variant["variant_id"]
        ids.append(identifier)
        if identifier in current:
            sharpes.append(_finite(current[identifier]))
            continue
        results = {e["number"]: e for e in variant.get("evals", [])}
        standalone = evaluations.get((variant["run_id"], variant["variant"]), {})
        if any(
            any(
                results[n].get(key) != result.get(key)
                for key in ("number", "name", "passed", "metrics")
            )
            for n, result in standalone.items()
            if n in results
        ):
            sharpes.append(None)
            continue
        results.update(standalone)
        dsr_metrics = results.get(5, {}).get("metrics", {})
        decay_metrics = results.get(4, {}).get("metrics", {})
        if "daily_sharpe" in dsr_metrics:
            value = _finite(dsr_metrics["daily_sharpe"])
        else:
            annual = _finite(decay_metrics.get("oos_sharpe", variant.get("verified_sharpe")))
            value = annual / math.sqrt(252) if annual is not None else None
        sharpes.append(value)
    return ids, sharpes


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None
