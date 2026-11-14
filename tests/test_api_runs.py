"""Core HTTP projections, finite/live event replay, and real background lifecycle."""

import importlib.util
import json
import threading

import pytest


def test_core_api_entry_point_exists():
    assert importlib.util.find_spec("factory.api.app") is not None


@pytest.fixture
def root(tmp_path):
    from factory.agents.records import Records
    from factory.agents.test_worker import spec
    from factory.orchestrator import _row

    with Records(tmp_path / "runs") as records:
        for run_id in ["r_live", "r_void"]:
            run = records.put("runs", run_id, run_id, {"run_id": run_id, "status": "RUNNING"})
            source = records.put(
                "sources",
                spec().paper_id,
                run_id,
                {
                    "source_id": spec().paper_id,
                    "title": spec().title,
                    "source_kind": "paper",
                    "spec": spec().model_dump(),
                    "provenance": {},
                },
            )
            run["source"] = source
            records.put("runs", run_id, run_id, run)
            records.event(run_id, "extract", "passed", "Extracted")
            row = _row(spec(), run_id, "A")
            row.update(
                status="FAILED_EVAL_2",
                evals_passed=1,
                code="original code",
                evals=[
                    {"number": 1, "name": "lookahead", "passed": True, "metrics": {}},
                    {
                        "number": 2,
                        "name": "friction",
                        "passed": False,
                        "metrics": {"sharpe_by_bps": {"5": 0.2}, "pass_bps": 5.0},
                    },
                ],
            )
            row = records.put("variants", row["variant_id"], run_id, row)
            for evaluation in row["evals"]:
                records.put(
                    "eval_results",
                    f"{run_id}_A_{evaluation['number']}",
                    run_id,
                    {"variant": "A", **evaluation},
                )
            records.put(
                "heal_attempts",
                f"{run_id}_A_1",
                run_id,
                {"variant": "A", "attempt": 1, "error": "lookahead at timestamp", "fixed": True},
            )
            records.put(
                "critiques",
                f"{run_id}_A",
                run_id,
                {"variant": "A", "text": "Legacy narrative claims it passed all evals."},
            )
            records.event(
                run_id, "eval", "passed", "IS bug validation passed", variant="A", data={"eval": 1}
            )
            run.update(status="COMPLETED", variants=[row])
            records.put("runs", run_id, run_id, run)
            records.event(run_id, "done", "passed", "Run finished", data={"status": "COMPLETED"})
        records.void_run("r_void", "Historical evidence invalidated")
    return tmp_path


def client_for(root, **kwargs):
    from fastapi.testclient import TestClient

    from factory.api.app import create_app

    return TestClient(create_app(root, **kwargs))


def test_real_record_views_and_void_audit_opt_in(root):
    with client_for(root) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["capabilities"]["paper_runs"] is True
        rows = client.get("/api/leaderboard").json()["rows"]
        assert [r["variant_id"] for r in rows] == ["r_live_A"]
        assert rows[0]["status"] == rows[0]["default_status"] == "FAILED_EVAL_2"
        assert rows[0]["evals_passed"] == 1
        detail = client.get("/api/variants/r_live_A").json()
        assert detail["equity"] is None
        assert detail["code"] == "original code"
        assert detail["source"]["spec"]["paper_id"]
        assert detail["heal_attempts"][0]["fixed"] is True
        assert detail["summary"] != detail["critique"]
        assert "Failed Eval 2" in detail["summary"]
        run = client.get("/api/runs/r_live").json()
        assert run["started_at"] is not None
        assert run["variants"][0]["steps"][1]["kind"] == "heal"
        for route in [
            "/api/runs/r_void",
            "/api/variants/r_void_A",
            "/api/runs/r_void/events/history",
            "/api/runs/r_void/events",
        ]:
            assert client.get(route).status_code == 404
            assert client.get(route + "?include_voided=true").status_code == 200
        graveyard = client.get("/api/graveyard").json()
        assert len(graveyard["entries"]) == 1
        assert graveyard["entries"][0]["status"] == "FAILED_EVAL_2"
        assert "unverified model narrative" in graveyard["markdown"].lower()
        assert client.get("/api/leaderboard?sort_by=DROP%20TABLE").status_code == 422


def test_preliminary_bug_check_is_not_a_performance_eval(root):
    from factory.agents.records import Records
    from factory.agents.test_worker import spec
    from factory.orchestrator import _row

    with Records(root / "runs") as records:
        row = _row(spec(), "r_live", "B")
        row.update(status="INACTIVE", days_traded=0)
        row = records.put("variants", row["variant_id"], "r_live", row)
        records.event(
            "r_live", "eval", "passed", "IS bug validation passed", variant="B", data={"eval": 1}
        )
    with client_for(root) as client:
        detail = client.get("/api/variants/r_live_B").json()
        evaluations = [s for s in detail["steps"] if s["kind"] == "eval"]
        assert len(evaluations) == 5
        assert all(s["state"] == "not_run" for s in evaluations)
        assert detail["evals"] == []


def test_finished_sse_replays_ids_and_resume_cursor(root):
    with client_for(root) as client:
        history = client.get("/api/runs/r_live/events/history?limit=2").json()
        assert len(history["events"]) == 2
        cursor = history["next_seq"]
        result = client.get("/api/runs/r_live/events", headers={"Last-Event-ID": str(cursor)})
        assert result.headers["content-type"].startswith("text/event-stream")
        events = [
            json.loads(line[6:]) for line in result.text.splitlines() if line.startswith("data: ")
        ]
        assert events and all(e["seq"] > cursor for e in events)
        assert events[-1]["stage"] == "done"
        assert f"id: {events[-1]['seq']}" in result.text
        assert (
            client.get("/api/runs/r_live/events", headers={"Last-Event-ID": "bad"}).status_code
            == 422
        )


def pdf_bytes():
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((40, 50), "A supplied paper describing a trading strategy.")
    result = document.tobytes()
    document.close()
    return result


def test_upload_reserves_id_and_runs_one_background_pipeline(root):
    from factory.agents.records import Records

    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    received = []

    def runner(paper, *, data_root, output_root, run_id):
        received.append((paper, run_id))
        entered.set()
        assert release.wait(5)
        with Records(output_root / "runs") as records:
            row = records.get("runs", run_id)
            assert row["submission"]["origin"] == "api"
            row["status"] = "COMPLETED"
            records.put("runs", run_id, run_id, row)
            records.event(
                run_id, "done", "passed", "Finished test pipeline", data={"status": "COMPLETED"}
            )
        finished.set()

    with client_for(root, runner=runner) as client:
        response = client.post(
            "/api/runs", files={"pdf": ("../../escape.pdf", pdf_bytes(), "application/pdf")}
        )
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        assert entered.wait(5)
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "RUNNING"
        assert (
            client.post(
                "/api/runs", files={"pdf": ("paper.pdf", pdf_bytes(), "application/pdf")}
            ).status_code
            == 409
        )
        release.set()
        assert finished.wait(5)
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "COMPLETED"
        assert received[0][0].is_relative_to(root / "runs" / "uploads" / run_id)
        assert not (root.parent / "escape.pdf").exists()


def test_invalid_pdf_and_unimplemented_controls_return_explicit_errors(root):
    with client_for(root) as client:
        assert (
            client.post(
                "/api/runs", files={"pdf": ("paper.pdf", b"not pdf", "application/pdf")}
            ).status_code
            == 422
        )
        assert client.post("/api/runs", json={"spec_id": "saved"}).status_code == 501
        for route in [
            "/api/intake",
            "/api/data/upload",
            "/api/providers/alpaca/key",
            "/api/data/candidates/example/approve",
        ]:
            response = client.post(route, json={})
            assert response.status_code == 501
            assert "not available yet" in response.json()["detail"].lower()


def test_existing_orchestrator_uses_reserved_identity_and_submission(root, monkeypatch):
    from factory.agents.records import Records
    from factory.orchestrator import run_paper
    from factory.record_migration import utc_now

    monkeypatch.delenv("EXTRACTOR_MODEL", raising=False)
    with Records(root / "runs") as records:
        initial = records.put(
            "runs",
            "r_reserved",
            "r_reserved",
            {
                "run_id": "r_reserved",
                "status": "RUNNING",
                "submission": {
                    "origin": "api",
                    "upload_name": "paper.pdf",
                    "upload_sha256": "a" * 64,
                    "input_path": "runs/uploads/r_reserved/paper.pdf",
                    "accepted_at": utc_now(),
                },
            },
        )
    result = run_paper("unused.pdf", output_root=root, run_id="r_reserved")
    assert result["run_id"] == "r_reserved"
    assert result["submission"] == initial["submission"]
    assert result["created_at"] == initial["created_at"]
    assert result["status"] == "FAILED"


def test_pipeline_persists_three_lanes_before_proposal_and_current_verdict_before_critic(
    root, monkeypatch
):
    from factory import orchestrator
    from factory.agents.records import Records
    from factory.agents.test_worker import bars, spec
    from factory.llm import Completion

    usage = Completion("Narrative", "fixture", 1, 1, 0, 0.001)
    for role in ("EXTRACTOR", "WORKER", "CRITIC"):
        monkeypatch.setenv(f"{role}_MODEL", "openai:fixture")
    monkeypatch.setattr(orchestrator, "extract", lambda *a, **kw: (spec(), usage))
    monkeypatch.setattr(orchestrator, "load_bars", lambda *a, **kw: bars())

    def propose(*args):
        with Records(root / "runs", read_only=True) as records:
            rows = records.list("variants", run_id="r_incremental")
        assert len(rows) == 3
        assert all(r["status"] == r["default_status"] == "RUNNING" for r in rows)
        return {lane: RuntimeError("fixture provider unavailable") for lane in "ABC"}

    def critic(*args):
        with Records(root / "runs", read_only=True) as records:
            rows = records.list("variants", run_id="r_incremental")
        assert all(r["status"] == r["default_status"] == "BUG_UNRESOLVED" for r in rows)
        return usage

    monkeypatch.setattr(orchestrator, "propose_parallel", propose)
    monkeypatch.setattr(orchestrator, "critique", critic)
    result = orchestrator.run_paper("unused.pdf", output_root=root, run_id="r_incremental")
    assert result["status"] == "FAILED"
    assert len(result["variants"]) == 3


def test_restart_recovers_only_api_owned_running_records(root):
    from factory.agents.records import Records
    from factory.record_migration import utc_now

    with Records(root / "runs") as records:
        records.put(
            "runs", "r_external", "r_external", {"run_id": "r_external", "status": "RUNNING"}
        )
        records.put(
            "runs",
            "r_abandoned",
            "r_abandoned",
            {
                "run_id": "r_abandoned",
                "status": "RUNNING",
                "submission": {
                    "origin": "api",
                    "upload_name": "paper.pdf",
                    "upload_sha256": "b" * 64,
                    "input_path": "runs/uploads/r_abandoned/paper.pdf",
                    "accepted_at": utc_now(),
                },
            },
        )
    with client_for(root) as client:
        result = client.get("/api/runs/r_abandoned").json()
        assert result["status"] == "FAILED" and result["error_type"] == "InterruptedRun"
        assert client.get("/api/runs/r_external").json()["status"] == "RUNNING"
        events = client.get("/api/runs/r_abandoned/events/history").json()["events"]
        assert events[-1]["stage"] == "done" and events[-1]["status"] == "failed"


def test_background_exception_is_terminal_and_does_not_expose_provider_details(root, monkeypatch):
    from factory.agents.records import Records

    sentinel = "fake-provider-secret-9382"
    monkeypatch.setenv("OPENAI_API_KEY", sentinel)
    called = threading.Event()

    def broken(*args, **kwargs):
        called.set()
        raise RuntimeError("SDK credentials " + sentinel)

    with client_for(root, runner=broken, poll_seconds=0.01) as client:
        created = client.post(
            "/api/runs", files={"pdf": ("paper.pdf", pdf_bytes(), "application/pdf")}
        )
        run_id = created.json()["run_id"]
        assert called.wait(5)
        stream = client.get(f"/api/runs/{run_id}/events")
        assert sentinel not in stream.text
        result = client.get(f"/api/runs/{run_id}").json()
        assert result["status"] == "FAILED" and result["error_type"] == "BackgroundRunError"
        assert sentinel not in json.dumps(result)
    with Records(root / "runs", read_only=True) as records:
        assert records.events(run_id)[-1]["stage"] == "done"


def test_upload_reuses_only_matching_verified_local_cache(root):
    import hashlib

    from factory.agents.records import Records

    papers = root / "papers"
    papers.mkdir()
    supplied = pdf_bytes()
    (papers / "approved.pdf").write_bytes(supplied)
    text = "# Owner-approved source text\n"
    (papers / "approved.md").write_text(text)
    metadata = {
        "source": {
            "sha256": hashlib.sha256(supplied).hexdigest(),
            "markdown_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "markdown_file": "approved.md",
            "pdf_file": "approved.pdf",
            "url": "https://example.com/approved-paper",
            "version_date": "2018",
        }
    }
    (papers / "approved.spec.json").write_text(json.dumps(metadata))
    original_sidecar = (papers / "approved.spec.json").read_bytes()
    observed = []

    def runner(paper, *, output_root, run_id, **kwargs):
        observed.append(
            (
                paper.with_suffix(".md").read_text(),
                json.loads(paper.with_suffix(".spec.json").read_text()),
            )
        )
        with Records(output_root / "runs") as records:
            row = records.get("runs", run_id)
            row["status"] = "COMPLETED"
            records.put("runs", run_id, run_id, row)
            records.event(run_id, "done", "passed", "Done", data={"status": "COMPLETED"})

    with client_for(root, runner=runner, poll_seconds=0.01) as client:
        run_id = client.post(
            "/api/runs", files={"pdf": ("copy.pdf", supplied, "application/pdf")}
        ).json()["run_id"]
        client.get(f"/api/runs/{run_id}/events")
    assert observed[0][0] == text
    assert observed[0][1]["source"]["url"] == metadata["source"]["url"]
    assert observed[0][1]["source"]["pdf_file"] == "paper.pdf"
    assert (papers / "approved.spec.json").read_bytes() == original_sidecar


def test_live_sse_follows_durable_events_and_stops_at_terminal(root):
    from factory.agents.records import Records

    with Records(root / "runs") as records:
        records.put("runs", "r_stream", "r_stream", {"run_id": "r_stream", "status": "RUNNING"})
        records.event("r_stream", "extract", "started", "Started")
    with client_for(root, poll_seconds=0.01, keepalive_seconds=0.05) as client:

        def finish():
            import time

            time.sleep(0.1)
            with Records(root / "runs") as records:
                records.event("r_stream", "extract", "passed", "Extracted")
                run = records.get("runs", "r_stream")
                run["status"] = "COMPLETED"
                records.put("runs", "r_stream", "r_stream", run)
                records.event(
                    "r_stream", "done", "passed", "Finished", data={"status": "COMPLETED"}
                )

        producer = threading.Thread(target=finish)
        producer.start()
        result = client.get("/api/runs/r_stream/events")
        producer.join(timeout=5)
        assert ": keepalive" in result.text
        events = [json.loads(x[6:]) for x in result.text.splitlines() if x.startswith("data: ")]
        assert [e["message"] for e in events] == ["Started", "Extracted", "Finished"]
        assert [e["seq"] for e in events] == sorted({e["seq"] for e in events})


def test_pdf_limit_and_no_text_pdf_are_rejected(root):
    import pymupdf

    with client_for(root) as client:
        document = pymupdf.open()
        document.new_page()
        blank = document.tobytes()
        document.close()
        assert (
            client.post(
                "/api/runs", files={"pdf": ("blank.pdf", blank, "application/pdf")}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/runs", files={"pdf": ("huge.pdf", b"x" * 30_000_001, "application/pdf")}
            ).status_code
            == 413
        )


def test_record_corruption_returns_safe_failure_without_input_echo(root, monkeypatch):
    import sqlite3

    sentinel = "fake-private-record-value-31ab"
    monkeypatch.setenv("OPENAI_API_KEY", sentinel)
    db = sqlite3.connect(root / "runs" / "factory.db")
    value = json.loads(
        db.execute("SELECT payload FROM variants WHERE id=?", ("r_live_A",)).fetchone()[0]
    )
    value["status"] = sentinel
    db.execute("UPDATE variants SET payload=? WHERE id=?", (json.dumps(value), "r_live_A"))
    db.commit()
    db.close()
    with client_for(root) as client:
        response = client.get("/api/variants/r_live_A")
        assert response.status_code == 500
        assert sentinel not in response.text
        assert "validated" in response.json()["detail"]


def test_run_artifact_inventory_alias_honors_run_visibility(root):
    with client_for(root) as client:
        response = client.get("/api/runs/r_live/artifacts")
        assert response.status_code == 200
        assert response.json() == client.get("/api/artifacts?run_id=r_live").json()
        assert client.get("/api/runs/missing/artifacts").status_code == 404
        assert client.get("/api/runs/r_void/artifacts").status_code == 404
        assert client.get("/api/runs/r_void/artifacts?include_voided=true").status_code == 200


def test_critic_remains_running_after_deterministic_lane_verdict(root):
    from factory.agents.records import Records

    with Records(root / "runs") as records:
        run = records.get("runs", "r_live")
        run["status"] = "RUNNING"
        records.put("runs", "r_live", "r_live", run)
        records.db.execute("DELETE FROM critiques WHERE run_id=?", ("r_live",))
        records.db.commit()
        records.event("r_live", "critic", "started", "Writing narrative", variant="A")
    with client_for(root) as client:
        detail = client.get("/api/variants/r_live_A").json()
        critic = next(s for s in detail["steps"] if s["kind"] == "critic")
        assert critic["state"] == "running"


def test_restart_adds_explicit_terminal_recovery_event_when_write_was_interrupted(root):
    from factory.agents.records import Records
    from factory.record_migration import utc_now

    with Records(root / "runs") as records:
        records.put(
            "runs",
            "r_terminal_gap",
            "r_terminal_gap",
            {
                "run_id": "r_terminal_gap",
                "status": "FAILED",
                "submission": {
                    "origin": "api",
                    "upload_name": "paper.pdf",
                    "upload_sha256": "c" * 64,
                    "input_path": "runs/uploads/r_terminal_gap/paper.pdf",
                    "accepted_at": utc_now(),
                },
            },
        )
    with client_for(root) as client:
        events = client.get("/api/runs/r_terminal_gap/events/history").json()["events"]
        assert len(events) == 1
        assert events[0]["stage"] == "done" and events[0]["status"] == "failed"
        assert "recovered" in events[0]["message"].lower()
        assert client.get("/api/runs/r_terminal_gap/events").status_code == 200


def test_terminal_replay_waits_for_tail_after_done(root):
    from factory.agents.records import Records
    from factory.api.runs import _event_page

    with Records(root / "runs") as records:
        done = records.events("r_live")[-1]["seq"]
        records.event("r_live", "critic", "info", "Later diagnostic retained")
    page = _event_page(root, "r_live", done - 1, 1, False)
    assert page[2] is False


def test_historical_terminal_without_done_closes_with_evidence_gap_comment(root):
    from factory.agents.records import Records

    with Records(root / "runs") as records:
        records.put("runs", "r_old_gap", "r_old_gap", {"run_id": "r_old_gap", "status": "FAILED"})
    with client_for(root, poll_seconds=0.01, terminal_grace_seconds=0.05) as client:
        result = client.get("/api/runs/r_old_gap/events")
        assert result.status_code == 200
        assert "no terminal event" in result.text.lower()
        assert "data:" not in result.text
