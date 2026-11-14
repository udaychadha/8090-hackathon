"""Offline WO-05 checks; these are not real-paper acceptance tests."""
import hashlib
import json

import pytest

from factory import llm
from factory.agents import extractor


def response(text="paper", **overrides):
    spec = {
        "paper_id": "p_" + hashlib.sha256(text.encode()).hexdigest()[:16],
        "title": "Example", "category": "momentum", "hypothesis": "Trend persists",
        "universe": ["SPY"], "frequency": "1day", "signal_rules": ["Prior trend"],
        "claimed_metrics": {}, "ambiguities": ["Position sizing unspecified"],
        "test_type": "replication", **overrides,
    }
    return llm.Completion(json.dumps(spec), "openai:test", 10, 20, .1, None)


def test_role_selection(monkeypatch):
    for provider in ("openai", "anthropic"):
        monkeypatch.setenv("EXTRACTOR_MODEL", f"{provider}:configured")
        assert llm.model_for("extractor") == (provider, "configured")
    monkeypatch.delenv("EXTRACTOR_MODEL", raising=False)
    with pytest.raises(llm.LLMError, match="Set EXTRACTOR_MODEL"):
        llm.model_for("extractor")


def test_valid_spec_and_prompt_boundary(monkeypatch):
    def fake(role, system, user):
        payload = json.loads(user)
        assert role == "extractor"
        assert set(payload) == {"schema", "paper_id", "available_price_tiers", "paper_text"}
        assert "untrusted" in system
        return response()
    monkeypatch.setattr(extractor, "complete", fake)
    spec, usage = extractor.extract_text("paper", {"1day": ["SPY"]})
    assert spec.ambiguities and spec.test_type == "replication"
    assert usage.cost_usd is None


@pytest.mark.parametrize("overrides", [
    {"ambiguities": []}, {"paper_id": "wrong"}, {"test_type": "VERIFIED"},
    {"universe": ["NOTAVAILABLE"]},
])
def test_reject_invalid_or_false_replication(monkeypatch, overrides):
    monkeypatch.setattr(extractor, "complete", lambda *args: response(**overrides))
    with pytest.raises(extractor.ExtractionError):
        extractor.extract_text("paper", {"1day": ["SPY"]})


def test_missing_paper(tmp_path):
    with pytest.raises(extractor.ExtractionError, match="owner-supplied"):
        extractor.pdf_text(tmp_path / "absent.pdf")


def test_explicit_cost_only(monkeypatch):
    monkeypatch.delenv("EXTRACTOR_INPUT_USD_PER_MTOK", raising=False)
    monkeypatch.delenv("EXTRACTOR_OUTPUT_USD_PER_MTOK", raising=False)
    assert llm._cost("extractor", 10, 20) is None
    monkeypatch.setenv("EXTRACTOR_INPUT_USD_PER_MTOK", "1")
    monkeypatch.setenv("EXTRACTOR_OUTPUT_USD_PER_MTOK", "2")
    assert llm._cost("extractor", 1_000_000, 1_000_000) == 3
    assert llm._cost("extractor", 10, 20, cached=1) is None
    monkeypatch.setenv("EXTRACTOR_OUTPUT_USD_PER_MTOK", "nan")
    with pytest.raises(llm.LLMError):
        llm._cost("extractor", 1, 1)
