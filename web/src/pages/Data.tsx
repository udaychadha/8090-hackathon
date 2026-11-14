import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { formatNumber, human, shortDate } from "../evidence";
import { useResource } from "../hooks";
import type { Dataset, Json, ObjectData } from "../types";
import { ArtifactLinks, EvidenceBrowser } from "../components/Artifacts";
import { DatasetChart } from "../components/Charts";
import {
  AuditToggle,
  Chip,
  Empty,
  ErrorState,
  JsonBlock,
  Loading,
  Notes,
  PageTitle,
  Prose,
  Unavailable,
} from "../components/common";

const tabs = [
  "Catalog",
  "Evidence",
  "Ingest log",
  "Audits",
  "Data contract",
  "Universe",
] as const;
type DataTab = (typeof tabs)[number];
type Scope = "main" | "smoke";
const count = (value: Json | undefined) =>
  typeof value === "number" ? value.toLocaleString() : "—";
const text = (value: Json | undefined) =>
  value == null
    ? "—"
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);

export function DataPage() {
  const [params, setParams] = useSearchParams();
  const requestedTab = params.get("tab");
  const tab: DataTab =
    tabs.find(
      (item) => item.toLowerCase().replaceAll(" ", "-") === requestedTab,
    ) ?? "Catalog";
  const scope: Scope = params.get("scope") === "smoke" ? "smoke" : "main";
  const audit = params.get("include_voided") === "true";
  function changeParam(key: string, value: string | null) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  }
  return (
    <>
      <PageTitle
        title="Data"
        aside={<Chip>Backtest only · no order placement</Chip>}
      />
      <div className="row between">
        <div className="tabs" role="tablist" aria-label="Data sections">
          {tabs.map((item) => (
            <button
              key={item}
              role="tab"
              aria-selected={tab === item}
              onClick={() =>
                changeParam(
                  "tab",
                  item === "Catalog"
                    ? null
                    : item.toLowerCase().replaceAll(" ", "-"),
                )
              }
            >
              {item}
            </button>
          ))}
        </div>
        {(tab === "Catalog" || tab === "Ingest log") && (
          <label className="caption">
            Scope
            <select
              aria-label="Dataset scope"
              value={scope}
              onChange={(event) =>
                changeParam(
                  "scope",
                  event.target.value === "main" ? null : "smoke",
                )
              }
            >
              <option value="main">Main datasets</option>
              <option value="smoke">Smoke datasets</option>
            </select>
          </label>
        )}
        {(tab === "Evidence" || tab === "Audits") && (
          <AuditToggle
            value={audit}
            onChange={(value) =>
              changeParam("include_voided", value ? "true" : null)
            }
          />
        )}
      </div>
      {scope === "smoke" && (tab === "Catalog" || tab === "Ingest log") && (
        <Notes
          notes={[
            "Smoke scope is a separate test dataset inventory. It is not the main research universe.",
          ]}
        />
      )}
      {tab === "Catalog" && <Catalog key={scope} scope={scope} audit={audit} />}
      {tab === "Evidence" && <EvidenceBrowser audit={audit} />}
      {tab === "Ingest log" && <IngestLog key={scope} scope={scope} />}
      {tab === "Audits" && <Audits audit={audit} />}
      {tab === "Data contract" && <DataContract />}
      {tab === "Universe" && <Universe />}
    </>
  );
}

function Catalog({ scope, audit }: { scope: Scope; audit: boolean }) {
  const resource = useResource(() => api.catalog(scope), `catalog:${scope}`);
  const [query, setQuery] = useState("");
  const [frequency, setFrequency] = useState("");
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const datasets = resource.data?.datasets ?? [];
  const filtered = datasets.filter(
    (dataset) =>
      (!frequency ||
        (frequency === "events"
          ? dataset.kind === "events"
          : dataset.frequency === frequency)) &&
      `${dataset.name} ${dataset.symbols.join(" ")} ${dataset.source}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const pageSize = 12;
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, pages - 1);
  const selected = datasets.find((dataset) => dataset.id === selectedId);
  const sharedNotes = datasets.length
    ? datasets[0].notes.filter((note) =>
        datasets.every((dataset) => dataset.notes.includes(note)),
      )
    : [];
  useEffect(() => {
    if (!selectedId && datasets.length)
      setSelectedId(
        (
          datasets.find(
            (dataset) =>
              dataset.symbols.includes("SPY") && dataset.frequency === "1min",
          ) ?? datasets[0]
        ).id,
      );
  }, [datasets, selectedId]);
  return (
    <>
      <div className="data-layout">
        <section className="stack">
          <div className="row between">
            <h2>Catalog</h2>
            <span className="caption">
              {resource.data
                ? `${datasets.length.toLocaleString()} ${scope} datasets on disk`
                : "Loading catalog…"}
            </span>
          </div>
          <div className="filters">
            <input
              aria-label="Search datasets"
              type="search"
              value={query}
              placeholder="Search symbol, dataset or source…"
              onChange={(event) => {
                setQuery(event.target.value);
                setPage(0);
              }}
            />
            <label>
              Tier
              <select
                aria-label="Dataset frequency"
                value={frequency}
                onChange={(event) => {
                  setFrequency(event.target.value);
                  setPage(0);
                }}
              >
                <option value="">All tiers</option>
                <option value="events">Events</option>
                {[
                  ...new Set(
                    datasets
                      .map((dataset) => dataset.frequency)
                      .filter(Boolean),
                  ),
                ]
                  .sort()
                  .map((value) => (
                    <option key={value} value={value!}>
                      {value}
                    </option>
                  ))}
              </select>
            </label>
          </div>
          {resource.error ? (
            <ErrorState
              message={resource.error}
              retry={() => void resource.reload()}
            />
          ) : resource.loading ? (
            <Loading label="Loading manifest-backed catalog…" />
          ) : (
            <>
              <Notes notes={sharedNotes} />
              <div className="table-wrap dataset-table">
                <table>
                  <thead>
                    <tr>
                      <th>Dataset</th>
                      <th>Kind / tier</th>
                      <th>Range</th>
                      <th>Source</th>
                      <th>Validation</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered
                      .slice(
                        currentPage * pageSize,
                        (currentPage + 1) * pageSize,
                      )
                      .map((dataset) => (
                        <tr
                          key={dataset.id}
                          className={
                            selectedId === dataset.id ? "selected" : ""
                          }
                        >
                          <td>
                            <button
                              className="text-button"
                              aria-pressed={selectedId === dataset.id}
                              onClick={() => setSelectedId(dataset.id)}
                            >
                              {dataset.name}
                            </button>
                            <p className="caption">
                              {dataset.symbols.join(", ")}
                            </p>
                            <Notes
                              notes={dataset.notes.filter(
                                (note) => !sharedNotes.includes(note),
                              )}
                            />
                          </td>
                          <td>
                            <Chip>{dataset.kind}</Chip>
                            <p className="caption">
                              {dataset.frequency ?? "—"}
                            </p>
                          </td>
                          <td className="mono dataset-range">
                            {shortDate(dataset.start)}
                            <br />
                            {shortDate(dataset.end)}
                          </td>
                          <td className="wrap">{dataset.source}</td>
                          <td>
                            <Chip>
                              {dataset.verified
                                ? "Validated"
                                : "Unverified source"}
                            </Chip>
                            <p className="caption">
                              {dataset.rows.toLocaleString()} rows
                            </p>
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
                {!filtered.length && (
                  <Empty>No datasets match these filters.</Empty>
                )}
              </div>
              <div className="pager">
                <button
                  disabled={currentPage === 0}
                  onClick={() => setPage(currentPage - 1)}
                >
                  Previous datasets
                </button>
                <span>
                  {filtered.length.toLocaleString()} matches · page{" "}
                  {currentPage + 1} of {pages}
                </span>
                <button
                  disabled={currentPage + 1 >= pages}
                  onClick={() => setPage(currentPage + 1)}
                >
                  Next datasets
                </button>
              </div>
            </>
          )}
        </section>
        {selected ? (
          <DatasetPanel key={selected.id} dataset={selected} audit={audit} />
        ) : (
          <section className="card dataset-preview">
            <span className="eyebrow">Preview</span>
            <Empty>
              {resource.loading
                ? "Loading datasets…"
                : "Select a dataset to inspect its visible observations."}
            </Empty>
          </section>
        )}
      </div>
      <div className="two-col">
        <div className="stack-lg">
          {scope === "main" && (
            <EventUpload
              onUploaded={async (dataset) => {
                await resource.reload();
                setSelectedId(dataset.id);
                setQuery("");
                setFrequency("events");
                setPage(0);
              }}
            />
          )}
          <Providers />
        </div>
        <section className="card">
          <div className="row between">
            <h2>Found sources</h2>
            <Chip>Finder</Chip>
          </div>
          <Empty>
            Public-source discovery is not available yet. No source candidates
            are recorded here.
          </Empty>
          <Unavailable label="Find / approve source" />
          <p className="notice">
            Online data is never downloaded or used until its specific source is
            approved in the interface.
          </p>
        </section>
      </div>
    </>
  );
}

export function EventUpload({
  onUploaded,
}: {
  onUploaded: (dataset: Dataset) => Promise<void>;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [availability, setAvailability] = useState("available_at");
  const [symbol, setSymbol] = useState("symbol");
  const [extraMapping, setExtraMapping] = useState("{}");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || busy) return;
    setError(null);
    setSuccess(null);
    if (file.size > 10 * 1024 * 1024) {
      setError("Event CSV exceeds 10 MiB.");
      return;
    }
    setBusy(true);
    try {
      const extra = JSON.parse(extraMapping);
      if (
        !extra ||
        typeof extra !== "object" ||
        Array.isArray(extra) ||
        Object.values(extra).some((value) => typeof value !== "string")
      ) {
        throw new Error(
          "Additional mappings must be a JSON object of destination names to CSV column names.",
        );
      }
      const dataset = await api.uploadEvents(file, name, {
        ...extra,
        available_at: availability,
        symbol,
      });
      await onUploaded(dataset);
      setSuccess(
        `Stored ${dataset.name}: ${dataset.rows.toLocaleString()} events. Unverified source.`,
      );
    } catch (error) {
      setError(error instanceof Error ? error.message : "Event upload failed.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card">
      <h2>Upload event CSV</h2>
      <form className="stack" onSubmit={(event) => void submit(event)}>
        <label className="upload-zone">
          Event CSV · UTF-8 · maximum 10 MiB
          <input
            aria-label="Event CSV file"
            type="file"
            accept=".csv,text/csv"
            required
            disabled={busy}
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setSuccess(null);
            }}
          />
        </label>
        <label>
          Dataset name
          <input
            aria-label="Event dataset name"
            required
            pattern="[A-Za-z][A-Za-z0-9_]{0,127}"
            value={name}
            disabled={busy}
            onChange={(event) => setName(event.target.value)}
            placeholder="my_events"
          />
        </label>
        <label>
          Availability column
          <input
            aria-label="Availability column"
            required
            value={availability}
            disabled={busy}
            onChange={(event) => setAvailability(event.target.value)}
          />
        </label>
        <label>
          Symbol column
          <input
            aria-label="Symbol column"
            required
            value={symbol}
            disabled={busy}
            onChange={(event) => setSymbol(event.target.value)}
          />
        </label>
        <details>
          <summary>Additional column mappings</summary>
          <p className="caption">
            Optional JSON: destination field to CSV column. Unmapped scalar
            fields are preserved; field names must use letters, digits and
            underscores.
          </p>
          <textarea
            aria-label="Additional column mappings"
            value={extraMapping}
            disabled={busy}
            onChange={(event) => setExtraMapping(event.target.value)}
          />
        </details>
        <p className="muted">
          available_at must include time and timezone, for example
          2024-06-03T14:00:00Z. A transaction date does not establish
          availability. Existing names cannot be overwritten.
        </p>
        <button type="submit" disabled={busy || !file || !name}>
          {busy ? "Validating and saving…" : "Upload event data"}
        </button>
        {error && (
          <p role="alert" className="notice">
            {error}
          </p>
        )}
        {success && <p role="status">{success}</p>}
      </form>
    </section>
  );
}

function DatasetPanel({
  dataset,
  audit,
}: {
  dataset: Dataset;
  audit: boolean;
}) {
  const [split, setSplit] = useState<"visible" | "IS" | "OOS">("visible");
  const detail = useResource(
    () => api.dataset(dataset.id),
    `dataset:${dataset.id}`,
  );
  const preview = useResource(
    () => api.preview(dataset.id, split),
    `preview:${dataset.id}:${split}`,
  );
  const coverage = preview.data?.coverage;
  return (
    <section className="card dataset-preview">
      <span className="eyebrow">Preview</span>
      <h2>{dataset.name}</h2>
      <div className="inline-meta">
        <Chip>{dataset.kind}</Chip>
        <Chip>{dataset.feed}</Chip>
        <Chip>{dataset.verified ? "Validated" : "Unverified source"}</Chip>
      </div>
      <Notes notes={dataset.notes} />
      <label className="caption">
        Visible split
        <select
          aria-label="Preview split"
          value={split}
          onChange={(event) =>
            setSplit(event.target.value as "visible" | "IS" | "OOS")
          }
        >
          <option value="visible">IS + OOS</option>
          <option value="IS">IS only</option>
          <option value="OOS">OOS only</option>
        </select>
      </label>
      {preview.error ? (
        <ErrorState
          message={preview.error}
          retry={() => void preview.reload()}
        />
      ) : preview.loading ? (
        <Loading label="Validating and loading visible observations…" />
      ) : (
        preview.data && (
          <>
            {dataset.kind === "events" ? (
              <div className="table-wrap">
                {preview.data.rows.length ? (
                  <table>
                    <thead>
                      <tr>
                        {Object.keys(preview.data.rows[0]).map((key) => (
                          <th key={key}>{key}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {preview.data.rows.map((row, index) => (
                        <tr key={index}>
                          {Object.keys(preview.data!.rows[0]).map((key) => (
                            <td className="mono" key={key}>
                              {text(row[key])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <Empty>No events are available in this split.</Empty>
                )}
              </div>
            ) : (
              <DatasetChart preview={preview.data} title={dataset.name} />
            )}
            <p className="caption">
              {preview.data.rows.length}{" "}
              {preview.data.downsampled ? "downsampled" : "retained"}{" "}
              observations shown. HOLDOUT is sealed; no HOLDOUT observations are
              returned.
            </p>
            <div className="spec-field">
              <span className="eyebrow">Selected coverage</span>
              <p className="mono">
                {shortDate(text(coverage?.start))} →{" "}
                {shortDate(text(coverage?.end))}
              </p>
              <div className="row between">
                <span>Observed rows</span>
                <span className="mono">{count(coverage?.observed_rows)}</span>
              </div>
              {dataset.kind === "price_bars" && (
                <>
                  <div className="row between">
                    <span>Expected rows</span>
                    <span className="mono">
                      {count(coverage?.expected_rows)}
                    </span>
                  </div>
                  <div className="row between">
                    <span>Missing rows</span>
                    <span className="mono">
                      {count(coverage?.missing_rows)}
                    </span>
                  </div>
                  <div className="row between">
                    <span>Locally filled rows</span>
                    <span className="mono">{count(coverage?.filled_rows)}</span>
                  </div>
                  <p className="caption">
                    Denominator: {text(coverage?.fill_rate_denominator)}.
                  </p>
                </>
              )}
              {dataset.kind === "events" && (
                <p className="caption">
                  Availability is determined by available_at. Events have no
                  expected price grid or inferred gaps.
                </p>
              )}
            </div>
            {dataset.kind === "price_bars" && (
              <details>
                <summary>
                  Gap intervals ({preview.data.total_gaps.toLocaleString()})
                </summary>
                {preview.data.gaps.length ? (
                  <>
                    <p className="caption">
                      Showing {preview.data.gaps.length.toLocaleString()} of{" "}
                      {preview.data.total_gaps.toLocaleString()} recorded
                      intervals in this split.
                    </p>
                    <JsonBlock value={preview.data.gaps} />
                  </>
                ) : (
                  <p className="muted">
                    No missing intervals in the selected session grid.
                  </p>
                )}
              </details>
            )}
            <details>
              <summary>
                Visible observation rows ({preview.data.rows.length})
              </summary>
              <JsonBlock value={preview.data.rows} />
            </details>
          </>
        )
      )}
      <div className="spec-field">
        <span className="eyebrow">Stored file</span>
        <p className="mono">
          {dataset.rows.toLocaleString()} rows · {dataset.adjustment} adjustment
        </p>
        {dataset.kind === "price_bars" && (
          <p className="muted">
            Locally filled rows / full expected session grid:{" "}
            {formatNumber(dataset.fill_rate * 100, 4)}%.
          </p>
        )}
        <p className="caption">
          Schema {dataset.schema_version} · {dataset.source}
        </p>
      </div>
      {detail.error ? (
        <ErrorState message={detail.error} retry={() => void detail.reload()} />
      ) : detail.loading ? (
        <Loading label="Loading dataset provenance…" />
      ) : (
        detail.data && (
          <>
            <details>
              <summary>Split boundaries · HOLDOUT sealed</summary>
              <JsonBlock value={detail.data.splits} />
            </details>
            <details>
              <summary>Manifest and fingerprint</summary>
              <JsonBlock value={detail.data.manifest} />
            </details>
            <details>
              <summary>Ingest metadata</summary>
              <JsonBlock value={detail.data.metadata} />
            </details>
            <details>
              <summary>Canonical fields and units</summary>
              <Fields fields={detail.data.fields} />
            </details>
            <div className="spec-field">
              <span className="eyebrow">Dataset evidence</span>
              <ArtifactLinks artifacts={detail.data.artifacts} audit={audit} />
            </div>
          </>
        )
      )}
    </section>
  );
}

function Fields({ fields }: { fields: ObjectData }) {
  return (
    <div className="stack">
      {Object.entries(fields).map(([name, value]) => {
        const field =
          value && typeof value === "object" && !Array.isArray(value)
            ? value
            : {};
        return (
          <div className="spec-field" key={name}>
            <strong className="mono">{name}</strong>
            <span className="caption">
              {text(field.dtype)} · {text(field.units)}
            </span>
            <p>{text(field.meaning ?? field.description)}</p>
            <details>
              <summary>Field constraints</summary>
              <JsonBlock value={value} />
            </details>
          </div>
        );
      })}
    </div>
  );
}

function Providers() {
  const resource = useResource(api.providers, "providers");
  return (
    <section className="card">
      <h2>Providers</h2>
      {resource.error ? (
        <ErrorState
          message={resource.error}
          retry={() => void resource.reload()}
        />
      ) : resource.loading ? (
        <Loading label="Reading provider configuration…" />
      ) : (
        resource.data?.providers.map((provider) => (
          <div className="spec-field" key={provider.name}>
            <div className="row between">
              <strong>{provider.name}</strong>
              <Chip>
                {provider.connected ? "Key configured" : "No key configured"}
              </Chip>
            </div>
            <p className="caption">{provider.covers.map(human).join(" · ")}</p>
            <Unavailable label="Add / update key" />
          </div>
        ))
      )}
      <p className="muted">
        Status reports server-side environment-key presence only. Provider
        connectivity has not been tested. Key values are never shown.
      </p>
    </section>
  );
}

function IngestLog({ scope }: { scope: Scope }) {
  const [offset, setOffset] = useState(0);
  const resource = useResource(
    () => api.ingest(scope, offset),
    `ingest:${scope}:${offset}`,
  );
  return (
    <section className="stack">
      <div className="row between">
        <h2>Ingest log</h2>
        <span className="caption">Original ingest event schema · {scope}</span>
      </div>
      <p className="muted">
        Retained ingest events are shown as recorded, separate from strategy-run
        events.
      </p>
      {resource.error ? (
        <ErrorState
          message={resource.error}
          retry={() => void resource.reload()}
        />
      ) : resource.loading ? (
        <Loading label="Loading ingest events…" />
      ) : (
        resource.data && (
          <>
            <div className="card">
              {resource.data.events.length ? (
                resource.data.events.map((event, index) => (
                  <details key={offset + index}>
                    <summary>
                      <span className="mono">#{offset + index + 1}</span>　
                      {text(
                        event.symbol ??
                          event.stage ??
                          event.event ??
                          event.status ??
                          "Recorded event",
                      )}
                      　
                      <span className="caption">
                        {text(event.ts ?? event.timestamp ?? event.started_at)}
                      </span>
                    </summary>
                    <JsonBlock value={event} />
                  </details>
                ))
              ) : (
                <Empty>No retained ingest events in this scope.</Empty>
              )}
            </div>
            <div className="pager">
              <button
                disabled={!offset}
                onClick={() => setOffset(Math.max(0, offset - 50))}
              >
                Previous events
              </button>
              <span>
                {resource.data.total.toLocaleString()} total ·{" "}
                {resource.data.events.length
                  ? `${offset + 1}–${offset + resource.data.events.length}`
                  : "0"}{" "}
                shown
              </span>
              <button
                disabled={resource.data.next_offset == null}
                onClick={() => setOffset(resource.data!.next_offset!)}
              >
                Next events
              </button>
            </div>
          </>
        )
      )}
    </section>
  );
}

function Audits({ audit }: { audit: boolean }) {
  const resource = useResource(() => api.audits(audit), `audits:${audit}`);
  return (
    <section className="stack">
      <h2>Historical audits</h2>
      <p className="muted">
        These are retained audit results, not a new audit of current files.
      </p>
      {resource.error ? (
        <ErrorState
          message={resource.error}
          retry={() => void resource.reload()}
        />
      ) : resource.loading ? (
        <Loading label="Loading historical audits…" />
      ) : (
        resource.data && (
          <>
            <section className="card">
              <h3>Data audit</h3>
              {resource.data.audit ? (
                <>
                  <div className="row">
                    <Chip>Historical</Chip>
                    <span className="caption">
                      Observed file timestamp:{" "}
                      {text(resource.data.audit.observed_file_mtime)}
                    </span>
                  </div>
                  <p>
                    Fill-rate denominator:{" "}
                    {text(resource.data.audit.fill_rate_denominator)}.
                  </p>
                  <JsonBlock value={resource.data.audit} />
                </>
              ) : (
                <Empty>No retained audit summary is available.</Empty>
              )}
            </section>
            <section className="card">
              <h3>Related evidence</h3>
              {resource.data.artifacts.length ? (
                <ArtifactLinks
                  artifacts={resource.data.artifacts}
                  audit={audit}
                />
              ) : (
                <Empty>No related audit artifacts were retained.</Empty>
              )}
            </section>
          </>
        )
      )}
    </section>
  );
}

function DataContract() {
  const resource = useResource(api.contract, "data-contract");
  return (
    <section className="stack">
      <h2>Market data and strategy-time contract</h2>
      {resource.error ? (
        <ErrorState
          message={resource.error}
          retry={() => void resource.reload()}
        />
      ) : resource.loading ? (
        <Loading label="Loading canonical data contract…" />
      ) : (
        resource.data && (
          <section className="card">
            <div className="row">
              <Chip>Schema {resource.data.schema_version}</Chip>
              <Chip>Generated reference</Chip>
            </div>
            <Prose text={resource.data.markdown} />
            <details>
              <summary>Canonical machine-readable contract</summary>
              <JsonBlock value={resource.data.contract} />
            </details>
          </section>
        )
      )}
    </section>
  );
}

function Universe() {
  const resource = useResource(api.universe, "data-universe");
  return (
    <section className="stack">
      <h2>Universe snapshot</h2>
      {resource.error ? (
        <ErrorState
          message={resource.error}
          retry={() => void resource.reload()}
        />
      ) : resource.loading ? (
        <Loading label="Loading retained universe membership…" />
      ) : (
        resource.data && (
          <>
            <Notes notes={resource.data.notes} />
            <section className="card">
              <div className="row between">
                <h3>Current membership snapshot</h3>
                <span className="caption">
                  {resource.data.symbols.length.toLocaleString()} symbols
                </span>
              </div>
              <div className="symbol-list">
                {resource.data.symbols.map((symbol) => (
                  <Chip key={symbol}>{symbol}</Chip>
                ))}
              </div>
            </section>
            <section className="card">
              <h3>Source provenance</h3>
              <JsonBlock value={resource.data.provenance} />
            </section>
          </>
        )
      )}
    </section>
  );
}
