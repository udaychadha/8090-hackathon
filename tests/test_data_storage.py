import hashlib
import json

import pandas as pd
import pytest

from factory.data import OHLCV, expected_index, load_bars, split_boundaries


def daily():
    index = expected_index("1day", "2024-06-03", "2024-06-14")
    return pd.DataFrame({**{c: 100.0 for c in OHLCV}, "is_filled": False}, index=index)


def store(tmp_path):
    from factory.data_contract.storage import write_dataset

    tier = tmp_path / "1day"
    path = tier / "SPY.parquet"
    frame = daily()
    write_dataset(
        path,
        frame,
        kind="price_bars",
        frequency="1day",
        start="2024-06-03",
        through="2024-06-14",
        source="https://data.alpaca.markets/v2/stocks/bars",
        feed="sip",
        adjustment="all",
    )
    (tier / "manifest.json").write_text(
        json.dumps(
            {
                "frequency": "1day",
                "start": "2024-06-03",
                "through": "2024-06-14",
                "feed": "sip",
                "adjustment": "all",
                "symbols": ["SPY"],
                "complete": True,
                "splits": split_boundaries(frame.index),
            }
        )
    )
    return path


def test_write_and_load_require_a_valid_manifest(tmp_path):
    from factory.data_contract import DataError
    from factory.data_contract.storage import manifest_path, read_dataset

    path = store(tmp_path)
    pd.testing.assert_frame_equal(read_dataset(path), daily())
    loaded = load_bars(tmp_path, "1day", ["SPY"], split="IS")["SPY"]
    assert len(loaded) == 6 and "is_filled" in loaded
    entry = json.loads(manifest_path(path).read_text())
    assert entry["schema_version"] == "1.0.0"
    assert entry["row_count"] == 10 and entry["fill_rate"] == 0.0
    assert entry["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path(path).unlink()
    with pytest.raises(DataError, match="SPY.*manifest.*row="):
        load_bars(tmp_path, "1day", ["SPY"], split="IS")


@pytest.mark.parametrize(
    "fault", ["missing_flag", "off_split_corruption", "hash", "count", "adjustment", "split"]
)
def test_no_invalid_file_can_load_even_if_error_is_outside_split(tmp_path, fault):
    from factory.data_contract import DataError
    from factory.data_contract.storage import manifest_path

    path = store(tmp_path)
    sidecar = manifest_path(path)
    entry = json.loads(sidecar.read_text())
    if fault in ("missing_flag", "off_split_corruption", "hash"):
        frame = pd.read_parquet(path)
        if fault == "missing_flag":
            frame = frame.drop(columns="is_filled")
        else:
            frame.iloc[-1, frame.columns.get_loc("volume")] = -1.0
        frame.to_parquet(path)
        if fault != "hash":
            entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    elif fault == "count":
        entry["row_count"] = 11
    elif fault == "adjustment":
        entry["adjustment"] = "not_applicable"
    else:
        p = path.parent / "manifest.json"
        tier = json.loads(p.read_text())
        tier["splits"]["IS"]["end"] = tier["splits"]["HOLDOUT"]["end"]
        p.write_text(json.dumps(tier))
    sidecar.write_text(json.dumps(entry))
    with pytest.raises(DataError, match="row="):
        load_bars(tmp_path, "1day", ["SPY"], split="IS")


def test_invalid_write_creates_no_dataset(tmp_path):
    from factory.data_contract import DataError
    from factory.data_contract.storage import write_dataset

    f = daily().drop(columns="is_filled")
    path = tmp_path / "bad.parquet"
    with pytest.raises(DataError, match="bad.*columns.*row="):
        write_dataset(
            path,
            f,
            kind="price_bars",
            frequency="1day",
            start="2024-06-03",
            through="2024-06-14",
            source="test",
            feed="sip",
            adjustment="all",
        )
    assert not path.exists()


def test_events_roundtrip_and_bad_availability(tmp_path):
    from factory.data_contract import DataError
    from factory.data_contract.storage import read_dataset, write_dataset

    f = pd.DataFrame(
        {
            "available_at": pd.to_datetime(["2024-06-03T13:00Z"]),
            "symbol": pd.Series(["SPY"], dtype="string"),
            "score": [1.0],
        }
    )
    path = tmp_path / "events.parquet"
    kwargs = dict(
        kind="events",
        frequency="event",
        start="2024-06-03",
        through="2024-06-03",
        source="approved upload",
        feed="user_supplied",
        adjustment="not_applicable",
    )
    write_dataset(path, f, **kwargs)
    pd.testing.assert_frame_equal(read_dataset(path), f)
    f["available_at"] = f.available_at.dt.tz_localize(None)
    with pytest.raises(DataError, match="dtype"):
        write_dataset(path, f, **kwargs)
    assert str(read_dataset(path).available_at.dtype) == "datetime64[ns, UTC]"


def test_event_load_filters_by_availability(tmp_path):
    from factory.data_contract.storage import load_events, write_dataset

    f = pd.DataFrame(
        {
            "available_at": pd.to_datetime(["2024-06-03T13:00Z", "2024-06-04T13:00Z"]),
            "symbol": pd.Series(["SPY", "SPY"], dtype="string"),
            "score": [1.0, 2.0],
        }
    )
    path = tmp_path / "events.parquet"
    write_dataset(
        path,
        f,
        kind="events",
        frequency="event",
        start="2024-06-03",
        through="2024-06-04",
        source="approved upload",
        feed="user_supplied",
        adjustment="not_applicable",
    )
    assert load_events(path, as_of="2024-06-03T14:00Z").score.tolist() == [1.0]


def test_corrupt_resume_does_not_call_provider(tmp_path):
    from factory.data import DataError
    from factory.ingest_alpaca import ingest_symbol

    class Client:
        calls = 0

        def fetch(self, *args):
            self.calls += 1
            return daily().drop(columns="is_filled")

    client = Client()
    ingest_symbol(client, tmp_path, "1day", "SPY", "2024-06-03", "2024-06-14")
    path = tmp_path / "1day/SPY.parquet"
    f = pd.read_parquet(path)
    f.iloc[-1, f.columns.get_loc("volume")] = -1.0
    f.to_parquet(path)
    with pytest.raises(DataError, match="sha256"):
        ingest_symbol(client, tmp_path, "1day", "SPY", "2024-06-03", "2024-06-14")
    assert client.calls == 1


def test_bad_requested_dates_have_dataerror_context(tmp_path):
    from factory.data_contract import DataError
    from factory.data_contract.storage import write_dataset

    with pytest.raises(DataError, match="bad.*calendar.*row="):
        write_dataset(
            tmp_path / "bad.parquet",
            daily(),
            kind="price_bars",
            frequency="1day",
            start="2024-99-99",
            through="2024-06-14",
            source="test",
            feed="sip",
            adjustment="all",
        )
