"""Validated event CSV ingestion and strictly availability-gated local reads."""

from __future__ import annotations

import csv
import fcntl
import io
import os
import re
from pathlib import Path

import pandas as pd

from factory.data_contract.generated import SPEC, validate_events
from factory.data_contract.storage import manifest_path, read_dataset, write_dataset

MAX_EVENT_BYTES = 10 * 1024 * 1024
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}\Z")


def event_path(data_root, name):
    """Resolve a named dataset without following any symlink components."""
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError(
            "Dataset name must start with a letter and contain letters, digits or underscores"
        )
    root = Path(data_root).absolute()
    path = root / "events" / f"{name}.parquet"
    for candidate in [path, *path.parents, manifest_path(path)]:
        if candidate.is_symlink():
            raise ValueError("Event dataset paths cannot contain symlinks")
    return path


def load_extra(data_root, names, *, as_of):
    """Load requested events, retaining schema even when no rows are visible."""
    stamp = pd.Timestamp(as_of)
    if pd.isna(stamp) or str(stamp.tz) != "UTC":
        raise ValueError("Event as_of must be a finite UTC timestamp")
    if not isinstance(names, (list, tuple)) or len(names) != len(set(names)):
        raise ValueError("EXTRA must be a list of distinct dataset names")
    result = {}
    for name in names:
        frame = read_dataset(event_path(data_root, name), expected={"kind": "events"})
        result[name] = frame.loc[frame.available_at <= stamp].copy()
    return result


def parse_event_csv(content, mapping):
    """Parse scalar CSV data, never code; explicit timezone information is required."""
    if len(content) > MAX_EVENT_BYTES:
        raise OverflowError("Event CSV exceeds 10 MiB")
    if not isinstance(mapping, dict) or not {"available_at", "symbol"} <= mapping.keys():
        raise ValueError("Mapping must include available_at and symbol")
    if any(
        not isinstance(k, str) or not _NAME.fullmatch(k) or not isinstance(v, str) or not v
        for k, v in mapping.items()
    ) or len(set(mapping.values())) != len(mapping):
        raise ValueError(
            "Mapping destinations must be valid unique field names and sources must be distinct"
        )
    try:
        decoded = content.decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(decoded), strict=True))
    except (UnicodeError, csv.Error) as error:
        raise ValueError("File must be valid UTF-8 CSV") from error
    if len(rows) < 2 or len(rows) > 100001:
        raise ValueError("CSV must contain between 1 and 100000 event rows")
    header, values = rows[0], rows[1:]
    if not header or len(header) != len(set(header)) or any(not name for name in header):
        raise ValueError("CSV headers must be nonempty and unique")
    if not set(mapping.values()) <= set(header):
        raise ValueError("Mapped source columns are missing")
    rename = {source: dest for dest, source in mapping.items()}
    columns = [rename.get(column, column) for column in header]
    if len(set(columns)) != len(columns) or any(not _NAME.fullmatch(name) for name in columns):
        raise ValueError("Mapped and preserved column names must be safe and must not collide")
    if any(len(row) != len(columns) or any(not value.strip() for value in row) for row in values):
        raise ValueError("Every event row must contain all scalar values")
    frame = pd.DataFrame(values, columns=columns, dtype="string")
    stamps = []
    for value in frame.available_at:
        # An offset or Z is mandatory; a date-only value cannot imply availability.
        if not re.search(r"[T ]\d{2}:\d{2}.*(?:Z|[+-]\d{2}:?\d{2})$", value):
            raise ValueError("available_at requires a date, time and explicit timezone")
        stamp = pd.Timestamp(value)
        if pd.isna(stamp) or stamp.tz is None:
            raise ValueError("available_at requires a valid explicit timezone")
        stamps.append(stamp.tz_convert("UTC"))
    frame["available_at"] = pd.Series(stamps, dtype="datetime64[ns, UTC]")
    for column in columns:
        if column in {"available_at", "symbol"}:
            continue
        if (
            frame[column]
            .str.lower()
            .isin(["nan", "nat", "null", "none", "inf", "+inf", "-inf", "infinity"])
            .any()
        ):
            raise ValueError("Event fields cannot contain null or non-finite values")
        if frame[column].str.lower().isin(["true", "false"]).all():
            frame[column] = frame[column].str.lower().eq("true").astype(bool)
        else:
            try:
                numeric = pd.to_numeric(frame[column], errors="raise")
            except (ValueError, TypeError):
                continue
            frame[column] = numeric.astype("int64" if numeric.dtype.kind in "iu" else "float64")
    frame = frame.sort_values("available_at", kind="stable").reset_index(drop=True)
    validate_events(frame, dataset="uploaded event CSV")
    return frame


def upload_event_csv(data_root, name, content, mapping):
    """Publish once under a local writer lock, using the canonical storage validator."""
    path = event_path(data_root, name)
    frame = parse_event_csv(content, mapping)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.parent / ".upload.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        path = event_path(data_root, name)
        if path.exists() or manifest_path(path).exists():
            raise FileExistsError("An event dataset with this name already exists")
        dates = frame.available_at.dt.tz_convert(SPEC["calendar"]["timezone"])
        write_dataset(
            path,
            frame,
            kind="events",
            frequency="event",
            feed="user_supplied",
            adjustment="not_applicable",
            source="user uploaded CSV",
            start=dates.min().date().isoformat(),
            through=dates.max().date().isoformat(),
        )
    finally:
        os.close(descriptor)
    return path
