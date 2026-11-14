"""Extraction schema and rejected-response accounting, without provider calls."""

import hashlib
import json

import pytest

from factory import orchestrator
from factory.agents import extractor
from factory.agents.records import Records, usage_record
from factory.contract import StrategySpec
from factory.data_contract.generated import SPEC
from factory.llm import Completion, LLMError

PAPER = "private paper text sentinel"
RESPONSE_SENTINEL = "private response sentinel"


def spec_payload(**changes):
    return {
        "paper_id": "p_" + hashlib.sha256(PAPER.encode()).hexdigest()[:16],
        "title": "Example",
        "category": "reversal",
        "hypothesis": "Example hypothesis",
        "universe": ["SPY"],
        "frequency": "1day",
        "signal_rules": ["Example rule"],
        "claimed_metrics": {},
        "ambiguities": ["Sizing unknown"],
        "test_type": "replication",
        **changes,
    }


def completion(payload, cost=0.125):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return Completion(text, "openai:offline", 1200, 300, 2.5, cost)


def test_full_daily_universe_roundtrips_without_a_size_limit(monkeypatch):
    symbols = ["BRK.B", "BF.B"] + [f"S{number:04}" for number in range(505)]
    result = completion(spec_payload(universe=symbols))
    monkeypatch.setattr(extractor, "complete", lambda *a, **kw: result)
    spec, usage = extractor.extract_text(PAPER, {"1day": symbols})
    assert spec.universe == symbols and len(spec.universe) == 507
    assert usage is result


def test_universe_schema_exposes_symbol_syntax_and_uniqueness():
    universe = StrategySpec.model_json_schema()["properties"]["universe"]
    assert universe["uniqueItems"] is True
    assert (
        universe["items"]["pattern"]
        == SPEC["ontology"]["Instrument"]["fields"]["symbol"]["pattern"]
    )


@pytest.mark.parametrize("symbols", [["BRK.B", "BRK.B"], ["BRK-B"], ["bf.b"]])
def test_bad_universe_reports_safe_field_diagnostics_and_usage(monkeypatch, symbols):
    result = completion(spec_payload(universe=symbols, title=RESPONSE_SENTINEL))
    monkeypatch.setattr(extractor, "complete", lambda *a, **kw: result)
    with pytest.raises(extractor.ExtractionError) as caught:
        extractor.extract_text(PAPER, {"1day": ["BRK.B", "BF.B"]})
    error = caught.value
    assert error.usages == [usage_record(result)]
    assert error.diagnostics
    assert error.diagnostics[0]["loc"][0] == "universe"
    assert set(error.diagnostics[0]) == {"loc", "type", "msg"}
    assert "fields" in str(error)
    serialized = json.dumps(vars(error)) + str(error)
    assert RESPONSE_SENTINEL not in serialized and PAPER not in serialized
    assert "text" not in error.usages[0]


@pytest.mark.parametrize("invalid_json", [True, False])
def test_diagnostics_never_include_response_values_or_arbitrary_field_names(
    monkeypatch, invalid_json
):
    secret = "secret-test-sentinel-long"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    raw = (
        ("{" + RESPONSE_SENTINEL + secret)
        if invalid_json
        else spec_payload(universe=[secret], **{RESPONSE_SENTINEL: PAPER})
    )
    result = completion(raw)
    monkeypatch.setattr(extractor, "complete", lambda *a, **kw: result)
    with pytest.raises(extractor.ExtractionError) as caught:
        extractor.extract_text(PAPER, {"1day": ["SPY"]})
    error = caught.value
    assert error.usages == [usage_record(result)]
    assert error.diagnostics
    assert (error.diagnostics[0]["type"] == "json_invalid") is invalid_json
    safe = json.dumps(vars(error)) + str(error)
    for forbidden in (secret, RESPONSE_SENTINEL, PAPER):
        assert forbidden not in safe


def test_extraction_error_redacts_accounting_metadata(monkeypatch):
    secret = "configured-secret-sentinel"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    result = Completion(RESPONSE_SENTINEL, "openai:" + secret, 1, 2, 0.1, 0.01)
    error = extractor.ExtractionError("Rejected " + secret, completion=result)
    assert secret not in str(error) + json.dumps(vars(error))
    assert RESPONSE_SENTINEL not in json.dumps(vars(error))


@pytest.mark.parametrize("stage", ["parse", "identity", "replication"])
@pytest.mark.parametrize("cost", [0.125, None])
def test_orchestrator_accounts_for_rejected_completed_extraction(
    monkeypatch, tmp_path, stage, cost
):
    if stage == "parse":
        raw = spec_payload(universe=["SPY", "SPY"], title=RESPONSE_SENTINEL)
    elif stage == "identity":
        raw = spec_payload(paper_id="p_wrong", title=RESPONSE_SENTINEL)
    else:
        raw = spec_payload(universe=["OTHER"], title=RESPONSE_SENTINEL)
    result = completion(raw, cost)
    monkeypatch.setattr(orchestrator, "model_for", lambda role: ("openai", "offline"))
    monkeypatch.setattr(extractor, "paper_text", lambda path: PAPER)
    monkeypatch.setattr(extractor, "catalog", lambda root: {"1day": ["SPY"]})
    monkeypatch.setattr(extractor, "complete", lambda *a, **kw: result)
    outcome = orchestrator.run_paper("offline.pdf", output_root=tmp_path)
    assert outcome["status"] == "FAILED"
    assert outcome["usage"] == [usage_record(result)]
    assert outcome["cost_complete"] is (cost is not None)
    assert outcome["estimated_model_cost_usd"] == cost
    assert bool(outcome.get("extraction_diagnostics")) is (stage == "parse")
    records = Records(tmp_path / "runs")
    try:
        stored = json.loads(records.db.execute("SELECT payload FROM runs").fetchone()[0])
        assert stored == outcome
        text = "\n".join(records.db.iterdump()) + (tmp_path / "runs/events.jsonl").read_text()
        assert RESPONSE_SENTINEL not in text and PAPER not in text
    finally:
        records.close()


@pytest.mark.parametrize(
    "error",
    [
        extractor.ExtractionError("Missing paper"),
        LLMError("Provider failed"),
        RuntimeError("Unknown failure"),
    ],
)
def test_precompletion_failure_keeps_cost_unknown(monkeypatch, tmp_path, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(orchestrator, "model_for", lambda role: ("openai", "offline"))
    monkeypatch.setattr(orchestrator, "extract", fail)
    outcome = orchestrator.run_paper("offline.pdf", output_root=tmp_path)
    assert outcome["status"] == "FAILED" and outcome["usage"] == []
    assert outcome["cost_complete"] is False
    assert outcome["estimated_model_cost_usd"] is None
