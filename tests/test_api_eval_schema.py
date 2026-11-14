"""Displayed eval rules must use the real locked configuration."""

from fastapi import FastAPI
from fastapi.testclient import TestClient


def client():
    from factory.api.eval_schema import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_schema_uses_runtime_configuration_without_rejudging(monkeypatch):
    from factory.evals import config

    monkeypatch.setattr(config, "FRICTION_MIN_SHARPE", 0.73)
    monkeypatch.setattr(config, "LOOKAHEAD_CUT_FRACTIONS", (0.25, 0.75))
    response = client().get("/api/evals/schema")
    assert response.status_code == 200
    schema = response.json()
    assert len(schema["evals"]) == 5
    assert schema["readonly"] is True
    assert schema["constants"]["LOOKAHEAD_CUT_FRACTIONS"] == [0.25, 0.75]
    friction = schema["evals"][1]
    check = next(item for item in friction["checks"] if item["key"] == "FRICTION_MIN_SHARPE")
    assert check["default"] == check["min"] == check["max"] == 0.73
    assert check["locked"] is True
    assert all(e["question"] and e["source_code"] for e in schema["evals"])


def test_only_default_profile_can_be_read_and_nothing_can_be_changed():
    api = client()
    profile = api.get("/api/evals/profiles/default").json()
    assert profile["editable"] is False and profile["stale"] is False
    assert profile["values"]["BASE_COST_BPS"] == 5.0
    assert api.get("/api/evals/profiles/custom").status_code == 404
    rejected = api.put("/api/evals/profiles/default", json={"BASE_COST_BPS": 1})
    assert rejected.status_code == 501
    assert rejected.json()["detail"] == "not available yet"
    assert api.get("/api/evals/profiles/default").json() == profile


def test_decay_describes_multiplication_instead_of_a_sign_sensitive_ratio():
    decay = client().get("/api/evals/schema").json()["evals"][3]
    check = next(item for item in decay["checks"] if item["key"] == "DECAY_MIN_RATIO")
    assert check["metric"] == "oos_sharpe"
    assert check["relative_to"] == "is_sharpe"
    assert check["op"] == ">="
    # A negative IS Sharpe does not reverse the harness's comparison.
    assert 0.2 >= check["default"] * -0.5


def test_owner_revision_exposes_positive_is_and_global_trial_rules():
    schema = client().get("/api/evals/schema").json()
    decay = schema["evals"][3]
    positive_is = next(c for c in decay["checks"] if c["key"] == "IS_SHARPE_POSITIVE")
    assert positive_is["metric"] == "is_sharpe" and positive_is["op"] == ">"
    assert positive_is["default"] == 0 and positive_is["locked"]
    notes = " ".join(schema["evals"][4]["notes"])
    assert "all runs" in notes and "control" in notes
