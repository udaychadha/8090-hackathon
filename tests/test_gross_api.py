"""Gross evidence is exposed separately without changing authoritative verdicts."""

from factory.agents.test_worker import spec
from factory.api.views import leaderboard_row
from factory.orchestrator import _row


def diagnostic():
    return {
        "schema_version": "1.0.0",
        "state": "complete",
        "cost_bps": 0,
        "eval_3": {
            "number": 3,
            "name": "sensitivity",
            "passed": True,
            "metrics": {
                "cost_bps": 0,
                "base_sharpe": 1.2,
                "worst_sharpe": 0.9,
                "worst_ratio": 0.75,
            },
        },
        "eval_4": {
            "number": 4,
            "name": "decay",
            "passed": True,
            "metrics": {
                "cost_bps": 0,
                "is_sharpe": 1.2,
                "oos_sharpe": 0.8,
                "oos_to_is_ratio": 2 / 3,
                "is_max_window_share": 0.2,
                "oos_max_window_share": 0.3,
            },
        },
        "label": "signal before costs",
        "reason": None,
    }


def test_gross_projection_preserves_failed_authoritative_verdict():
    row = _row(spec(), "r_gross", "A")
    row.update(
        status="FAILED_EVAL_2",
        default_status="FAILED_EVAL_2",
        evals_passed=2,
        default_evals_passed=2,
        gross_diagnostics=diagnostic(),
    )
    projected = leaderboard_row(row)
    assert projected["gross_diagnostics"] == diagnostic()
    assert projected["status"] == projected["default_status"] == "FAILED_EVAL_2"
    assert projected["evals_passed"] == projected["default_evals_passed"] == 2
    assert "Failed Eval 2" in projected["summary"]


def test_legacy_projection_has_no_invented_gross_measurements():
    row = _row(spec(), "r_gross", "A")
    row.pop("gross_diagnostics", None)
    assert leaderboard_row(row)["gross_diagnostics"] is None


def test_http_gross_evidence_matches_both_views_and_old_records_stay_readable(tmp_path):
    from fastapi.testclient import TestClient

    from factory.agents.records import Records
    from factory.api.app import create_app

    with Records(tmp_path / "runs") as records:
        records.put("runs", "r_gross", "r_gross", {"run_id": "r_gross", "status": "COMPLETED"})
        for lane in "AB":
            row = _row(spec(), "r_gross", lane)
            row.update(
                status="FAILED_EVAL_2",
                default_status="FAILED_EVAL_2",
                evals_passed=2,
                default_evals_passed=2,
            )
            row["evals"] = [
                {"number": 1, "name": "lookahead", "passed": True, "metrics": {}},
                {"number": 2, "name": "friction", "passed": False, "metrics": {}},
                {"number": 3, "name": "sensitivity", "passed": True, "metrics": {}},
            ]
            row.pop("gross_diagnostics", None)
            if lane == "A":
                row["gross_diagnostics"] = diagnostic()
            records.put("variants", row["variant_id"], "r_gross", row)
    with TestClient(create_app(tmp_path)) as client:
        response = client.get("/api/leaderboard")
        assert response.status_code == 200
        rows = {row["variant"]: row for row in response.json()["rows"]}
        assert rows["A"]["gross_diagnostics"]["eval_3"]["metrics"]["base_sharpe"] == 1.2
        assert rows["B"]["gross_diagnostics"] is None
        detail = client.get("/api/variants/r_gross_A").json()
        assert detail["gross_diagnostics"] == rows["A"]["gross_diagnostics"]
        assert detail["status"] == detail["default_status"] == "FAILED_EVAL_2"
        assert detail["evals_passed"] == 2
        assert [e["n"] for e in detail["evals"]] == [1, 2, 3]
        assert detail["evals"][2]["metrics"] == {}  # Gross evidence stays separate.
        assert client.get("/api/variants/r_gross_B").json()["gross_diagnostics"] is None
