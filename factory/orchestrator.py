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
from factory.contract import InactiveStrategy, StrategySpec
from factory.data import DataError, load_bars
from factory.data_contract.prompts import worker_context
from factory.evals.runner import with_deflated
from factory.evaluation import evaluate_file
from factory.gross_diagnostics import diagnostics_for_status, pending_diagnostics
from factory.llm import LLMError, model_for
from factory.trials import trial_cohort

SURVIVORSHIP = "Daily universe uses current index membership; results carry survivorship bias."


def run_spec(spec, *, data_root="data", output_root=".", run_id=None, retained_run_id=None):
    """Run a frozen, owner-supplied original specification through the same arena."""
    payload = spec.model_dump() if isinstance(spec, StrategySpec) else spec
    validated = StrategySpec.model_validate(payload)
    if validated.source_kind != "described" or validated.test_type != "original":
        raise ValueError("Handwritten specifications must be described/original")
    return run_paper(
        None,
        data_root=data_root,
        output_root=output_root,
        run_id=run_id,
        supplied_spec=validated,
        retained_run_id=retained_run_id,
    )


def run_paper(
    paper,
    *,
    data_root="data",
    output_root=".",
    run_id=None,
    supplied_spec=None,
    retained_run_id=None,
):
    started = time.perf_counter()
    root = Path(output_root)
    run_id = run_id or ("r_" + uuid.uuid4().hex[:12])
    records = Records(root / "runs")
    usages, rows, reports = [], {}, {}
    gross_by_variant = {}
    operational_failed = False
    summary = records.get("runs", run_id, include_voided=True)
    if summary is not None and (summary["status"] != "RUNNING" or summary.get("source")):
        records.close()
        raise ValueError("Run identity is already in use")
    summary = summary or {"run_id": run_id, "status": "RUNNING", "variants": [], "data_needs": []}
    summary = records.put("runs", run_id, run_id, summary)
    try:
        for role in (
            ("extractor", "worker", "critic") if supplied_spec is None else ("worker", "critic")
        ):
            model_for(role)
        if supplied_spec is None:
            records.event(run_id, "extract", "started", "Extracting owner-supplied paper")
            spec, usage = extract(paper, data_root=data_root)
            usages.append(usage_record(usage))
        else:
            spec = supplied_spec
            records.event(
                run_id, "intake", "passed", "Frozen owner-supplied specification validated"
            )
        source = {
            "source_id": spec.paper_id,
            "title": spec.title,
            "source_kind": spec.source_kind,
            "spec": spec.model_dump(),
            "provenance": paper_metadata(paper).get("source", {}) if paper is not None else {},
        }
        source = records.put("sources", spec.paper_id, run_id, source)
        summary["source"] = source
        summary = records.put("runs", run_id, run_id, summary)
        if supplied_spec is None:
            records.event(run_id, "extract", "passed", "StrategySpec validated")
        records.event(run_id, "data", "started", "Checking required local datasets")
        missing_kind, missing_name = "price_bars", "Required local price bars"
        extra = None
        try:
            is_bars = load_bars(
                data_root,
                spec.frequency,
                spec.universe,
                split="IS",
                **({"allow_empty_symbols": True} if spec.extra else {}),
            )
            if spec.extra:
                from factory.event_execution import decision_times
                from factory.events import load_extra

                missing_kind, missing_name = "events", ", ".join(spec.extra)
                extra = load_extra(
                    data_root, spec.extra, as_of=decision_times(is_bars, spec.frequency).max()
                )
        except (DataError, OSError, KeyError, ValueError):
            need = {
                "id": f"{run_id}_bars",
                "kind": missing_kind,
                "name": missing_name,
                "symbols": spec.universe,
                "frequency": spec.frequency if missing_kind == "price_bars" else None,
                "start": None,
                "end": None,
                "status": "unavailable",
                "provider": None,
                "candidates": [],
            }
            need = records.put("data_needs", need["id"], run_id, need)
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
            "start": str(min(f.index[0] for f in is_bars.values() if not f.empty)),
            "end": None,
            "status": "on_disk",
            "provider": None,
            "candidates": [],
        }
        need = records.put("data_needs", need["id"], run_id, need)
        summary["data_needs"] = [need]
        for name in spec.extra:
            event_need = {
                **need,
                "id": f"{run_id}_event_{name}",
                "kind": "events",
                "name": name,
                "frequency": None,
                "start": None,
            }
            # Record identity metadata belongs to each individual need.
            event_need = {
                key: event_need[key]
                for key in (
                    "id",
                    "kind",
                    "name",
                    "symbols",
                    "frequency",
                    "start",
                    "end",
                    "status",
                    "provider",
                    "candidates",
                )
            }
            summary["data_needs"].append(
                records.put("data_needs", event_need["id"], run_id, event_need)
            )
        summary = records.put("runs", run_id, run_id, summary)
        records.event(run_id, "data", "passed", "Required local datasets ready")
        schema = worker_context(
            is_bars, spec.frequency, **({"extra": extra} if extra is not None else {})
        )
        retained = None
        if retained_run_id is not None:
            previous = records.get("runs", retained_run_id, include_voided=True)
            candidates = records.list("variants", run_id=retained_run_id, include_voided=True)
            if (
                not previous
                or previous["status"] != "VOID"
                or (previous.get("source") or {}).get("spec") != spec.model_dump()
                or {item["variant"] for item in candidates} != set(VARIANTS)
                or any(
                    item.get("reached_eval_2") or item.get("evals") or not item.get("code")
                    for item in candidates
                )
            ):
                raise ValueError(
                    "Reuse requires identical spec and void candidates with no eval results"
                )
            retained = {item["variant"]: (item["code"], None) for item in candidates}
        for variant in VARIANTS:
            rows[variant] = _save_row(records, _row(spec, run_id, variant))
            if retained is not None:
                rows[variant]["notes"].append(
                    f"Candidate retained from invalidated harness attempt {retained_run_id}; "
                    "no new generation or prior performance results."
                )
            records.event(
                run_id,
                "worker",
                "started",
                "Loading retained candidate" if retained is not None else "Generating strategy",
                variant=variant,
            )
        proposals = retained if retained is not None else propose_parallel(spec, schema)
        # All three model proposals are concurrent. Validation remains deterministic.
        for variant, proposal in proposals.items():
            row = rows[variant]
            try:
                if isinstance(proposal, Exception):
                    row["status"] = "BUG_UNRESOLVED"
                    row["notes"].append("Worker provider failed; no candidate was evaluated")
                    summary["cost_complete"] = False
                    operational_failed = True
                    records.event(
                        run_id, "worker", "failed", "Worker provider failed", variant=variant
                    )
                    continue
                code, usage = proposal
                if usage is not None:
                    usages.append(usage_record(usage))
                path = root / "strategies" / spec.paper_id / run_id / f"{variant}.py"
                records.event(
                    run_id,
                    "worker",
                    "passed",
                    "Retained candidate loaded" if retained is not None else "Candidate generated",
                    variant=variant,
                )
                try:
                    definition, heals = validate_and_heal(
                        spec,
                        variant,
                        code,
                        is_bars,
                        path,
                        records,
                        run_id,
                        **({"extra": extra} if extra is not None else {}),
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
                        run_id,
                        "worker",
                        "failed",
                        "IS validation or repair failed",
                        variant=variant,
                    )
                    continue
                records.event(run_id, "eval", "started", "Running all five evals", variant=variant)
                row["eval_eligible"] = True
                try:
                    # No failed metric or OOS exception is ever fed back to workers.
                    def mark_eval2_started(row=row):
                        row["reached_eval_2"] = True
                        _save_row(records, row)

                    evaluation = evaluate_file(path, data_root, on_eval2_started=mark_eval2_started)
                    records.event(
                        run_id,
                        "eval",
                        "info",
                        "Variant computation complete; awaiting final judgment",
                        variant=variant,
                        data={},
                    )
                    reports[variant] = evaluation.report
                    gross_by_variant[variant] = evaluation.gross_diagnostics
                    row["equity"] = evaluation.equity
                    row["equity_boundaries"] = evaluation.boundaries
                    row["activity"] = evaluation.activity
                    if evaluation.cost_sharpes is not None:
                        row["cost_sharpes"] = evaluation.cost_sharpes
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
                except Exception:
                    row["status"] = "BUG_UNRESOLVED"
                    row["notes"].append("Execution/harness failed; no pass claimed, no OOS repair")
                    operational_failed = True
                    records.event(
                        run_id, "eval", "failed", "Execution or harness failed", variant=variant
                    )
            finally:
                rows[variant] = _save_row(records, row)
        trial_ids, trials = trial_cohort(
            records,
            {rows[v]["variant_id"]: report.oos_daily_sharpe for v, report in reports.items()},
        )
        for variant, report in reports.items():
            report = with_deflated(report, trials, trial_variant_ids=trial_ids)
            row = rows[variant]
            row.update(
                status=(
                    "INSUFFICIENT_SAMPLE"
                    if report.status == "VERIFIED" and not spec.verification_eligible
                    else report.status
                ),
                evals_passed=sum(result.passed for result in report.results.values()),
                verified_sharpe=(
                    report.oos_daily_sharpe * (252**0.5)
                    if report.oos_daily_sharpe is not None
                    else None
                ),
                break_even_bps=report.results[2].metrics.get("break_even_bps"),
                evals=[result.to_dict() for result in report.results.values()],
            )
            row["gross_diagnostics"] = diagnostics_for_status(
                gross_by_variant.get(variant), row["status"]
            )
            rows[variant] = _save_row(records, row)
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
                        if key
                        not in {
                            "code",
                            "params",
                            "equity",
                            "equity_boundaries",
                            "gross_diagnostics",
                        }
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
            rows[variant] = _save_row(records, row)
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
        summary.update(status="FAILED", error_type=type(error).__name__)
        if isinstance(error, ExtractionError) and error.usages is not None:
            usages.extend(error.usages)
            if error.diagnostics:
                summary["extraction_diagnostics"] = error.diagnostics
        else:
            summary["cost_complete"] = False
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
        "source_kind": spec.source_kind,
        "variant": variant,
        "test_type": spec.test_type,
        "frequency": spec.frequency,
        "claimed_sharpe": spec.claimed_metrics.sharpe,
        "verified_sharpe": None,
        "break_even_bps": None,
        "evals_passed": 0,
        "status": "RUNNING",
        "gross_diagnostics": pending_diagnostics(),
        "eval_eligible": False,
        "reached_eval_2": False,
        "days_traded": None,
        "verification_eligible": spec.verification_eligible,
        "eligibility_reason": spec.eligibility_reason,
        "notes": list(
            dict.fromkeys(
                ([SURVIVORSHIP] if spec.frequency == "1day" else [])
                + spec.notes
                + (["unverified source"] if spec.extra else [])
                + ([spec.eligibility_reason] if spec.eligibility_reason else [])
            )
        ),
    }


def _save_row(records, row):
    # Defaults are the only active profile. Refresh projections on every state change.
    row["gross_diagnostics"] = diagnostics_for_status(row.get("gross_diagnostics"), row["status"])
    row["default_status"] = row["status"]
    row["default_evals_passed"] = row["evals_passed"]
    return records.put("variants", row["variant_id"], row["run_id"], row)


def _finish(records, summary, rows, usages, started):
    for variant, row in rows.items():
        rows[variant] = _save_row(records, row)
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
    summary = records.put("runs", summary["run_id"], summary["run_id"], summary)
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
