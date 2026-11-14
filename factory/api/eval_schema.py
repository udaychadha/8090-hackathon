"""Read-only descriptions of the existing harness; never evaluates or changes it."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from factory.evals import config

router = APIRouter(prefix="/api/evals", tags=["evals"])


class Tooltip(BaseModel):
    what_it_is: str
    if_raised: str
    if_lowered: str


class Knob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    label: str
    default: float
    min: float
    max: float
    locked: Literal[True] = True
    tooltip: Tooltip


class Check(Knob):
    metric: str
    op: Literal[">=", "<=", ">"]
    relative_to: str | None = None


class EvalDefinition(BaseModel):
    n: int
    name: str
    question: str
    settings: list[Knob]
    checks: list[Check]
    data_scope: str
    notes: list[str]
    source_file: str
    source_code: str


class EvalSchema(BaseModel):
    evals: list[EvalDefinition]
    readonly: Literal[True] = True
    constants: dict[str, float | list[float]]
    notes: list[str]


class EvalProfile(BaseModel):
    name: Literal["default"] = "default"
    editable: Literal[False] = False
    values: dict[str, float]
    stale: Literal[False] = False


def _constants():
    return {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in vars(config).items()
        if key.isupper() and isinstance(value, (int, float, tuple))
    }


def _knob(key, label, meaning, *, metric=None, op=">=", fixed=None, relative_to=None):
    value = getattr(config, key) if fixed is None else fixed
    lower_bound = op in (">=", ">")
    data = {
        "key": key,
        "label": label,
        "default": value,
        "min": value,
        "max": value,
        "tooltip": {
            "what_it_is": meaning,
            "if_raised": "Would make the check stricter."
            if lower_bound
            else "Would allow a larger value before failure.",
            "if_lowered": "Would make the check easier."
            if lower_bound
            else "Would tighten the allowed value.",
        },
    }
    if metric is not None:
        return Check(**data, metric=metric, op=op, relative_to=relative_to)
    data["tooltip"]["if_raised"] = "Would change the experiment and require a fresh run."
    data["tooltip"]["if_lowered"] = "Would change the experiment and require a fresh run."
    return Knob(**data)


def schema():
    cost = _knob(
        "BASE_COST_BPS", "Trading cost, round trip", "Basis points charged per round trip."
    )
    definitions = [
        {
            "name": "Lookahead",
            "module": "lookahead",
            "data_scope": "IS",
            "question": "Does the strategy use only information available at the time?",
            "settings": [],
            "checks": [
                _knob(
                    "LOOKAHEAD_TOLERANCE",
                    "Maximum weight difference",
                    "Allowed difference when future bars are removed.",
                    metric="max_abs_weight_difference",
                    op="<=",
                )
            ],
            "notes": [
                "Cut points: "
                + ", ".join(f"{v:.0%}" for v in config.LOOKAHEAD_CUT_FRACTIONS)
                + " of in-sample timestamps."
            ],
        },
        {
            "name": "Friction",
            "module": "friction",
            "data_scope": "IS",
            "question": "Does it still perform after trading costs?",
            "settings": [cost],
            "checks": [
                _knob(
                    "FRICTION_MIN_SHARPE",
                    "Minimum net Sharpe",
                    "Annualized net Sharpe required at the base trading cost.",
                    metric="net_sharpe_at_base_cost",
                )
            ],
            "notes": [
                "Cost grid: "
                + ", ".join(f"{v:g}" for v in config.FRICTION_BPS_GRID)
                + " bps round trip.",
                "Break-even bps is where Sharpe crosses the required threshold, not zero PnL.",
            ],
        },
        {
            "name": "Sensitivity",
            "module": "sensitivity",
            "data_scope": "IS",
            "question": "Does the result survive small parameter changes?",
            "settings": [
                cost,
                _knob(
                    "SENSITIVITY_MAX_PARAMS",
                    "Maximum parameters tested",
                    "First numeric parameters, in their recorded order.",
                ),
            ],
            "checks": [
                _knob(
                    "SENSITIVITY_MIN_RATIO",
                    "Minimum robustness ratio",
                    "Worst perturbed Sharpe divided by the base Sharpe.",
                    metric="worst_ratio",
                ),
                _knob(
                    "BASE_SHARPE_POSITIVE",
                    "Positive base Sharpe",
                    "An undefined or nonpositive baseline cannot pass.",
                    metric="base_sharpe",
                    op=">",
                    fixed=0,
                ),
            ],
            "notes": [
                "Parameter changes: "
                + ", ".join(f"{v:+.0%}" for v in config.SENSITIVITY_JITTERS)
                + ". Integer changes round away from zero and move at least one.",
                "With no distinct perturbations, a positive baseline is required.",
            ],
        },
        {
            "name": "Decay",
            "module": "decay",
            "data_scope": "IS and OOS",
            "question": "Does it survive later data without depending on one brief profit spike?",
            "settings": [
                cost,
                _knob(
                    "CONCENTRATION_WINDOW_DAYS",
                    "Profit concentration window",
                    "Number of trading days in each rolling concentration window.",
                ),
            ],
            "checks": [
                _knob(
                    "DECAY_MIN_RATIO",
                    "OOS Sharpe relative to IS",
                    "OOS Sharpe must be at least this factor times IS Sharpe.",
                    metric="oos_sharpe",
                    relative_to="is_sharpe",
                ),
                _knob(
                    "OOS_SHARPE_POSITIVE",
                    "Positive OOS Sharpe",
                    "Later Sharpe must be strictly above zero.",
                    metric="oos_sharpe",
                    op=">",
                    fixed=0,
                ),
                *[
                    _knob(
                        "CONCENTRATION_MAX_SHARE",
                        f"Maximum {part} window share",
                        "Largest rolling-window share of total PnL.",
                        metric=f"{part.lower()}_max_window_share",
                        op="<=",
                    )
                    for part in ("IS", "OOS")
                ],
            ],
            "notes": [
                "Both Sharpes must be defined; OOS Sharpe is compared with factor × IS Sharpe.",
                "Undefined or nonpositive total PnL cannot pass the concentration check.",
            ],
        },
        {
            "name": "Deflated Sharpe",
            "module": "deflated",
            "data_scope": "OOS",
            "question": "Is the result still credible after accounting for multiple attempts?",
            "settings": [
                cost,
                _knob(
                    "DSR_MIN_TRIALS",
                    "Minimum trial count",
                    "Floor on the number of sibling trials used in the adjustment.",
                ),
            ],
            "checks": [
                _knob(
                    "DSR_MIN",
                    "Minimum deflated Sharpe probability",
                    "Probability after accounting for trials and return distribution.",
                    metric="dsr",
                )
            ],
            "notes": [
                "Counts eligible siblings that reached Eval 2; voided runs do not count.",
                "Missing sibling evidence or undefined trial variance fails closed.",
                "Related variants are correlated; this is not proof of independent trials.",
            ],
        },
    ]
    evals = []
    for number, definition in enumerate(definitions, 1):
        module = definition.pop("module")
        filename = f"factory/evals/{module}.py"
        evals.append(
            EvalDefinition(
                n=number,
                **definition,
                source_file=filename,
                source_code=(Path(config.__file__).parent / f"{module}.py").read_text(),
            )
        )
    return EvalSchema(
        evals=evals,
        constants=_constants(),
        notes=[
            "Read-only view of the existing harness. No thresholds or verdicts are changed here.",
            "Fixed zero guards come from the displayed implementation and cannot be configured.",
        ],
    )


@router.get("/schema", response_model=EvalSchema)
def get_schema():
    return schema()


@router.get("/profiles/{name}", response_model=EvalProfile)
def get_profile(name: str):
    if name != "default":
        raise HTTPException(404, "Profile not found")
    return EvalProfile(
        values={
            key: value for key, value in _constants().items() if isinstance(value, (int, float))
        }
    )


@router.put("/profiles/{name}")
def unavailable_profile(name: str):
    raise HTTPException(501, "not available yet")
