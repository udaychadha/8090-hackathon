"""Read APIs expose validated visible data without changing storage."""

import json
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def data_root(tmp_path):
    from factory.data import expected_index, split_boundaries
    from factory.data_contract.storage import write_dataset

    root = tmp_path
    index = expected_index("1day", "2024-06-03", "2024-06-14")
    frame = pd.DataFrame(
        {
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 10.0,
            "is_filled": False,
        },
        index=index,
    ).drop(index[2])
    for scope in ["", "smoke"]:
        base = root / "data" / scope
        path = base / "1day" / "SPY.parquet"
        write_dataset(
            path,
            frame,
            kind="price_bars",
            frequency="1day",
            start="2024-06-03",
            through="2024-06-14",
            source="fixture",
            feed="sip",
            adjustment="all",
        )
        (path.parent / "manifest.json").write_text(
            json.dumps(
                {
                    "frequency": "1day",
                    "symbols": ["SPY"],
                    "start": "2024-06-03",
                    "through": "2024-06-14",
                    "feed": "sip",
                    "adjustment": "all",
                    "normalizer_version": 1,
                    "splits": split_boundaries(index),
                    "complete": True,
                    "failed_symbols": [],
                }
            )
        )
        metadata = base / "metadata" / "1day" / "SPY.json"
        metadata.parent.mkdir(parents=True)
        metadata.write_text(json.dumps({"expected_rows": 10, "missing_rows": 1}))
    return root


def test_catalog_separates_smoke_and_preview_seals_holdout(data_root):
    from factory.api.datasets import DatasetRegistry

    registry = DatasetRegistry(data_root)
    main = registry.catalog()
    smoke = registry.catalog(scope="smoke")
    assert len(main) == len(smoke) == 1
    assert main[0].scope == "main" and smoke[0].scope == "smoke"
    assert main[0].start == "2024-06-03" and main[0].end == "2024-06-14"
    assert main[0].id != smoke[0].id
    preview = registry.preview(main[0].id, limit=3)
    assert len(preview.rows) == 3 and preview.downsampled
    assert preview.holdout_sealed
    assert preview.total_gaps == 1
    assert preview.gaps[0].rows == 1
    assert max(r["timestamp"] for r in preview.rows) < preview.splits["HOLDOUT"]["start"]
    detail = registry.detail(main[0].id)
    assert detail.metadata["missing_rows"] == 1
    assert "minutes_since_open" in detail.fields


def test_preview_rejects_holdout_and_validates_corrupted_bytes(data_root):
    from fastapi import HTTPException

    from factory.api.datasets import DatasetRegistry

    registry = DatasetRegistry(data_root)
    dataset = registry.catalog()[0]
    with pytest.raises(HTTPException) as rejected:
        registry.preview(dataset.id, split="HOLDOUT")
    assert rejected.value.status_code == 422
    path = data_root / "data/1day/SPY.parquet"
    path.write_bytes(path.read_bytes() + b"corruption")
    with pytest.raises(HTTPException) as corrupt:
        registry.preview(dataset.id)
    assert corrupt.value.status_code == 409


def test_dataset_ids_cannot_read_arbitrary_paths_or_symlinks(data_root, tmp_path):
    from fastapi import HTTPException

    from factory.api.datasets import DatasetRegistry

    registry = DatasetRegistry(data_root)
    with pytest.raises(HTTPException) as missing:
        registry.detail("../../.env")
    assert missing.value.status_code == 404
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    manifest = data_root / "data/1day/SPY.manifest.json"
    manifest.unlink()
    manifest.symlink_to(outside)
    assert registry.catalog() == []


def test_real_catalog_counts_are_from_main_and_smoke_manifests():
    from factory.api.datasets import DatasetRegistry

    root = Path(__file__).resolve().parents[1]
    if not (root / "data/1day/manifest.json").exists():
        pytest.skip("Local owner data unavailable")
    registry = DatasetRegistry(root)
    assert len(registry.catalog()) == 557
    assert len(registry.catalog(scope="smoke")) == 3


def test_data_routes_keep_ingest_schema_and_bound_offsets(data_root):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from factory.api.datasets import router

    (data_root / "data/ingest.jsonl").write_text(
        '{"event":"chunk_written","time":"2024-01-01T00:00:00Z"}\n'
        '{"event":"symbol_complete","symbol":"SPY"}\n'
    )
    app = FastAPI()
    app.state.root = data_root
    app.include_router(router)
    client = TestClient(app)
    response = client.get("/api/data/ingest-events?limit=1")
    assert response.status_code == 200
    assert response.json() == {
        "events": [{"event": "chunk_written", "time": "2024-01-01T00:00:00Z"}],
        "total": 2,
        "next_offset": 1,
    }
    assert client.get("/api/data/ingest-events?offset=-1").status_code == 422


def test_data_detail_audit_universe_and_contract_routes_read_real_evidence(data_root):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from factory.api.datasets import router

    (data_root / "data/audit.json").write_text(
        '{"passed":true,"errors":[],"symbols":[],"split_checks":[]}'
    )
    (data_root / "data/sp500.csv").write_text("Symbol,Security\nSPY,Fixture ETF\n")
    (data_root / "data/sp500.source.json").write_text('{"source":"owner supplied"}')
    (data_root / "docs").mkdir()
    (data_root / "docs/DATA.md").write_text("Retained generated contract reference")
    app = FastAPI()
    app.state.root = data_root
    app.include_router(router)
    client = TestClient(app)
    dataset = client.get("/api/data/catalog").json()["datasets"][0]
    detail = client.get(f"/api/data/datasets/{dataset['id']}")
    assert detail.status_code == 200
    assert detail.json()["manifest"]["row_count"] == 9
    assert len(detail.json()["artifacts"]) == 2
    preview = client.get(f"/api/data/datasets/{dataset['id']}/preview?split=OOS")
    assert preview.status_code == 200
    assert len(preview.json()["rows"]) == 2
    assert (
        client.get(f"/api/data/datasets/{dataset['id']}/preview?split=HOLDOUT").status_code == 422
    )
    audit = client.get("/api/data/audits").json()["audit"]
    assert audit["historical"] and audit["passed"]
    assert audit["observed_file_mtime"]
    universe = client.get("/api/data/universe").json()
    assert universe["symbols"] == ["SPY"]
    assert universe["provenance"] == {"source": "owner supplied"}
    contract = client.get("/api/data/contract").json()
    assert contract["markdown"] == "Retained generated contract reference"
    assert contract["contract"]["activity"]["status"] == "INACTIVE"
