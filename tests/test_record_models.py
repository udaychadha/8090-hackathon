"""Typed storage rejects malformed new records, including nested evidence."""

import importlib.util

import pytest
from pydantic import ValidationError


def test_records_have_one_typed_model_module():
    assert importlib.util.find_spec("factory.record_models") is not None


def test_invalid_status_nested_metric_and_unknown_fields_are_rejected(tmp_path):
    from factory.agents.records import Records

    store = Records(tmp_path)
    for payload in [
        {"run_id": "r", "status": "WON"},
        {"run_id": "r", "status": "RUNNING", "mystery": 1},
        {"run_id": "r", "status": "RUNNING", "wall_seconds": float("nan")},
        {"run_id": "r", "status": "RUNNING", "cost_complete": "yes"},
    ]:
        with pytest.raises((ValueError, ValidationError)):
            store.put("runs", "r", "r", payload)
    assert store.db.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
    store.close()


def test_identity_mismatch_is_rejected(tmp_path):
    from factory.agents.records import Records

    store = Records(tmp_path)
    with pytest.raises(ValueError, match="identity"):
        store.put("runs", "r", "r", {"run_id": "different", "status": "RUNNING"})
    store.close()


def test_every_schema_field_has_description():
    from factory.record_models import RECORD_MODELS

    for model in RECORD_MODELS.values():
        schema = model.model_json_schema()
        for definition in [schema, *schema.get("$defs", {}).values()]:
            if definition.get("title") in {"StrategySpec", "ClaimedMetrics"}:
                continue  # Imported canonical strategy contract is unchanged.
            for name, field in definition.get("properties", {}).items():
                assert field.get("description"), (definition.get("title"), name)


def test_strict_metrics_and_equity_are_typed():
    from factory.record_models import Equity, EvalMetrics

    with pytest.raises(ValidationError):
        Equity.model_validate(
            {
                "dates": ["2026-01-01"],
                "gross": [1.0],
                "net": [],
                "is_end": "2026-01-01",
                "oos_end": "2026-01-01",
            }
        )
    with pytest.raises(ValidationError):
        EvalMetrics.model_validate(
            {"jitters": [{"param": "lookback", "fraction": 0.1, "value": 10, "sharpe": "garbage"}]}
        )
    with pytest.raises(ValidationError):
        EvalMetrics.model_validate({"dsr": float("inf")})


def test_source_year_precision_and_strict_claimed_metric():
    from factory.agents.test_worker import spec
    from factory.record_migration import prepare
    from factory.record_models import Provenance, Source

    assert Provenance.model_validate({"version_date": "2018"}).version_date == "2018"
    value = prepare(
        "sources",
        spec().paper_id,
        "r",
        {
            "source_id": spec().paper_id,
            "title": spec().title,
            "source_kind": "paper",
            "spec": spec().model_dump(),
            "provenance": {},
        },
    )
    value["spec"]["claimed_metrics"]["sharpe"] = "123.456"
    with pytest.raises(ValidationError):
        Source.model_validate(value)


def test_activity_counts_cannot_exceed_observed_bars():
    from factory.record_models import Activity

    with pytest.raises(ValidationError):
        Activity.model_validate({"active_bars": 100, "total_bars": 1, "days_traded": 1000})


def test_variant_verdict_counts_must_match_evidence(tmp_path):
    from factory.agents.records import Records
    from factory.agents.test_worker import spec
    from factory.orchestrator import _row

    with Records(tmp_path) as store:
        row = _row(spec(), "r", "A")
        row.update(status="VERIFIED", evals_passed=5)
        with pytest.raises(ValueError):
            store.put("variants", "r_A", "r", row)
        row.update(
            status="FAILED_EVAL_2",
            evals_passed=2,
            evals=[{"number": 1, "name": "lookahead", "passed": True, "metrics": {}}],
        )
        with pytest.raises(ValueError):
            store.put("variants", "r_A", "r", row)


def test_void_flag_cannot_hide_nonvoid_run(tmp_path):
    from factory.agents.records import Records

    with Records(tmp_path) as records:
        with pytest.raises(ValueError):
            records.put("runs", "r", "r", {"run_id": "r", "status": "RUNNING", "voided": True})
