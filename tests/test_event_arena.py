"""Offline upload-to-arena acceptance with real storage, sandbox, evals and records."""

import hashlib
import json

import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from factory import orchestrator
from factory.agents import critic, worker
from factory.agents.records import Records
from factory.api.datasets import router
from factory.contract import StrategySpec
from factory.data import expected_index, load_bars, session_schedule, split_boundaries
from factory.data_contract.storage import read_dataset, write_dataset
from factory.evals import config
from factory.event_execution import decision_times
from factory.events import load_extra
from factory.llm import Completion
from factory.record_models import RECORD_MODELS
from factory.sandbox import run_strategy

STRATEGY = """import pandas as pd
FREQUENCY = "1day"
UNIVERSE = ["SPY"]
PARAMS = {"weight": WEIGHT}
EXTRA = ["uploaded_filings"]
def generate_signals(bars, params, extra=None):
    index = bars["SPY"].index
    filings = extra["uploaded_filings"]
    transactions = pd.to_datetime(filings["transaction_date"], utc=True)
    eligible = filings.loc[(transactions <= index[-1]) &
                           (filings["sessions_since_available"] >= 0)]
    weight = params["weight"] * len(eligible)
    return pd.DataFrame(weight, index=index[-1:], columns=UNIVERSE)
"""


def test_uploaded_events_complete_original_three_lane_arena(tmp_path, monkeypatch):
    """Only model completions are stubbed; performance outcomes are not prescribed."""
    data = tmp_path / "data"
    start, through = "2024-01-02", "2024-02-16"
    index = expected_index("1day", start, through)
    splits = split_boundaries(index)
    returns = np.resize(np.array([0.006, -0.004, 0.002, -0.003, 0.001]), len(index))
    closes = pd.Series(100 * np.cumprod(1 + returns), index=index)
    prices = pd.DataFrame({field: closes for field in ("open", "high", "low", "close")})
    prices["volume"], prices["is_filled"] = 100.0, False
    write_dataset(
        data / "1day/SPY.parquet",
        prices,
        kind="price_bars",
        frequency="1day",
        start=start,
        through=through,
        source="offline synthetic integration fixture",
        feed="sip",
        adjustment="all",
    )
    (data / "1day/manifest.json").write_text(
        json.dumps(
            {
                "frequency": "1day",
                "start": start,
                "through": through,
                "feed": "sip",
                "adjustment": "all",
                "symbols": ["SPY"],
                "complete": True,
                "splits": splits,
            }
        )
    )
    schedule = session_schedule(start, through)
    first_disclosure = schedule.open.iloc[3]
    oos_start = pd.Timestamp(splits["OOS"]["start"])
    holdout_start = pd.Timestamp(splits["HOLDOUT"]["start"])
    oos_disclosure = schedule.open.iloc[index.get_loc(oos_start)]
    holdout_disclosure = schedule.open.iloc[index.get_loc(holdout_start)]
    content = (
        "released,ticker,transaction_date,marker\n"
        f"{first_disclosure.isoformat()},SPY,2000-01-01,IS_DISCLOSURE\n"
        f"{oos_disclosure.isoformat()},SPY,2000-01-01,OOS_DISCLOSURE\n"
        f"{holdout_disclosure.isoformat()},SPY,2000-01-01,HOLDOUT_DISCLOSURE\n"
    )
    app = FastAPI()
    app.state.root = tmp_path
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post(
            "/api/data/upload",
            files={"file": ("filings.csv", content, "text/csv")},
            data={
                "name": "uploaded_filings",
                "mapping": json.dumps({"available_at": "released", "symbol": "ticker"}),
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["kind"] == "events"
        assert response.json()["verified"] is False
        preview = client.get(f"/api/data/datasets/{response.json()['id']}/preview").json()
        assert {row["marker"] for row in preview["rows"]} == {"IS_DISCLOSURE", "OOS_DISCLOSURE"}
        assert preview["holdout_sealed"] is True

    event_file = data / "events/uploaded_filings.parquet"
    manifest = json.loads(event_file.with_suffix(".manifest.json").read_text())
    assert manifest["sha256"] == hashlib.sha256(event_file.read_bytes()).hexdigest()
    assert manifest["kind"] == "events" and manifest["frequency"] == "event"
    assert len(read_dataset(event_file, expected={"kind": "events"})) == 3
    stored_fingerprints = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in data.rglob("*")
        if path.is_file()
    }

    # Configuration is local to this test; no SDK or real provider is invoked.
    monkeypatch.setenv("WORKER_MODEL", "openai:offline-fixture")
    monkeypatch.setenv("CRITIC_MODEL", "openai:offline-fixture")
    worker_requests, critic_requests = [], []

    def complete_worker(role, system, user, **kwargs):
        payload = json.loads(user)
        worker_requests.append(payload)
        assert role == "worker" and "error" not in payload, "Fixture must not need self-heal"
        variant = next(
            key for key, description in worker.VARIANTS.items() if description == payload["variant"]
        )
        weight = {"A": "0.2", "B": "0.3", "C": "0.4"}[variant]
        return Completion(STRATEGY.replace("WEIGHT", weight), "openai:offline-fixture", 1, 1, 0, 0)

    def complete_critic(role, system, user, **kwargs):
        critic_requests.append(json.loads(user))
        assert role == "critic"
        return Completion(
            '{"review_topics":["data_availability"]}', "openai:offline-fixture", 1, 1, 0, 0
        )

    monkeypatch.setattr(worker, "complete", complete_worker)
    monkeypatch.setattr(critic, "complete", complete_critic)
    spec = StrategySpec(
        paper_id="uploaded_event_acceptance",
        title="Offline disclosed-event acceptance fixture",
        category="event",
        hypothesis="Exposure begins only after each event becomes available.",
        universe=["SPY"],
        frequency="1day",
        signal_rules=["Increase SPY exposure after each visible filing; remain flat beforehand."],
        claimed_metrics={},
        ambiguities=[],
        source_kind="described",
        test_type="original",
        extra=["uploaded_filings"],
        notes=["unverified source"],
    )
    result = orchestrator.run_spec(spec, data_root=data, output_root=tmp_path)
    assert result["status"] == "COMPLETED", result
    assert len(worker_requests) == len(critic_requests) == 3
    for payload in worker_requests:
        context = payload["data_context"]
        assert context["split"] == "IS"
        assert all(pd.Timestamp(row["timestamp"]) < oos_start for row in context["example_rows"])
        assert {row["marker"] for row in context["events"]["uploaded_filings"]["example_rows"]} == {
            "IS_DISCLOSURE"
        }
        assert "OOS_DISCLOSURE" not in json.dumps(payload)
        assert "HOLDOUT_DISCLOSURE" not in json.dumps(payload)

    is_bars = load_bars(data, "1day", ["SPY"], split="IS", allow_empty_symbols=True)
    oos_bars = load_bars(data, "1day", ["SPY"], split="OOS", allow_empty_symbols=True)
    all_visible_events = load_extra(
        data, ["uploaded_filings"], as_of=decision_times(oos_bars, "1day").max()
    )
    path = tmp_path / "strategies" / spec.paper_id / result["run_id"] / "A.py"
    weights = run_strategy(path, is_bars, extra=all_visible_events)
    # The candidate intentionally trusts old transaction dates. Even when supplied
    # OOS events, the real sandbox cannot expose either disclosure prematurely.
    assert weights.SPY.iloc[:3].eq(0).all()
    assert weights.SPY.iloc[3:].eq(0.2).all()
    assert weights.index.equals(is_bars["SPY"].index)

    variant_ids = {row["variant_id"] for row in result["variants"]}
    assert {row["variant"] for row in result["variants"]} == {"A", "B", "C"}
    for row in result["variants"]:
        assert row["source_kind"] == "described" and row["test_type"] == "original"
        assert row["days_traded"] == len(is_bars["SPY"]) - 3 >= 5
        evals = {item["number"]: item for item in row["evals"]}
        assert set(evals) == {1, 2, 3, 4, 5}
        assert evals[1]["passed"] is True
        assert [cut["fraction"] for cut in evals[1]["metrics"]["cuts"]] == list(
            config.LOOKAHEAD_CUT_FRACTIONS
        )
        assert set(evals[5]["metrics"]["trial_variant_ids"]) == variant_ids
        assert evals[5]["metrics"]["trial_count"] == 3
        assert row["reached_eval_2"] is True
        assert row["evals_passed"] == sum(item["passed"] for item in evals.values())
        failed = [number for number in sorted(evals) if not evals[number]["passed"]]
        assert row["status"] == (f"FAILED_EVAL_{failed[0]}" if failed else "VERIFIED")
        assert row["equity"]["gross"][:4] == [1.0] * 4  # Includes engine execution lag.
        for split in ("IS", "OOS"):
            assert set(row["cost_sharpes"][split]) == {
                f"{cost:g}" for cost in config.FRICTION_BPS_GRID
            }
        assert "unverified source" in row["notes"]

    with Records(tmp_path / "runs", read_only=True) as records:
        for table, model in RECORD_MODELS.items():
            for payload in records.list(table):
                model.model_validate(payload)
        assert len(records.list("variants")) == 3
        assert len(records.list("eval_results")) == 15
        assert records.list("heal_attempts") == []
        assert records.get("runs", result["run_id"])["status"] == "COMPLETED"
        events = records.list("events")
        assert events[-1]["stage"] == "done"
    mirrored = [
        json.loads(line) for line in (tmp_path / "runs/events.jsonl").read_text().splitlines()
    ]
    assert mirrored == events
    assert stored_fingerprints == {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in stored_fingerprints
    }
