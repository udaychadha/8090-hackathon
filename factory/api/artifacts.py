"""Allowlisted, read-only evidence inventory and sanitized attachments."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from factory.agents.records import Records
from factory.api.common import root_from, sanitize

router = APIRouter(prefix="/api", tags=["artifacts"])
_OMIT = object()


class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    kind: str
    media_type: str
    size_bytes: int = Field(ge=0)
    run_ids: list[str] = Field(default_factory=list)
    source_id: str | None = None
    dataset_id: str | None = None
    historical: bool = False
    audit_only: bool = False
    downloadable: bool = True
    notes: list[str] = Field(default_factory=list)


class ArtifactView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact: Artifact
    content: str | None
    offset: int = Field(ge=0)
    next_offset: int | None


class ArtifactList(BaseModel):
    artifacts: list[Artifact]


def dataset_identifier(scope, frequency, symbol):
    return f"{scope}-{frequency}-{symbol}"


def safe_path(root, path):
    """Reject every symlink component, even a link back inside the root."""
    root, path = Path(root).resolve(), Path(path)
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None
    current = root
    for part in relative.parts:
        if part in {".", ".."}:
            return None
        current = current / part
        if current.is_symlink():
            return None
    return current if current.is_file() and current.resolve().is_relative_to(root) else None


def read_json(root, path):
    path = safe_path(root, path)
    if path is None:
        raise HTTPException(404, "Evidence not found")
    try:
        return json.loads(path.read_text())
    except (OSError, UnicodeError, ValueError):
        raise HTTPException(409, "Evidence cannot be read as valid JSON") from None


class ArtifactRegistry:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def _runs(self):
        path = self.root / "runs/factory.db"
        if safe_path(self.root, path) is None:
            return {}
        try:
            with Records(path.parent, read_only=True) as records:
                return {row["run_id"]: row for row in records.list("runs", include_voided=True)}
        except (OSError, ValueError):
            raise HTTPException(409, "Stored records require validation or migration") from None

    def _inventory(self):
        runs = self._runs()
        voided = {
            key
            for key, value in runs.items()
            if value.get("voided") or value.get("status") == "VOID"
        }
        items = {}

        def add(
            relative,
            kind,
            *,
            run_ids=None,
            source_id=None,
            dataset_id=None,
            historical=False,
            audit_only=False,
            downloadable=True,
            notes=None,
        ):
            path = safe_path(self.root, self.root / relative)
            if path is None:
                return
            name = path.relative_to(self.root).as_posix()
            suffix = path.suffix.lower()
            media = {
                ".json": "application/json",
                ".jsonl": "application/x-ndjson",
                ".pdf": "application/pdf",
                ".jpg": "image/jpeg",
                ".png": "image/png",
                ".csv": "text/csv",
            }.get(suffix, "text/plain")
            if suffix in {".db", ".sqlite3"}:
                media, downloadable = "application/vnd.sqlite3", False
            if kind in {"event_backup", "record_backup"} and suffix == ".jsonl":
                media = "text/plain"
            identifiers = sorted(set(run_ids or []))
            audit_only = audit_only or bool(identifiers and set(identifiers) <= voided)
            descriptor = Artifact(
                id="a_" + hashlib.sha256(name.encode()).hexdigest()[:24],
                name=name,
                kind=kind,
                media_type=media,
                size_bytes=path.stat().st_size,
                run_ids=identifiers,
                source_id=source_id,
                dataset_id=dataset_id,
                historical=historical,
                audit_only=audit_only,
                downloadable=downloadable,
                notes=notes or [],
            )
            items[descriptor.id] = (descriptor, path)

        # Registered research sources; sidecars never authorize an arbitrary path.
        for sidecar in sorted((self.root / "papers").glob("*.spec.json")):
            if safe_path(self.root, sidecar) is None:
                continue
            metadata = read_json(self.root, sidecar)
            source_id = (metadata.get("strategy_spec") or {}).get("paper_id")
            if not isinstance(source_id, str):
                continue
            ids = [
                key
                for key, value in runs.items()
                if value.get("source_id") == source_id
                or (value.get("source") or {}).get("source_id") == source_id
            ]
            stem = sidecar.name.removesuffix(".spec.json")
            for suffix, kind in [
                (".spec.json", "source_spec"),
                (".md", "paper_text"),
                (".pdf", "paper_pdf"),
            ]:
                add(f"papers/{stem}{suffix}", kind, source_id=source_id, run_ids=ids)

        for run_id, run in runs.items():
            submission = run.get("submission") or {}
            expected = f"runs/uploads/{run_id}/paper.pdf"
            if (
                not re.fullmatch(r"r_[a-zA-Z0-9]+", run_id)
                or submission.get("origin") != "api"
                or submission.get("input_path") != expected
            ):
                continue
            for suffix, kind in [
                (".pdf", "paper_pdf"),
                (".md", "paper_text"),
                (".spec.json", "source_spec"),
            ]:
                add(
                    f"runs/uploads/{run_id}/paper{suffix}",
                    kind,
                    run_ids=[run_id],
                    source_id=run.get("source_id"),
                )

        for path in sorted((self.root / "strategies").glob("*/*/[ABC].py")):
            source_id, run_id = path.parts[-3:-1]
            if run_id not in runs:
                continue
            add(path.relative_to(self.root), "strategy_code", run_ids=[run_id], source_id=source_id)

        for source_id in ("congress_all", "congress_committee"):
            add(
                f"specs/{source_id}.json",
                "source_spec",
                source_id=source_id,
                run_ids=[
                    key
                    for key, run in runs.items()
                    if (run.get("source") or {}).get("source_id") == source_id
                ],
            )
        for filename in (
            "wo12-source-audit.md",
            "wo12-source-audit.json",
            "wo12-committee-audit.md",
            "wo12-committee-audit.json",
            "wo12-runs.json",
            "wo12-results.md",
            "wo12-proof.json",
            "WO12-CHECKPOINT.md",
        ):
            add(f"report/{filename}", "report", notes=["Owner-approved WO-12 event-data evidence."])

        add(
            "runs/factory.db",
            "record_database",
            downloadable=False,
            notes=["Metadata only; database bytes are never served."],
        )
        add("runs/events.jsonl", "run_events", run_ids=list(runs))
        old_run_id = None
        for relative in ["runs/wo05-second-extraction.json", "runs/wo07-real-paper.json"]:
            if safe_path(self.root, self.root / relative) is None:
                continue
            payload = read_json(self.root, self.root / relative)
            run_id = payload.get("run_id")
            if relative == "runs/wo07-real-paper.json":
                old_run_id = run_id
            source_id = (payload.get("spec") or {}).get("paper_id")
            add(
                relative,
                "run_export" if run_id else "extraction_export",
                run_ids=[run_id] if run_id else [],
                source_id=source_id,
                historical=True,
            )
        add(
            "runs/wo17-before-void.sqlite3",
            "record_backup",
            historical=True,
            audit_only=True,
            downloadable=False,
            run_ids=[old_run_id] if old_run_id else [],
        )
        for backup in sorted((self.root / "runs").glob("record-backup-*")):
            for filename in ("factory.db", "events.jsonl", "audit.json"):
                add(
                    (backup / filename).relative_to(self.root),
                    "record_backup",
                    historical=True,
                    audit_only=True,
                )
        for backup in sorted((self.root / "runs").glob("rejudge-backup-*")):
            for filename in ("factory.db", "events.jsonl", "plan.json", "applied.json"):
                add(
                    (backup / filename).relative_to(self.root),
                    "record_backup",
                    historical=True,
                    audit_only=True,
                )
        for filename in (
            "eval45-rejudgment.json",
            "eval45-rejudgment.md",
            "eval45-proof.json",
            "eval45-record-audit.json",
            "eval45-tearsheet.png",
            "eval45-rules.png",
            "wo08-protected-files.json",
        ):
            add(
                f"report/{filename}",
                "report",
                historical=True,
                audit_only=True,
                notes=[
                    "Owner-authorized Eval 4/5 revision; includes historical and void evidence."
                ],
            )
        for filename in (
            "gross-diagnostics-backfill.json",
            "gross-diagnostics-congress.json",
            "gross-diagnostics-results.md",
            "gross-diagnostics-proof.json",
            "gross-diagnostics-record-audit.json",
            "gross-diagnostics-staged.json",
            "gross-schema-compatibility.json",
        ):
            add(
                f"report/{filename}",
                "report",
                historical=True,
                audit_only=True,
                notes=["Separate diagnostic evidence; includes historical and void variants."],
            )
        for backup in sorted((self.root / "runs").glob("gross-diagnostics-backup-*")):
            add(
                (backup / "factory.db").relative_to(self.root),
                "record_backup",
                historical=True,
                audit_only=True,
            )
        add(
            "runs/gross-staging-before.sqlite3",
            "record_backup",
            historical=True,
            audit_only=True,
        )
        for path in sorted((self.root / "runs").glob("events.jsonl.*")):
            # Records preserves divergent mirrors with this specific backup prefix.
            if "backup" in path.name or "conflict" in path.name:
                add(path.relative_to(self.root), "event_backup", historical=True, audit_only=True)
        for path in sorted((self.root / "runs").glob("events-recovery-*.json*")):
            add(path.relative_to(self.root), "event_backup", historical=True, audit_only=True)

        report_names = {
            "wo17-audit-step1.json",
            "wo17-canary.json",
            "wo17-daily-retries.json",
            "wo17-fixture-after.json",
            "wo17-fixture-before.json",
            "wo17-load-validation-probes.json",
            "wo17-migration.json",
            "wo17-paper-reruns.json",
            "wo17-results.json",
            "wo17-results.md",
            "wo17-void.json",
            "wo07-real-paper.html",
            "wo07-real-paper.jpg",
            "wo09-record-proof.json",
            "wo09-record-audit-before.json",
            "wo09-record-migration.json",
            "wo09-record-repeat.json",
        }
        for path in sorted((self.root / "report").glob("*")):
            if path.name not in report_names and not re.fullmatch(
                r"wo17-r_[a-z0-9]+\.json", path.name
            ):
                continue
            if safe_path(self.root, path) is None:
                continue
            ids = []
            if path.suffix == ".json":
                payload = read_json(self.root, path)
                text = json.dumps(payload)
                ids = sorted(set(re.findall(r"\br_[a-z0-9]+\b", text)) & runs.keys())
            elif path.suffix in {".html", ".md"}:
                ids = sorted(set(re.findall(r"\br_[a-z0-9]+\b", path.read_text())) & runs.keys())
            backup_capture = path.name in {"wo07-real-paper.html", "wo07-real-paper.jpg"}
            if backup_capture and old_run_id:
                ids = [old_run_id]
            add(
                path.relative_to(self.root),
                "historical_capture" if backup_capture else "report",
                run_ids=ids,
                historical=True,
                audit_only=backup_capture or path.name == "wo17-void.json",
                notes=["Historical capture; current run status supersedes this evidence."]
                if backup_capture
                else ["Historical diagnostic; not a new strategy verdict."],
            )

        add(
            "wiki/graveyard.md",
            "graveyard",
            run_ids=list(runs),
            notes=["Model narrative is unverified; current stored verdicts are authoritative."],
        )
        for relative, kind in [
            ("data/audit.json", "data_audit"),
            ("data/audit.txt", "data_audit"),
            ("data/wo02-smoke.json", "data_audit"),
            ("data/ingest.jsonl", "ingest_events"),
            ("data/smoke/ingest.jsonl", "ingest_events"),
            ("data/sp500.csv", "universe"),
            ("data/sp500.source.json", "universe"),
            ("docs/DATA.md", "data_contract"),
            ("factory/data_contract/contract.yaml", "data_contract"),
            ("factory/data_contract/agent_data.md", "data_contract"),
            ("factory/data_contract/generated.py", "data_contract"),
        ]:
            add(relative, kind, historical=kind == "data_audit")
        for scope, directory in [("main", "data"), ("smoke", "data/smoke")]:
            for frequency in ["1min", "1day"]:
                base = self.root / directory
                add(f"{directory}/{frequency}/manifest.json", "tier_manifest")
                for path in sorted((base / frequency).glob("*.manifest.json")):
                    symbol = path.name.removesuffix(".manifest.json")
                    dataset_id = dataset_identifier(scope, frequency, symbol)
                    add(path.relative_to(self.root), "dataset_manifest", dataset_id=dataset_id)
                    add(
                        f"{directory}/metadata/{frequency}/{symbol}.json",
                        "ingest_metadata",
                        dataset_id=dataset_id,
                    )
            for path in sorted((self.root / directory / "events").glob("*.manifest.json")):
                name = path.name.removesuffix(".manifest.json")
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", name):
                    continue
                dataset_id = dataset_identifier(scope, "events", name)
                add(
                    path.relative_to(self.root),
                    "dataset_manifest",
                    dataset_id=dataset_id,
                    notes=["unverified source; raw event data is not an artifact download"],
                )
        return items, voided

    def list(self, run_id=None, source_id=None, dataset_id=None, include_voided=False):
        items, voided = self._inventory()
        if run_id in voided and not include_voided:
            return []
        result = []
        for descriptor, _ in items.values():
            if descriptor.audit_only and not include_voided:
                continue
            if run_id is not None and run_id not in descriptor.run_ids:
                continue
            if source_id is not None and source_id != descriptor.source_id:
                continue
            if dataset_id is not None and dataset_id != descriptor.dataset_id:
                continue
            value = descriptor.model_dump()
            if not include_voided:
                value["run_ids"] = [
                    identifier for identifier in value["run_ids"] if identifier not in voided
                ]
            result.append(Artifact.model_validate(sanitize(value)))
        return result

    def _resolve(self, artifact_id, include_voided):
        items, voided = self._inventory()
        match = items.get(artifact_id)
        if match is None or (match[0].audit_only and not include_voided):
            raise HTTPException(404, "Evidence not found")
        descriptor, path = match
        descriptor = descriptor.model_copy(
            update={
                "run_ids": [
                    run_id
                    for run_id in descriptor.run_ids
                    if include_voided or run_id not in voided
                ]
            }
        )
        return Artifact.model_validate(sanitize(descriptor.model_dump())), path, voided

    @staticmethod
    def _filter(value, voided):
        def hidden(text):
            return isinstance(text, str) and any(
                re.search(r"(?<![a-zA-Z0-9])" + re.escape(run_id) + r"(?=$|[^a-z0-9])", text)
                for run_id in voided
            )

        if isinstance(value, dict):
            if hidden(value.get("run_id")) or hidden(value.get("id")):
                return _OMIT
            return {
                key: filtered
                for key, item in value.items()
                if key not in {"cross_tier_spy_examples"}
                and not hidden(key)
                and (filtered := ArtifactRegistry._filter(item, voided)) is not _OMIT
            }
        if isinstance(value, list):
            return [
                filtered
                for item in value
                if (filtered := ArtifactRegistry._filter(item, voided)) is not _OMIT
            ]
        if hidden(value):
            return _OMIT
        return value

    def _text(self, descriptor, path, voided, include_voided):
        if safe_path(self.root, path) is None:
            raise HTTPException(404, "Evidence not found")
        if not descriptor.downloadable or descriptor.media_type in {
            "application/pdf",
            "image/jpeg",
            "image/png",
        }:
            return None
        hidden = set() if include_voided else voided
        try:
            raw = path.read_text()
            if descriptor.kind in {"event_backup", "record_backup"} and path.suffix == ".jsonl":
                # Recovery and migration snapshots may preserve torn input. They are
                # audit-only evidence, not a replay source; retain sanitized text.
                return sanitize(raw)
            if path.suffix == ".json":
                value = self._filter(json.loads(raw), hidden)
                if value is _OMIT:
                    raise HTTPException(404, "Evidence not found")
                return json.dumps(sanitize(value), indent=2, ensure_ascii=False, allow_nan=False)
            if path.suffix == ".jsonl":
                rows = [
                    self._filter(json.loads(line), hidden)
                    for line in raw.splitlines()
                    if line.strip()
                ]
                return (
                    "\n".join(
                        json.dumps(sanitize(row), ensure_ascii=False, allow_nan=False)
                        for row in rows
                        if row is not _OMIT
                    )
                    + "\n"
                )
            if hidden:
                if descriptor.kind == "graveyard":
                    sections = re.split(
                        r"(?=^## .*\| r_[a-z0-9]+ \| [ABC]\s*$)", raw, flags=re.MULTILINE
                    )
                    raw = "\n".join(
                        section
                        for section in sections
                        if not set(re.findall(r"\br_[a-z0-9]+\b", section)) & hidden
                    )
                else:
                    raw = "\n".join(
                        line
                        for line in raw.splitlines()
                        if not set(re.findall(r"\br_[a-z0-9]+\b", line)) & hidden
                    )
            return sanitize(raw)
        except (OSError, UnicodeError, ValueError):
            raise HTTPException(409, "Evidence cannot be safely decoded") from None

    def view(self, artifact_id, include_voided=False, offset=0, limit=100000):
        if offset < 0 or not 1 <= limit <= 100000:
            raise HTTPException(422, "Preview bounds are invalid")
        descriptor, path, voided = self._resolve(artifact_id, include_voided)
        content = self._text(descriptor, path, voided, include_voided)
        next_offset = (
            offset + limit if content is not None and len(content) > offset + limit else None
        )
        return ArtifactView(
            artifact=descriptor,
            content=None if content is None else content[offset : offset + limit],
            offset=offset,
            next_offset=next_offset,
        )

    def download(self, artifact_id, include_voided=False):
        descriptor, path, voided = self._resolve(artifact_id, include_voided)
        if not descriptor.downloadable:
            raise HTTPException(404, "Evidence download is unavailable")
        text = self._text(descriptor, path, voided, include_voided)
        if safe_path(self.root, path) is None:
            raise HTTPException(404, "Evidence not found")
        filename = path.name + ".txt" if path.suffix == ".html" else path.name
        return (
            path.read_bytes() if text is None else text.encode(),
            descriptor.media_type,
            filename,
        )


@router.get("/artifacts", response_model=ArtifactList)
def list_artifacts(request: Request, run_id: str | None = None, include_voided: bool = False):
    return ArtifactList(
        artifacts=ArtifactRegistry(root_from(request)).list(
            run_id=run_id, include_voided=include_voided
        )
    )


@router.get("/artifacts/{artifact_id}", response_model=ArtifactView)
def view_artifact(
    request: Request,
    artifact_id: str,
    include_voided: bool = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(100000, ge=1, le=100000),
):
    return ArtifactRegistry(root_from(request)).view(artifact_id, include_voided, offset, limit)


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(request: Request, artifact_id: str, include_voided: bool = False):
    content, media_type, filename = ArtifactRegistry(root_from(request)).download(
        artifact_id, include_voided
    )
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", filename)
    return Response(
        content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )
