import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useResource } from "../hooks";
import type { Artifact } from "../types";
import { Chip, Empty, ErrorState, Loading, Notes } from "./common";

export function ArtifactLinks({
  artifacts,
  audit = false,
}: {
  artifacts: Artifact[];
  audit?: boolean;
}) {
  const [selected, setSelected] = useState<Artifact | null>(null);
  return (
    <>
      <div className="artifact-links">
        {artifacts.map((artifact) => (
          <button key={artifact.id} onClick={() => setSelected(artifact)}>
            {artifact.name}
          </button>
        ))}
      </div>
      {selected && (
        <ArtifactDialog
          artifact={selected}
          audit={audit}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  );
}
export function ArtifactDialog({
  artifact,
  audit,
  onClose,
}: {
  artifact: Artifact;
  audit: boolean;
  onClose: () => void;
}) {
  const [offset, setOffset] = useState(0);
  const resource = useResource(
    () => api.artifact(artifact.id, audit, offset),
    `${artifact.id}:${audit}:${offset}`,
  );
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    const previous = document.activeElement as HTMLElement | null;
    element?.showModal();
    return () => {
      element?.close();
      previous?.focus();
    };
  }, []);
  return (
    <div className="modal-backdrop">
      <dialog
        ref={dialog}
        className="artifact-dialog"
        aria-labelledby="artifact-title"
        onCancel={onClose}
      >
        <div className="row between">
          <h2 id="artifact-title" className="wrap">
            {artifact.name}
          </h2>
          <button onClick={onClose} aria-label="Close artifact preview">
            Close ×
          </button>
        </div>
        <div className="row">
          <Chip>{artifact.kind}</Chip>
          <span className="caption">
            {artifact.size_bytes.toLocaleString()} bytes · {artifact.media_type}
          </span>
          {artifact.historical && <Chip>Historical</Chip>}
          {artifact.audit_only && <Chip>Audit only</Chip>}
        </div>
        <Notes notes={artifact.notes} />
        {resource.error ? (
          <ErrorState
            message={resource.error}
            retry={() => void resource.reload()}
          />
        ) : resource.loading ? (
          <Loading label="Loading artifact preview…" />
        ) : resource.data?.content == null ? (
          <Empty>No text preview is available for this evidence.</Empty>
        ) : (
          <>
            <pre className="code" tabIndex={0}>
              {resource.data.content}
            </pre>
            <div className="pager">
              <button
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - 30000))}
              >
                Previous text
              </button>
              <span>
                Characters {offset.toLocaleString()}–
                {(offset + resource.data.content.length).toLocaleString()}
              </span>
              <button
                disabled={resource.data.next_offset == null}
                onClick={() => setOffset(resource.data!.next_offset!)}
              >
                Next text
              </button>
            </div>
          </>
        )}
        {artifact.downloadable && (
          <a className="button" href={api.downloadUrl(artifact.id, audit)}>
            Download attachment ↓
          </a>
        )}
        <p className="caption">
          Evidence is shown as text. Source documents and model output cannot
          execute in this view.
        </p>
      </dialog>
    </div>
  );
}
export function EvidenceBrowser({ audit = false }: { audit?: boolean }) {
  const resource = useResource(
    () => api.artifacts(audit),
    `artifacts:${audit}`,
  );
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<Artifact | null>(null);
  const artifacts = resource.data?.artifacts ?? [];
  const filtered = artifacts.filter(
    (a) =>
      (!kind || a.kind === kind) &&
      a.name.toLowerCase().includes(search.toLowerCase()),
  );
  const size = 20;
  const pages = Math.max(1, Math.ceil(filtered.length / size));
  const current = Math.min(page, pages - 1);
  return (
    <section className="stack evidence-browser">
      <div className="row between">
        <h2>Evidence browser</h2>
        <span className="caption">
          {resource.data
            ? `${artifacts.length.toLocaleString()} registered artifacts`
            : "Loading inventory…"}
        </span>
      </div>
      <p className="muted">
        Source documents, strategy code, manifests, historical audits and
        reports.
      </p>
      <div className="filters">
        <input
          aria-label="Search evidence"
          type="search"
          placeholder="Search artifact paths…"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(0);
          }}
        />
        <label>
          Kind
          <select
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
              setPage(0);
            }}
          >
            <option value="">All kinds</option>
            {[...new Set(artifacts.map((a) => a.kind))].sort().map((k) => (
              <option key={k}>{k}</option>
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
        <Loading />
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Evidence</th>
                  <th>Kind</th>
                  <th>Size</th>
                  <th>Context</th>
                </tr>
              </thead>
              <tbody>
                {filtered
                  .slice(current * size, (current + 1) * size)
                  .map((a) => (
                    <tr key={a.id}>
                      <td className="source-cell">
                        <button
                          className="text-button mono wrap"
                          onClick={() => setSelected(a)}
                        >
                          {a.name}
                        </button>
                        <Notes notes={a.notes} />
                      </td>
                      <td>
                        <Chip>{a.kind}</Chip>
                      </td>
                      <td className="mono">
                        {a.size_bytes.toLocaleString()} B
                      </td>
                      <td className="caption">
                        {a.historical ? "Historical · " : ""}
                        {a.audit_only ? "Audit · " : ""}
                        {a.run_ids.length
                          ? `${a.run_ids.length} run(s)`
                          : a.dataset_id
                            ? "Dataset"
                            : a.source_id
                              ? "Source"
                              : "Repository"}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
            {!filtered.length && (
              <Empty>No artifacts match these filters.</Empty>
            )}
          </div>
          <div className="pager">
            <button
              disabled={current === 0}
              onClick={() => setPage(current - 1)}
            >
              Previous
            </button>
            <span>
              {filtered.length} matches · page {current + 1} of {pages}
            </span>
            <button
              disabled={current + 1 >= pages}
              onClick={() => setPage(current + 1)}
            >
              Next
            </button>
          </div>
        </>
      )}
      {selected && (
        <ArtifactDialog
          artifact={selected}
          audit={audit}
          onClose={() => setSelected(null)}
        />
      )}
    </section>
  );
}
