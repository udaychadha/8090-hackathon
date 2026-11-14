import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def five_bars():
    index = pd.date_range("2024-06-03T04:00:00Z", periods=5, freq="B", name="timestamp")
    close = np.array([100.0, 110.0, 99.0, 118.8, 106.92])
    frame = pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": 100.0}, index=index
    )
    return {"SPY": frame}


@pytest.fixture
def valid_source():
    return """import pandas as pd
FREQUENCY = "1day"
UNIVERSE = ["SPY"]
PARAMS = {"weight": 0.25}

def generate_signals(bars, params):
    return pd.DataFrame(params["weight"], index=bars["SPY"].index, columns=UNIVERSE)
"""
