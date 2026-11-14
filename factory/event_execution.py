"""Causal event inputs: availability is checked at every completed-bar decision.

Stored event frames are validated before visibility filtering. Generated code
receives fresh copies of visible rows only, with no metadata or original index
that could carry hidden future observations. The legacy vectorized path does
not use this module.
"""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd

from factory.contract import ContractViolation, validate_weights
from factory.data import session_schedule
from factory.data_contract import DataError
from factory.data_contract.generated import SPEC, validate_events
from factory.data_contract.runtime import validate
from factory.data_contract.sessions import protected_session_columns


def decision_times(bars: dict[str, pd.DataFrame], frequency: str) -> pd.Series:
    """Map union bar labels to XNYS session close (daily) or bar end (minute)."""
    index = pd.DatetimeIndex([], tz="UTC", name="timestamp")
    for frame in bars.values():
        index = index.union(frame.index)
    index = index.sort_values()
    if frequency == "1min":
        clocks = index + pd.Timedelta(minutes=1)
    elif frequency == "1day":
        dates = index.tz_convert("America/New_York").normalize().tz_localize(None)
        if index.empty:
            clocks = index
        else:
            schedule = session_schedule(str(dates.min().date()), str(dates.max().date()))
            clocks = pd.DatetimeIndex(schedule.reindex(dates)["close"])
            if clocks.hasnans:
                raise ContractViolation("Daily event decisions require scheduled XNYS sessions")
    else:
        raise ContractViolation("Unsupported event decision frequency")
    return pd.Series(clocks, index=index, name="decision_time")


def validate_extra(extra: dict[str, pd.DataFrame] | None, required: tuple[str, ...]) -> dict:
    """Validate full supplied datasets; missing data never becomes an empty dataset."""
    if not isinstance(extra, dict) or not set(required) <= set(extra):
        raise ContractViolation(f"Required EXTRA datasets are missing: {', '.join(required)}")
    result = {}
    for name in required:
        try:
            frame = extra[name]
            if isinstance(frame, pd.DataFrame) and frame.empty:
                # Storage/load_extra validates the physical nonempty dataset first.
                # Visible subsets can be empty; all other canonical rules still run.
                visible_spec = copy.deepcopy(SPEC)
                visible_spec["datasets"]["events"]["invariants"] = [
                    rule
                    for rule in SPEC["datasets"]["events"]["invariants"]
                    if rule["op"] != "nonempty"
                ]
                validate(visible_spec, "events", frame, dataset=name)
            else:
                validate_events(frame, dataset=name)
        except DataError as error:
            raise ContractViolation(str(error)) from error
        result[name] = extra[name]
    return result


def prepare_event_ordinals(extra: dict[str, pd.DataFrame], decisions: pd.Series):
    """Prepare XNYS session ordinals, including disclosed events before the bar slice.

    An event first belongs to the session whose close is at or after its
    availability instant. These are public scheduled sessions, not future data.
    """
    first = decisions.min()
    for frame in extra.values():
        if not frame.empty:
            first = min(first, frame.available_at.min())
    start = str(first.tz_convert("America/New_York").date())
    through = str((decisions.max() + pd.Timedelta(days=7)).tz_convert("America/New_York").date())
    closes = pd.DatetimeIndex(session_schedule(start, through)["close"])
    return (
        closes.searchsorted(pd.DatetimeIndex(decisions), side="left"),
        {
            name: closes.searchsorted(frame.available_at, side="left")
            for name, frame in extra.items()
        },
    )


def truncate_extra(extra: dict[str, pd.DataFrame], as_of: pd.Timestamp, *, ordinals=None) -> dict:
    """Copy visible events and derive their read-only XNYS session age.

    The first available trading session has age zero. Original indices and attrs
    are removed. Empty visible subsets retain canonical column dtypes.
    ``ordinals`` is a trusted optimization: (current ordinal, per-dataset ordinals).
    """
    if ordinals is None:
        current, event_ordinals = prepare_event_ordinals(extra, pd.Series([as_of]))
        current = current[0]
    else:
        current, event_ordinals = ordinals
    result = {}
    for name, frame in extra.items():
        end = frame.available_at.searchsorted(as_of, side="right")
        visible = frame.iloc[:end].copy(deep=True).reset_index(drop=True)
        visible.attrs = {}
        visible["sessions_since_available"] = np.asarray(
            current - event_ordinals[name][:end], dtype="int64"
        )
        result[name] = visible
    return result


class _CausalBars(dict):
    """Dictionary whose public values are independent, current-prefix copies.

    Private backing references belong to the trusted harness, never frame attrs.
    Generated source cannot access private attributes. Materialize only symbols
    a strategy actually reads; checking unchanged, unread inputs is unnecessary.
    """

    def __init__(self, bars, positions, row):
        super().__init__((symbol, None) for symbol in bars)
        self._bars = bars
        self._positions = positions
        self._row = row
        self._accessed = set()

    def __iter__(self):
        # This override also prevents dict(self) from using dict's raw-value
        # copy shortcut; it calls our __getitem__ and obtains real prefixes.
        return super().__iter__()

    def __getitem__(self, symbol):
        value = super().__getitem__(symbol)
        if symbol not in self._accessed:
            end = self._positions[symbol][self._row]
            value = self._bars[symbol].iloc[:end].copy(deep=True)
            value.attrs = {}
            super().__setitem__(symbol, value)
            self._accessed.add(symbol)
        return value

    def __setitem__(self, symbol, value):
        self._accessed.add(symbol)
        super().__setitem__(symbol, value)

    def get(self, symbol, default=None):
        return self[symbol] if symbol in self else default

    def items(self):
        return ((symbol, self[symbol]) for symbol in self)

    def values(self):
        return (self[symbol] for symbol in self)

    def copy(self):
        return {symbol: self[symbol] for symbol in self}

    def update(self, other=(), **kwargs):
        for symbol, value in dict(other, **kwargs).items():
            self[symbol] = value

    def validate_protected(self):
        if set(self) != set(self._bars):
            raise ContractViolation("Bar symbols/session fields are read-only")
        protected = list(protected_session_columns())
        assigned = {symbol for symbol, value in super().items() if value is not None}
        for symbol in self._accessed | assigned:
            end = self._positions[symbol][self._row]
            original = self._bars[symbol].iloc[:end]
            columns = protected + (["is_filled"] if "is_filled" in original else [])
            try:
                if not original[columns].equals(super().__getitem__(symbol)[columns]):
                    raise AssertionError("Protected fields changed")
            except (AssertionError, KeyError, TypeError) as error:
                raise ContractViolation(
                    f"{symbol}: session/provenance fields are read-only"
                ) from error


def validate_observed_weights(weights, bars):
    """Reject exposure before a symbol's first observed price; never invent quotes."""
    for symbol, frame in bars.items():
        before = weights.index < frame.index[0] if len(frame) else np.ones(len(weights), dtype=bool)
        if weights.loc[before, symbol].ne(0).any():
            raise ContractViolation(f"{symbol}: weights must be zero before its first observed bar")


def generate_event_weights(strategy, definition, bars, params, extra):
    """Execute causal prefixes; accept only each invocation's final target.

    Event strategies may return either full-prefix weights or one row indexed
    by the current bar label, with the full declared universe in both cases.
    Historical targets never overwrite targets decided before later filings.
    Every returned weight still passes the exposure/shape/finite-value contract.
    """
    clocks = decision_times(bars, definition.frequency)
    index = clocks.index
    values = np.empty((len(index), len(definition.universe)), dtype=float)
    positions = {
        symbol: frame.index.searchsorted(index, side="right") for symbol, frame in bars.items()
    }
    observed = np.column_stack([positions[symbol] > 0 for symbol in definition.universe])
    current_ordinals, event_ordinals = prepare_event_ordinals(extra, clocks)
    for row, decision in enumerate(clocks):
        inputs = _CausalBars(bars, positions, row)
        visible = truncate_extra(extra, decision, ordinals=(current_ordinals[row], event_ordinals))
        ages = {
            name: frame["sessions_since_available"].copy(deep=True)
            for name, frame in visible.items()
        }
        output = strategy.generate_signals(inputs, copy.deepcopy(params), visible)
        inputs.validate_protected()
        for name, expected in ages.items():
            try:
                if not expected.equals(visible[name]["sessions_since_available"]):
                    raise AssertionError("Event session age changed")
            except (AssertionError, KeyError, TypeError) as error:
                raise ContractViolation(f"{name}: sessions_since_available is read-only") from error
        output_index = (
            index[row : row + 1]
            if isinstance(output, pd.DataFrame) and len(output) == 1
            else index[: row + 1]
        )
        weights = validate_weights(output, output_index, definition.universe)
        values[row] = weights.iloc[-1].to_numpy()
        invalid = (values[row] != 0) & ~observed[row]
        if invalid.any():
            symbol = definition.universe[np.flatnonzero(invalid)[0]]
            raise ContractViolation(f"{symbol}: weights must be zero before its first observed bar")
    return pd.DataFrame(values, index=index, columns=list(definition.universe))
