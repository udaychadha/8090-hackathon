"""One owner-supplied paper -> three proposals -> deterministic evals -> postmortems."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

from factory.agents.critic import critique
from factory.agents.extractor import ExtractionError, extract, paper_metadata
from factory.agents.records import Records, usage_record
from factory.agents.worker import VARIANTS, RepairFailure, propose_parallel, validate_and_heal
from factory.contract import InactiveStrategy
from factory.data import DataError, load_bars
from factory.data_contract.prompts import worker_context
from factory.evals.common import EvalResult
from factory.evals.lookahead import LookaheadBiasError
from factory.evals.runner import with_deflated
from factory.evaluation import evaluate_file
from factory.llm import LLMError, model_for

SURVIVORSHIP = "Daily universe uses current index membership; results carry survivorship bias."


def run_paper(paper, *, data_root="data", output_root="."):
    started = time.perf_counter()
    root = Path(output_root)
    run_id = "r_" + uuid.uuid4().hex[:12]
    records = Records(root / "runs")
    usages, rows, reports = [], {}, {}
    operational_failed = False
    harness_failed = False
    summary = {"run_id": run_id, "status": "RUNNING", "variants": [], "data_needs": []}
    records.put("runs", run_id, run_id, summary)
    try:
        for role in ("extractor", "worker", "critic"):
            model_for(role)
        records.event(run_id, "extract", "started", "Extracting owner-supplied paper")
        spec, usage = extract(paper, data_root=data_root)
        usages.append(usage_record(usage))
        source = {
            "source_id": spec.paper_id,
            "title": spec.title,
            "source_kind": "paper",
            "spec": spec.model_dump(),
            "provenance": paper_metadata(paper).get("source", {}),
        }
        summary["source"] = source
        records.put("sources", spec.paper_id, run_id, source)
        records.event(run_id, "extract", "passed", "StrategySpec validated")
        records.event(run_id, "data", "started", "Checking existing price data only")
        try:
            is_bars = load_bars(data_root, spec.frequency, spec.universe, split="IS")
        except (DataError, OSError, KeyError, ValueError):
            need = {
                "id": f"{run_id}_bars",
                "kind": "price_bars",
                "name": "Required local price bars",
                "symbols": spec.universe,
                "frequency": spec.frequency,
                "start": None,
                "end": None,
                "status": "unavailable",
                "provider": None,
                "candidates": [],
            }
            records.put("data_needs", need["id"], run_id, need)
            summary["data_needs"] = [need]
            summary["status"] = "BLOCKED_DATA"
            records.event(run_id, "data", "failed", "Required local data unavailable")
            for variant in VARIANTS:
                rows[variant] = _row(spec, run_id, variant)
                rows[variant]["status"] = "BLOCKED_DATA"
            return _finish(records, summary, rows, usages, started)
        need = {
            "id": f"{run_id}_bars",
            "kind": "price_bars",
            "name": "Local price bars",
            "symbols": spec.universe,
            "frequency": spec.frequency,
            "start": str(min(f.index[0] for f in is_bars.values())),
            "end": None,
            "status": "on_disk",
            "provider": None,
            "candidates": [],
        }
        records.put("data_needs", need["id"], run_id, need)
        summary["data_needs"] = [need]
        records.event(run_id, "data", "passed", "Existing price tiers ready")
        schema = worker_context(is_bars, spec.frequency)
        for variant in VARIANTS:
            records.event(run_id, "worker", "started", "Generating strategy", variant=variant)
        proposals = propose_parallel(spec, schema)
        # All three model proposals are concurrent. Validation remains deterministic.
        for variant, proposal in proposals.items():
            row = rows[variant] = _row(spec, run_id, variant)
            if isinstance(proposal, Exception):
                row["status"] = "BUG_UNRESOLVED"
                row["notes"].append("Worker provider failed; no candidate was evaluated")
                summary["cost_complete"] = False
                operational_failed = True
                records.event(run_id, "worker", "failed", "Worker provider failed", variant=variant)
                continue
            code, usage = proposal
            usages.append(usage_record(usage))
            path = root / "strategies" / spec.paper_id / run_id / f"{variant}.py"
            records.event(run_id, "worker", "passed", "Candidate generated", variant=variant)
            try:
                definition, heals = validate_and_heal(
                    spec, variant, code, is_bars, path, records, run_id
                )
                usages.extend(usage_record(item) for item in heals)
                row["code"] = path.read_text()
                if definition is None:
                    row["status"] = "BUG_UNRESOLVED"
                    continue
                row["params"] = definition.params
            except InactiveStrategy as error:
                usages.extend(usage_record(item) for item in error.usages)
                row.update(
                    status=error.status,
                    activity={"IS": error.activity},
                    days_traded=error.activity["days_traded"],
                    eval_eligible=False,
                )
                row["code"] = path.read_text()
                row["notes"].append(str(error))
                continue
            except Exception as error:
                if isinstance(error, RepairFailure):
                    usages.extend(usage_record(item) for item in error.usages)
                if path.is_file():
                    row["code"] = path.read_text()
                row["status"] = "BUG_UNRESOLVED"
                row["notes"].append("IS validation or repair failed before Eval 2")
                summary["cost_complete"] = False
                operational_failed = True
                records.event(
                    run_id, "worker", "failed", "IS validation or repair failed", variant=variant
                )
                continue
            records.event(run_id, "eval", "started", "Running all five evals", variant=variant)
            row["eval_eligible"] = True
            try:
                # No failed metric or OOS exception is ever fed back to workers.
                evaluation = evaluate_file(path, data_root)
                reports[variant] = evaluation.report
                row["equity"] = evaluation.equity
                row["equity_boundaries"] = evaluation.boundaries
                row["activity"] = evaluation.activity
                if evaluation.activity:
                    row["days_traded"] = evaluation.activity["IS"].get("days_traded")
                if evaluation.activity and evaluation.activity["IS"]["active_bars"] == 0:
                    row["notes"].append(
                        "No executed exposure in IS; the strategy hypothesis was not exercised."
                    )
                if evaluation.artifact_error:
                    operational_failed = True
                    row["notes"].append(evaluation.artifact_error)
                    records.event(
                        run_id, "eval", "failed", evaluation.artifact_error, variant=variant
                    )
            except Exception as error:
                row["status"] = "BUG_UNRESOLVED"
                row["notes"].append("Execution/harness failed; no pass claimed, no OOS repair")
                operational_failed = True
                # Lookahead rejection is before Eval 2. An unknown harness error
                # may have lost a trial and must still fail DSR accounting closed.
                harness_failed |= not isinstance(error, LookaheadBiasError)
                records.event(
                    run_id, "eval", "failed", "Execution or harness failed", variant=variant
                )
        trials = [report.oos_daily_sharpe for report in reports.values()]
        for variant, report in reports.items():
            report = with_deflated(report, trials)
            if harness_failed or any(value is None for value in trials):
                report.results[5] = EvalResult(
                    5,
                    "deflated_sharpe",
                    False,
                    {"reason": "Incomplete sibling trial accounting or undefined trial Sharpe"},
                )
            row = rows[variant]
            row.update(
                status=report.status,
                evals_passed=sum(result.passed for result in report.results.values()),
                verified_sharpe=(
                    report.oos_daily_sharpe * (252**0.5)
                    if report.oos_daily_sharpe is not None
                    else None
                ),
                break_even_bps=report.results[2].metrics.get("break_even_bps"),
                evals=[result.to_dict() for result in report.results.values()],
            )
            for number, result in report.results.items():
                records.put(
                    "eval_results",
                    f"{run_id}_{variant}_{number}",
                    run_id,
                    {"variant": variant, **result.to_dict()},
                )
                records.event(
                    run_id,
                    "eval",
                    "passed" if result.passed else "failed",
                    f"Eval {number} {'passed' if result.passed else 'failed'}",
                    variant=variant,
                    data={"eval": number, **result.metrics},
                )
        for variant, row in rows.items():
            records.event(
                run_id, "critic", "started", "Writing narrative postmortem", variant=variant
            )
            try:
                result = critique(
                    spec,
                    variant,
                    {
                        key: value
                        for key, value in row.items()
                        if key not in {"code", "params", "equity", "equity_boundaries"}
                    },
                )
                usages.append(usage_record(result))
                row["critique"] = result.text
            except Exception:
                row["critique"] = (
                    "Narrative unavailable: critic provider failed. Eval status unchanged."
                )
                summary["cost_complete"] = False
                operational_failed = True
                records.event(run_id, "critic", "failed", "Critic unavailable", variant=variant)
            else:
                records.event(run_id, "critic", "passed", "Narrative recorded", variant=variant)
            records.put(
                "critiques",
                f"{run_id}_{variant}",
                run_id,
                {"variant": variant, "text": row["critique"]},
            )
            graveyard = root / "wiki" / "graveyard.md"
            graveyard.parent.mkdir(parents=True, exist_ok=True)
            with graveyard.open("a") as stream:
                stream.write(
                    records.safe(
                        f"\n## {spec.title} | {run_id} | {variant}\n\n"
                        f"{row['status']} ({row['evals_passed']}/5)\n\n" + row["critique"] + "\n"
                    )
                )
        summary["status"] = "FAILED" if operational_failed else "COMPLETED"
        return _finish(records, summary, rows, usages, started)
    except Exception as error:
        # Avoid dumping SDK errors, prompts or environment variables to disk/stdout.
        summary.update(status="FAILED", error_type=type(error).__name__, cost_complete=False)
        if isinstance(error, (LLMError, ExtractionError)):
            summary["error"] = str(error)
        for row in rows.values():
            if row["status"] == "RUNNING":
                row["status"] = "BUG_UNRESOLVED"
        return _finish(records, summary, rows, usages, started)
    finally:
        records.close()


def _row(spec, run_id, variant):
    return {
        "variant_id": f"{run_id}_{variant}",
        "run_id": run_id,
        "source_id": spec.paper_id,
        "source_title": spec.title,
        "source_kind": "paper",
        "variant": variant,
        "test_type": spec.test_type,
        "frequency": spec.frequency,
        "claimed_sharpe": spec.claimed_metrics.sharpe,
        "verified_sharpe": None,
        "break_even_bps": None,
        "evals_passed": 0,
        "status": "RUNNING",
        "eval_eligible": False,
        "days_traded": None,
        "notes": [SURVIVORSHIP] if spec.frequency == "1day" else [],
    }


def _finish(records, summary, rows, usages, started):
    for row in rows.values():
        records.put("variants", row["variant_id"], summary["run_id"], row)
    summary["variants"] = list(rows.values())
    summary["wall_seconds"] = time.perf_counter() - started
    summary["usage"] = usages
    complete_cost = summary.get("cost_complete", True) and all(
        item["cost_usd"] is not None for item in usages
    )
    summary["cost_complete"] = complete_cost
    summary["estimated_model_cost_usd"] = (
        sum(item["cost_usd"] for item in usages) if complete_cost else None
    )
    records.put("runs", summary["run_id"], summary["run_id"], summary)
    records.event(
        summary["run_id"],
        "done",
        "passed" if summary["status"] == "COMPLETED" else "failed",
        "Run finished",
        data={
            "status": summary["status"],
            "wall_seconds": summary["wall_seconds"],
            "estimated_model_cost_usd": summary["estimated_model_cost_usd"],
        },
    )
    return records.safe(summary)


def main():
    load_dotenv(override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paper")
    parser.add_argument("--data", default="data")
    parser.add_argument("--output", default=".")
    args = parser.parse_args()
    result = run_paper(args.paper, data_root=args.data, output_root=args.output)
    print(json.dumps(result, indent=2, allow_nan=False))
    if result["status"] != "COMPLETED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
