"""Fixture: rigged.py with the leak removed. Still flips side every bar."""

import numpy as np
import pandas as pd

FREQUENCY = "1day"
UNIVERSE = ["SPY"]
PARAMS = {"period": 2}


def generate_signals(bars, params):
    close = bars["SPY"].close
    side = pd.Series(
        np.where(np.arange(len(close)) % params["period"] == 0, 1.0, -1.0), index=close.index
    )
    return pd.DataFrame({"SPY": side})
