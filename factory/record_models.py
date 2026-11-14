"""Versioned, strict storage models. These describe evidence, never judge strategies.

Absent optional evidence remains absent on serialization; explicit null stays null.
``legacy_extensions`` is reserved for reported forward migration, not new writers.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from factory.contract import StrategySpec

SCHEMA_VERSION = "1.0.0"
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Count = Annotated[StrictInt, Field(ge=0)]
Identifier = Annotated[StrictStr, Field(min_length=1)]


def _utc(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("Timestamp must include UTC offset")
    return value


def _date(value: str) -> str:
    from datetime import date

    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("Date must be YYYY-MM-DD")
    return value


UTCString = Annotated[StrictStr, AfterValidator(_utc)]
DateString = Annotated[StrictStr, AfterValidator(_date)]


def _year_or_date(value: str) -> str:
    if len(value) == 4 and value.isdecimal() and 1 <= int(value) <= 9999:
        return value
    return _date(value)


YearOrDate = Annotated[StrictStr, AfterValidator(_year_or_date)]


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED_DATA = "BLOCKED_DATA"
    VOID = "VOID"


class VariantStatus(StrEnum):
    RUNNING = "RUNNING"
    VERIFIED = "VERIFIED"
    FAILED_EVAL_1 = "FAILED_EVAL_1"
    FAILED_EVAL_2 = "FAILED_EVAL_2"
    FAILED_EVAL_3 = "FAILED_EVAL_3"
    FAILED_EVAL_4 = "FAILED_EVAL_4"
    FAILED_EVAL_5 = "FAILED_EVAL_5"
    BUG_UNRESOLVED = "BUG_UNRESOLVED"
    BLOCKED_DATA = "BLOCKED_DATA"
    INACTIVE = "INACTIVE"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    VOID = "VOID"


class NeedStatus(StrEnum):
    ON_DISK = "on_disk"
    FETCHING = "fetching"
    FETCHED = "fetched"
    NEEDS_PROVIDER = "needs_provider"
    NEEDS_UPLOAD = "needs_upload"
    CANDIDATES = "candidates"
    UNAVAILABLE = "unavailable"


class EventStatus(StrEnum):
    STARTED = "started"
    PASSED = "passed"
    FAILED = "failed"
    INFO = "info"


class Stage(StrEnum):
    INTAKE = "intake"
    EXTRACT = "extract"
    DATA = "data"
    WORKER = "worker"
    HEAL = "heal"
    EVAL = "eval"
    CRITIC = "critic"
    DONE = "done"


class Lane(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class SourceKind(StrEnum):
    PAPER = "paper"
    DESCRIBED = "described"


class TestType(StrEnum):
    REPLICATION = "replication"
    TRANSFER = "transfer"
    ORIGINAL = "original"


class Frequency(StrEnum):
    MINUTE = "1min"
    DAY = "1day"


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_assignment=True)
    legacy_extensions: dict[str, JsonValue] = Field(
        default_factory=dict,
        description="Unrecognized legacy fields retained by audited migration only.",
    )


class TimestampOrigin(Evidence):
    method: Literal["write_clock", "event_timestamp", "unknown"] = Field(
        description="Whether creation is observed, taken from this event, or unknown."
    )
    event_seq: StrictInt | None = Field(
        default=None, description="Evidence event sequence, if used."
    )


class Record(Evidence):
    schema_version: Literal["1.0.0"] = Field(description="Version of this persisted record schema.")
    id: Identifier = Field(description="Stable SQLite primary key for this record.")
    run_id: Identifier = Field(
        description="Run owning this record or last writing a shared source."
    )
    source_id: Identifier | None = Field(default=None, description="Source identity when known.")
    created_at: UTCString | None = Field(
        description="Creation or earliest observed UTC time; null if unknown."
    )
    created_at_provenance: TimestampOrigin = Field(description="Origin of the recorded timestamp.")
    voided: StrictBool = Field(
        default=False, description="Whether this record is excluded with a void run."
    )


class MarkdownExtraction(Evidence):
    method: StrictStr = Field(description="Method used to extract text.")
    pages: Count = Field(description="Number of pages extracted.")
    summarized: StrictBool = Field(description="Whether text was summarized.")


class SourceVerification(Evidence):
    method: StrictStr | None = Field(default=None, description="Verification method.")
    notes: StrictStr | None = Field(
        default=None, description="Verification evidence or limitations."
    )
    page_one_match_verified: StrictBool | None = Field(
        default=None, description="Whether first-page identity matched."
    )
    physical_page_verified: Count | None = Field(
        default=None, description="Physical PDF page checked."
    )
    title_authors_match_candidate: StrictBool | None = Field(
        default=None, description="Whether title and authors matched."
    )


class Provenance(Evidence):
    title: StrictStr | None = Field(default=None, description="Source title from provenance.")
    authors: list[StrictStr] | None = Field(default=None, description="Source authors.")
    url: StrictStr | None = Field(default=None, description="Owner-approved source URL.")
    downloaded_at: UTCString | None = Field(default=None, description="Legacy download timestamp.")
    downloaded_at_utc: UTCString | None = Field(default=None, description="UTC download timestamp.")
    first_version_date: YearOrDate | None = Field(default=None, description="First version date.")
    version: StrictStr | None = Field(default=None, description="Source version label.")
    version_date: YearOrDate | None = Field(default=None, description="Source version date.")
    markdown_extraction: MarkdownExtraction | None = Field(
        default=None, description="Text extraction provenance."
    )
    markdown_file: StrictStr | None = Field(
        default=None, description="Relative extracted text filename."
    )
    markdown_sha256: StrictStr | None = Field(
        default=None, description="Fingerprint of extracted text."
    )
    pdf_file: StrictStr | None = Field(default=None, description="Relative supplied PDF filename.")
    sha256: StrictStr | None = Field(default=None, description="Fingerprint of supplied PDF.")
    verification: SourceVerification | None = Field(
        default=None, description="Source identity verification evidence."
    )
    verification_note: StrictStr | None = Field(
        default=None, description="Legacy verification note."
    )
    verified_title_authors_page: Count | None = Field(
        default=None, description="Page checked for title and authors."
    )


class Source(Record):
    source_id: Identifier = Field(description="Source identity; matches id and spec.paper_id.")
    title: Identifier = Field(description="Source title.")
    source_kind: SourceKind = Field(description="Paper or English description.")
    spec: StrategySpec = Field(
        description="Source specification snapshot; never silently replaced in old runs."
    )
    provenance: Provenance = Field(
        default_factory=Provenance, description="Source origin and verification evidence."
    )

    @field_validator("spec", mode="before")
    @classmethod
    def strict_spec(cls, value):
        if isinstance(value, StrategySpec):
            value = value.model_dump(exclude_unset=True)
        return StrategySpec.model_validate(value, strict=True)

    @model_validator(mode="after")
    def identity(self):
        if self.id != self.source_id or self.spec.paper_id != self.source_id:
            raise ValueError("Source identity mismatch")
        return self


class Usage(Evidence):
    model: Identifier = Field(description="Provider/model identifier returned by the wrapper.")
    input_tokens: Count = Field(description="Input token count.")
    output_tokens: Count = Field(description="Output token count.")
    wall_seconds: Annotated[Number, Field(ge=0)] = Field(
        description="Request wall time in seconds."
    )
    cost_usd: Annotated[Number, Field(ge=0)] | None = Field(
        description="Estimated request cost; null if unavailable."
    )
    cached_input_tokens: Count = Field(default=0, description="Input tokens served from cache.")
    cache_write_input_tokens: Count = Field(
        default=0, description="Input tokens written to short cache."
    )
    cache_write_long_input_tokens: Count = Field(
        default=0, description="Input tokens written to long cache."
    )


class Cut(Evidence):
    bars: Count = Field(description="Number of bars retained at the lookahead cut.")
    fraction: Number = Field(description="Fraction of IS bars at the cut.")
    last_timestamp: UTCString = Field(description="Last bar timestamp retained.")


class Jitter(Evidence):
    param: Identifier = Field(description="Parameter changed for this sensitivity experiment.")
    fraction: Number = Field(description="Relative parameter perturbation.")
    value: StrictInt | Number = Field(description="Perturbed numeric parameter value.")
    sharpe: Number | None = Field(description="Sharpe under perturbation, null when undefined.")
    error: StrictStr | None = Field(
        default=None, description="Contract or runtime failure under perturbation."
    )


class EvalMetrics(Evidence):
    """Sparse typed telemetry: undefined or uncomputed metrics are not invented."""

    cuts: list[Cut] | None = Field(
        default=None, description="Lookahead cut points actually checked."
    )
    tolerance: Number | None = Field(default=None, description="Lookahead numerical tolerance.")
    sharpe_by_bps: dict[str, Number | None] | None = Field(
        default=None, description="Annualized Sharpe at each trading cost."
    )
    min_sharpe: Number | None = Field(
        default=None, description="Recorded minimum net Sharpe threshold."
    )
    pass_bps: Number | None = Field(
        default=None, description="Trading cost used for the friction verdict."
    )
    break_even_bps: Number | None = Field(
        default=None, description="Interpolated cost at the friction threshold."
    )
    break_even_note: StrictStr | None = Field(
        default=None, description="Why break-even cost is missing or how it was found."
    )
    annualized_return: Number | None = Field(
        default=None, description="Annualized return from the evaluated path."
    )
    max_drawdown: Number | None = Field(
        default=None, description="Maximum drawdown from the evaluated path."
    )
    average_daily_turnover: Number | None = Field(
        default=None, description="Mean daily traded exposure."
    )
    trading_days: Count | None = Field(
        default=None, description="Days in the evaluated return series."
    )
    base_sharpe: Number | None = Field(
        default=None, description="Unperturbed annualized net Sharpe."
    )
    worst_sharpe: Number | None = Field(
        default=None, description="Worst Sharpe across parameter perturbations."
    )
    worst_ratio: Number | None = Field(
        default=None, description="Worst perturbed Sharpe divided by base Sharpe."
    )
    min_ratio: Number | None = Field(
        default=None, description="Recorded robustness or decay threshold."
    )
    cost_bps: Number | None = Field(
        default=None, description="Recorded round-trip trading cost in basis points."
    )
    jitters: list[Jitter] | None = Field(
        default=None, description="Parameter sensitivity observations."
    )
    numeric_params_not_jittered: list[StrictStr] | None = Field(
        default=None, description="Numeric parameters outside the jitter limit."
    )
    is_sharpe: Number | None = Field(default=None, description="Annualized in-sample net Sharpe.")
    oos_sharpe: Number | None = Field(
        default=None, description="Annualized out-of-sample net Sharpe."
    )
    oos_to_is_ratio: Number | None = Field(
        default=None, description="Out-of-sample Sharpe divided by in-sample Sharpe."
    )
    sharpe_ok: StrictBool | None = Field(
        default=None, description="Recorded deterministic decay Sharpe check."
    )
    is_max_window_share: Number | None = Field(
        default=None, description="Largest IS window share of PnL."
    )
    is_total_pnl: Number | None = Field(
        default=None,
        description="Sum of IS daily net returns used by concentration; not compounded.",
    )
    oos_total_pnl: Number | None = Field(
        default=None,
        description="Sum of OOS daily net returns used by concentration; not compounded.",
    )
    oos_max_window_share: Number | None = Field(
        default=None, description="Largest OOS window share of PnL."
    )
    window_days: Count | None = Field(
        default=None, description="Recorded concentration window length."
    )
    max_share: Number | None = Field(
        default=None, description="Recorded maximum concentration threshold."
    )
    concentration_ok: StrictBool | None = Field(
        default=None, description="Recorded deterministic concentration check."
    )
    is_days: Count | None = Field(default=None, description="Number of IS return observations.")
    oos_days: Count | None = Field(default=None, description="Number of OOS return observations.")
    n_trials: Count | None = Field(default=None, description="Trial count used by deflated Sharpe.")
    trial_sharpes_supplied: Count | None = Field(
        default=None, description="Number of finite Sharpes available from the selected population."
    )
    trial_count: Count | None = Field(
        default=None, description="Selected trial count before the unchanged configured N floor."
    )
    trial_variant_ids: list[Identifier] | None = Field(
        default=None, description="Exact distinct variant identities used by this global judgment."
    )
    trial_scope: Literal["all_runs", "supplied"] | None = Field(
        default=None,
        description="Whether the population is all retained eligible runs or supplied.",
    )
    judgment_revision: StrictStr | None = Field(
        default=None,
        description="Owner-sanctioned deterministic rule revision used for this judgment.",
    )
    min: Number | None = Field(
        default=None, description="Recorded minimum deflated Sharpe threshold."
    )
    daily_sharpe: Number | None = Field(
        default=None, description="Nonannualized daily Sharpe used by DSR."
    )
    observations: Count | None = Field(default=None, description="Return observations used by DSR.")
    trial_variance: Number | None = Field(
        default=None, description="Sample variance of the selected population's daily OOS Sharpes."
    )
    sr0: Number | None = Field(default=None, description="Expected maximum null Sharpe benchmark.")
    skew: Number | None = Field(default=None, description="Population skewness of returns.")
    kurtosis: Number | None = Field(
        default=None, description="Population non-excess kurtosis of returns."
    )
    dsr: Annotated[Number, Field(ge=0, le=1)] | None = Field(
        default=None, description="Deflated Sharpe probability."
    )
    reason: StrictStr | None = Field(
        default=None, description="Explanation when an eval metric is unavailable."
    )


class EvalEvidence(Evidence):
    number: Annotated[StrictInt, Field(ge=1, le=5)] = Field(
        description="Eval number from one through five."
    )
    name: Identifier = Field(description="Eval name supplied by the deterministic harness.")
    passed: StrictBool = Field(description="Verdict supplied only by the deterministic harness.")
    metrics: EvalMetrics = Field(description="Typed numerical evidence from the harness.")


class EvalResult(Record, EvalEvidence):
    variant: Lane = Field(description="Candidate lane owning this eval result.")


class HealAttempt(Record):
    variant: Lane = Field(description="Candidate lane being repaired.")
    attempt: Annotated[StrictInt, Field(ge=1, le=3)] = Field(
        description="Bounded repair attempt number."
    )
    error: Identifier = Field(description="Exact redacted bug that caused the repair.")
    fixed: StrictBool = Field(description="Whether IS bug validation passed after this attempt.")
    result_error: StrictStr | None = Field(
        default=None, description="Remaining bug or provider failure."
    )


class Critique(Record):
    variant: Lane = Field(description="Candidate lane discussed by the narrative.")
    text: StrictStr = Field(description="Narrative only; cannot influence any eval verdict.")


class Candidate(Evidence):
    id: Identifier = Field(description="Proposed source identity.")
    title: Identifier = Field(description="Proposed source title.")
    url: Identifier = Field(
        description="Proposed source location; approval required before download."
    )
    licence: StrictStr | None = Field(description="Stated licence, if known.")
    coverage: StrictStr = Field(description="Proposed data coverage.")
    availability_column: StrictStr = Field(
        description="Column representing when information became known."
    )


class DataNeed(Record):
    kind: Literal["price_bars", "events"] = Field(description="Required dataset kind.")
    name: Identifier = Field(description="Human-readable missing or resolved data need.")
    symbols: list[Identifier] = Field(description="Required symbols.")
    frequency: Frequency | None = Field(description="Required price frequency, null for events.")
    start: DateString | UTCString | None = Field(
        description="Required or observed beginning; null if unknown."
    )
    end: DateString | UTCString | None = Field(
        description="Required or observed end; null if unknown."
    )
    status: NeedStatus = Field(description="Current deterministic resolution state.")
    provider: StrictStr | None = Field(description="Responsible provider when known.")
    candidates: list[Candidate] = Field(description="Sources awaiting explicit owner approval.")


class Equity(Evidence):
    dates: list[DateString] = Field(
        description="Unique chronological exchange dates of chart observations."
    )
    gross: list[Number] = Field(description="Cumulative equity before transaction costs.")
    net: list[Number] = Field(description="Cumulative equity after transaction costs.")
    is_end: DateString = Field(description="Exchange date of final IS bar.")
    oos_end: DateString = Field(description="Exchange date of final OOS bar.")

    @model_validator(mode="after")
    def aligned(self):
        if not len(self.dates) == len(self.gross) == len(self.net):
            raise ValueError("Equity arrays must have equal lengths")
        if self.dates != sorted(set(self.dates)):
            raise ValueError("Equity dates must be unique and ordered")
        if self.is_end > self.oos_end:
            raise ValueError("IS boundary must precede OOS boundary")
        return self


class EquityBoundaries(Evidence):
    is_end: UTCString = Field(description="Exact UTC timestamp of final IS bar.")
    oos_end: UTCString = Field(description="Exact UTC timestamp of final OOS bar.")


class Activity(Evidence):
    active_bars: Count = Field(
        description="Bars with nonzero target or executed weights, as recorded."
    )
    total_bars: Count = Field(description="Bars in this evaluated slice.")
    days_traded: Count = Field(description="Exchange days with nonzero target weights.")
    target_active_bars: Count | None = Field(
        default=None, description="Bars with nonzero targets if separately recorded."
    )

    @model_validator(mode="after")
    def counts_fit(self):
        if any(
            v > self.total_bars
            for v in (self.active_bars, self.days_traded, self.target_active_bars or 0)
        ):
            raise ValueError("Activity counts exceed total bars")
        return self


class OriginalResult(Evidence):
    status: RunStatus | VariantStatus = Field(description="Preserved verdict before invalidation.")
    default_status: VariantStatus | None = Field(
        default=None, description="Preserved default verdict."
    )
    evals_passed: Annotated[StrictInt, Field(ge=0, le=5)] | None = Field(
        default=None, description="Preserved count of passed evals."
    )
    default_evals_passed: Annotated[StrictInt, Field(ge=0, le=5)] | None = Field(
        default=None, description="Preserved default count of passed evals."
    )
    verified_sharpe: Number | None = Field(default=None, description="Preserved OOS net Sharpe.")
    break_even_bps: Number | None = Field(
        default=None, description="Preserved break-even trading cost."
    )


class Voidable(Record):
    is_control: StrictBool = Field(
        default=False,
        description="Explicit control experiment, excluded from research trial counts.",
    )
    original_result: OriginalResult | None = Field(
        default=None, description="Unchanged original verdict evidence when voided."
    )
    leaderboard_eligible: StrictBool = Field(
        default=True, description="Whether this record may enter comparisons."
    )
    eval_eligible: StrictBool = Field(
        default=True, description="Whether this record may enter trial accounting."
    )
    void_reason: StrictStr | None = Field(
        default=None, description="Why the owner invalidated this evidence."
    )
    voided_at: UTCString | None = Field(default=None, description="Actual UTC invalidation time.")

    @model_validator(mode="after")
    def void_consistent(self):
        if self.voided and getattr(self, "status", None) != "VOID":
            raise ValueError("Voided run or variant must have VOID status")
        if getattr(self, "status", None) == "VOID":
            if not self.voided or self.leaderboard_eligible or self.eval_eligible:
                raise ValueError("VOID record must be voided and ineligible")
            if not self.void_reason or not self.voided_at or self.original_result is None:
                raise ValueError("VOID requires reason, timestamp, and original result")
        return self


class Variant(Voidable):
    cost_sharpes: dict[Literal["IS", "OOS"], dict[str, Number | None]] | None = Field(
        default=None, description="Annualized Sharpes by round-trip bps from the captured targets."
    )
    verification_eligible: StrictBool = Field(
        default=True, description="Whether the frozen sample gate allows a VERIFIED verdict."
    )
    eligibility_reason: StrictStr | None = Field(
        default=None, description="Predeclared reason a sample cannot establish verification."
    )
    reached_eval_2: StrictBool = Field(
        default=False, description="Durable evidence that this candidate entered Eval 2."
    )
    judgment_revision: StrictStr | None = Field(
        default=None, description="Most recent owner-sanctioned recorded-metric judgment revision."
    )
    variant_id: Identifier = Field(description="Stable candidate identity; matches id.")
    source_id: Identifier = Field(description="Source of this candidate experiment.")
    source_title: Identifier = Field(description="Source title at experiment time.")
    source_kind: SourceKind = Field(description="Paper or English description.")
    variant: Lane = Field(description="Candidate generation lane.")
    test_type: TestType = Field(description="Replication, transfer, or original experiment.")
    frequency: Frequency = Field(description="Bar frequency used by this candidate.")
    claimed_sharpe: Number | None = Field(
        default=None, description="Claimed source Sharpe, if stated."
    )
    verified_sharpe: Number | None = Field(
        default=None, description="Observed OOS net Sharpe; does not imply VERIFIED."
    )
    break_even_bps: Number | None = Field(
        default=None, description="Trading cost at the friction threshold, if defined."
    )
    evals_passed: Annotated[StrictInt, Field(ge=0, le=5)] = Field(
        description="Count of passed deterministic evals."
    )
    status: VariantStatus = Field(
        description="Candidate verdict from the harness or operational failure."
    )
    profile: Identifier = Field(
        default="default", description="Eval profile that judged this record."
    )
    default_status: VariantStatus = Field(description="Unmodified default-profile verdict.")
    default_evals_passed: Annotated[StrictInt, Field(ge=0, le=5)] = Field(
        description="Passed eval count under defaults."
    )
    code: StrictStr | None = Field(
        default=None, description="Generated strategy code if generation completed."
    )
    params: dict[str, JsonValue] | None = Field(
        default=None, description="Strategy-defined tunable parameter names and values."
    )
    evals: list[EvalEvidence] = Field(
        default_factory=list, description="Recorded deterministic evals, without recomputation."
    )
    equity: Equity | None = Field(
        default=None, description="Recorded chart artifact, absent if not produced."
    )
    equity_boundaries: EquityBoundaries | None = Field(
        default=None, description="Exact timestamp boundaries for chart slices."
    )
    activity: dict[Literal["IS", "OOS"], Activity] | None = Field(
        default=None, description="Observed activity in evaluated slices."
    )
    days_traded: Count | None = Field(
        default=None, description="IS exchange dates with nonzero targets."
    )
    critique: StrictStr | None = Field(
        default=None, description="Narrative postmortem; never a verdict."
    )
    notes: list[StrictStr] = Field(
        default_factory=list, description="Always-visible caveats and operational notes."
    )

    @model_validator(mode="after")
    def identity(self):
        if self.id != self.variant_id or self.variant_id != f"{self.run_id}_{self.variant}":
            raise ValueError("Variant identity mismatch")
        numbers = [e.number for e in self.evals]
        if len(numbers) != len(set(numbers)):
            raise ValueError("Duplicate eval number")
        if self.status != "VOID" and self.evals_passed != sum(e.passed for e in self.evals):
            raise ValueError("Passed eval count differs from recorded evidence")
        if self.status == "VERIFIED" and (
            set(numbers) != set(range(1, 6))
            or self.evals_passed != 5
            or not self.verification_eligible
        ):
            raise ValueError("VERIFIED requires five recorded passing evals")
        if not self.verification_eligible and not self.eligibility_reason:
            raise ValueError("Ineligible verification requires a reason")
        if self.status == "INSUFFICIENT_SAMPLE" and (
            self.verification_eligible or self.evals_passed != 5
        ):
            raise ValueError("INSUFFICIENT_SAMPLE requires five passes and failed eligibility")
        if self.original_result and self.original_result.status not in set(VariantStatus):
            raise ValueError("Original variant status is not a variant verdict")
        return self


class Diagnostic(Evidence):
    loc: list[StrictStr | StrictInt] = Field(description="Sanitized schema field location.")
    type: StrictStr = Field(description="Validation error category.")
    msg: StrictStr = Field(description="Safe diagnostic text with no rejected input.")


class Submission(Evidence):
    origin: Literal["api"] = Field(description="Submission owner for restart recovery.")
    upload_name: Identifier = Field(
        description="User-supplied display filename, never a disk path."
    )
    upload_sha256: Annotated[StrictStr, Field(pattern=r"^[a-f0-9]{64}$")] = Field(
        description="Fingerprint of the supplied PDF bytes."
    )
    input_path: Identifier = Field(description="Project-relative registered upload location.")
    accepted_at: UTCString = Field(description="Actual UTC instant when the API accepted this PDF.")

    @model_validator(mode="after")
    def relative_upload(self):
        path = PurePosixPath(self.input_path)
        if path.is_absolute() or ".." in path.parts or "\\" in self.input_path:
            raise ValueError("Upload location must be a safe relative path")
        if path.parts[:2] != ("runs", "uploads") or path.suffix.lower() != ".pdf":
            raise ValueError("Upload location must be a registered PDF")
        if PurePosixPath(self.upload_name).name != self.upload_name or "\\" in self.upload_name:
            raise ValueError("Display filename must not contain a path")
        return self


class Run(Voidable):
    submission: Submission | None = Field(
        default=None,
        description="API intake ownership and provenance; absent for historical CLI runs.",
    )
    status: RunStatus = Field(
        description="Pipeline lifecycle state; COMPLETED does not mean strategy success."
    )
    source: Source | None = Field(
        default=None, description="Historic source snapshot for this run."
    )
    variants: list[Variant] = Field(
        default_factory=list, description="Candidate snapshots saved with this run."
    )
    data_needs: list[DataNeed] = Field(
        default_factory=list, description="Data resolution evidence for this run."
    )
    wall_seconds: Annotated[Number, Field(ge=0)] | None = Field(
        default=None, description="Measured run wall time; null if unrecorded."
    )
    usage: list[Usage] = Field(
        default_factory=list, description="Recorded model request accounting."
    )
    cost_complete: StrictBool | None = Field(
        default=None, description="Whether all model costs are known."
    )
    estimated_model_cost_usd: Annotated[Number, Field(ge=0)] | None = Field(
        default=None, description="Summed known model cost only when complete."
    )
    error_type: StrictStr | None = Field(default=None, description="Operational exception class.")
    error: StrictStr | None = Field(
        default=None, description="Redacted safe operational error description."
    )
    extraction_diagnostics: list[Diagnostic] = Field(
        default_factory=list, description="Sanitized extractor validation failures."
    )

    @model_validator(mode="after")
    def identity(self):
        if self.id != self.run_id:
            raise ValueError("Run identity mismatch")
        if len({v.variant for v in self.variants}) != len(self.variants):
            raise ValueError("Duplicate variant lane")
        if self.original_result and self.original_result.status not in set(RunStatus):
            raise ValueError("Original run status is not a run lifecycle state")
        if any(item.run_id != self.run_id for item in [*self.variants, *self.data_needs]):
            raise ValueError("Nested run identity mismatch")
        return self


class EventData(EvalMetrics):
    eval: Annotated[StrictInt, Field(ge=1, le=5)] | None = Field(
        default=None, description="Eval concerned by the state change."
    )
    attempt: Annotated[StrictInt, Field(ge=1, le=3)] | None = Field(
        default=None, description="Bug repair attempt concerned."
    )
    error: StrictStr | None = Field(
        default=None, description="Redacted exact bug or operational error."
    )
    status: RunStatus | VariantStatus | NeedStatus | None = Field(
        default=None, description="Domain state accompanying the event."
    )
    wall_seconds: Number | None = Field(default=None, description="Measured run wall time.")
    estimated_model_cost_usd: Number | None = Field(
        default=None, description="Known complete estimated model cost."
    )
    active_bars: Count | None = Field(default=None, description="Observed active IS bars.")
    total_bars: Count | None = Field(default=None, description="Observed IS bar count.")
    days_traded: Count | None = Field(
        default=None, description="IS exchange dates with nonzero targets."
    )


class Event(Record):
    seq: Annotated[StrictInt, Field(ge=1)] = Field(
        description="Global monotonically increasing SQLite event sequence."
    )
    ts: UTCString = Field(description="UTC instant when this state change was recorded.")
    stage: Stage = Field(description="Pipeline stage emitting this event.")
    variant: Lane | None = Field(description="Candidate lane, null for run-wide state changes.")
    status: EventStatus = Field(description="State change outcome.")
    message: StrictStr = Field(description="Redacted human-readable state change.")
    data: EventData = Field(description="Typed sparse telemetry accompanying the state change.")


RECORD_MODELS = {
    "sources": Source,
    "runs": Run,
    "variants": Variant,
    "eval_results": EvalResult,
    "heal_attempts": HealAttempt,
    "critiques": Critique,
    "data_needs": DataNeed,
    "events": Event,
}


def dump(model: Evidence) -> dict:
    """Do not turn missing legacy evidence into explicit null or empty values."""
    return model.model_dump(mode="json", exclude_unset=True)
