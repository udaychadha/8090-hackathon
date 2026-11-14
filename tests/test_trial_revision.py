"""Global trial accounting uses identities and retains incomplete reached trials."""

import math

import pandas as pd
import pytest

from factory.agents.records import Records
from factory.evals import runner
from factory.evals.common import EvalResult


def add_run(records, run_id, **extra):
    return records.put("runs", run_id, run_id, {"run_id": run_id, "status": "COMPLETED", **extra})


def add_variant(records, run_id, variant="A", **extra):
    identifier = f"{run_id}_{variant}"
    return records.put(
        "variants",
        identifier,
        run_id,
        {
            "variant_id": identifier,
            "run_id": run_id,
            "variant": variant,
            "status": "FAILED_EVAL_2",
            "source_id": "p_test",
            "source_title": "Test",
            "source_kind": "paper",
            "test_type": "transfer",
            "frequency": "1day",
            "evals_passed": 0,
            "evals": [{"number": 2, "name": "friction", "passed": False, "metrics": {}}],
            **extra,
        },
    )


def test_global_trial_selection_preserves_repeated_runs_and_failed_trials(tmp_path):
    with Records(tmp_path) as records:
        add_run(records, "one", eval_eligible=False)
        add_run(records, "two")
        add_variant(records, "one", eval_eligible=False)
        add_variant(records, "two", status="BUG_UNRESOLVED")
        add_variant(records, "two", "B", status="INACTIVE", evals=[])
        add_variant(records, "two", "C", status="BUG_UNRESOLVED", evals=[])
        assert [r["variant_id"] for r in records.trial_variants()] == ["one_A", "two_A"]


def test_trial_cohort_deduplicates_ids_not_equal_values_and_keeps_missing(tmp_path):
    from factory.trials import trial_cohort

    with Records(tmp_path) as records:
        for run_id in ("one", "two", "three"):
            add_run(records, run_id)
        add_variant(records, "one", verified_sharpe=math.sqrt(252) * 0.1)
        add_variant(records, "two", verified_sharpe=math.sqrt(252) * 0.1)
        add_variant(records, "three")
        ids, values = trial_cohort(records, {"one_A": 0.2})
        assert ids == ["one_A", "three_A", "two_A"]
        assert values == [0.2, None, pytest.approx(0.1)]


def test_eval2_marker_is_called_before_friction_exception(monkeypatch):
    marked = []
    monkeypatch.setattr(
        runner, "lookahead_eval", lambda *a: (EvalResult(1, "lookahead", True), None)
    )

    def friction(*args):
        assert marked == [True]
        raise RuntimeError("Eval 2 failed during execution")

    monkeypatch.setattr(runner, "friction_eval", friction)
    with pytest.raises(RuntimeError, match="Eval 2 failed"):
        runner.evaluate(None, {}, "1day", {}, {}, on_eval2_started=lambda: marked.append(True))


def test_controls_and_voids_excluded_but_reached_marker_survives_failure(tmp_path):
    with Records(tmp_path) as records:
        for run_id in ("ordinary", "voided", "control"):
            add_run(records, run_id, is_control=run_id == "control")
        add_variant(records, "ordinary", evals=[], reached_eval_2=True, status="BUG_UNRESOLVED")
        add_variant(records, "ordinary", "B", is_control=True)
        from factory.agents.records import _void_payload

        row = add_variant(records, "ordinary", "C")
        records.put(
            "variants",
            "ordinary_C",
            "ordinary",
            _void_payload(row, "Invalidated variant", "2026-11-14T12:00:00Z"),
        )
        add_variant(records, "voided")
        add_variant(records, "control")
        records.void_run("voided", "Invalidated fixture")
        assert [v["variant_id"] for v in records.trial_variants()] == ["ordinary_A"]


def test_standalone_eval2_and_daily_sharpe_sources(tmp_path):
    from factory.trials import trial_cohort

    with Records(tmp_path) as records:
        add_run(records, "one")
        add_variant(records, "one", evals=[])
        records.put(
            "eval_results",
            "one_A_2",
            "one",
            {
                "variant": "A",
                "number": 2,
                "name": "friction",
                "passed": False,
                "metrics": {},
            },
        )
        records.put(
            "eval_results",
            "one_A_5",
            "one",
            {
                "variant": "A",
                "number": 5,
                "name": "deflated_sharpe",
                "passed": False,
                "metrics": {"daily_sharpe": 0.15},
            },
        )
        add_variant(
            records,
            "one",
            "B",
            evals=[
                {"number": 2, "name": "friction", "passed": False, "metrics": {}},
                {
                    "number": 4,
                    "name": "decay",
                    "passed": False,
                    "metrics": {"oos_sharpe": 0.2 * math.sqrt(252)},
                },
            ],
        )
        assert trial_cohort(records) == (["one_A", "one_B"], [0.15, pytest.approx(0.2)])


@pytest.fixture
def offline_pipeline(monkeypatch):
    from pathlib import Path

    from factory import orchestrator
    from factory.agents.test_worker import CLEAN, bars, spec
    from factory.contract import parse_strategy
    from factory.evals.common import daily_sharpe
    from factory.evaluation import RecordedEvaluation
    from factory.llm import Completion

    usage = Completion("fixture", "fixture", 10, 5, 0.01, 0.001)
    for role in ("EXTRACTOR", "WORKER", "CRITIC"):
        monkeypatch.setenv(f"{role}_MODEL", "openai:fixture")
    monkeypatch.setattr(orchestrator, "extract", lambda *a, **kw: (spec(), usage))
    monkeypatch.setattr(orchestrator, "load_bars", lambda *a, **kw: bars())
    monkeypatch.setattr(
        orchestrator, "propose_parallel", lambda *a: {v: (CLEAN, usage) for v in "ABC"}
    )
    monkeypatch.setattr(orchestrator, "critique", lambda *a: usage)

    def heal(s, variant, code, is_bars, path, *args):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(code)
        return parse_strategy(code), []

    def evaluate(path, *args, on_eval2_started=None):
        if on_eval2_started:
            on_eval2_started()
        offset = (ord(Path(path).stem) - ord("A")) * 0.001
        returns = pd.Series([0.01 + offset, -0.004, 0.006, 0.002] * 80)
        return RecordedEvaluation(
            runner.EvalReport(
                {n: EvalResult(n, f"eval{n}", True, {}) for n in range(1, 5)},
                {},
                returns,
                daily_sharpe(returns),
            )
        )

    monkeypatch.setattr(orchestrator, "validate_and_heal", heal)
    monkeypatch.setattr(orchestrator, "evaluate_file", evaluate)
    return evaluate


def test_two_actual_orchestrator_runs_use_global_trial_ids(offline_pipeline, tmp_path):
    from factory import orchestrator

    first = orchestrator.run_paper("offline.pdf", output_root=tmp_path, run_id="first")
    second = orchestrator.run_paper("offline.pdf", output_root=tmp_path, run_id="second")
    assert first["status"] == second["status"] == "COMPLETED"
    expected = [f"{run}_{variant}" for run in ("first", "second") for variant in "ABC"]
    first_metrics = next(e["metrics"] for e in first["variants"][0]["evals"] if e["number"] == 5)
    for row in second["variants"]:
        metrics = next(e["metrics"] for e in row["evals"] if e["number"] == 5)
        assert metrics["trial_variant_ids"] == expected
        assert metrics["n_trials"] == 6
        assert metrics["trial_count"] == 6
        # Repeated observed Sharpes are still six trials: sample variance uses
        # ddof=1 over all six, not a deduplicated set of three values.
        assert metrics["trial_variance"] == pytest.approx(first_metrics["trial_variance"] * 4 / 5)


def test_failure_after_eval2_remains_in_next_run_cohort(offline_pipeline, tmp_path, monkeypatch):
    from pathlib import Path

    from factory import orchestrator
    from factory.trials import trial_cohort

    def fail(path, *args, on_eval2_started=None):
        if Path(path).stem == "A":
            on_eval2_started()
            raise RuntimeError("After Eval 2 started")
        return offline_pipeline(path, *args, on_eval2_started=on_eval2_started)

    monkeypatch.setattr(orchestrator, "evaluate_file", fail)
    first = orchestrator.run_paper("offline.pdf", output_root=tmp_path, run_id="first")
    assert first["status"] == "FAILED"
    with Records(tmp_path / "runs", read_only=True) as records:
        ids, values = trial_cohort(records)
        assert ids == ["first_A", "first_B", "first_C"]
        assert values[0] is None
        assert records.get("variants", "first_A")["reached_eval_2"] is True
    monkeypatch.setattr(orchestrator, "evaluate_file", offline_pipeline)
    second = orchestrator.run_paper("offline.pdf", output_root=tmp_path, run_id="second")
    for row in second["variants"]:
        result = next(e for e in row["evals"] if e["number"] == 5)
        assert result["passed"] is False
        assert len(result["metrics"]["trial_variant_ids"]) == 6


def test_conflicting_embedded_and_standalone_trial_metrics_fail_closed(tmp_path):
    from factory.trials import trial_cohort

    with Records(tmp_path) as records:
        add_run(records, "one")
        add_variant(
            records,
            "one",
            evals=[
                {"number": 2, "name": "friction", "passed": False, "metrics": {}},
                {
                    "number": 5,
                    "name": "deflated_sharpe",
                    "passed": False,
                    "metrics": {"daily_sharpe": 0.1},
                },
            ],
        )
        records.put(
            "eval_results",
            "one_A_5",
            "one",
            {
                "variant": "A",
                "number": 5,
                "name": "deflated_sharpe",
                "passed": False,
                "metrics": {"daily_sharpe": 0.9},
            },
        )
        assert trial_cohort(records) == (["one_A"], [None])


def test_failure_before_eval2_does_not_create_a_trial(offline_pipeline, tmp_path, monkeypatch):
    from pathlib import Path

    from factory import orchestrator
    from factory.trials import trial_cohort

    def fail(path, *args, **kwargs):
        if Path(path).stem == "A":
            raise RuntimeError("Before Eval 2")
        return offline_pipeline(path, *args, **kwargs)

    monkeypatch.setattr(orchestrator, "evaluate_file", fail)
    orchestrator.run_paper("offline.pdf", output_root=tmp_path, run_id="first")
    with Records(tmp_path / "runs", read_only=True) as records:
        assert trial_cohort(records)[0] == ["first_B", "first_C"]
        assert records.get("variants", "first_A")["reached_eval_2"] is False
