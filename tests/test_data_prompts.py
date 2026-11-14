"""Prompt context is authoritative documentation and a bounded, actual IS sample."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factory.data_contract.errors import DataError
from factory.data_contract.sessions import add_session_columns


def prompt_api():
    from factory.data_contract import prompts

    return prompts


def input_bars(count=390, frequency="1min"):
    if frequency == "1min":
        index = pd.date_range("2024-03-11T13:30Z", periods=count, freq="min", name="timestamp")
    else:
        index = pd.date_range("2024-03-11T04:00Z", periods=count, freq="D", name="timestamp")
    frame = pd.DataFrame(index=index)
    for column in ("open", "high", "low", "close"):
        frame[column] = 100 + np.arange(count, dtype=float) / 100
    frame["volume"] = np.arange(count, dtype=float)
    frame["is_filled"] = False
    frame.attrs.update(split="IS", path="private/data/SPY.parquet", key="secret-sentinel")
    return {"SPY": frame}


def test_context_has_live_schema_and_three_unmodified_actual_rows(monkeypatch):
    prompts = prompt_api()
    monkeypatch.setenv("OPENAI_API_KEY", "secret-sentinel")
    source = input_bars()
    original = source["SPY"].copy(deep=True)
    result = prompts.worker_context(source, "1min")
    expected = add_session_columns(source["SPY"], "1min")
    assert result["split"] == "IS"
    assert result["data_contract"] == (Path(__file__).parents[1] / "docs/DATA.md").read_text()
    assert set(result) == {"split", "data_contract", "is_schema", "example_rows"}
    assert result["is_schema"]["SPY"] == {
        "columns": list(expected.columns),
        "dtypes": {name: str(dtype) for name, dtype in expected.dtypes.items()},
        "index": "datetime64[ns, UTC]",
    }
    examples = result["example_rows"]
    assert len(examples) == 3
    assert [row["timestamp"] for row in examples] == [
        "2024-03-11T13:30:00+00:00",
        "2024-03-11T13:59:00+00:00",
        "2024-03-11T19:59:00+00:00",
    ]
    for example, position in zip(examples, [0, 29, 389], strict=True):
        assert example["symbol"] == "SPY"
        assert set(example) == {"symbol", "timestamp", *expected.columns}
        for field in expected:
            actual = expected[field].iloc[position]
            assert example[field] == (
                actual.isoformat() if isinstance(actual, pd.Timestamp) else actual
            )
        assert type(example["is_filled"]) is bool
        assert type(example["minutes_since_open"]) is int
    serialized = json.dumps(result, allow_nan=False)
    assert "secret-sentinel" not in serialized
    assert "private/data/SPY.parquet" not in serialized
    pd.testing.assert_frame_equal(source["SPY"], original)


@pytest.mark.parametrize(
    "frequency,count,positions", [("1min", 5, [0, 2, 4]), ("1day", 3, [0, 1, 2])]
)
def test_short_inputs_use_three_unique_spread_rows(frequency, count, positions):
    source = input_bars(count, frequency)
    result = prompt_api().worker_context(source, frequency)
    assert [row["timestamp"] for row in result["example_rows"]] == [
        source["SPY"].index[position].isoformat() for position in positions
    ]


@pytest.mark.parametrize("split", ["OOS", "HOLDOUT"])
def test_refuses_non_is_rows_even_when_other_symbol_is_is(split):
    source = input_bars()
    source["QQQ"] = source["SPY"].copy()
    source["QQQ"].attrs["split"] = split
    with pytest.raises(DataError, match="IS"):
        prompt_api().worker_context(source, "1min")


def test_missing_split_attribute_allows_synthetic_callers():
    source = input_bars(3)
    source["SPY"].attrs.clear()
    assert len(prompt_api().worker_context(source, "1min")["example_rows"]) == 3


def test_rejects_existing_forged_or_partial_session_context():
    source = input_bars()
    source["SPY"] = add_session_columns(source["SPY"], "1min")
    source["SPY"].iloc[4, source["SPY"].columns.get_loc("minutes_since_open")] = 99
    with pytest.raises(DataError, match="session_derivation"):
        prompt_api().worker_context(source, "1min")
    source = input_bars()
    source["SPY"]["is_last_bar"] = True
    with pytest.raises(DataError, match="session_derivation"):
        prompt_api().worker_context(source, "1min")


@pytest.mark.parametrize("count", [0, 1, 2])
def test_insufficient_rows_cannot_fabricate_three_examples(count):
    with pytest.raises(DataError, match="three"):
        prompt_api().worker_context(input_bars(count), "1min")


@pytest.mark.parametrize(
    "changed",
    [
        "docs/DATA.md",
        "factory/data_contract/agent_data.md",
        "factory/data_contract/generated.py",
        "yaml",
    ],
)
def test_context_rejects_stale_contract_artifacts(tmp_path, monkeypatch, changed):
    from factory.data_contract import generate

    prompts = prompt_api()
    generate.generate(root=tmp_path)
    monkeypatch.setattr(prompts, "ROOT", tmp_path)
    if changed == "yaml":
        source = tmp_path / "contract.yaml"
        source.write_text(
            generate.SOURCE.read_text().replace(
                "schema_version: '1.0.0'", "schema_version: '9.0.0'"
            )
        )
        monkeypatch.setattr(generate, "SOURCE", source)
    else:
        with (tmp_path / changed).open("a") as stream:
            stream.write("\nstale edit\n")
    with pytest.raises(ValueError, match="stale"):
        prompts.data_section()


def test_extractor_and_critic_receive_generated_context(monkeypatch):
    from factory.agents import critic, extractor
    from factory.llm import Completion

    section = (Path(__file__).parents[1] / "docs/DATA.md").read_text()
    supplied = {
        "paper_id": "p_" + hashlib.sha256(b"paper").hexdigest()[:16],
        "title": "Example",
        "category": "momentum",
        "hypothesis": "Trend persists",
        "universe": ["SPY"],
        "frequency": "1day",
        "signal_rules": ["Prior trend"],
        "claimed_metrics": {},
        "ambiguities": ["Sizing unspecified"],
        "test_type": "replication",
    }
    calls = []

    def complete(role, system, user, **kwargs):
        calls.append((role, system))
        return Completion(
            json.dumps(supplied)
            if role == "extractor"
            else '{"review_topics":["execution_convention"]}',
            "test",
            1,
            1,
            0,
            0,
        )

    monkeypatch.setattr(extractor, "complete", complete)
    monkeypatch.setattr(critic, "complete", complete)
    spec, _ = extractor.extract_text("paper", {"1day": ["SPY"]})
    assert critic.TOPICS["execution_convention"] in critic.critique(spec, "A", {}).text
    assert [role for role, _ in calls] == ["extractor", "critic"]
    assert all(system.endswith(section) for _, system in calls)


def test_examples_choose_first_symbol_with_three_real_rows():
    source = input_bars(2)
    source["QQQ"] = input_bars(5)["SPY"]
    result = prompt_api().worker_context(source, "1min")
    assert {row["symbol"] for row in result["example_rows"]} == {"QQQ"}
    assert set(result["is_schema"]) == {"SPY", "QQQ"}
