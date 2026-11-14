"""Storage query boundaries preserve eligibility, types and relational identity."""

import pytest

from factory.agents.records import Records


def test_filters_and_order_use_projected_fields(tmp_path):
    with Records(tmp_path) as records:
        for run_id, status, source_id in [
            ("r_a", "RUNNING", "p_a"),
            ("r_b", "FAILED", "p_a"),
            ("r_c", "FAILED", "p_b"),
        ]:
            records.put(
                "runs",
                run_id,
                run_id,
                {
                    "run_id": run_id,
                    "status": status,
                    "source_id": source_id,
                },
            )
        rows = records.list("runs", source_id="p_a", status="FAILED", sort_by="id")
        assert [r["id"] for r in rows] == ["r_b"]
        assert [r["id"] for r in records.list("runs", sort_by="id", descending=True)] == [
            "r_c",
            "r_b",
            "r_a",
        ]
        with pytest.raises(ValueError):
            records.list("runs", sort_by="id; DROP TABLE runs")
        assert len(records.list("runs")) == 3


def test_void_hides_child_events_and_critique_by_default(tmp_path):
    with Records(tmp_path) as records:
        records.put("runs", "r", "r", {"run_id": "r", "status": "FAILED"})
        records.event("r", "done", "failed", "Run failed")
        records.put("critiques", "r_A", "r", {"variant": "A", "text": "Retained narrative"})
        records.void_run("r", "Invalidated fixture")
        assert records.get("runs", "r") is None
        assert records.get("critiques", "r_A") is None
        assert records.events("r") == []
        assert records.list("critiques") == []
        assert records.get("critiques", "r_A", include_voided=True)["text"] == "Retained narrative"
        assert len(records.events("r", include_voided=True)) == 2


def test_child_source_must_match_known_parent(tmp_path):
    with Records(tmp_path) as records:
        records.put(
            "runs",
            "r",
            "r",
            {
                "run_id": "r",
                "status": "RUNNING",
                "source_id": "p_a",
            },
        )
        with pytest.raises(ValueError, match="source identity"):
            records.put(
                "critiques",
                "r_A",
                "r",
                {
                    "variant": "A",
                    "text": "Narrative",
                    "source_id": "p_other",
                },
            )
        assert records.list("critiques") == []


def test_invalid_types_cannot_be_hidden_by_redaction(tmp_path):
    class Stringable:
        def __str__(self):
            return "Looks like text"

    with Records(tmp_path) as records:
        with pytest.raises(ValueError):
            records.event("r", "worker", "started", Stringable())
        assert records.events(include_voided=True) == []


def test_tampered_projection_fails_before_read(tmp_path):
    with Records(tmp_path) as records:
        records.put("runs", "r", "r", {"run_id": "r", "status": "FAILED"})
        records.db.execute("UPDATE runs SET status='COMPLETED' WHERE id='r'")
        records.db.commit()
        with pytest.raises(ValueError, match="index mismatch"):
            records.get("runs", "r")


def test_validation_errors_do_not_expose_rejected_inputs(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-invalid-status")
    with Records(tmp_path) as records:
        with pytest.raises(ValueError) as failure:
            records.put(
                "runs",
                "r",
                "r",
                {
                    "run_id": "r",
                    "status": "secret-invalid-status",
                },
            )
        assert "secret-invalid-status" not in str(failure.value)
        assert "status" in str(failure.value)
        assert records.list("runs") == []
