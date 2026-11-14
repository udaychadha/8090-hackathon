"""Long from decision time 10:00 to 15:30 NY, flat at any scheduled close."""

import pandas as pd

FREQUENCY = "1min"
UNIVERSE = ["SPY"]
PARAMS = {"entry_start_minute": 29, "exit_start_minute": 359, "long_weight": 1.0}


def generate_signals(bars, params):
    frame = bars["SPY"]
    active = (
        (frame.minutes_since_open >= params["entry_start_minute"])
        & (frame.minutes_since_open < params["exit_start_minute"])
        & ~frame.is_last_bar
    )
    return pd.DataFrame({"SPY": active.astype(float) * params["long_weight"]}, index=frame.index)
