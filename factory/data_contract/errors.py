class DataError(ValueError):
    """Missing, malformed, or incompatible market data."""


def fail(dataset, rule, frame=None, position=0, detail=""):
    row = "<dataset>"
    if frame is not None and len(frame):
        position = min(int(position), len(frame) - 1)
        row = f"{position}:{frame.index[position]}"
    raise DataError(f"{dataset}: rule={rule}; row={row}; {detail}")
