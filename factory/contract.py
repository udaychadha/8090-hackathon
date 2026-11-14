"""Strategy metadata, source policy, input validation, and target-weight contract.

The source checks are deliberately conservative lint, not a Python security
proof. Actual execution belongs in factory.sandbox, never in a worker process
that holds OOS/HOLDOUT data or credentials.
"""

from __future__ import annotations

import ast
import builtins
import math
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from factory.data import OHLCV, DataError, Frequency, validate_symbol


class ContractViolation(ValueError):
    """A strategy bug, eligible for later bug-only self-heal."""


class ClaimedMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    sharpe: float | None = None
    sample_period: str | None = None
    costs_assumed: str | None = None


class StrategySpec(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    paper_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1)
    category: str = Field(min_length=1)
    hypothesis: str = Field(min_length=1)
    universe: list[str] = Field(min_length=1)
    frequency: Frequency
    signal_rules: list[str] = Field(min_length=1)
    claimed_metrics: ClaimedMetrics
    ambiguities: list[str] = Field(min_length=1)
    test_type: Literal["replication", "transfer"]

    @field_validator("universe")
    @classmethod
    def valid_universe(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Universe contains duplicate symbols")
        return [validate_symbol(symbol) for symbol in value]

    @field_validator("signal_rules", "ambiguities")
    @classmethod
    def nonempty_entries(cls, value):
        if any(not item.strip() for item in value):
            raise ValueError("Entries must not be blank")
        return value


@dataclass(frozen=True)
class StrategyDefinition:
    source: str
    frequency: Frequency
    universe: tuple[str, ...]
    params: dict


SAFE_BUILTINS = {
    "abs",
    "all",
    "any",
    "bool",
    "dict",
    "enumerate",
    "float",
    "int",
    "isinstance",
    "len",
    "list",
    "max",
    "min",
    "range",
    "round",
    "set",
    "sorted",
    "str",
    "sum",
    "tuple",
    "zip",
    "ValueError",
    "TypeError",
    "RuntimeError",
    "Exception",
}
ALLOWED_IMPORTS = {"numpy", "pandas", "math"}
# Known deterministic scientific operations. Unknown calls fail closed and
# yield actionable contract errors instead of silently admitting I/O helpers.
SAFE_METHODS = {
    "DataFrame",
    "Series",
    "Index",
    "DatetimeIndex",
    "Timestamp",
    "Timedelta",
    "DateOffset",
    "abs",
    "absolute",
    "add",
    "agg",
    "aggregate",
    "align",
    "all",
    "any",
    "append",
    "apply",
    "arange",
    "argmax",
    "argmin",
    "argsort",
    "array",
    "asarray",
    "assign",
    "astype",
    "at_time",
    "between",
    "between_time",
    "bfill",
    "clip",
    "column_stack",
    "combine_first",
    "concat",
    "copy",
    "corr",
    "count",
    "cov",
    "cummax",
    "cummin",
    "cumprod",
    "cumsum",
    "date",
    "date_range",
    "diff",
    "div",
    "divide",
    "dot",
    "drop",
    "dropna",
    "duplicated",
    "empty",
    "eq",
    "ewm",
    "exp",
    "expand_dims",
    "expanding",
    "fillna",
    "ffill",
    "first",
    "flatten",
    "floor",
    "floor_divide",
    "full",
    "full_like",
    "ge",
    "get",
    "groupby",
    "gt",
    "head",
    "idxmax",
    "idxmin",
    "insert",
    "interpolate",
    "isclose",
    "isfinite",
    "isin",
    "isna",
    "isnan",
    "isnull",
    "items",
    "join",
    "keys",
    "kurt",
    "last",
    "le",
    "log",
    "log1p",
    "logical_and",
    "logical_not",
    "logical_or",
    "lt",
    "mask",
    "max",
    "maximum",
    "mean",
    "median",
    "merge",
    "min",
    "minimum",
    "mode",
    "mul",
    "multiply",
    "ne",
    "nlargest",
    "nsmallest",
    "normalize",
    "notna",
    "notnull",
    "nunique",
    "ones",
    "ones_like",
    "pct_change",
    "pivot",
    "pivot_table",
    "pow",
    "power",
    "prod",
    "quantile",
    "rank",
    "reindex",
    "reindex_like",
    "rename",
    "rename_axis",
    "repeat",
    "replace",
    "resample",
    "reset_index",
    "reshape",
    "rolling",
    "round",
    "select",
    "set_axis",
    "set_index",
    "shift",
    "sign",
    "size",
    "skew",
    "sort_index",
    "sort_values",
    "sqrt",
    "square",
    "squeeze",
    "stack",
    "std",
    "sub",
    "subtract",
    "sum",
    "tail",
    "take",
    "to_datetime",
    "to_list",
    "to_numpy",
    "tolist",
    "transform",
    "transpose",
    "truediv",
    "tz_convert",
    "tz_localize",
    "unstack",
    "update",
    "values",
    "var",
    "where",
    "xs",
    "zeros",
    "zeros_like",
    "ceil",
    "isinf",
    "copysign",
    "expm1",
    "log2",
    "log10",
    "default_rng",
    "normal",
    "standard_normal",
    "uniform",
    "integers",
    "choice",
}


def validate_params(params: dict, base: dict | None = None) -> dict:
    if not isinstance(params, dict) or any(not isinstance(key, str) or not key for key in params):
        raise ContractViolation("PARAMS must be a dict with nonempty string keys")
    for key, value in params.items():
        if type(value) not in (int, float, bool, str) or (
            isinstance(value, (int, float)) and not math.isfinite(value)
        ):
            raise ContractViolation(f"PARAMS[{key!r}] must be a finite JSON scalar")
        if isinstance(value, str) and value.lower() in ("now", "today"):
            raise ContractViolation("Wall-clock parameter values are forbidden")
    if base is not None:
        if set(params) != set(base):
            raise ContractViolation("Parameter overrides must preserve every PARAMS key")
        for key in base:
            expected = type(base[key])
            if expected is float and type(params[key]) in (int, float):
                continue
            if type(params[key]) is not expected:
                raise ContractViolation(f"Parameter {key!r} must keep type {expected.__name__}")
    return dict(params)


def parse_strategy(
    source: str, *, available_universe: list[str] | None = None
) -> StrategyDefinition:
    try:
        tree = ast.parse(source, filename="strategy.py")
    except SyntaxError as error:
        raise ContractViolation(f"Syntax error at line {error.lineno}: {error.msg}") from error
    metadata, parameter_node, functions, imported_names = {}, None, set(), set()
    for node in tree.body:
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module]
            )
            if any(name not in ALLOWED_IMPORTS for name in names) or getattr(node, "level", 0):
                raise ContractViolation("Only numpy, pandas and math imports are allowed")
            for alias in node.names:
                if isinstance(node, ast.ImportFrom) and alias.asname:
                    raise ContractViolation("Import scientific functions by their original names")
                if alias.name == "*" or alias.name.startswith("_"):
                    raise ContractViolation("Wildcard/private imports are forbidden")
                imported_names.add(alias.asname or alias.name)
                if isinstance(node, ast.ImportFrom) and alias.name not in SAFE_METHODS | {
                    "nan",
                    "inf",
                    "pi",
                    "e",
                }:
                    raise ContractViolation(f"Unsupported scientific import: {alias.name}")
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            key = node.targets[0].id
            if key not in {"FREQUENCY", "UNIVERSE", "PARAMS"} or key in metadata:
                raise ContractViolation(
                    "Only one literal FREQUENCY, UNIVERSE and PARAMS assignment is allowed"
                )
            try:
                metadata[key] = ast.literal_eval(node.value)
            except (ValueError, TypeError) as error:
                raise ContractViolation(f"{key} must be a literal") from error
            if key == "PARAMS":
                parameter_node = node.value
        elif isinstance(node, ast.FunctionDef):
            if node.decorator_list or node.name in functions or node.name.startswith("_"):
                raise ContractViolation(
                    "Strategy functions must be unique, public, and undecorated"
                )
            functions.add(node.name)
        else:
            raise ContractViolation(f"Unsupported module-level statement at line {node.lineno}")
    if set(metadata) != {"FREQUENCY", "UNIVERSE", "PARAMS"} or "generate_signals" not in functions:
        raise ContractViolation(
            "Define FREQUENCY, UNIVERSE, PARAMS and generate_signals(bars, params)"
        )
    if metadata["FREQUENCY"] not in ("1min", "1day"):
        raise ContractViolation("FREQUENCY must be '1min' or '1day'")
    universe = metadata["UNIVERSE"]
    if not isinstance(universe, list) or not universe:
        raise ContractViolation("UNIVERSE must be a nonempty list")
    try:
        for symbol in universe:
            validate_symbol(symbol)
    except DataError as error:
        raise ContractViolation(str(error)) from error
    if len(universe) != len(set(universe)):
        raise ContractViolation("UNIVERSE must have unique symbols")
    if available_universe is not None and not set(universe) <= set(available_universe):
        raise ContractViolation("UNIVERSE is not a subset of the tier")
    params = validate_params(metadata["PARAMS"])
    parameter_nodes = set(ast.walk(parameter_node))
    for node in ast.walk(tree):
        if node in parameter_nodes:
            continue
        if isinstance(node, (ast.Global, ast.Nonlocal, ast.AsyncFunctionDef, ast.Await)):
            raise ContractViolation(
                f"Global state and async execution are forbidden (line {node.lineno})"
            )
        if isinstance(node, ast.Import | ast.ImportFrom) and node not in tree.body:
            raise ContractViolation("Imports must be at module scope")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ContractViolation("Private/reflection names are forbidden")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ContractViolation("Private/reflection attributes are forbidden")
        if isinstance(node, ast.Constant):
            if type(node.value) in (int, float, complex) and node.value not in (0, 1):
                raise ContractViolation(f"Move numeric literal at line {node.lineno} into PARAMS")
            if isinstance(node.value, str) and node.value.lower() in ("now", "today"):
                raise ContractViolation("Wall-clock values are forbidden")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id not in SAFE_BUILTINS | functions | imported_names:
                    raise ContractViolation(
                        f"Unsupported function {node.func.id} at line {node.lineno}"
                    )
            elif isinstance(node.func, ast.Attribute):
                if node.func.attr not in SAFE_METHODS:
                    raise ContractViolation(
                        f"Unsupported method {node.func.attr} at line {node.lineno}"
                    )
                if (
                    isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == "random"
                    and node.func.attr != "default_rng"
                ):
                    raise ContractViolation(
                        "Use numpy.random.default_rng(params['seed']) for randomness"
                    )
            else:
                raise ContractViolation("Indirect/dynamic function calls are forbidden")
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            if (
                name in {"Timestamp", "DatetimeIndex", "to_datetime", "date_range"}
                and not node.args
                and not node.keywords
            ):
                raise ContractViolation("Datetime constructors require explicit data")
            if name == "default_rng":
                seed = (
                    node.args[0]
                    if node.args
                    else next((k.value for k in node.keywords if k.arg == "seed"), None)
                )
                if (
                    not isinstance(seed, ast.Subscript)
                    or not isinstance(seed.value, ast.Name)
                    or seed.value.id not in {"params", "PARAMS"}
                ):
                    raise ContractViolation("default_rng requires an explicit seed from PARAMS")
                if (
                    not isinstance(seed.slice, ast.Constant)
                    or type(params.get(seed.slice.value)) is not int
                ):
                    raise ContractViolation("The RNG seed must be an integer PARAMS entry")
        if isinstance(node, ast.FunctionDef) and node.name == "generate_signals":
            args = node.args
            if (
                [arg.arg for arg in args.args] != ["bars", "params"]
                or args.posonlyargs
                or args.kwonlyargs
                or args.vararg
                or args.kwarg
                or args.defaults
            ):
                raise ContractViolation("Use exactly generate_signals(bars, params)")
    return StrategyDefinition(source, metadata["FREQUENCY"], tuple(universe), params)


def read_strategy(path: Path | str, **kwargs) -> StrategyDefinition:
    return parse_strategy(Path(path).read_text(), **kwargs)


def load_strategy(definition: StrategyDefinition) -> ModuleType:
    """Execute validated source. Call only inside the isolated subprocess."""
    safe_builtins = {key: getattr(builtins, key) for key in SAFE_BUILTINS}

    def import_scientific(name, globals=None, locals=None, fromlist=(), level=0):
        if level or name not in ALLOWED_IMPORTS:
            raise ContractViolation(f"Import forbidden: {name}")
        return builtins.__import__(name, globals, locals, fromlist, level)

    safe_builtins["__import__"] = import_scientific
    module = ModuleType("arena_strategy")
    module.__dict__["__builtins__"] = safe_builtins
    exec(compile(definition.source, "strategy.py", "exec"), module.__dict__)
    return module


def validate_bars(bars: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
    if not isinstance(bars, dict) or not bars:
        raise ContractViolation("bars must be a nonempty symbol → DataFrame dictionary")
    index = pd.DatetimeIndex([], tz="UTC", name="timestamp")
    for symbol, frame in bars.items():
        try:
            validate_symbol(symbol)
        except DataError as error:
            raise ContractViolation(str(error)) from error
        if not isinstance(frame, pd.DataFrame) or frame.empty or not set(OHLCV) <= set(frame):
            raise ContractViolation(f"{symbol}: require nonempty OHLCV DataFrame")
        if any(
            not pd.api.types.is_numeric_dtype(frame[column])
            or pd.api.types.is_complex_dtype(frame[column])
            for column in OHLCV
        ):
            raise ContractViolation(f"{symbol}: OHLCV must be real numeric values")
        current = frame.index
        if (
            not isinstance(current, pd.DatetimeIndex)
            or str(current.tz) != "UTC"
            or current.hasnans
            or not current.is_unique
            or not current.is_monotonic_increasing
        ):
            raise ContractViolation(f"{symbol}: timestamps must be unique, ordered and UTC")
        try:
            values = frame[OHLCV].to_numpy(dtype=float)
        except (ValueError, TypeError) as error:
            raise ContractViolation(f"{symbol}: OHLCV must be numeric") from error
        if not np.isfinite(values).all() or (values[:, :4] <= 0).any() or (values[:, 4] < 0).any():
            raise ContractViolation(
                f"{symbol}: prices must be finite/positive and volume nonnegative"
            )
        if (frame.high < frame[["open", "close", "low"]].max(axis=1)).any() or (
            frame.low > frame[["open", "close", "high"]].min(axis=1)
        ).any():
            raise ContractViolation(f"{symbol}: inconsistent OHLC")
        index = index.union(current)
    return index.sort_values()


def validate_weights(
    weights: pd.DataFrame, index: pd.DatetimeIndex, universe: list[str] | tuple[str, ...]
) -> pd.DataFrame:
    if not isinstance(weights, pd.DataFrame):
        raise ContractViolation("generate_signals must return a DataFrame")
    if not weights.index.equals(index) or not weights.index.is_unique:
        raise ContractViolation("Weights must match every input timestamp in order")
    if not weights.columns.is_unique or set(weights.columns) != set(universe):
        raise ContractViolation("Weight columns must match UNIVERSE exactly")
    if any(
        not pd.api.types.is_numeric_dtype(dtype) or pd.api.types.is_complex_dtype(dtype)
        for dtype in weights.dtypes
    ):
        raise ContractViolation("Weights must be real numeric values")
    weights = weights.loc[:, list(universe)].astype(float)
    values = weights.to_numpy()
    invalid = ~np.isfinite(values) | (np.abs(values) > 1)
    if invalid.any():
        row, column = np.argwhere(invalid)[0]
        raise ContractViolation(
            f"Invalid weight at {weights.index[row].isoformat()}, {weights.columns[column]}: "
            "each weight must be finite and in [-1, 1]; use zero during warmup"
        )
    gross = weights.abs().sum(axis=1)
    if (gross > 1 + 1e-12).any():
        stamp = gross.index[gross > 1 + 1e-12][0]
        raise ContractViolation(f"Gross exposure exceeds 1 at {stamp.isoformat()}")
    return weights
