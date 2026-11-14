"""Event upload, immutable storage, and disclosure visibility boundaries."""

import json

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_api_data import data_root as price_data_root


@pytest.fixture
def data_root(tmp_path):
    return price_data_root.__wrapped__(tmp_path)


def client_for(root):
    from factory.api.datasets import router

    app = FastAPI()
    app.state.root = root
    app.include_router(router)
    return TestClient(app)


def upload(client, text, name="filings", mapping=None):
    return client.post(
        "/api/data/upload",
        files={"file": ("events.csv", text, "text/csv")},
        data={
            "name": name,
            "mapping": json.dumps(mapping or {"available_at": "disclosed", "symbol": "ticker"}),
        },
    )


def test_upload_preserves_free_fields_and_load_extra_gates_availability(data_root):
    from factory.events import load_extra

    client = client_for(data_root)
    body = (
        "disclosed,ticker,transaction_date,amount\n"
        "2024-06-03T14:00:00Z,SPY,2024-01-01,20\n"
        "2024-06-12T21:00:00Z,SPY,2023-01-01,30\n"
    )
    response = upload(client, body)
    assert response.status_code == 200, response.text
    dataset = response.json()
    assert dataset["frequency"] is None and not dataset["verified"]
    assert "unverified source" in dataset["notes"]
    visible = load_extra(
        data_root / "data", ["filings"], as_of=pd.Timestamp("2024-06-04T20:00:00Z")
    )
    assert visible["filings"]["transaction_date"].tolist() == ["2024-01-01"]
    assert visible["filings"].amount.tolist() == [20]
    empty = load_extra(data_root / "data", ["filings"], as_of=pd.Timestamp("2020-01-01T00:00Z"))
    assert empty["filings"].empty and "amount" in empty["filings"]
    assert upload(client, body).status_code == 409
    detail = client.get(f"/api/data/datasets/{dataset['id']}").json()
    assert "available_at" in detail["fields"] and "amount" in detail["fields"]
    assert all(not item["name"].endswith(".parquet") for item in detail["artifacts"])
    preview = client.get(f"/api/data/datasets/{dataset['id']}/preview").json()
    assert len(preview["rows"]) == 1  # June 12 after close lies after stored OOS end.
    assert preview["gaps"] == [] and preview["coverage"]["expected_rows"] is None


@pytest.mark.parametrize(
    "body,mapping",
    [
        ("disclosed,ticker\n2024-06-03,SPY\n", None),
        ("disclosed,ticker\n2024-06-03T14:00:00,SPY\n", None),
        ("disclosed,ticker\nNaT,SPY\n", None),
        ("disclosed,ticker,x\n2024-06-03T14:00Z,SPY,NaN\n", None),
        ("disclosed,ticker,x\n2024-06-03T14:00Z,SPY,\n", None),
        ("disclosed,ticker,ticker\n2024-06-03T14:00Z,SPY,QQQ\n", None),
        ("disclosed,ticker,symbol\n2024-06-03T14:00Z,SPY,SPY\n", None),
        ("disclosed,ticker\n2024-06-03T14:00Z,SPY\n", {"available_at": "disclosed"}),
    ],
)
def test_upload_rejects_ambiguous_or_invalid_inputs(tmp_path, body, mapping):
    assert upload(client_for(tmp_path), body, mapping=mapping).status_code == 422
    assert not list(tmp_path.glob("data/events/*.parquet"))


def test_upload_size_name_and_symlinks_fail_closed(tmp_path):
    from factory.events import load_extra

    client = client_for(tmp_path)
    body = "disclosed,ticker\n2024-06-03T14:00Z,SPY\n"
    assert upload(client, body, name="../oops").status_code == 422
    assert upload(client, b"x" * (10 * 1024 * 1024 + 1)).status_code == 413
    (tmp_path / "data").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "data/events").symlink_to(outside)
    assert upload(client, body).status_code == 422
    with pytest.raises(ValueError):
        load_extra(tmp_path / "data", ["../oops"], as_of=pd.Timestamp("2024-06-03T00:00Z"))
    with pytest.raises(ValueError):
        load_extra(tmp_path / "data", ["filings"], as_of=pd.Timestamp("2024-06-03T00:00Z"))


def test_event_catalog_retains_manifest_sample_limitations(data_root):
    client = client_for(data_root)
    dataset = upload(client, "disclosed,ticker\n2024-06-03T14:00Z,SPY\n").json()
    path = data_root / "data/events/filings.manifest.json"
    manifest = json.loads(path.read_text())
    limitation = "0 qualifying purchases; disclosed rows remain with committee_match=false."
    manifest["notes"] = ["unverified source", limitation]
    path.write_text(json.dumps(manifest))
    detail = client.get(f"/api/data/datasets/{dataset['id']}").json()
    assert limitation in detail["dataset"]["notes"]
