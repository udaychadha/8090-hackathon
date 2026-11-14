from pathlib import Path

import pandas as pd
import pytest


def test_contract_artifacts_are_current():
    source = Path("factory/data_contract/contract.yaml")
    assert source.exists(), "The single-source data contract is missing"
    from factory.data_contract.generate import check

    check()


def frame():
    return pd.DataFrame(
        {
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.0],
            "volume": [10.0],
            "is_filled": [False],
        },
        index=pd.DatetimeIndex(["2024-03-11T19:59:00Z"], name="timestamp"),
    )


@pytest.mark.parametrize(
    "case,rule",
    [
        ("seconds", "calendar"),
        ("weekend", "calendar"),
        ("flag", "columns"),
        ("volume", "nonnegative"),
        ("price", "positive"),
        ("bounds", "ohlc_bounds"),
        ("dtype", "dtype"),
        ("nan", "finite"),
        ("filled", "fill_shape"),
    ],
)
def test_price_contract_rejects_bad_rows_with_context(case, rule):
    from factory.data_contract import DataError, validate_price_bars

    f = frame()
    if case == "seconds":
        f.index += pd.Timedelta(seconds=1)
    if case == "weekend":
        f.index += pd.Timedelta(days=5)
    if case == "flag":
        f = f.drop(columns="is_filled")
    if case == "volume":
        f.loc[f.index[0], "volume"] = -1.0
    if case == "price":
        f.loc[f.index[0], "open"] = 0.0
    if case == "bounds":
        f.loc[f.index[0], "high"] = 50.0
    if case == "dtype":
        f["volume"] = f.volume.astype("int64")
    if case == "nan":
        f.loc[f.index[0], "close"] = float("nan")
    if case == "filled":
        f["is_filled"] = True
    with pytest.raises(DataError) as error:
        validate_price_bars(
            f, dataset="1min/SPY", frequency="1min", start="2024-03-11", through="2024-03-18"
        )
    assert "1min/SPY" in str(error.value)
    assert rule in str(error.value)
    assert "row=" in str(error.value)


def test_valid_data_and_event_availability_contract():
    from factory.data_contract import DataError, validate_events, validate_price_bars

    validate_price_bars(
        frame(), dataset="SPY", frequency="1min", start="2024-03-11", through="2024-03-11"
    )
    events = pd.DataFrame(
        {
            "available_at": pd.to_datetime(["2024-03-11T14:00Z"]),
            "symbol": pd.Series(["SPY"], dtype="string"),
            "score": [1.0],
        }
    )
    validate_events(events, dataset="news")
    with pytest.raises(DataError, match="news.*columns.*row="):
        validate_events(events.drop(columns="available_at"), dataset="news")
    events["available_at"] = events.available_at.dt.tz_localize(None)
    with pytest.raises(DataError, match="news.*dtype.*row="):
        validate_events(events, dataset="news")


def test_generation_detects_edits_and_unknown_rules(tmp_path):
    from factory.data_contract.generate import check, generate, read_contract

    spec = read_contract()
    generate(tmp_path, spec)
    check(tmp_path, spec)
    (tmp_path / "docs/DATA.md").write_text("manual drift")
    with pytest.raises(ValueError, match="stale"):
        check(tmp_path, spec)
    spec["datasets"]["price_bars"]["invariants"][0]["op"] = "made_up"
    with pytest.raises(ValueError, match="Unknown"):
        generate(tmp_path, spec)


@pytest.mark.parametrize("value", ["false", 0, 1, None])
def test_record_boolean_rejects_non_booleans(value):
    from factory.data_contract import DataError
    from factory.data_contract.generate import read_contract
    from factory.data_contract.runtime import validate_entity

    record = frame().iloc[0].to_dict() | {"timestamp": frame().index[0]}
    record["is_filled"] = value
    with pytest.raises(DataError, match="SPY.*entity_fields.dtype.*is_filled"):
        validate_entity(read_contract(), "Bar", record, dataset="SPY")


def test_record_dates_are_real_calendar_dates():
    from factory.data_contract import DataError
    from factory.data_contract.generate import read_contract
    from factory.data_contract.runtime import validate_entity

    spec = read_contract()
    # Exercise the actual Dataset field definition without unrelated provenance fields.
    spec["ontology"]["Dataset"]["fields"] = {
        "start": spec["ontology"]["Dataset"]["fields"]["start"]
    }
    for invalid in ("2024-99-99", "2023-02-29", "2024-02-30"):
        with pytest.raises(DataError, match="SPY.*entity_fields.date.*start"):
            validate_entity(spec, "Dataset", {"start": invalid}, dataset="SPY")
    validate_entity(spec, "Dataset", {"start": "2024-02-29"}, dataset="SPY")


def test_unsupported_record_dtype_fails_closed():
    from factory.data_contract import DataError
    from factory.data_contract.generate import read_contract
    from factory.data_contract.runtime import validate_entity

    spec = read_contract()
    spec["ontology"]["Instrument"]["fields"]["symbol"]["dtype"] = "made_up"
    with pytest.raises(DataError, match="SPY.*entity_fields.dtype"):
        validate_entity(
            spec,
            "Instrument",
            {
                "symbol": "SPY",
                "asset_class": "etf",
                "currency": "USD",
                "calendar": "XNYS",
                "timezone": "America/New_York",
            },
            dataset="SPY",
        )


def test_unknown_dtype_fails_generation():
    from factory.data_contract.generate import artifacts, read_contract

    spec = read_contract()
    spec["ontology"]["Instrument"]["fields"]["symbol"]["dtype"] = "made_up"
    with pytest.raises(ValueError, match="Unknown.*dtype"):
        artifacts(spec)


def test_unknown_record_operation_fails_generation():
    from factory.data_contract.generate import artifacts, read_contract

    spec = read_contract()
    spec["record_invariants"][0]["op"] = "made_up"
    with pytest.raises(ValueError, match="Unknown.*operation"):
        artifacts(spec)


@pytest.mark.parametrize("change", ["open", "close", "duration_minutes", "session_date"])
def test_session_records_match_the_scheduled_half_day(change):
    from factory.data_contract import DataError
    from factory.data_contract.generate import read_contract
    from factory.data_contract.runtime import validate_entity

    spec = read_contract()
    record = {
        "session_date": pd.Timestamp("2024-11-29", tz="America/New_York"),
        "open": pd.Timestamp("2024-11-29T14:30:00Z"),
        "close": pd.Timestamp("2024-11-29T18:00:00Z"),
        "duration_minutes": 210,
    }
    validate_entity(spec, "Session", record, dataset="XNYS")
    if change == "duration_minutes":
        record[change] = 390
    elif change == "session_date":
        record[change] += pd.Timedelta(days=1)
    else:
        record[change] += pd.Timedelta(minutes=1)
    with pytest.raises(DataError, match="XNYS.*session_interval"):
        validate_entity(spec, "Session", record, dataset="XNYS")


@pytest.mark.parametrize("change", ["interval", "fraction"])
def test_split_record_interval_and_name_fraction(change):
    from factory.data_contract import DataError
    from factory.data_contract.generate import read_contract
    from factory.data_contract.runtime import validate_entity

    spec = read_contract()
    record = {
        "name": "IS",
        "start": "2024-03-11T13:30:00Z",
        "end": "2024-03-11T19:59:00Z",
        "fraction": 0.6,
    }
    validate_entity(spec, "Split", record, dataset="1min")
    if change == "interval":
        record["start"], record["end"] = record["end"], record["start"]
    else:
        record["fraction"] = 0.2
    with pytest.raises(DataError, match="1min.*split_interval"):
        validate_entity(spec, "Split", record, dataset="1min")
