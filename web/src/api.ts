import type {
  Artifact,
  ArtifactView,
  Dataset,
  DatasetDetail,
  DatasetPreview,
  EvalProfile,
  EvalSchema,
  Event,
  GraveyardEntry,
  LeaderboardRow,
  ObjectData,
  Provider,
  RunDetail,
  RunSummary,
  Source,
  VariantDetail,
} from "./types";

type Query = Record<string, string | number | boolean | undefined>;
const url = (path: string, query: Query = {}) => {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([k, v]) => {
    if (v !== undefined && v !== "") params.set(k, String(v));
  });
  return `/api${path}${params.size ? `?${params}` : ""}`;
};
async function request<T>(
  path: string,
  query: Query = {},
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(url(path, query), init);
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(
      typeof data?.detail === "string"
        ? data.detail
        : `Request failed (${response.status}). Please try again.`,
    );
  }
  return response.json() as Promise<T>;
}
const id = encodeURIComponent;
export const api = {
  health: () =>
    request<{ status: string; capabilities: Record<string, boolean> }>(
      "/health",
    ),
  runs: (audit = false) =>
    request<{ runs: RunSummary[] }>("/runs", { include_voided: audit }),
  run: (runId: string, audit = false) =>
    request<RunDetail>(`/runs/${id(runId)}`, { include_voided: audit }),
  leaderboard: (query: Query = {}) =>
    request<{ rows: LeaderboardRow[] }>("/leaderboard", query),
  variant: (variantId: string, audit = false) =>
    request<VariantDetail>(`/variants/${id(variantId)}`, {
      include_voided: audit,
    }),
  graveyard: (audit = false) =>
    request<{ entries: GraveyardEntry[]; markdown: string }>("/graveyard", {
      include_voided: audit,
    }),
  sources: () => request<{ sources: Source[] }>("/sources"),
  source: (sourceId: string, audit = false) =>
    request<{ source: Source; artifacts: Artifact[] }>(
      `/sources/${id(sourceId)}`,
      { include_voided: audit },
    ),
  events: (runId: string, audit = false, afterSeq = 0) =>
    request<{ events: Event[]; next_seq: number }>(
      `/runs/${id(runId)}/events/history`,
      { include_voided: audit, after_seq: afterSeq, limit: 1000 },
    ),
  startRun: (file: File) => {
    const body = new FormData();
    body.append("pdf", file);
    return request<{ run_id: string }>("/runs", {}, { method: "POST", body });
  },
  artifacts: (audit = false, runId?: string) =>
    request<{ artifacts: Artifact[] }>("/artifacts", {
      include_voided: audit,
      run_id: runId,
    }),
  artifact: (artifactId: string, audit = false, offset = 0) =>
    request<ArtifactView>(`/artifacts/${id(artifactId)}`, {
      include_voided: audit,
      offset,
      limit: 30000,
    }),
  downloadUrl: (artifactId: string, audit = false) =>
    url(`/artifacts/${id(artifactId)}/download`, { include_voided: audit }),
  catalog: (scope = "main") =>
    request<{ datasets: Dataset[] }>("/data/catalog", { scope }),
  uploadEvents: (file: File, name: string, mapping: Record<string, string>) => {
    const body = new FormData();
    body.append("file", file);
    body.append("name", name);
    body.append("mapping", JSON.stringify(mapping));
    return request<Dataset>("/data/upload", {}, { method: "POST", body });
  },
  dataset: (datasetId: string) =>
    request<DatasetDetail>(`/data/datasets/${id(datasetId)}`),
  preview: (datasetId: string, split: "visible" | "IS" | "OOS" = "visible") =>
    request<DatasetPreview>(`/data/datasets/${id(datasetId)}/preview`, {
      split,
      limit: 500,
    }),
  providers: () => request<{ providers: Provider[] }>("/providers"),
  ingest: (scope = "main", offset = 0) =>
    request<{
      events: ObjectData[];
      total: number;
      next_offset: number | null;
    }>("/data/ingest-events", { scope, offset, limit: 50 }),
  audits: (audit = false) =>
    request<{ audit: ObjectData | null; artifacts: Artifact[] }>(
      "/data/audits",
      { include_voided: audit },
    ),
  contract: () =>
    request<{ schema_version: string; contract: ObjectData; markdown: string }>(
      "/data/contract",
    ),
  universe: () =>
    request<{ symbols: string[]; provenance: ObjectData; notes: string[] }>(
      "/data/universe",
    ),
  evals: () => request<EvalSchema>("/evals/schema"),
  profile: () => request<EvalProfile>("/evals/profiles/default"),
};

/** One stream per mounted run. Native EventSource resumes with Last-Event-ID.
 * Explicit cursor is also retained across effect restarts. Terminal done events
 * are already durable; refresh the record and close to avoid reconnect storms. */
export function subscribeRun(
  runId: string,
  audit: boolean,
  afterSeq: number,
  onEvent: (event: Event) => void,
  onState: (state: string) => void,
) {
  const stream = new EventSource(
    url(`/runs/${id(runId)}/events`, {
      include_voided: audit,
      after_seq: afterSeq,
    }),
  );
  let cursor = afterSeq;
  stream.onopen = () => onState("Live event stream");
  stream.onmessage = (message) => {
    try {
      const event = JSON.parse(message.data) as Event;
      if (event.seq <= cursor) return;
      cursor = event.seq;
      onEvent(event);
      if (event.stage === "done") {
        stream.close();
        onState("Run finished · events recorded");
      }
    } catch {
      onState("Could not read an event. Reload the run to retry.");
    }
  };
  stream.onerror = () =>
    onState("Connection interrupted · reconnecting from the last event");
  return () => stream.close();
}
