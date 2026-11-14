"""Generated agent context; callers must supply IS-only frames, never a data root."""

import numpy as np
import pandas as pd

from factory.data_contract import generate
from factory.data_contract.errors import fail
from factory.data_contract.sessions import (
    add_session_columns,
    protected_session_columns,
    validate_session_columns,
)

ROOT = generate.ROOT


def data_section() -> str:
    """Return exact generated documentation after checking every generated artifact."""
    generate.check(root=ROOT)
    return (ROOT / "docs/DATA.md").read_text()


def _example_positions(frame: pd.DataFrame, frequency: str) -> list[int]:
    if frequency == "1min":
        first_session = frame.session_date.eq(frame.session_date.iloc[0])
        choices = [
            np.flatnonzero((first_session & frame.is_first_bar).to_numpy()),
            np.flatnonzero((first_session & frame.minutes_since_open.eq(29)).to_numpy()),
            np.flatnonzero((first_session & frame.is_last_bar).to_numpy()),
        ]
        if all(len(choice) for choice in choices):
            positions = [int(choice[0]) for choice in choices]
            if len(set(positions)) == 3:
                return positions
    return [0, len(frame) // 2, len(frame) - 1]


def _scalar(value):
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    return value


def worker_context(bars: dict[str, pd.DataFrame], frequency: str, *, extra=None) -> dict:
    """Describe supplied IS frames and exactly three unchanged, distinct rows.

    Production callers must use load_bars(..., split='IS'). An absent split
    attribute is accepted only to support synthetic callers; explicit non-IS
    metadata is always rejected, including on symbols not selected for examples.
    This helper never reads market-data files or copies frame attributes.
    """
    if frequency not in ("1min", "1day"):
        fail("worker context", "frequency", detail=f"Unsupported frequency {frequency!r}")
    if not bars:
        fail("worker context", "examples", detail="Need three actual IS rows")
    for symbol, frame in bars.items():
        if "split" in frame.attrs and frame.attrs["split"] != "IS":
            fail(symbol, "worker_context.split", frame, detail="Only IS data may enter a prompt")
    section = data_section()
    prepared = {}
    for symbol, frame in bars.items():
        if set(protected_session_columns()) & set(frame.columns):
            validate_session_columns(frame, frequency, symbol)
            prepared[symbol] = frame
        else:
            prepared[symbol] = add_session_columns(frame, frequency)
    eligible = [(symbol, frame) for symbol, frame in prepared.items() if len(frame) >= 3]
    if not eligible:
        fail(
            "worker context", "examples", detail="Need three distinct actual IS rows for one symbol"
        )
    symbol, frame = eligible[0]
    examples = [
        {
            "symbol": symbol,
            "timestamp": frame.index[position].isoformat(),
            **{name: _scalar(frame[name].iloc[position]) for name in frame},
        }
        for position in _example_positions(frame, frequency)
    ]
    context = {
        "data_contract": section,
        "is_schema": {
            symbol: {
                "columns": list(frame.columns),
                "dtypes": {name: str(dtype) for name, dtype in frame.dtypes.items()},
                "index": str(frame.index.dtype),
            }
            for symbol, frame in prepared.items()
        },
        "example_rows": examples,
        "split": "IS",
    }
    if extra is not None:
        from factory.event_execution import decision_times, truncate_extra

        # The caller may supply only validated event datasets. Always re-apply
        # the IS visibility bound before copying any observation into a prompt.
        visible = truncate_extra(extra, decision_times(prepared, frequency).max())
        context["events"] = {
            name: {
                "columns": list(events.columns),
                "dtypes": {key: str(dtype) for key, dtype in events.dtypes.items()},
                "example_rows": [
                    {key: _scalar(value) for key, value in row.items()}
                    for row in events.head(3).to_dict("records")
                ],
            }
            for name, events in visible.items()
        }
    return context
