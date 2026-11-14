"""Run the two frozen owner specifications in order; never revise them from results."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

from factory.agents.records import Records
from factory.contract import StrategySpec
from factory.evals.runner import with_deflated
from factory.evaluation import evaluate_file
from factory.orchestrator import _finish, _row, _save_row, run_spec
from factory.trials import trial_cohort

STATE = Path("report/wo12-runs.json")


def state():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(value):
    STATE.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def control():
    """One explicit non-trial, deterministic SPY control on identical tier splits."""
    started = time.perf_counter()
    run_id = "r_" + uuid.uuid4().hex[:12]
    spec = StrategySpec(
        paper_id="congress_spy_control",
        title="Buy-and-hold SPY control",
        category="control",
        hypothesis="Fixed buy-and-hold benchmark; not a research trial.",
        universe=["SPY"],
        frequency="1day",
        signal_rules=["Hold SPY at target weight one."],
        claimed_metrics={},
        ambiguities=[],
        test_type="original",
        source_kind="described",
    )
    code = """import pandas as pd
FREQUENCY = "1day"
UNIVERSE = ["SPY"]
PARAMS = {}
def generate_signals(bars, params):
    return pd.DataFrame(1, index=bars["SPY"].index, columns=UNIVERSE)
"""
    path = Path("strategies") / spec.paper_id / run_id / "A.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code)
    with Records("runs") as records:
        source = records.put(
            "sources",
            spec.paper_id,
            run_id,
            {
                "source_id": spec.paper_id,
                "title": spec.title,
                "source_kind": "described",
                "spec": spec.model_dump(),
                "provenance": {},
            },
        )
        summary = records.put(
            "runs",
            run_id,
            run_id,
            {
                "status": "RUNNING",
                "source": source,
                "is_control": True,
                "variants": [],
                "data_needs": [],
            },
        )
        row = _row(spec, run_id, "A")
        row.update(is_control=True, code=code, params={})
        _save_row(records, row)
        records.event(
            run_id, "worker", "passed", "Fixed deterministic buy-and-hold control", variant="A"
        )
        evaluation = evaluate_file(path)
        ids, sharpes = trial_cohort(records)
        report = with_deflated(evaluation.report, sharpes, trial_variant_ids=ids)
        row.update(
            status=report.status,
            eval_eligible=True,
            reached_eval_2=True,
            evals_passed=sum(item.passed for item in report.results.values()),
            evals=[item.to_dict() for item in report.results.values()],
            equity=evaluation.equity,
            equity_boundaries=evaluation.boundaries,
            activity=evaluation.activity,
            cost_sharpes=evaluation.cost_sharpes,
            verified_sharpe=None
            if report.oos_daily_sharpe is None
            else report.oos_daily_sharpe * 252**0.5,
            break_even_bps=report.results[2].metrics.get("break_even_bps"),
        )
        if evaluation.activity:
            row["days_traded"] = evaluation.activity["IS"]["days_traded"]
        row["notes"].append("Buy-and-hold control; excluded from Eval 5 trial accounting.")
        for number, result in report.results.items():
            records.put(
                "eval_results", f"{run_id}_A_{number}", run_id, {"variant": "A", **result.to_dict()}
            )
            records.event(
                run_id,
                "eval",
                "passed" if result.passed else "failed",
                f"Eval {number} {'passed' if result.passed else 'failed'}",
                variant="A",
                data={"eval": number, **result.metrics},
            )
        summary["status"] = "COMPLETED"
        return _finish(records, summary, {"A": row}, [], started)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", choices=["congress_all", "congress_committee", "control"])
    args = parser.parse_args()
    load_dotenv(".env", override=False)
    load_dotenv("runs/secrets.env", override=False)
    previous = state()
    if args.experiment in previous:
        raise ValueError("This frozen acceptance experiment already has a run; inspect its records")
    if args.experiment == "congress_committee":
        if "congress_all" not in previous or previous["congress_all"]["status"] == "RUNNING":
            raise ValueError("All-Congress run must finish before Committee Congress")
    if args.experiment == "control":
        result = control()
        digest = None
    else:
        path = Path("specs") / f"{args.experiment}.json"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        spec = StrategySpec.model_validate_json(path.read_text())
        run_id = "r_" + uuid.uuid4().hex[:12]
        previous[args.experiment] = {"run_id": run_id, "status": "RUNNING", "spec_sha256": digest}
        save_state(previous)
        print(json.dumps(previous[args.experiment]), flush=True)
        result = run_spec(spec, run_id=run_id)
    summary = {
        key: result.get(key)
        for key in ("run_id", "status", "wall_seconds", "estimated_model_cost_usd", "cost_complete")
    }
    summary["spec_sha256"] = digest
    summary["variants"] = [
        {
            key: row.get(key)
            for key in (
                "variant_id",
                "variant",
                "status",
                "evals_passed",
                "days_traded",
                "cost_sharpes",
                "notes",
            )
        }
        for row in result["variants"]
    ]
    previous[args.experiment] = summary
    save_state(previous)
    print(json.dumps(summary, indent=2, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
