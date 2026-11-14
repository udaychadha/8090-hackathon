from pathlib import Path

import numpy as np
import pytest

from factory.contract import ContractViolation
from factory.sandbox import StrategyExecutionError, StrategyTimeoutError, run_strategy


def write_strategy(tmp_path, source):
    path = tmp_path / "example.py"
    path.write_text(source)
    return path


def test_subprocess_roundtrip_and_parameter_override(tmp_path, five_bars, valid_source):
    path = write_strategy(tmp_path, valid_source)
    weights = run_strategy(path, five_bars, params={"weight": 0.5})
    np.testing.assert_allclose(weights.SPY, 0.5)
    assert weights.index.equals(five_bars["SPY"].index)


def test_runtime_traceback_preserved(tmp_path, five_bars, valid_source):
    source = (
        valid_source[: valid_source.index("    return")]
        + '    raise RuntimeError("deliberate bug")'
    )
    with pytest.raises(StrategyExecutionError, match="deliberate bug") as error:
        run_strategy(write_strategy(tmp_path, source), five_bars)
    assert 'File "strategy.py"' in error.value.remote_traceback


def test_invalid_generated_weights_rejected(tmp_path, five_bars, valid_source):
    source = valid_source.replace('"weight": 0.25', '"weight": 1.5')
    with pytest.raises(ContractViolation, match="Invalid weight"):
        run_strategy(write_strategy(tmp_path, source), five_bars)


def test_stateful_nondeterminism_is_a_contract_bug(tmp_path, five_bars, valid_source):
    source = valid_source.replace('params["weight"]', 'params["weight"] * counter()')
    source += "\ndef counter(history=[]):\n    history.append(1)\n    return len(history)\n"
    with pytest.raises(ContractViolation, match="nondeterministic"):
        run_strategy(write_strategy(tmp_path, source), five_bars)


def test_timeout_cleans_temp_directory_and_strips_credentials(
    tmp_path, five_bars, valid_source, monkeypatch
):
    from factory import sandbox

    original = sandbox.subprocess.Popen
    observed = {}

    def capture(*args, **kwargs):
        observed.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(sandbox.subprocess, "Popen", capture)
    monkeypatch.setenv("APCA_API_KEY_ID", "test-secret-never-forward")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-secret-never-forward")
    source = valid_source[: valid_source.index("    return")] + "    while True:\n        pass\n"
    with pytest.raises(StrategyTimeoutError):
        run_strategy(write_strategy(tmp_path, source), five_bars, timeout=0.2)
    assert "APCA_API_KEY_ID" not in observed["env"]
    assert "ANTHROPIC_API_KEY" not in observed["env"]
    assert not Path(observed["cwd"]).exists()


def test_seeded_random_strategy_is_repeatable(tmp_path, five_bars):
    source = """import numpy as np
import pandas as pd
FREQUENCY = "1day"
UNIVERSE = ["SPY"]
PARAMS = {"seed": 7, "low": -0.5, "high": 0.5}
def generate_signals(bars, params):
    rng = np.random.default_rng(params["seed"])
    values = rng.uniform(params["low"], params["high"], len(bars["SPY"]))
    return pd.DataFrame(values, index=bars["SPY"].index, columns=UNIVERSE)
"""
    path = write_strategy(tmp_path, source)
    first, second = run_strategy(path, five_bars), run_strategy(path, five_bars)
    np.testing.assert_array_equal(first, second)
