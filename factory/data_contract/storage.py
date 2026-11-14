"""Validated data-file I/O and per-file manifests. Corrupt files fail closed."""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from factory.data_contract.errors import DataError, fail
from factory.data_contract.generated import SPEC, validate_events, validate_price_bars
from factory.data_contract.runtime import validate_entity


def manifest_path(path):
    return Path(path).with_suffix(".manifest.json")


def _digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _validate(frame, entry, dataset):
    kind = entry.get("kind")
    if kind not in SPEC["datasets"]:
        fail(dataset, "manifest.kind", frame, detail=f"Unknown kind {kind}")
    if kind == "price_bars":
        validate_price_bars(
            frame, dataset=dataset, **{k: entry.get(k) for k in ("frequency", "start", "through")}
        )
    else:
        validate_events(frame, dataset=dataset)
    for key, allowed in SPEC["datasets"][kind]["metadata"].items():
        if entry.get(key) not in allowed:
            fail(dataset, f"manifest.{key}", frame, detail=f"Expected one of {allowed}")


def _facts(frame, entry):
    if entry["kind"] == "price_bars":
        from factory.data import expected_index

        grid = expected_index(entry["frequency"], entry["start"], entry["through"])
        timestamps = frame.index
        fill_rate = float(frame.is_filled.sum() / len(grid))
    else:
        timestamps = frame.available_at
        fill_rate = 0.0
    return {
        "row_count": len(frame),
        "fill_rate": fill_rate,
        "date_range": {"start": timestamps.min().isoformat(), "end": timestamps.max().isoformat()},
    }


def _entry(path, frame, metadata):
    entry = {
        "name": str(Path(path)),
        "schema_version": SPEC["schema_version"],
        "calendar": SPEC["calendar"]["name"],
        "calendar_version": SPEC["calendar"]["version"],
        "created_at": datetime.now(UTC).isoformat(),
        **metadata,
    }
    _validate(frame, entry, str(path))
    entry.update(_facts(frame, entry))
    # Validate metadata before any destination file is touched.
    validate_entity(SPEC, "Dataset", {**entry, "sha256": "0" * 64}, dataset=str(path))
    if entry["start"] > entry["through"]:
        fail(str(path), "manifest.date_range", frame, detail="Requested dates are reversed")
    return entry


def _atomic_json(path, payload):
    path = Path(path)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def attach_manifest(path, frame, **metadata):
    """Validate existing bytes and add provenance without rewriting price files."""
    path = Path(path)
    # Callers cannot attach provenance to a different frame than the file holds.
    actual = pd.read_parquet(path)
    try:
        pd.testing.assert_frame_equal(frame, actual, check_exact=True, check_freq=False)
    except AssertionError:
        fail(str(path), "manifest.content", actual, detail="Provided frame differs from file")
    entry = _entry(path, actual, metadata)
    entry["sha256"] = _digest(path)
    _atomic_json(manifest_path(path), entry)
    return entry


def write_dataset(path, frame, **metadata):
    """Validate before writing; interrupted file/manifest pairs are never loadable."""
    path = Path(path)
    entry = _entry(path, frame, metadata)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    try:
        stored = frame.copy()
        stored.attrs = {}
        stored.to_parquet(temporary, engine="pyarrow", compression="zstd", index=True)
        # Check serialized roundtrip before publishing the file.
        actual = pd.read_parquet(temporary)
        _validate(actual, entry, str(path))
        pd.testing.assert_frame_equal(stored, actual, check_exact=True, check_freq=False)
        entry["sha256"] = _digest(temporary)
        temporary.replace(path)
        _atomic_json(manifest_path(path), entry)
    finally:
        temporary.unlink(missing_ok=True)
    return entry


def read_dataset(path, *, expected=None):
    """Validate the whole file before returning any subset to a caller."""
    path = Path(path)
    try:
        entry = json.loads(manifest_path(path).read_text())
        validate_entity(SPEC, "Dataset", entry, dataset=str(path))
        if _digest(path) != entry["sha256"]:
            fail(str(path), "manifest.sha256", detail="File differs from validated manifest")
        for key, value in (expected or {}).items():
            if entry.get(key) != value:
                fail(str(path), f"manifest.{key}", detail=f"Expected {value!r}")
        frame = pd.read_parquet(path)
        _validate(frame, entry, str(path))
        for key, value in _facts(frame, entry).items():
            if entry[key] != value:
                fail(str(path), f"manifest.{key}", frame, detail=f"Expected {value!r}")
        return frame
    except DataError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        fail(str(path), "manifest.read", detail=f"Cannot validate dataset: {type(error).__name__}")


def load_events(path, *, as_of):
    """Availability gate for event consumers; future information stays inaccessible."""
    stamp = pd.Timestamp(as_of)
    if str(stamp.tz) != "UTC":
        fail(str(path), "availability", detail="as_of must be UTC")
    frame = read_dataset(path, expected={"kind": "events"})
    return frame.loc[frame.available_at <= stamp].copy()
