"""Compose the local API. Run with uvicorn factory.api.app:app --host 127.0.0.1."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from factory.api import artifacts, datasets, eval_schema, runs
from factory.api.common import sanitize
from factory.api.runner import RunRuntime
from factory.orchestrator import run_paper


def create_app(
    root=".", *, runner=None, poll_seconds=0.25, keepalive_seconds=10, terminal_grace_seconds=2
):
    root = Path(root).resolve()
    runtime = RunRuntime(root, runner or run_paper)

    @asynccontextmanager
    async def lifespan(application):
        load_dotenv(root / ".env", override=False)
        load_dotenv(root / "runs" / "secrets.env", override=False)
        try:
            await asyncio.to_thread(runtime.startup)
            yield
        finally:
            await asyncio.to_thread(runtime.close)

    app = FastAPI(title="Financial Models in the Arena", lifespan=lifespan)
    app.state.root = root
    app.state.runtime = runtime
    app.state.poll_seconds = max(float(poll_seconds), 0.01)
    app.state.keepalive_seconds = max(float(keepalive_seconds), 0.05)
    app.state.terminal_grace_seconds = max(float(terminal_grace_seconds), 0.05)

    @app.exception_handler(HTTPException)
    async def safe_http_error(request: Request, error: HTTPException):
        return JSONResponse(
            {"detail": sanitize(error.detail)}, status_code=error.status_code, headers=error.headers
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        return JSONResponse({"detail": "Invalid request fields"}, status_code=422)

    async def invalid_evidence(request: Request, error: Exception):
        return JSONResponse(
            {"detail": "Stored evidence could not be validated or read"}, status_code=500
        )

    for error in (ValueError, ValidationError, ResponseValidationError, sqlite3.Error, OSError):
        app.add_exception_handler(error, invalid_evidence)
    app.include_router(runs.router)
    app.include_router(datasets.router)
    app.include_router(artifacts.router)
    app.include_router(eval_schema.router)
    return app


app = create_app()
