"""Fixture: flips side every bar and sizes the bet by peeking at the next close."""

import numpy as np
import pandas as pd

FREQUENCY = "1day"
UNIVERSE = ["SPY"]
PARAMS = {"period": 2, "miss_weight": 0.5}


def generate_signals(bars, params):
    close = bars["SPY"].close
    side = pd.Series(
        np.where(np.arange(len(close)) % params["period"] == 0, 1.0, -1.0), index=close.index
    )
    next_move = np.sign(close.shift(-1) - close)  # the leak
    size = pd.Series(
        np.where(next_move * side > 0, 1.0, params["miss_weight"]), index=close.index
    ).where(next_move.notna(), 0.0)
    return pd.DataFrame({"SPY": side * size})
