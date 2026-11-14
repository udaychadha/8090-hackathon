import { useEffect, useRef, useState } from "react";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { api, subscribeRun } from "../api";
import {
  auditSuffix,
  formatDate,
  formatNumber,
  isTerminal,
  laneNames,
  mergeEvents,
} from "../evidence";
import { useResource } from "../hooks";
import type { Event, RunSummary } from "../types";
import { ArtifactLinks } from "../components/Artifacts";
import {
  AuditToggle,
  Chip,
  DataNeedRow,
  Empty,
  ErrorState,
  JsonBlock,
  Loading,
  LogList,
  Notes,
  PageTitle,
  SpecPanel,
  Stat,
  StatusPill,
  StepPipeline,
  Unavailable,
  VariantCard,
  VariantStatus,
} from "../components/common";

export function RunPage() {
  const { runId } = useParams();
  const [params, setParams] = useSearchParams();
  const audit = params.get("include_voided") === "true";
  const navigate = useNavigate();
  const history = useResource(() => api.runs(audit), `runs:${audit}`);
  if (!runId)
    return (
      <>
        <PageTitle
          title="Runs"
          aside={
            <Link className="button primary" to="/new">
              ＋ New run
            </Link>
          }
        />
        <div className="row between">
          <p className="muted">
            Retained factory runs. Reopen any run to inspect its recorded
            evidence.
          </p>
          <AuditToggle
            value={audit}
            onChange={(value) =>
              setParams(value ? { include_voided: "true" } : {})
            }
          />
        </div>
        {history.loading ? (
          <Loading />
        ) : history.error ? (
          <ErrorState
            message={history.error}
            retry={() => void history.reload()}
          />
        ) : history.data?.runs.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Run / source</th>
                  <th>Started</th>
                  <th>Status</th>
                  <th>Variants</th>
                  <th>Time / model cost</th>
                </tr>
              </thead>
              <tbody>
                {history.data.runs.map((run) => (
                  <tr key={run.run_id}>
                    <td className="source-cell">
                      <Link to={`/runs/${run.run_id}${auditSuffix(audit)}`}>
                        {run.source?.title ??
                          run.submission?.upload_name ??
                          "Extraction did not produce a source"}
                      </Link>
                      <p className="caption">{run.run_id}</p>
                      {run.error && <p className="failed-text">{run.error}</p>}
                      <Notes
                        notes={[
                          ...new Set(run.variants.flatMap((v) => v.notes)),
                          ...(run.void_reason ? [run.void_reason] : []),
                        ]}
                      />
                    </td>
                    <td className="caption">{formatDate(run.started_at)}</td>
                    <td>
                      <StatusPill status={run.status} />
                    </td>
                    <td>
                      <div className="stack">
                        {run.variants.map((v) => (
                          <Link
                            key={v.variant_id}
                            to={`/variants/${v.variant_id}${auditSuffix(audit)}`}
                            className="row"
                          >
                            <Chip>
                              {v.variant} · {v.test_type} · {v.evals_passed}/5
                            </Chip>
                            <StatusPill status={v.status} />
                          </Link>
                        ))}
                        {!run.variants.length && (
                          <span className="muted">None produced</span>
                        )}
                      </div>
                    </td>
                    <td className="mono">
                      {formatNumber(run.wall_seconds, 1)} s<br />
                      {run.estimated_model_cost_usd == null
                        ? "—"
                        : `$${formatNumber(run.estimated_model_cost_usd, 4)}`}
                      <p className="caption">
                        {run.cost_complete === false
                          ? "Incomplete cost estimate"
                          : run.cost_complete === true
                            ? "Estimated model cost"
                            : "Cost completeness unknown"}
                      </p>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>No recorded runs yet. Upload a paper to start.</Empty>
        )}
      </>
    );
  return (
    <RunDetailPage
      key={`${runId}:${audit}`}
      runId={runId}
      audit={audit}
      onAudit={(value) => setParams(value ? { include_voided: "true" } : {})}
      selectRun={(id) => navigate(`/runs/${id}${auditSuffix(audit)}`)}
      runs={history.data?.runs ?? []}
    />
  );
}

function RunDetailPage({
  runId,
  audit,
  onAudit,
  selectRun,
  runs,
}: {
  runId: string;
  audit: boolean;
  onAudit: (v: boolean) => void;
  selectRun: (id: string) => void;
  runs: Pick<RunSummary, "run_id" | "source" | "submission">[];
}) {
  const resource = useResource(
    () => api.run(runId, audit),
    `${runId}:${audit}`,
  );
  const [events, setEvents] = useState<Event[]>([]);
  const [eventError, setEventError] = useState<string | null>(null);
  const [streamState, setStreamState] = useState("Loading event history…");
  const [lane, setLane] = useState("overview");
  const cursor = useRef(0);
  const refresh = useRef<ReturnType<typeof setTimeout> | null>(null);
  const run = resource.data;
  const active = run ? !isTerminal(run.status) : false;
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        let after = 0;
        for (;;) {
          const page = await api.events(runId, audit, after);
          if (cancelled) return;
          setEvents((previous) => mergeEvents(previous, page.events));
          if (page.events.length)
            cursor.current = Math.max(
              cursor.current,
              ...page.events.map((e) => e.seq),
            );
          if (page.events.length < 1000 || page.next_seq <= after) break;
          after = page.next_seq;
        }
        setStreamState("Recorded event history");
      } catch (e) {
        if (!cancelled)
          setEventError(
            e instanceof Error ? e.message : "Event history unavailable",
          );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runId, audit]);
  useEffect(() => {
    if (!active) return;
    const close = subscribeRun(
      runId,
      audit,
      cursor.current,
      (event) => {
        cursor.current = Math.max(cursor.current, event.seq);
        setEvents((previous) => mergeEvents(previous, [event]));
        if (refresh.current) clearTimeout(refresh.current);
        refresh.current = setTimeout(
          () => void resource.reload(true),
          event.stage === "done" ? 0 : 350,
        );
        if (event.stage === "done")
          void api
            .events(runId, audit, event.seq)
            .then((tail) =>
              setEvents((previous) => mergeEvents(previous, tail.events)),
            )
            .catch(() =>
              setEventError(
                "The final event tail could not be read. Reload to retry.",
              ),
            );
      },
      setStreamState,
    );
    const interval = setInterval(() => void resource.reload(true), 12000);
    return () => {
      close();
      clearInterval(interval);
      if (refresh.current) clearTimeout(refresh.current);
    };
  }, [runId, audit, active, resource.reload]);
  if (resource.loading && !run) return <Loading label="Loading run…" />;
  if (!run)
    return (
      <ErrorState
        message={resource.error ?? "Run not found."}
        retry={() => void resource.reload()}
      />
    );
  const selected = run.variants.find((v) => v.variant === lane);
  const sourceArtifacts = run.artifacts.filter(
    (a) =>
      a.source_id === run.source?.source_id &&
      ["paper_pdf", "paper_text", "source_spec"].includes(a.kind),
  );
  return (
    <>
      <PageTitle
        title={`Run ${run.run_id}`}
        aside={<StatusPill status={run.status} />}
      >
        <span className="caption">
          {run.source?.title ??
            run.submission?.upload_name ??
            "No source extracted"}
        </span>
      </PageTitle>
      <div className="row between">
        <div className="row">
          <Link className="caption" to={`/runs${auditSuffix(audit)}`}>
            ← Run history
          </Link>
          <label className="caption run-selector">
            Open run
            <select
              aria-label="Open run"
              value={runId}
              onChange={(e) => selectRun(e.target.value)}
            >
              {/* The current detail keeps changing during extraction; history
                  may still contain the original source-less reservation. */}
              {[run, ...runs.filter((r) => r.run_id !== runId)].map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.run_id} ·{" "}
                  {r.source?.title ??
                    r.submission?.upload_name ??
                    "No extracted source"}
                </option>
              ))}
            </select>
          </label>
        </div>
        <AuditToggle value={audit} onChange={onAudit} />
      </div>
      {resource.error && (
        <ErrorState
          message={resource.error}
          retry={() => void resource.reload()}
        />
      )}
      <Notes
        notes={[
          ...(run.void_reason ? [run.void_reason] : []),
          ...(run.error
            ? [`${run.error_type ?? "Run failure"}: ${run.error}`]
            : []),
        ]}
      />
      <div className="run-layout">
        <aside className="stack">
          <SpecPanel source={run.source}>
            <ArtifactLinks artifacts={sourceArtifacts} audit={audit} />
          </SpecPanel>
          <section className="card">
            <span className="eyebrow">Data needs</span>
            {run.data_needs.length ? (
              run.data_needs.map((need) => (
                <DataNeedRow key={need.id} need={need} />
              ))
            ) : (
              <p className="muted">No data needs were recorded.</p>
            )}
          </section>
        </aside>
        <div className="stack">
          <div className="run-tabs" role="tablist" aria-label="Variant lanes">
            <button
              role="tab"
              aria-selected={lane === "overview"}
              onClick={() => setLane("overview")}
            >
              <strong>Overview</strong>
              <span className="caption">All recorded variants</span>
              <span className="mono">
                {run.variants.length} variants ·{" "}
                {run.variants.filter((v) => v.status === "VERIFIED").length}{" "}
                verified
              </span>
            </button>
            {["A", "B", "C"].map((letter) => {
              const v = run.variants.find((v) => v.variant === letter);
              return (
                <button
                  key={letter}
                  role="tab"
                  aria-selected={lane === letter}
                  onClick={() => setLane(letter)}
                >
                  <strong>
                    {letter}　{laneNames[letter]}
                  </strong>
                  {v ? (
                    <>
                      <span className="caption">
                        {v.test_type} · {v.evals_passed}/5
                      </span>
                      <VariantStatus variant={v} parentStatus={run.status} />
                    </>
                  ) : (
                    <span className="caption">
                      {active ? "Not produced yet" : "Not produced"}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
          {lane === "overview" ? (
            <>
              {run.variants.map((v) => (
                <VariantCard
                  key={v.variant_id}
                  variant={v}
                  parentStatus={run.status}
                  audit={audit}
                  onSelect={() => setLane(v.variant)}
                />
              ))}
              {!run.variants.length && (
                <section className="card">
                  <h2>
                    {active
                      ? "The factory is working"
                      : "No variants were produced"}
                  </h2>
                  <p>
                    {active
                      ? "Extraction and data checks appear below as they are recorded."
                      : "The retained errors and events below explain where the run stopped."}
                  </p>
                </section>
              )}
              <p className="caption">
                One idea, three implementations. Each dot is one of the five
                evals, in order. Only recorded harness results establish a pass
                or failure.
              </p>
              {run.steps.length > 0 && (
                <section className="card">
                  <h2>Shared pipeline</h2>
                  <StepPipeline steps={run.steps} />
                </section>
              )}
            </>
          ) : selected ? (
            <>
              <VariantCard
                variant={selected}
                parentStatus={run.status}
                audit={audit}
              />
              <section className="card">
                <h2>{laneNames[selected.variant]} · steps &amp; repairs</h2>
                <p className="muted">
                  Bug-only repairs are bounded to three attempts. Performance
                  failures are final.
                </p>
                <StepPipeline steps={selected.steps} />
              </section>
            </>
          ) : (
            <Empty>This variant has not been produced.</Empty>
          )}
          <div className="stats">
            <Stat
              label="Wall time"
              value={
                run.wall_seconds == null
                  ? "—"
                  : `${formatNumber(run.wall_seconds, 1)} s`
              }
            />
            <Stat
              label="Model cost"
              value={
                run.estimated_model_cost_usd == null
                  ? "—"
                  : `$${formatNumber(run.estimated_model_cost_usd, 4)}`
              }
              detail={
                run.cost_complete === false
                  ? "Incomplete estimate"
                  : run.cost_complete === true
                    ? "Complete estimate"
                    : "Not recorded"
              }
            />
            <Stat
              label="Started"
              value={<span className="mono">{formatDate(run.started_at)}</span>}
            />
            <Stat
              label="Created"
              value={<span className="mono">{formatDate(run.created_at)}</span>}
            />
          </div>
          <section className="card">
            <div className="row between">
              <h2>Event log</h2>
              <span className="caption">
                {active ? streamState : "Recorded history · run terminated"}
              </span>
            </div>
            {eventError && <ErrorState message={eventError} />}
            {events.length > 0 && (
              <p className="notice">
                <span className="eyebrow">
                  Latest event · #{events.at(-1)!.seq}
                </span>
                <br />
                {events.at(-1)!.message}
              </p>
            )}
            <div
              className="log-scroll"
              tabIndex={0}
              aria-label="Recorded run events"
            >
              <LogList
                events={
                  lane === "overview"
                    ? events
                    : events.filter(
                        (e) => e.variant === lane || e.variant == null,
                      )
                }
              />
            </div>
          </section>
          {run.extraction_diagnostics.length > 0 && (
            <section className="card">
              <h2>Extraction diagnostics</h2>
              <JsonBlock value={run.extraction_diagnostics} />
            </section>
          )}
          <section className="card">
            <h2>Retained evidence</h2>
            <ArtifactLinks artifacts={run.artifacts} audit={audit} />
            {!run.artifacts.length && (
              <Empty>No related artifacts recorded.</Empty>
            )}
            <details>
              <summary>Model usage ({run.usage.length} records)</summary>
              <JsonBlock value={run.usage} />
            </details>
          </section>
        </div>
      </div>
    </>
  );
}

export function NewRunPage() {
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const navigate = useNavigate();
  function selectFile(candidate: File | undefined) {
    setError(null);
    if (!candidate) return;
    if (!candidate.name.toLowerCase().endsWith(".pdf")) {
      setError("Choose a PDF file.");
      setFile(null);
      return;
    }
    if (candidate.size > 30_000_000) {
      setError("The PDF must be 30 MB or smaller.");
      setFile(null);
      return;
    }
    setFile(candidate);
  }
  async function submit() {
    if (!file || busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.startRun(file);
      navigate(`/runs/${result.run_id}`);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "The run could not be started.",
      );
      setBusy(false);
    }
  }
  return (
    <>
      <PageTitle title="New run" />
      <div className="flow-strip" aria-label="Factory flow">
        <div className="current">
          <span className="mono">01</span> Idea
        </div>
        <div>
          <span className="mono">02</span> Extract
        </div>
        <div>
          <span className="mono">03</span> Data check
        </div>
        <div>
          <span className="mono">04</span> Three workers
        </div>
        <div>
          <span className="mono">05</span> Deterministic evals
        </div>
      </div>
      <div className="two-col">
        <section className="card">
          <div className="row between">
            <h2>Upload a paper</h2>
            <Chip>Paper</Chip>
          </div>
          <div
            className={`upload-zone ${dragging ? "dragging" : ""}`}
            onDragOver={(event) => {
              event.preventDefault();
              if (!busy) setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              if (!busy) selectFile(event.dataTransfer.files[0]);
            }}
          >
            <span aria-hidden="true">↥</span>
            <strong>Drag a PDF here</strong>
            <label className="screen-reader-only" htmlFor="paper-upload">
              Choose paper PDF
            </label>
            <input
              id="paper-upload"
              className="file-input"
              type="file"
              accept="application/pdf,.pdf"
              disabled={busy}
              onChange={(event) => selectFile(event.target.files?.[0])}
            />
            <span className="caption">Text-based PDF · up to 30 MB</span>
          </div>
          {file && (
            <div className="notice">
              <strong>{file.name}</strong>
              <p className="caption">
                {(file.size / 1_000_000).toFixed(2)} MB selected
              </p>
            </div>
          )}
          {error && <ErrorState message={error} />}
          <p className="muted">
            The extractor reads your paper into a strategy spec. Three workers
            implement it, and the same deterministic harness judges every
            variant.
          </p>
          <div className="spec-field">
            <span className="eyebrow">Extract · LLM</span>
            <ul>
              <li>PDF text → recorded strategy specification</li>
              <li>Claimed metrics read from the source</li>
              <li>Ambiguities retained for inspection</li>
            </ul>
          </div>
          <button
            className="primary"
            disabled={!file || busy}
            onClick={() => void submit()}
          >
            {busy ? "Starting real run…" : "▷ Test in arena"}
          </button>
          <p className="caption">
            Starting a run uses the configured server-side models. You will
            follow extraction, workers and evals on the Run screen.
          </p>
        </section>
        <section className="card">
          <div className="row between">
            <h2>Describe a strategy</h2>
            <Chip>Original</Chip>
          </div>
          <textarea
            aria-label="Describe a strategy"
            disabled
            placeholder="Describe an idea in plain English…"
          />
          <Unavailable label="Send" />
          <p className="muted">
            English intake and follow-up questions are not available yet.
          </p>
          <div className="spec-field">
            <span className="eyebrow">One research path</span>
            <p>
              Once implemented, described ideas will enter the same data check,
              three-worker pipeline and deterministic evals.
            </p>
          </div>
        </section>
        <section className="card">
          <div className="row between">
            <h2>Review spec</h2>
            <Chip>After extraction</Chip>
          </div>
          <p className="muted">
            The recorded spec appears on the Run screen after extraction. No
            spec has been generated for this submission yet.
          </p>
          <Unavailable label="Edit / approve spec" />
        </section>
        <section className="card">
          <h2>Data needs</h2>
          <p className="muted">
            Requirements are checked after extraction. Existing market data can
            be inspected in the catalog.
          </p>
          <Link className="button" to="/data">
            Manage data →
          </Link>
          <p className="caption">
            External-source approval, provider-key entry and event uploads are
            not available yet.
          </p>
        </section>
      </div>
    </>
  );
}
