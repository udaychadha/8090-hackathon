"""Core records API, durable PDF submission, and asynchronous SSE replay."""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from starlette.datastructures import UploadFile

from factory.api import schemas, views
from factory.api.artifacts import ArtifactList, ArtifactRegistry
from factory.api.common import get_records, root_from, sanitize
from factory.record_models import (
    RECORD_MODELS,
    SCHEMA_VERSION,
    Frequency,
    RunStatus,
    TestType,
    VariantStatus,
)

router = APIRouter(prefix="/api", tags=["research"])


def response(model, value):
    canonical = model.model_validate(value).model_dump(mode="json", exclude_unset=True)
    return model.model_validate(sanitize(canonical))


def required(records, table, identifier, include_voided):
    value = records.get(table, identifier, include_voided=include_voided)
    if value is None:
        raise HTTPException(404, "Record not found")
    return value


@router.get("/health", response_model=schemas.Health)
def health():
    return schemas.Health(
        schema_version=SCHEMA_VERSION,
        capabilities={
            "paper_runs": True,
            "live_events": True,
            "record_history": True,
            "data_catalog": True,
            "data_preview": True,
            "artifacts": True,
            "eval_schema": True,
            "intake": False,
            "saved_spec_runs": False,
            "data_upload": True,
            "provider_keys": False,
            "source_approval": False,
            "custom_eval_profiles": False,
        },
    )


@router.get("/records/schema", response_model=schemas.RecordSchemas)
def record_schema():
    return {
        "schema_version": SCHEMA_VERSION,
        "models": {name: model.model_json_schema() for name, model in RECORD_MODELS.items()},
    }


@router.get("/runs", response_model=schemas.RunList, response_model_exclude_unset=True)
def list_runs(
    request: Request,
    source_id: str | None = None,
    status: RunStatus | None = None,
    include_voided: bool = False,
):
    with get_records(root_from(request)) as records:
        runs = records.list(
            "runs",
            source_id=source_id,
            status=status,
            sort_by="created_at",
            descending=True,
            include_voided=include_voided,
        )
        return response(
            schemas.RunList,
            {
                "runs": [
                    views.run_summary(run, records, include_voided=include_voided) for run in runs
                ]
            },
        )


@router.get("/sources", response_model=schemas.SourceList, response_model_exclude_unset=True)
def sources(request: Request, include_voided: bool = False):
    with get_records(root_from(request)) as records:
        return response(
            schemas.SourceList, {"sources": records.list("sources", include_voided=include_voided)}
        )


@router.get(
    "/sources/{source_id}", response_model=schemas.SourceDetail, response_model_exclude_unset=True
)
def source_detail(request: Request, source_id: str, include_voided: bool = False):
    root = root_from(request)
    with get_records(root) as records:
        source = required(records, "sources", source_id, include_voided)
    return response(
        schemas.SourceDetail,
        {
            "source": source,
            "artifacts": ArtifactRegistry(root).list(
                source_id=source_id, include_voided=include_voided
            ),
        },
    )


@router.get("/runs/{run_id}", response_model=schemas.RunDetail, response_model_exclude_unset=True)
def run_detail(request: Request, run_id: str, include_voided: bool = False):
    root = root_from(request)
    with get_records(root) as records:
        run = required(records, "runs", run_id, include_voided)
        events = records.events(run_id, include_voided=include_voided)
        detail = views.run_summary(run, records, include_voided=include_voided, events=events)
        detail["variants"] = []
        for row in records.list("variants", run_id=run_id, include_voided=include_voided):
            *_, steps = views.lane_evidence(
                row, run, records, include_voided=include_voided, events=events
            )
            detail["variants"].append(
                {**views.leaderboard_row(row, run=run, events=events), "steps": steps}
            )
        detail.update(
            steps=views.run_steps(run, events),
            usage=run.get("usage", []),
            extraction_diagnostics=run.get("extraction_diagnostics", []),
        )
    detail["artifacts"] = ArtifactRegistry(root).list(run_id=run_id, include_voided=include_voided)
    return response(schemas.RunDetail, detail)


@router.get("/runs/{run_id}/artifacts", response_model=ArtifactList)
def run_artifacts(request: Request, run_id: str, include_voided: bool = False):
    root = root_from(request)
    with get_records(root) as records:
        required(records, "runs", run_id, include_voided)
    return response(
        ArtifactList,
        {"artifacts": ArtifactRegistry(root).list(run_id=run_id, include_voided=include_voided)},
    )


Sort = Literal[
    "source_title",
    "status",
    "variant",
    "created_at",
    "evals_passed",
    "verified_sharpe",
    "claimed_sharpe",
    "break_even_bps",
]


@router.get("/leaderboard", response_model=schemas.Leaderboard, response_model_exclude_unset=True)
def leaderboard(
    request: Request,
    source_id: str | None = None,
    status: VariantStatus | None = None,
    test_type: TestType | None = None,
    frequency: Frequency | None = None,
    sort_by: Sort = "evals_passed",
    direction: Literal["asc", "desc"] = "desc",
    include_voided: bool = False,
):
    indexed = sort_by in {"status", "variant", "created_at"}
    with get_records(root_from(request)) as records:
        rows = records.list(
            "variants",
            source_id=source_id,
            status=status,
            sort_by=sort_by if indexed else None,
            descending=direction == "desc",
            include_voided=include_voided,
        )
        rows = [
            row
            for row in rows
            if (include_voided or row.get("leaderboard_eligible", True))
            and (test_type is None or row["test_type"] == test_type)
            and (frequency is None or row["frequency"] == frequency)
        ]
        if not indexed:
            available = [r for r in rows if r.get(sort_by) is not None]
            missing = [r for r in rows if r.get(sort_by) is None]
            rows = (
                sorted(
                    available,
                    key=lambda r: (r[sort_by], r["variant_id"]),
                    reverse=direction == "desc",
                )
                + missing
            )
        return response(
            schemas.Leaderboard,
            {
                "rows": [
                    views.leaderboard_row(
                        row,
                        run=records.get("runs", row["run_id"], include_voided=include_voided),
                        events=records.events(row["run_id"], include_voided=include_voided)
                        if row["status"] == "RUNNING"
                        else (),
                    )
                    for row in rows
                ]
            },
        )


@router.get(
    "/variants/{variant_id}",
    response_model=schemas.VariantDetail,
    response_model_exclude_unset=True,
)
def variant_detail(request: Request, variant_id: str, include_voided: bool = False):
    root = root_from(request)
    with get_records(root) as records:
        row = required(records, "variants", variant_id, include_voided)
        run = required(records, "runs", row["run_id"], include_voided)
        events = records.events(row["run_id"], include_voided=include_voided)
        evals, heals, critique, steps = views.lane_evidence(
            row, run, records, include_voided=include_voided, events=events
        )
        value = {
            **views.leaderboard_row(row, run=run, events=events),
            **{
                key: row.get(key)
                for key in (
                    "code",
                    "params",
                    "equity",
                    "activity",
                    "equity_boundaries",
                    "original_result",
                    "cost_sharpes",
                    "eligibility_reason",
                )
            },
            "source": run.get("source"),
            "verification_eligible": row.get("verification_eligible", True),
            "critique": critique,
            "steps": steps,
            "evals": [
                {
                    "n": e["number"],
                    "name": e["name"],
                    "passed": e["passed"],
                    "metrics": e["metrics"],
                }
                for e in views.display_evaluations(row, run, evals)
            ],
            "heal_attempts": [
                {key: h.get(key) for key in schemas.HealView.model_fields} for h in heals
            ],
        }
    value["artifacts"] = ArtifactRegistry(root).list(
        run_id=row["run_id"], include_voided=include_voided
    )
    return response(schemas.VariantDetail, value)


def _event_page(root, run_id, after_seq, limit, include_voided):
    with get_records(root) as records:
        run = required(records, "runs", run_id, include_voided)
        all_events = records.events(run_id, include_voided=include_voided)
        events = [e for e in all_events if e["seq"] > after_seq][:limit]
        final_seq = max((e["seq"] for e in all_events if e["stage"] == "done"), default=None)
        cursor = events[-1]["seq"] if events else after_seq
        tail_seq = max((e["seq"] for e in all_events), default=0)
        terminal = run["status"] != "RUNNING"
        finished = terminal and final_seq is not None and cursor >= tail_seq
        terminal_gap = terminal and final_seq is None and cursor >= tail_seq
        return sanitize(events), cursor, finished, terminal_gap


@router.get(
    "/runs/{run_id}/events/history",
    response_model=schemas.EventHistory,
    response_model_exclude_unset=True,
)
def history(
    request: Request,
    run_id: str,
    after_seq: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    include_voided: bool = False,
):
    events, cursor, _, _ = _event_page(root_from(request), run_id, after_seq, limit, include_voided)
    return response(schemas.EventHistory, {"events": events, "next_seq": cursor})


@router.get("/runs/{run_id}/events")
async def event_stream(
    request: Request,
    run_id: str,
    after_seq: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header()] = None,
    include_voided: bool = False,
):
    if last_event_id is not None:
        try:
            parsed = int(last_event_id)
            if parsed < 0:
                raise ValueError
        except ValueError:
            raise HTTPException(422, "Last-Event-ID must be a nonnegative event sequence") from None
        after_seq = max(after_seq, parsed)
    root = root_from(request)
    first = await asyncio.to_thread(_event_page, root, run_id, after_seq, 1000, include_voided)

    async def stream():
        page = first
        last_heartbeat = time.monotonic()
        gap_started = None
        while True:
            if await request.is_disconnected():
                return
            events, cursor, finished, terminal_gap = page
            for event in events:
                yield f"id: {event['seq']}\ndata: {json.dumps(event, allow_nan=False)}\n\n"
            if finished:
                return
            now = time.monotonic()
            if terminal_gap:
                gap_started = now if gap_started is None or events else gap_started
                if now - gap_started >= request.app.state.terminal_grace_seconds:
                    yield ": Run is terminal; no terminal event was retained.\n\n"
                    return
            else:
                gap_started = None
            if now - last_heartbeat >= request.app.state.keepalive_seconds:
                yield ": keepalive\n\n"
                last_heartbeat = now
            await asyncio.sleep(request.app.state.poll_seconds)
            try:
                page = await asyncio.to_thread(
                    _event_page, root, run_id, cursor, 1000, include_voided
                )
            except HTTPException as error:
                if error.status_code == 404:
                    return  # A newly voided run is no longer visible on this stream.
                raise
            except (ValueError, OSError):
                yield 'event: error\ndata: {"detail":"Stored evidence could not be read"}\n\n'
                return

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/graveyard", response_model=schemas.Graveyard, response_model_exclude_unset=True)
def graveyard(request: Request, include_voided: bool = False):
    with get_records(root_from(request)) as records:
        rows = records.list("variants", include_voided=include_voided)
        entries = [
            views.graveyard_entry(row, records, include_voided=include_voided)
            for row in rows
            if row["status"] != "RUNNING"
        ]
    sections = []
    for entry in entries:
        sections.append(
            f"## {entry['source_title']} | {entry['run_id']} | {entry['variant']}\n\n"
            f"{entry['status']} ({entry['evals_passed']}/5)\n\n"
            f"{entry['summary']}\n\n{entry['cause']}\n\n"
            "### Unverified model narrative\n\n"
            + (entry["critique"] or "No narrative was recorded.")
        )
    return response(schemas.Graveyard, {"entries": entries, "markdown": "\n\n".join(sections)})


@router.get("/providers", response_model=schemas.Providers)
def providers():
    # Presence only, never an API connectivity claim and never the key value.
    return schemas.Providers(
        providers=[
            schemas.Provider(
                name="alpaca",
                connected=bool(os.getenv("APCA_API_KEY_ID") and os.getenv("APCA_API_SECRET_KEY")),
                covers=["price_bars"],
            ),
            schemas.Provider(
                name="databento",
                connected=bool(os.getenv("DATABENTO_API_KEY")),
                covers=["price_bars"],
            ),
        ]
    )


@router.post("/runs", response_model=schemas.StartedRun, status_code=202)
async def start_run(request: Request):
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type == "application/json":
        raise HTTPException(501, "Saved-spec starts are not available yet")
    if content_type != "multipart/form-data":
        raise HTTPException(422, "Upload a text-based PDF as multipart field pdf")
    async with request.form(max_files=1, max_fields=2) as form:
        upload = form.get("pdf")
        if not isinstance(upload, UploadFile):
            raise HTTPException(422, "Multipart field pdf is required")
        run_id = await asyncio.to_thread(
            request.app.state.runtime.submit, upload.file, upload.filename
        )
    return schemas.StartedRun(run_id=run_id)


@router.post("/intake")
@router.post("/providers/{name}/key")
@router.post("/data/candidates/{candidate_id}/approve")
def unavailable():
    raise HTTPException(501, "not available yet")
