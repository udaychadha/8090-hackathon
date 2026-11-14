"""Original specifications share the paper arena without extraction or verdict tuning."""

import pytest

from factory import orchestrator
from factory.agents.records import Records
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


def test_harness_retry_reuses_only_void_candidates_without_performance(
    request, monkeypatch, tmp_path
):
    _, normal_heal, _ = request.getfixturevalue("run_fixture")

    def rejected(*args, **kwargs):
        normal_heal(*args, **kwargs)
        return None, []

    monkeypatch.setattr(orchestrator, "validate_and_heal", rejected)
    first = orchestrator.run_spec(original(), output_root=tmp_path)
    with Records(tmp_path / "runs") as records:
        records.void_run(first["run_id"], "Synthetic pre-eval harness defect")
    monkeypatch.setattr(orchestrator, "validate_and_heal", normal_heal)
    monkeypatch.setattr(orchestrator, "propose_parallel", lambda *a: pytest.fail("No regeneration"))
    retry = orchestrator.run_spec(original(), output_root=tmp_path, retained_run_id=first["run_id"])
    assert retry["status"] == "COMPLETED"
    assert all(row["evals_passed"] == 5 for row in retry["variants"])
    assert all("Candidate retained" in " ".join(row["notes"]) for row in retry["variants"])

    # Even void status cannot authorize replaying a measured strategy as if it
    # had never reached performance evaluation.
    with Records(tmp_path / "runs") as records:
        records.void_run(retry["run_id"], "Synthetic audit invalidation")
    forbidden = orchestrator.run_spec(
        original(), output_root=tmp_path, retained_run_id=retry["run_id"]
    )
    assert forbidden["status"] == "FAILED" and forbidden["error_type"] == "ValueError"
