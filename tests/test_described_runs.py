"""Original specifications share the paper arena without extraction or verdict tuning."""

import pytest

from factory import orchestrator
from factory.agents.test_worker import spec
from factory.contract import StrategySpec
from tests.test_orchestration_regressions import run_fixture  # noqa: F401

pytestmark = pytest.mark.usefixtures("run_fixture")


def original(**changes):
    return StrategySpec.model_validate(
        {
            **spec().model_dump(),
            "source_kind": "described",
            "test_type": "original",
            "ambiguities": [],
            "notes": ["unverified source"],
            **changes,
        }
    )


def test_described_uses_same_three_lane_arena_without_extractor(monkeypatch, tmp_path):
    monkeypatch.delenv("EXTRACTOR_MODEL")
    monkeypatch.setattr(orchestrator, "extract", lambda *a, **kw: pytest.fail("No PDF extraction"))
    result = orchestrator.run_spec(original(), output_root=tmp_path)
    assert result["status"] == "COMPLETED"
    assert result["source"]["source_kind"] == "described"
    assert len(result["variants"]) == 3
    for row in result["variants"]:
        assert row["test_type"] == "original" and row["source_kind"] == "described"
        assert len(row["evals"]) == 5
        assert "unverified source" in row["notes"]
        assert any("survivorship" in note for note in row["notes"])


def test_short_sample_preserves_passes_but_prohibits_verified(tmp_path):
    result = orchestrator.run_spec(
        original(
            verification_eligible=False,
            eligibility_reason="short sample: not a verdict",
        ),
        output_root=tmp_path,
    )
    assert result["status"] == "COMPLETED"
    for row in result["variants"]:
        assert row["evals_passed"] == 5
        assert row["status"] == row["default_status"] == "INSUFFICIENT_SAMPLE"
        assert "short sample: not a verdict" in row["notes"]
        assert not row["verification_eligible"]


def test_missing_event_dataset_blocks_before_generation(monkeypatch, tmp_path):
    monkeypatch.setattr(orchestrator, "propose_parallel", lambda *a: pytest.fail("Missing events"))
    result = orchestrator.run_spec(
        original(extra=["missing_events"]), data_root=tmp_path / "data", output_root=tmp_path
    )
    assert result["status"] == "BLOCKED_DATA"
    assert any(need["kind"] == "events" for need in result["data_needs"])
    assert all(row["status"] == "BLOCKED_DATA" for row in result["variants"])
