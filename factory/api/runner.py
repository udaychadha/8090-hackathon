"""One local background run, durable reservation, and owned-run restart recovery."""

from __future__ import annotations

import fcntl
import hashlib
import json
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import HTTPException

from factory.agents.extractor import ExtractionError, pdf_text
from factory.agents.records import Records
from factory.api.common import sanitize
from factory.record_migration import utc_now

MAX_PDF_BYTES = 30_000_000


class RunRuntime:
    def __init__(self, root, runner):
        self.root = Path(root).resolve()
        self.runner = runner
        self.lock = threading.Lock()
        self.busy = False
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="arena-run")
        self.process_lock = None

    def startup(self):
        (self.root / "runs").mkdir(parents=True, exist_ok=True)
        self.process_lock = (self.root / "runs" / "api-runtime.lock").open("a")
        try:
            fcntl.flock(self.process_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.process_lock.close()
            self.process_lock = None
            raise RuntimeError("Another local API process owns the run queue") from None
        with Records(self.root / "runs") as records:
            owned = [
                r
                for r in records.list("runs")
                if (r.get("submission") or {}).get("origin") == "api"
            ]
        for run in owned:
            if run["status"] == "RUNNING":
                self._failed(
                    run["run_id"],
                    "InterruptedRun",
                    "The local API stopped before this run finished.",
                )
            else:
                self._ensure_terminal_event(run["run_id"])

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=False)
        if self.process_lock is not None:
            fcntl.flock(self.process_lock.fileno(), fcntl.LOCK_UN)
            self.process_lock.close()
            self.process_lock = None

    def _copy_known_source(self, target, digest):
        """Reuse only matching, fingerprint-verified owner-approved local evidence."""
        papers = self.root / "papers"
        if not papers.is_dir():
            return
        for candidate in sorted(papers.rglob("*.pdf")):
            if candidate.is_symlink() or not candidate.resolve().is_relative_to(papers.resolve()):
                continue
            if candidate.stat().st_size > MAX_PDF_BYTES:
                continue
            if hashlib.sha256(candidate.read_bytes()).hexdigest() != digest:
                continue
            sidecar = candidate.with_suffix(".spec.json")
            if not sidecar.is_file() or sidecar.is_symlink() or sidecar.stat().st_size > 1_000_000:
                continue
            try:
                metadata = json.loads(sidecar.read_text())
                source = metadata.get("source")
                if not isinstance(source, dict) or source.get("sha256") != digest:
                    continue
            except (ValueError, UnicodeError):
                continue
            markdown = candidate.with_suffix(".md")
            if (
                markdown.is_file()
                and not markdown.is_symlink()
                and markdown.stat().st_size <= 1_000_000
            ):
                text = markdown.read_bytes()
                if hashlib.sha256(text).hexdigest() == source.get("markdown_sha256"):
                    target.with_suffix(".md").write_bytes(text)
                    source["markdown_file"] = target.with_suffix(".md").name
                else:
                    # No unverified text enters a new extraction.
                    for key in ("markdown_file", "markdown_sha256", "markdown_extraction"):
                        source.pop(key, None)
            source["pdf_file"] = target.name
            target.with_suffix(".spec.json").write_text(
                json.dumps(sanitize(metadata), indent=2) + "\n"
            )
            return

    def submit(self, file, filename):
        with self.lock:
            if self.busy:
                raise HTTPException(409, "A local run is already in progress")
            self.busy = True
        run_id = "r_" + uuid.uuid4().hex[:12]
        directory = self.root / "runs" / "uploads" / run_id
        reserved = False
        try:
            directory.mkdir(parents=True, exist_ok=False)
            target = directory / "paper.pdf"
            size, digest = 0, hashlib.sha256()
            with target.open("wb") as stream:
                while chunk := file.read(1_048_576):
                    size += len(chunk)
                    if size > MAX_PDF_BYTES:
                        raise HTTPException(413, "PDF exceeds the 30 MB limit")
                    digest.update(chunk)
                    stream.write(chunk)
            try:
                pdf_text(target)
            except ExtractionError as error:
                raise HTTPException(422, sanitize(str(error))) from None
            self._copy_known_source(target, digest.hexdigest())
            safe_name = Path((filename or "paper.pdf").replace("\\", "/")).name
            safe_name = safe_name.replace("\x00", "")[:255] or "paper.pdf"
            with Records(self.root / "runs") as records:
                records.put(
                    "runs",
                    run_id,
                    run_id,
                    {
                        "run_id": run_id,
                        "status": "RUNNING",
                        "variants": [],
                        "data_needs": [],
                        "submission": {
                            "origin": "api",
                            "upload_name": safe_name,
                            "upload_sha256": digest.hexdigest(),
                            "input_path": target.relative_to(self.root).as_posix(),
                            "accepted_at": utc_now(),
                        },
                    },
                )
                reserved = True
                records.event(run_id, "intake", "started", "Owner-supplied PDF accepted")
            self.executor.submit(self._execute, target, run_id)
            return run_id
        except BaseException:
            try:
                if reserved:
                    self._failed(run_id, "SubmissionError", "The local run could not be scheduled.")
                else:
                    shutil.rmtree(directory, ignore_errors=True)
            finally:
                with self.lock:
                    self.busy = False
            raise

    def _execute(self, paper, run_id):
        try:
            self.runner(paper, data_root=self.root / "data", output_root=self.root, run_id=run_id)
            with Records(self.root / "runs", read_only=True) as records:
                run = records.get("runs", run_id, include_voided=True)
            if run is None or run["status"] == "RUNNING":
                self._failed(
                    run_id, "IncompleteRun", "The pipeline returned without a final result."
                )
            else:
                self._ensure_terminal_event(run_id)
        except Exception:
            # SDK exceptions may contain prompts and credentials. Store a stable
            # operational category, never the exception message or traceback.
            self._failed(
                run_id, "BackgroundRunError", "The background pipeline stopped unexpectedly."
            )
        finally:
            with self.lock:
                self.busy = False

    def _ensure_terminal_event(self, run_id):
        with Records(self.root / "runs") as records:
            run = records.get("runs", run_id)
            if run is None or run["status"] == "RUNNING":
                return
            if not any(e["stage"] == "done" for e in records.events(run_id)):
                records.event(
                    run_id,
                    "done",
                    "passed" if run["status"] == "COMPLETED" else "failed",
                    "Recovered terminal state from the stored run; "
                    "original terminal event was not retained",
                    data={"status": run["status"]},
                )

    def _failed(self, run_id, category, message):
        with Records(self.root / "runs") as records:
            run = records.get("runs", run_id, include_voided=True)
            if run is None or run["status"] == "VOID":
                return
            rows = records.list("variants", run_id=run_id)
            for row in rows:
                if row["status"] == "RUNNING":
                    row.update(status="BUG_UNRESOLVED", default_status="BUG_UNRESOLVED")
                    records.put("variants", row["variant_id"], run_id, row)
            run.update(
                status="FAILED",
                error_type=category,
                error=message,
                variants=rows,
                cost_complete=False,
                estimated_model_cost_usd=None,
            )
            records.put("runs", run_id, run_id, run)
            records.event(run_id, "done", "failed", message, data={"status": "FAILED"})
