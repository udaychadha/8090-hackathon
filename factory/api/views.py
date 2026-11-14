"""Deterministic presentation of stored evidence; no LLM or eval recomputation."""

from __future__ import annotations

from factory.api.schemas import DataNeed, LeaderboardRow, RunSummary

EVAL_NAMES = {1: "Lookahead", 2: "Friction", 3: "Sensitivity", 4: "Decay", 5: "Deflated Sharpe"}


def summary(row):
    status, count = row["status"], row["evals_passed"]
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


def leaderboard_row(row):
    fields = set(LeaderboardRow.model_fields) - {"summary"}
    projected = {key: row.get(key) for key in fields}
    projected["notes"] = row.get("notes", [])
    projected["summary"] = summary(row)
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


def variant_steps(row, run, events, evals, heals, critique):
    lane = row["variant"]
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
        else:
            state = "not_run" if terminal else ("running" if harness_started else "pending")
            details = ["No completed eval result was recorded."] if terminal else []
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
    value["variants"] = [leaderboard_row(row) for row in rows]
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
    steps = variant_steps(row, run, events, evals, heals, critique)
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
