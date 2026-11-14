"""Validated HTTP projections; persisted records remain the evidence source."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from factory.api.artifacts import Artifact
from factory.record_models import (
    Activity,
    Candidate,
    Diagnostic,
    Equity,
    EquityBoundaries,
    EvalMetrics,
    Event,
    Frequency,
    Lane,
    NeedStatus,
    Number,
    OriginalResult,
    RunStatus,
    Source,
    SourceKind,
    Submission,
    TestType,
    Usage,
    VariantStatus,
)


class Response(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Health(Response):
    status: Literal["ok"] = "ok"
    schema_version: str
    capabilities: dict[str, bool]


class RecordSchemas(Response):
    schema_version: str
    models: dict[str, dict[str, JsonValue]]


class Step(Response):
    id: str
    kind: Literal["extract", "data", "code", "heal", "eval", "critic"]
    label: str
    state: Literal["pending", "running", "pass", "failed", "recorded", "fixed", "not_run"]
    number: int | None = None
    attempts: int = 0
    max_attempts: int | None = None
    details: list[str] = Field(default_factory=list)
    logs: list[Event] = Field(default_factory=list)


class LeaderboardRow(Response):
    variant_id: str
    run_id: str
    source_id: str
    source_title: str
    source_kind: SourceKind
    variant: Lane
    test_type: TestType
    frequency: Frequency
    claimed_sharpe: Number | None
    verified_sharpe: Number | None
    break_even_bps: Number | None
    evals_passed: int = Field(ge=0, le=5)
    status: VariantStatus
    profile: str
    default_status: VariantStatus
    default_evals_passed: int = Field(ge=0, le=5)
    summary: str
    days_traded: int | None
    notes: list[str]
    voided: bool
    void_reason: str | None
    created_at: str | None


class Leaderboard(Response):
    rows: list[LeaderboardRow]


class VariantRun(LeaderboardRow):
    steps: list[Step]


class DataNeed(Response):
    id: str
    kind: Literal["price_bars", "events"]
    name: str
    symbols: list[str]
    frequency: Frequency | None
    start: str | None
    end: str | None
    status: NeedStatus
    provider: str | None
    candidates: list[Candidate]


class RunSummary(Response):
    submission: Submission | None
    run_id: str
    status: RunStatus
    source: Source | None
    variants: list[LeaderboardRow]
    data_needs: list[DataNeed]
    created_at: str | None
    started_at: str | None
    wall_seconds: Number | None
    estimated_model_cost_usd: Number | None
    cost_complete: bool | None
    voided: bool
    void_reason: str | None
    error_type: str | None
    error: str | None


class RunList(Response):
    runs: list[RunSummary]


class RunDetail(RunSummary):
    variants: list[VariantRun]
    steps: list[Step]
    usage: list[Usage]
    extraction_diagnostics: list[Diagnostic]
    artifacts: list[Artifact]


class EvalView(Response):
    n: int = Field(ge=1, le=5)
    name: str
    passed: bool
    metrics: EvalMetrics


class HealView(Response):
    attempt: int = Field(ge=1, le=3)
    error: str
    fixed: bool
    result_error: str | None = None


class VariantDetail(LeaderboardRow):
    cost_sharpes: dict[Literal["IS", "OOS"], dict[str, Number | None]] | None = None
    verification_eligible: bool = True
    eligibility_reason: str | None = None
    code: str | None
    params: dict[str, JsonValue] | None
    evals: list[EvalView]
    equity: Equity | None
    heal_attempts: list[HealView]
    critique: str | None
    steps: list[Step]
    activity: dict[Literal["IS", "OOS"], Activity] | None
    equity_boundaries: EquityBoundaries | None
    source: Source | None
    artifacts: list[Artifact]
    original_result: OriginalResult | None


class SourceList(Response):
    sources: list[Source]


class SourceDetail(Response):
    source: Source
    artifacts: list[Artifact]


class EventHistory(Response):
    events: list[Event]
    next_seq: int


class GraveyardEntry(Response):
    variant_id: str
    run_id: str
    source_title: str
    variant: Lane
    status: VariantStatus
    test_type: TestType
    frequency: Frequency
    evals_passed: int = Field(ge=0, le=5)
    summary: str
    cause: str
    critique: str | None
    notes: list[str]
    voided: bool
    void_reason: str | None
    original_result: OriginalResult | None


class Graveyard(Response):
    markdown: str
    entries: list[GraveyardEntry]


class Provider(Response):
    name: str
    connected: bool
    covers: list[Literal["price_bars", "events"]]


class Providers(Response):
    providers: list[Provider]


class StartedRun(Response):
    run_id: str
