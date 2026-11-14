"""Deterministic stored evidence and labelled, read-only live result recovery."""

from __future__ import annotations

from factory.api.live_evidence import recover_evaluations
from factory.api.schemas import DataNeed, LeaderboardRow, RunSummary

EVAL_NAMES = {1: "Lookahead", 2: "Friction", 3: "Sensitivity", 4: "Decay", 5: "Deflated Sharpe"}


COMPUTATION_COMPLETE_EVENT = "Variant computation complete; awaiting final judgment"


def computation_complete(row, events=()):
    """Completion evidence describes execution only, never an eval outcome."""
    if any(
        event["stage"] == "eval"
        and event["status"] == "info"
        and event["variant"] == row["variant"]
        and event["message"] == COMPUTATION_COMPLETE_EVENT
        for event in events
    ):
        return True
    activity = row.get("activity") or {}
    boundaries = row.get("equity_boundaries") or {}
    return all(activity.get(period) for period in ("IS", "OOS")) and all(
        boundaries.get(key) for key in ("is_end", "oos_end")
    )


def summary(row, *, run=None, events=()):
    status, count = row["status"], row["evals_passed"]
    if status == "RUNNING":
        if run is not None and run["status"] != "RUNNING":
            return (
                "Run ended before final evaluation results were published; "
                f"{count}/5 evaluations recorded as passed."
            )
        known = {n: item["result"] for n, item in recover_evaluations(row).items()}
        known.update({item["number"]: item for item in row.get("evals", [])})
        failed = next((n for n in sorted(known) if not known[n]["passed"]), None)
        if failed is not None:
            return (
                f"Eval {failed} ({EVAL_NAMES[failed]}) failed; {len(known)}/5 results available. "
                "Remaining checks continue."
            )
        if known:
            return (
                f"{sum(e['passed'] for e in known.values())}/5 checks passed so far; "
                "remaining results appear as they finish."
            )
        if computation_complete(row, events):
            return "Checks finished; this older runner has not published individual outcomes yet."
    if status == "VERIFIED":
        return "All five deterministic evaluations passed."
    if status.startswith("FAILED_EVAL_"):
        return f"Failed Eval {status.rsplit('_', 1)[1]}; {count}/5 evaluations passed."
    return {
        "INSUFFICIENT_SAMPLE": "All five evaluations passed; short sample: not a verdict.",
        "INACTIVE": (
            "The strategy did not meet the IS activity requirement; performance was not verified."
        ),
        "BUG_UNRESOLVED": (
            f"Bug validation or execution did not complete; {count}/5 evaluations passed."
        ),
        "BLOCKED_DATA": "Required data was unavailable; the strategy could not be evaluated.",
        "VOID": "This historical result was invalidated and is excluded from comparisons.",
        "RUNNING": f"Work is in progress; {count}/5 evaluations recorded as passed.",
    }[status]


def leaderboard_row(row, *, run=None, events=()):
    fields = set(LeaderboardRow.model_fields) - {"summary"}
    projected = {key: row.get(key) for key in fields}
    projected["notes"] = row.get("notes", [])
    projected["summary"] = summary(row, run=run, events=events)
    if row["status"] == "RUNNING" and (run is None or run["status"] == "RUNNING"):
        known = {n: item["result"] for n, item in recover_evaluations(row).items()}
        known.update({item["number"]: item for item in row.get("evals", [])})
        if known:
            projected["evals_passed"] = sum(item["passed"] for item in known.values())
            projected["default_evals_passed"] = projected["evals_passed"]
    return projected


def evaluations(row, records, *, include_voided=False):
    """Both tables and embedded snapshots are persisted evidence; conflicts fail closed."""
    values = {e["number"]: e for e in row.get("evals", [])}
    for stored in records.list(
        "eval_results", run_id=row["run_id"], variant=row["variant"], include_voided=include_voided
    ):
        item = {key: stored[key] for key in ("number", "name", "passed", "metrics")}
        if item["number"] in values and item != values[item["number"]]:
            raise ValueError("Embedded and standalone eval evidence disagree")
        values[item["number"]] = item
    return [values[n] for n in sorted(values)]


def display_evaluations(row, run, recorded):
    """Tearsheet view only: distinguish recovered measurements from stored reports."""
    values = {item["number"]: item for item in recorded}
    if row["status"] == "RUNNING" and run["status"] == "RUNNING":
        for number, evidence in recover_evaluations(row).items():
            if number in values:
                continue
            result = evidence["result"]
            provenance = evidence.get("provenance") or " ".join(evidence["details"])
            values[number] = {
                **result,
                "metrics": {
                    **result["metrics"],
                    "evidence_source": "recovered_from_saved_evidence",
                    "reason": provenance,
                },
            }
    return [values[n] for n in sorted(values)]


def metric_details(evaluation):
    m, number = evaluation["metrics"], evaluation["number"]
    details = [f"Recorded verdict: {'pass' if evaluation['passed'] else 'fail'}."]
    if number == 1:
        if m.get("cuts") is not None:
            details.append(f"{len(m['cuts'])} truncation cuts checked.")
        if m.get("tolerance") is not None:
            details.append(f"Maximum allowed difference: {m['tolerance']:g}.")
    elif number == 2:
        bps = m.get("pass_bps")
        sharpes = m.get("sharpe_by_bps") or {}
        value = sharpes.get(f"{bps:g}") if bps is not None else None
        if bps is not None:
            details.append(
                f"Net Sharpe at {bps:g} bps: {value:.3f}."
                if value is not None
                else f"Net Sharpe at {bps:g} bps is undefined."
            )
        if m.get("break_even_bps") is not None:
            details.append(f"Break-even cost at the threshold: {m['break_even_bps']:.2f} bps.")
        elif m.get("break_even_note"):
            details.append(f"Break-even cost: {m['break_even_note']}.")
    elif number == 3:
        if m.get("worst_sharpe") is not None:
            details.append(f"Worst perturbed Sharpe: {m['worst_sharpe']:.3f}.")
        if m.get("worst_ratio") is not None:
            details.append(f"Worst/base Sharpe ratio: {m['worst_ratio']:.3f}.")
    elif number == 4:
        for key, label in [
            ("is_sharpe", "IS Sharpe"),
            ("oos_sharpe", "OOS Sharpe"),
            ("oos_to_is_ratio", "OOS/IS Sharpe ratio"),
        ]:
            if key in m:
                details.append(
                    f"{label}: {m[key]:.3f}." if m[key] is not None else f"{label} is undefined."
                )
        for period in ("is", "oos"):
            share = m.get(f"{period}_max_window_share")
            details.append(
                f"{period.upper()} concentration share: {share:.3f}."
                if share is not None
                else f"{period.upper()} concentration share: not applicable or unavailable (fails)."
            )
    elif number == 5:
        if m.get("dsr") is not None:
            details.append(f"Deflated Sharpe probability: {m['dsr']:.3f}.")
        if m.get("n_trials") is not None:
            details.append(f"Trial count used: {m['n_trials']}.")
    if m.get("reason"):
        details.append(m["reason"])
    return details


def _step(identifier, kind, label, state, logs=(), details=(), **kwargs):
    return {
        "id": identifier,
        "kind": kind,
        "label": label,
        "state": state,
        "number": None,
        "attempts": 0,
        "max_attempts": None,
        "details": list(details),
        "logs": list(logs),
        **kwargs,
    }


def _event_state(logs, terminal):
    if logs:
        return {"started": "running", "passed": "recorded", "failed": "failed", "info": "recorded"}[
            logs[-1]["status"]
        ]
    return "not_run" if terminal else "pending"


def run_steps(run, events):
    terminal = run["status"] != "RUNNING"
    result = []
    for stage, label in [
        ("extract", "Extract strategy specification"),
        ("data", "Resolve data needs"),
    ]:
        if stage == "extract" and (run.get("source") or {}).get("source_kind") == "described":
            logs = [e for e in events if e["stage"] == "intake" and e["variant"] is None]
            result.append(
                _step(
                    "intake",
                    "extract",
                    "Owner-supplied specification",
                    "recorded",
                    logs,
                    [e["message"] for e in logs],
                )
            )
            continue
        logs = [e for e in events if e["stage"] == stage and e["variant"] is None]
        state = _event_state(logs, terminal)
        if stage == "extract" and run.get("source"):
            state = "recorded"
        details = [e["message"] for e in logs]
        if terminal and state == "running":
            state = "failed"
        result.append(_step(stage, stage, label, state, logs, details))
    return result


def variant_steps(row, run, events, evals, heals, critique, *, siblings=()):
    lane = row["variant"]
    all_events = events
    events = [e for e in events if e["variant"] == lane]
    terminal = run["status"] != "RUNNING" or row["status"] != "RUNNING"
    code_logs = [e for e in events if e["stage"] == "worker"]
    state = "recorded" if row.get("code") is not None else _event_state(code_logs, terminal)
    if terminal and state == "running":
        state = "failed"
    steps = [
        _step(
            f"{lane}-code",
            "code",
            "Generate strategy code",
            state,
            code_logs,
            [e["message"] for e in code_logs],
        )
    ]
    heal_logs = [
        e
        for e in events
        if e["stage"] == "heal"
        or (e["stage"] == "eval" and e["message"].startswith("IS bug validation"))
    ]
    attempts = max((h["attempt"] for h in heals), default=0)
    latest_heal = max(heals, key=lambda h: h["attempt"], default=None)
    heal_state = (
        ("fixed" if latest_heal["fixed"] else ("failed" if terminal else "running"))
        if latest_heal
        else ("not_run" if terminal else "pending")
    )
    heal_details = []
    for heal in sorted(heals, key=lambda h: h["attempt"]):
        heal_details.append(f"Attempt {heal['attempt']}/3: {heal['error']}")
        if heal.get("result_error"):
            heal_details.append(heal["result_error"])
    label = f"Fixed {attempts}/3" if heal_state == "fixed" else "Bug-only self-heal"
    if heals or any(e["stage"] == "heal" for e in events):
        steps.append(
            _step(
                f"{lane}-heal",
                "heal",
                label,
                heal_state,
                heal_logs,
                heal_details,
                attempts=attempts,
                max_attempts=3,
            )
        )
    by_number = {e["number"]: e for e in evals}
    harness_started = any(e["stage"] == "eval" and e["status"] == "started" for e in events)
    completed = computation_complete(row, events)
    recovered = {} if terminal else recover_evaluations(row)
    granular = any(
        e["stage"] == "eval" and e["data"].get("eval") is not None and e["status"] == "started"
        for e in events
    )
    waiting = [
        s["variant"]
        for s in siblings
        if s["status"] == "RUNNING" and not computation_complete(s, all_events)
    ]
    for number in range(1, 6):
        logs = [
            e
            for e in events
            if e["stage"] == "eval"
            and e["data"].get("eval") == number
            and not e["message"].startswith("IS bug validation")
        ]
        result = by_number.get(number)
        if result:
            state = "pass" if result["passed"] else "failed"
            details = metric_details(result)
        elif number in recovered:
            item = recovered[number]
            state = "pass" if item["result"]["passed"] else "failed"
            details = item.get("details") or metric_details(item["result"])[1:] + [
                item["provenance"]
            ]
        else:
            if terminal:
                state, details = "not_run", ["No completed eval result was recorded."]
            elif any(e["status"] == "started" for e in logs):
                state = "running"
                details = [logs[-1]["message"]]
            elif number == 5 and (completed or any(e["number"] == 4 for e in evals)):
                state = "awaiting_judgment"
                details = [
                    f"Waiting for {', '.join(waiting)} to finish its checks."
                    if waiting
                    else "Waiting for the shared trial cohort to be assembled.",
                    "Eval 5 compares all eligible trials together. "
                    "Results from Evals 1–4 are available independently.",
                ]
            elif completed:
                state = "recorded"
                details = [
                    "Computation finished, but this older runner has not published "
                    "this eval's detailed outcome.",
                    "The running process remains untouched; its retained report "
                    "will appear when it publishes.",
                ]
            elif harness_started and not granular:
                state = "awaiting_results"
                details = [
                    "This run started before per-eval streaming; "
                    "its current individual check is not reported.",
                    "The harness is active. Saved results appear here "
                    "as evidence becomes available.",
                ]
            else:
                state, details = "pending", []
        steps.append(
            _step(
                f"{lane}-eval-{number}",
                "eval",
                f"{number}. {EVAL_NAMES[number]}",
                state,
                logs,
                details,
                number=number,
            )
        )
    logs = [e for e in events if e["stage"] == "critic"]
    pipeline_terminal = run["status"] != "RUNNING"
    state = _event_state(logs, pipeline_terminal)
    if critique is not None and (not logs or logs[-1]["status"] != "failed"):
        state = "recorded"
    if pipeline_terminal and state == "running":
        state = "failed"
    steps.append(
        _step(
            f"{lane}-critic",
            "critic",
            "Unverified model narrative",
            state,
            logs,
            ["Narrative is separate from deterministic results and cannot change them."],
        )
    )
    return steps


def run_summary(run, records, *, include_voided=False, events=None):
    events = (
        events
        if events is not None
        else records.events(run["run_id"], include_voided=include_voided)
    )
    rows = records.list("variants", run_id=run["run_id"], include_voided=include_voided)
    fields = set(RunSummary.model_fields) - {"variants", "data_needs", "started_at"}
    value = {key: run.get(key) for key in fields}
    value["variants"] = [leaderboard_row(row, run=run, events=events) for row in rows]
    needs = records.list("data_needs", run_id=run["run_id"], include_voided=include_voided)
    value["data_needs"] = [{key: need[key] for key in DataNeed.model_fields} for need in needs]
    value["started_at"] = min((event["ts"] for event in events), default=None)
    return value


def lane_evidence(row, run, records, *, include_voided=False, events=None):
    events = (
        events
        if events is not None
        else records.events(run["run_id"], include_voided=include_voided)
    )
    evals = evaluations(row, records, include_voided=include_voided)
    heals = records.list(
        "heal_attempts", run_id=row["run_id"], variant=row["variant"], include_voided=include_voided
    )
    critiques = records.list(
        "critiques", run_id=row["run_id"], variant=row["variant"], include_voided=include_voided
    )
    critique = critiques[-1]["text"] if critiques else row.get("critique")
    siblings = (
        records.list("variants", run_id=row["run_id"], include_voided=include_voided)
        if run["status"] == "RUNNING"
        else ()
    )
    steps = variant_steps(row, run, events, evals, heals, critique, siblings=siblings)
    return evals, heals, critique, steps


def graveyard_entry(row, records, *, include_voided=False):
    run = records.get("runs", row["run_id"], include_voided=include_voided)
    evals, _, critique, _ = lane_evidence(row, run, records, include_voided=include_voided)
    first_failed = next((e for e in evals if not e["passed"]), None)
    cause = " ".join(metric_details(first_failed)) if first_failed else summary(row)
    fields = (
        "variant_id",
        "run_id",
        "source_title",
        "variant",
        "status",
        "test_type",
        "frequency",
        "evals_passed",
        "voided",
        "void_reason",
        "original_result",
    )
    return {
        **{key: row.get(key) for key in fields},
        "summary": summary(row),
        "cause": cause,
        "critique": critique,
        "notes": row.get("notes", []),
    }
