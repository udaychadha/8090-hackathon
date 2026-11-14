"""Rule primitives. Field definitions, thresholds and selected rules live in YAML."""

import importlib.metadata
import re
from datetime import date

import numpy as np
import pandas as pd

from factory.data_contract.errors import fail

OPERATIONS = {
    "nonempty",
    "schema",
    "ordered_index",
    "finite",
    "lower_bound",
    "ohlc_bounds",
    "calendar",
    "fill_shape",
    "fill_history",
    "sorted_column",
    "pattern",
    "event_values",
}
RECORD_OPERATIONS = {
    "entity_fields",
    "session_interval",
    "split_interval",
    "manifest_content",
    "session_derivation",
    "activity",
}


def supported_dtype(dtype):
    if dtype in {"string", "date_string", "utc_string", "int64", "float64", "object", "bool"}:
        return True
    try:
        parsed = pd.api.types.pandas_dtype(dtype)
    except (TypeError, ValueError):
        return False
    return isinstance(parsed, pd.DatetimeTZDtype) and parsed.unit == "ns"


def reject(mask, frame, dataset, rule, detail=""):
    values = np.asarray(mask)
    if values.ndim > 1:
        values = values.any(axis=1)
    if values.any():
        fail(dataset, rule, frame, np.flatnonzero(values)[0], detail)


def validate(spec, kind, frame, *, dataset, **context):
    if not isinstance(frame, pd.DataFrame):
        fail(dataset, "frame", detail="Expected a DataFrame")
    definition = spec["datasets"][kind]
    fields = definition.get("fields") or spec["ontology"][definition["entity"]]["fields"]
    for rule in definition["invariants"]:
        name, op = rule["id"], rule["op"]
        if op == "nonempty":
            if frame.empty:
                fail(dataset, name, frame, detail="No rows")
        elif op == "schema":
            columns = [k for k, v in fields.items() if v.get("location") != "index"]
            if (
                not frame.columns.is_unique
                or not set(columns) <= set(frame.columns)
                or (not definition["extra_columns"] and set(columns) != set(frame.columns))
            ):
                fail(dataset, name, frame, detail=f"Expected columns {columns}")
            for field, info in fields.items():
                values = frame.index if info.get("location") == "index" else frame[field]
                if str(values.dtype) != info["dtype"]:
                    fail(
                        dataset,
                        f"{name}.dtype",
                        frame,
                        detail=f"{field}: expected {info['dtype']}, got {values.dtype}",
                    )
            if kind == "price_bars" and frame.index.name != "timestamp":
                fail(dataset, name, frame, detail="Index must be named timestamp")
            for column in set(frame.columns) - set(columns):
                if str(frame[column].dtype) not in definition["extension_dtypes"]:
                    fail(
                        dataset,
                        f"{name}.dtype",
                        frame,
                        detail=f"Unsupported event extension {column}",
                    )
        elif op == "ordered_index":
            index = frame.index
            reject(index.isna() | index.duplicated(), frame, dataset, name)
            reject(np.r_[False, index.asi8[1:] <= index.asi8[:-1]], frame, dataset, name)
        elif op == "finite":
            reject(~np.isfinite(frame[rule["fields"]].to_numpy()), frame, dataset, name)
        elif op == "lower_bound":
            values = frame[rule["fields"]].to_numpy()
            reject(
                values <= rule["minimum"] if rule["strict"] else values < rule["minimum"],
                frame,
                dataset,
                name,
            )
        elif op == "ohlc_bounds":
            reject(
                (frame.high < frame[["open", "close", "low"]].max(axis=1))
                | (frame.low > frame[["open", "close", "high"]].min(axis=1)),
                frame,
                dataset,
                name,
            )
        elif op == "calendar":
            from factory.data import expected_index

            if (
                importlib.metadata.version(spec["calendar"]["library"])
                != spec["calendar"]["version"]
            ):
                fail(dataset, name, frame, detail="Calendar library version differs from contract")
            if context.get("frequency") not in ("1min", "1day"):
                fail(dataset, name, frame, detail="Missing or invalid frequency")
            if not context.get("start") or not context.get("through"):
                fail(dataset, name, frame, detail="Missing requested date bounds")
            try:
                grid = expected_index(context["frequency"], context["start"], context["through"])
            except (ValueError, TypeError):
                fail(dataset, name, frame, detail="Invalid requested calendar dates")
            reject(~frame.index.isin(grid), frame, dataset, name)
        elif op == "fill_shape":
            filled = frame.is_filled
            flat = (
                frame.open.eq(frame.close) & frame.high.eq(frame.close) & frame.low.eq(frame.close)
            )
            bad = filled & (~flat | frame.volume.ne(0))
            if context["frequency"] == "1day":
                bad |= filled
            reject(bad, frame, dataset, name)
        elif op == "fill_history" and context["frequency"] == "1min":
            observed = frame.close.where(~frame.is_filled).reindex(grid)
            days = grid.tz_convert(spec["calendar"]["timezone"]).normalize()
            prior = observed.groupby(days).ffill(limit=spec["calendar"]["fill_limit"])
            expected_fill = observed.isna() & prior.notna()
            actual_fill = frame.is_filled.reindex(grid, fill_value=False)
            bad = expected_fill != actual_fill
            if bad.any():
                stamp = grid[np.flatnonzero(bad.to_numpy())[0]]
                fail(dataset, name, detail=f"first offending row timestamp={stamp}")
            reject(
                frame.is_filled & frame.close.ne(prior.reindex(frame.index)), frame, dataset, name
            )
        elif op == "sorted_column":
            values = frame[rule["field"]]
            reject(values.isna() | values.lt(values.shift()), frame, dataset, name)
        elif op == "pattern":
            reject(
                ~frame[rule["field"]].str.fullmatch(rule["pattern"], na=False), frame, dataset, name
            )
        elif op == "event_values":
            reject(frame.isna(), frame, dataset, name)
            numeric = frame.select_dtypes(include="number")
            reject(~np.isfinite(numeric.to_numpy()), frame, dataset, name)
    return frame


def validate_entity(spec, entity, record, *, dataset):
    fields = spec["ontology"][entity]["fields"]
    for name, info in fields.items():
        if name not in record:
            fail(dataset, "entity_fields", detail=f"Missing {entity}.{name}")
        value, dtype = record[name], info["dtype"]
        valid = False
        if dtype in ("string", "date_string", "utc_string"):
            valid = isinstance(value, str) and bool(value)
        elif dtype == "int64":
            valid = type(value) is int
        elif dtype == "float64":
            valid = type(value) in (float, int) and np.isfinite(value)
        elif dtype == "object":
            valid = isinstance(value, dict)
        elif dtype == "bool":
            valid = type(value) is bool
        elif supported_dtype(dtype) and dtype.startswith("datetime64"):
            valid = (
                isinstance(value, pd.Timestamp) and str(pd.DatetimeIndex([value]).dtype) == dtype
            )
        if not valid:
            fail(dataset, "entity_fields.dtype", detail=f"{entity}.{name}: {dtype}")
        if "allowed" in info and value not in info["allowed"]:
            fail(dataset, "entity_fields.allowed", detail=f"{entity}.{name}={value}")
        if "pattern" in info and not re.fullmatch(info["pattern"], value):
            fail(dataset, "entity_fields.pattern", detail=f"{entity}.{name}")
        if (
            "minimum" in info
            and value < info["minimum"]
            or "maximum" in info
            and value > info["maximum"]
        ):
            fail(dataset, "entity_fields.bounds", detail=f"{entity}.{name}")
        if dtype == "utc_string":
            try:
                stamp = pd.Timestamp(value)
            except ValueError:
                fail(dataset, "entity_fields.timestamp", detail=name)
            if str(stamp.tz) != "UTC":
                fail(dataset, "entity_fields.timestamp", detail=name)
        if dtype == "date_string":
            try:
                parsed = date.fromisoformat(value)
                if parsed.isoformat() != value:
                    raise ValueError("Date must be YYYY-MM-DD")
            except ValueError:
                fail(dataset, "entity_fields.date", detail=name)
    if entity == "Session":
        from factory.data import session_schedule

        if importlib.metadata.version(spec["calendar"]["library"]) != spec["calendar"]["version"]:
            fail(
                dataset, "session_interval", detail="Calendar library version differs from contract"
            )
        session = record["session_date"]
        if session != session.normalize() or str(session.tz) != spec["calendar"]["timezone"]:
            fail(dataset, "session_interval", detail="Session date must be exchange-local midnight")
        day = session.date().isoformat()
        schedule = session_schedule(day, day)
        if schedule.empty:
            fail(dataset, "session_interval", detail="Date is not a scheduled session")
        expected = schedule.iloc[0]
        duration = (expected.close - expected.open).total_seconds() / 60
        if (
            record["open"] != expected.open
            or record["close"] != expected.close
            or record["duration_minutes"] != duration
        ):
            fail(
                dataset, "session_interval", detail="Open, close or duration differs from calendar"
            )
    elif entity == "Split":
        if (
            pd.Timestamp(record["start"]) > pd.Timestamp(record["end"])
            or record["fraction"] != spec["splits"][record["name"]]
        ):
            fail(dataset, "split_interval", detail="Reversed bounds or fraction differs from name")
    return record
