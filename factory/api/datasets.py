"""Manifest-backed catalog and bounded, contract-validated visible price previews."""

from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import UploadFile

from factory.api.artifacts import (
    Artifact,
    ArtifactRegistry,
    dataset_identifier,
    read_json,
    safe_path,
)
from factory.api.common import root_from, sanitize
from factory.data import (
    DAILY_LIMITATION,
    expected_index,
    load_bars,
    session_schedule,
    validate_tier_manifest,
)
from factory.data_contract.generated import SPEC
from factory.data_contract.runtime import validate_entity
from factory.data_contract.storage import read_dataset
from factory.events import MAX_EVENT_BYTES, event_path, upload_event_csv

router = APIRouter(prefix="/api/data", tags=["data"])


class Dataset(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str
    name: str
    kind: Literal["price_bars", "events"]
    symbols: list[str]
    frequency: Literal["1min", "1day", "event"] | None
    start: str
    end: str
    rows: int = Field(ge=0)
    source: str
    verified: bool
    scope: Literal["main", "smoke"]
    schema_version: str
    feed: str
    adjustment: str
    fill_rate: float = Field(ge=0, le=1)
    expected_rows: int | None = Field(default=None, ge=0)
    missing_rows: int | None = Field(default=None, ge=0)
    notes: list[str] = Field(default_factory=list)


class DatasetDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset: Dataset
    manifest: dict
    metadata: dict
    splits: dict
    fields: dict
    artifacts: list[Artifact]


class Gap(BaseModel):
    start: str
    end: str
    rows: int = Field(ge=1)


class DatasetPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str
    rows: list[dict]
    splits: dict
    coverage: dict
    gaps: list[Gap]
    total_gaps: int = Field(ge=0)
    holdout_sealed: Literal[True] = True
    downsampled: bool


class Catalog(BaseModel):
    datasets: list[Dataset]


class IngestEvents(BaseModel):
    events: list[dict]
    total: int
    next_offset: int | None


class AuditView(BaseModel):
    audit: dict | None
    artifacts: list[Artifact]


class ContractView(BaseModel):
    schema_version: str
    contract: dict
    markdown: str


class UniverseView(BaseModel):
    symbols: list[str]
    provenance: dict
    notes: list[str]


class DatasetRegistry:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def _entries(self, scope):
        if scope not in {"main", "smoke"}:
            raise HTTPException(422, "Scope must be main or smoke")
        base = self.root / ("data" if scope == "main" else "data/smoke")
        result = {}
        for frequency in ("1min", "1day"):
            tier_path = base / frequency / "manifest.json"
            if safe_path(self.root, tier_path) is None:
                continue
            tier = read_json(self.root, tier_path)
            try:
                validate_tier_manifest(tier, frequency, dataset=str(tier_path))
            except (ValueError, KeyError, TypeError):
                raise HTTPException(409, "Dataset tier metadata failed validation") from None
            for symbol in tier["symbols"]:
                path = base / frequency / f"{symbol}.parquet"
                manifest_path = path.with_suffix(".manifest.json")
                metadata_path = base / "metadata" / frequency / f"{symbol}.json"
                if (
                    safe_path(self.root, path) is None
                    or safe_path(self.root, manifest_path) is None
                ):
                    continue
                manifest = read_json(self.root, manifest_path)
                metadata = (
                    read_json(self.root, metadata_path)
                    if safe_path(self.root, metadata_path)
                    else {}
                )
                try:
                    validate_entity(SPEC, "Dataset", manifest, dataset=str(path))
                    if manifest["frequency"] != frequency or manifest["kind"] != "price_bars":
                        raise ValueError
                    item = Dataset(
                        id=dataset_identifier(scope, frequency, symbol),
                        name=f"{scope}/{frequency}/{symbol}",
                        kind="price_bars",
                        symbols=[symbol],
                        frequency=frequency,
                        start=pd.Timestamp(manifest["date_range"]["start"]).date().isoformat(),
                        end=pd.Timestamp(manifest["date_range"]["end"]).date().isoformat(),
                        rows=manifest["row_count"],
                        source=manifest["source"],
                        verified=True,
                        scope=scope,
                        schema_version=manifest["schema_version"],
                        feed=manifest["feed"],
                        adjustment=manifest["adjustment"],
                        fill_rate=manifest["fill_rate"],
                        expected_rows=metadata.get("expected_rows"),
                        missing_rows=metadata.get("missing_rows"),
                        notes=([DAILY_LIMITATION] if frequency == "1day" else [])
                        + [
                            "Manifest-backed inventory; preview performs full "
                            "stored-file validation.",
                            "Fill rate denominator is the expected session grid, "
                            "not retained rows.",
                        ]
                        + (
                            ["Smoke fixture; excluded from the main catalog."]
                            if scope == "smoke"
                            else []
                        ),
                    )
                except (ValueError, KeyError, TypeError):
                    raise HTTPException(409, "Dataset metadata failed validation") from None
                result[item.id] = (item, manifest, metadata, tier, base, path)
        events = base / "events"
        for path in sorted(events.glob("*.parquet")):
            name = path.stem
            try:
                event_path(base, name)
            except ValueError:
                continue
            if (
                safe_path(self.root, path) is None
                or safe_path(self.root, path.with_suffix(".manifest.json")) is None
            ):
                continue
            try:
                frame = read_dataset(path, expected={"kind": "events"})
                manifest = read_json(self.root, path.with_suffix(".manifest.json"))
                item = Dataset(
                    id=dataset_identifier(scope, "events", name),
                    name=name,
                    kind="events",
                    symbols=sorted(frame.symbol.unique().tolist()),
                    frequency=None,
                    start=pd.Timestamp(manifest["date_range"]["start"]).date().isoformat(),
                    end=pd.Timestamp(manifest["date_range"]["end"]).date().isoformat(),
                    rows=len(frame),
                    source=manifest["source"],
                    verified=False,
                    scope=scope,
                    schema_version=manifest["schema_version"],
                    feed=manifest["feed"],
                    adjustment=manifest["adjustment"],
                    fill_rate=0,
                    notes=[
                        "unverified source",
                        "Event visibility uses available_at only.",
                        "Preview uses the daily price tier's completed-session boundaries; "
                        "HOLDOUT is sealed.",
                    ],
                )
                tier_path = base / "1day/manifest.json"
                tier = (
                    read_json(self.root, tier_path)
                    if safe_path(self.root, tier_path)
                    else {"splits": {}}
                )
                if tier["splits"]:
                    validate_tier_manifest(tier, "1day", dataset=str(tier_path))
                metadata = {
                    "fields": {column: {"dtype": str(frame[column].dtype)} for column in frame}
                }
                result[item.id] = (item, manifest, metadata, tier, base, path)
            except (ValueError, KeyError, TypeError, OSError):
                raise HTTPException(409, "Event dataset failed stored-file validation") from None
        return result

    def catalog(self, scope="main"):
        return [
            Dataset.model_validate(sanitize(row[0].model_dump()))
            for row in self._entries(scope).values()
        ]

    def _entry(self, dataset_id):
        scope = "smoke" if dataset_id.startswith("smoke-") else "main"
        entry = self._entries(scope).get(dataset_id)
        if entry is None:
            raise HTTPException(404, "Dataset not found")
        return entry

    def detail(self, dataset_id):
        item, manifest, metadata, tier, _, _ = self._entry(dataset_id)
        fields = {**SPEC["ontology"]["Bar"]["fields"], **SPEC["ontology"]["Bar"]["derived_fields"]}
        if item.kind == "events":
            fields = {**metadata.get("fields", {}), **SPEC["datasets"]["events"]["fields"]}
        return DatasetDetail.model_validate(
            sanitize(
                {
                    "dataset": item.model_dump(),
                    "manifest": manifest,
                    "metadata": metadata,
                    "splits": tier["splits"],
                    "fields": fields,
                    "artifacts": [
                        artifact.model_dump()
                        for artifact in ArtifactRegistry(self.root).list(dataset_id=dataset_id)
                    ],
                }
            )
        )

    def preview(self, dataset_id, split="visible", limit=500):
        if split not in {"visible", "IS", "OOS"}:
            raise HTTPException(422, "Only visible, IS and OOS previews are available")
        if not 1 <= limit <= 2000:
            raise HTTPException(422, "Preview limit must be between 1 and 2000")
        item, _, _, tier, base, path = self._entry(dataset_id)
        if item.kind == "events":
            return self._event_preview(item, tier, path, split, limit)
        partitions = ["IS", "OOS"] if split == "visible" else [split]
        for required in [path, path.with_suffix(".manifest.json"), path.parent / "manifest.json"]:
            if safe_path(self.root, required) is None:
                raise HTTPException(404, "Dataset not found")
        try:
            # The canonical loader validates whole stored files before selecting
            # each partition, preserving all storage and calendar invariants.
            frames = [
                load_bars(base, item.frequency, item.symbols, split=partition)[item.symbols[0]]
                for partition in partitions
            ]
            frame = pd.concat(frames).sort_index()
            grid = expected_index(item.frequency, tier["start"], tier["through"])
            left = pd.Timestamp(tier["splits"][partitions[0]]["start"])
            right = pd.Timestamp(tier["splits"][partitions[-1]]["end"])
            grid = grid[(grid >= left) & (grid <= right)]
            missing = ~grid.isin(frame.index)
            starts = np.flatnonzero(missing & np.r_[True, ~missing[:-1]])
            ends = np.flatnonzero(missing & np.r_[~missing[1:], True])
            gaps = [
                Gap(start=grid[a].isoformat(), end=grid[b].isoformat(), rows=int(b - a + 1))
                for a, b in zip(starts[:200], ends[:200], strict=True)
            ]
            sampled = frame.iloc[
                np.unique(np.linspace(0, len(frame) - 1, min(len(frame), limit), dtype=int))
            ]
            rows = []
            for timestamp, row in sampled.iterrows():
                values = {
                    key: value.isoformat()
                    if isinstance(value, pd.Timestamp)
                    else value.item()
                    if isinstance(value, np.generic)
                    else value
                    for key, value in row.items()
                }
                rows.append({"timestamp": timestamp.isoformat(), **values})
            payload = {
                "dataset_id": dataset_id,
                "rows": rows,
                "splits": tier["splits"],
                "coverage": {
                    "split": split,
                    "expected_rows": len(grid),
                    "observed_rows": len(frame),
                    "missing_rows": int(missing.sum()),
                    "filled_rows": int(frame.is_filled.sum()),
                    "start": left.isoformat(),
                    "end": right.isoformat(),
                    "gap_intervals_returned": len(gaps),
                    "fill_rate_denominator": "expected rows in the selected session grid",
                },
                "gaps": [gap.model_dump() for gap in gaps],
                "total_gaps": len(starts),
                "holdout_sealed": True,
                "downsampled": len(frame) > limit,
            }
            return DatasetPreview.model_validate(sanitize(payload))
        except (OSError, ValueError, KeyError, TypeError):
            raise HTTPException(
                409, "Dataset failed stored-file validation; preview unavailable"
            ) from None

    def _event_preview(self, item, tier, path, split, limit):
        if not tier.get("splits"):
            raise HTTPException(
                409, "Daily price split boundaries are required for a sealed event preview"
            )
        try:
            schedule = session_schedule(tier["start"], tier["through"])

            def close(label):
                day = (
                    pd.Timestamp(label).tz_convert("America/New_York").tz_localize(None).normalize()
                )
                return pd.Timestamp(schedule.loc[day, "close"])

            splits = tier["splits"]
            right = close(splits["IS" if split == "IS" else "OOS"]["end"])
            frame = read_dataset(path, expected={"kind": "events"})
            # IS/visible includes earlier disclosures as historical context. OOS
            # displays only newly available events after the IS decision cutoff.
            frame = frame.loc[frame.available_at <= right]
            left = close(splits["IS"]["end"]) if split == "OOS" else None
            if left is not None:
                frame = frame.loc[frame.available_at > left]
            sampled = frame.iloc[
                np.unique(np.linspace(0, len(frame) - 1, min(len(frame), limit), dtype=int))
            ]
            rows = [
                {
                    key: value.isoformat()
                    if isinstance(value, pd.Timestamp)
                    else value.item()
                    if isinstance(value, np.generic)
                    else value
                    for key, value in row.items()
                }
                for _, row in sampled.iterrows()
            ]
            return DatasetPreview.model_validate(
                sanitize(
                    {
                        "dataset_id": item.id,
                        "rows": rows,
                        "splits": splits,
                        "coverage": {
                            "split": split,
                            "observed_rows": len(frame),
                            "expected_rows": None,
                            "missing_rows": None,
                            "filled_rows": None,
                            "start": left.isoformat() if left is not None else None,
                            "end": right.isoformat(),
                            "availability_field": "available_at",
                            "note": "Events have no expected price grid or gap inference.",
                        },
                        "gaps": [],
                        "total_gaps": 0,
                        "holdout_sealed": True,
                        "downsampled": len(frame) > limit,
                    }
                )
            )
        except (ValueError, KeyError, TypeError, OSError):
            raise HTTPException(
                409, "Event preview failed stored-file or boundary validation"
            ) from None


@router.post("/upload", response_model=Dataset)
async def upload_events(request: Request):
    if "multipart/form-data" not in request.headers.get("content-type", ""):
        raise HTTPException(422, "Upload an event CSV with file, name and mapping fields")
    async with request.form(max_files=1, max_fields=2) as form:
        upload, name, raw_mapping = form.get("file"), form.get("name"), form.get("mapping")
        if (
            not isinstance(upload, UploadFile)
            or not isinstance(name, str)
            or not isinstance(raw_mapping, str)
        ):
            raise HTTPException(422, "Multipart file, name and mapping fields are required")
        content = await upload.read(MAX_EVENT_BYTES + 1)
        if len(content) > MAX_EVENT_BYTES:
            raise HTTPException(413, "Event CSV exceeds 10 MiB")
        try:

            def unique_object(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("Duplicate mapping destination")
                    result[key] = value
                return result

            mapping = json.loads(raw_mapping, object_pairs_hook=unique_object)
            await asyncio.to_thread(
                upload_event_csv, root_from(request) / "data", name, content, mapping
            )
        except FileExistsError:
            raise HTTPException(409, "An event dataset with this name already exists") from None
        except (ValueError, TypeError, OSError, OverflowError):
            raise HTTPException(
                422,
                "Invalid event CSV: use unique mapped fields, finite scalar values "
                "and explicit availability timezones",
            ) from None
    return DatasetRegistry(root_from(request))._entry(dataset_identifier("main", "events", name))[0]


@router.get("/catalog", response_model=Catalog)
def catalog(request: Request, scope: Literal["main", "smoke"] = "main"):
    return Catalog(datasets=DatasetRegistry(root_from(request)).catalog(scope))


@router.get("/datasets/{dataset_id}", response_model=DatasetDetail)
def dataset_detail(request: Request, dataset_id: str):
    return DatasetRegistry(root_from(request)).detail(dataset_id)


@router.get("/datasets/{dataset_id}/preview", response_model=DatasetPreview)
def dataset_preview(
    request: Request,
    dataset_id: str,
    split: Literal["visible", "IS", "OOS"] = "visible",
    limit: int = Query(500, ge=1, le=2000),
):
    return DatasetRegistry(root_from(request)).preview(dataset_id, split, limit)


@router.get("/ingest-events", response_model=IngestEvents)
def ingest_events(
    request: Request,
    scope: Literal["main", "smoke"] = "main",
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    root = root_from(request)
    path = root / ("data/ingest.jsonl" if scope == "main" else "data/smoke/ingest.jsonl")
    events, total = [], 0
    if safe_path(root, path):
        try:
            with path.open() as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError
                    if offset <= total < offset + limit:
                        events.append(sanitize(event))
                    total += 1
        except (ValueError, OSError):
            raise HTTPException(409, "Ingest log cannot be decoded") from None
    return IngestEvents(
        events=events, total=total, next_offset=offset + limit if total > offset + limit else None
    )


@router.get("/audits", response_model=AuditView)
def data_audits(request: Request, include_voided: bool = False):
    root = root_from(request)
    path = root / "data/audit.json"
    audit = sanitize(read_json(root, path)) if safe_path(root, path) else None
    if audit is not None:
        audit["historical"] = True
        audit["observed_file_mtime"] = pd.Timestamp(
            path.stat().st_mtime, unit="s", tz="UTC"
        ).isoformat()
        audit["fill_rate_denominator"] = "expected session-grid rows"
    artifacts = [
        artifact
        for artifact in ArtifactRegistry(root).list(include_voided=include_voided)
        if artifact.kind == "data_audit"
        or artifact.name.startswith("report/wo17-")
        and not re_run_report(artifact.name)
    ]
    return AuditView(audit=audit, artifacts=artifacts)


def re_run_report(name):
    return name.startswith("report/wo17-r_") or name in {
        "report/wo17-results.json",
        "report/wo17-results.md",
        "report/wo17-paper-reruns.json",
        "report/wo17-daily-retries.json",
        "report/wo17-void.json",
    }


@router.get("/contract", response_model=ContractView)
def contract(request: Request):
    root = root_from(request)
    reference = safe_path(root, root / "docs/DATA.md")
    # The installed generated specification is the same canonical source used by
    # runtime validation; a deployment need not copy mutable repository YAML.
    return ContractView(
        schema_version=SPEC["schema_version"],
        contract=sanitize(SPEC),
        markdown=sanitize(reference.read_text()) if reference else "",
    )


@router.get("/universe", response_model=UniverseView)
def universe(request: Request):
    root = root_from(request)
    path = safe_path(root, root / "data/sp500.csv")
    symbols = []
    if path:
        try:
            with path.open() as stream:
                rows = csv.DictReader(stream)
                for row in rows:
                    symbol = row.get("Symbol") or row.get("symbol")
                    if symbol:
                        symbols.append(symbol)
        except (OSError, UnicodeError, csv.Error):
            raise HTTPException(409, "Universe snapshot cannot be read") from None
    source = root / "data/sp500.source.json"
    provenance = read_json(root, source) if safe_path(root, source) else {}
    return UniverseView.model_validate(
        sanitize(
            {
                "symbols": symbols,
                "provenance": provenance,
                "notes": [DAILY_LIMITATION],
            }
        )
    )
