import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import Markdown from "react-markdown";
import {
  auditSuffix,
  formatNumber,
  human,
  isTerminal,
  laneDescriptions,
  laneNames,
} from "../evidence";
import type { DataNeed, Event, Source, Step, VariantRun } from "../types";

export function StatusPill({ status }: { status: string }) {
  const tone =
    status === "VERIFIED"
      ? "verified"
      : status.startsWith("FAILED") ||
          status === "BUG_UNRESOLVED" ||
          status === "INACTIVE"
        ? "failed"
        : status === "RUNNING"
          ? "running"
          : "";
  return <span className={`pill status ${tone}`}>{status}</span>;
}
export function Chip({ children }: { children: ReactNode }) {
  return <span className="pill">{children}</span>;
}
export function Notes({ notes }: { notes: string[] }) {
  return notes.length ? (
    <div className="notes">
      {notes.map((note, index) => (
        <div className="notice" key={`${index}-${note}`}>
          {note}
        </div>
      ))}
    </div>
  ) : null;
}
export function PageTitle({
  title,
  aside,
  children,
}: {
  title: string;
  aside?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="page-title">
      <div className="title-group">
        <h1>{title}</h1>
        {children}
      </div>
      {aside}
    </div>
  );
}
export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
export function Loading({
  label = "Loading recorded evidence…",
}: {
  label?: string;
}) {
  return (
    <div className="empty" role="status">
      {label}
    </div>
  );
}
export function ErrorState({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  return (
    <div className="notice error" role="alert">
      <span>{message}</span>
      {retry && <button onClick={retry}>Try again</button>}
    </div>
  );
}
export function Unavailable({ label }: { label: string }) {
  return (
    <span className="unavailable">
      <button disabled>{label}</button>
      <span className="caption">Not available yet</span>
    </span>
  );
}
export function Stat({
  label,
  value,
  detail,
  verified = false,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  verified?: boolean;
}) {
  return (
    <div className="card stat">
      <span className="eyebrow">{label}</span>
      <strong className={verified ? "verified-text" : ""}>{value}</strong>
      <span className="muted">{detail}</span>
    </div>
  );
}
export function JsonBlock({ value }: { value: unknown }) {
  return <pre className="code">{JSON.stringify(value, null, 2)}</pre>;
}
export function Prose({ text }: { text: string }) {
  return (
    <div className="prose">
      <Markdown
        skipHtml
        components={{
          img: ({ alt }) => (
            <span className="caption">[Image: {alt ?? "source image"}]</span>
          ),
          a: ({ href, children }) => (
            <a href={href} rel="noopener noreferrer" target="_blank">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </Markdown>
    </div>
  );
}
export function AuditToggle({
  value,
  onChange,
}: {
  value: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="audit-toggle">
      <input
        type="checkbox"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
      />{" "}
      Include voided records · audit
    </label>
  );
}
export function EvalDots({
  passed,
  results = [],
  verified = false,
}: {
  passed: number;
  results?: { n: number; passed: boolean }[];
  verified?: boolean;
}) {
  return (
    <div className={`eval-dots ${verified ? "is-verified" : ""}`}>
      <div className="dots">
        {[1, 2, 3, 4, 5].map((n) => {
          const result = results.find((e) => e.n === n);
          const state = result
            ? result.passed
              ? "pass"
              : "failed"
            : "not recorded";
          return (
            <span
              className={`dot ${result ? (result.passed ? "pass" : "failed") : ""}`}
              key={n}
              aria-label={`Eval ${n}: ${state}`}
              title={`Eval ${n}: ${state}`}
            />
          );
        })}
      </div>
      <span className="mono">{passed}/5</span>
    </div>
  );
}
export function LogList({ events }: { events: Event[] }) {
  return events.length ? (
    <ol className="log-list">
      {events.map((event) => (
        <li key={event.seq}>
          <div className="log-meta mono">
            <span>#{event.seq}</span>
            <time dateTime={event.ts}>
              {event.ts.replace("T", " ").replace("Z", " UTC")}
            </time>
            <span>
              {event.stage}
              {event.variant ? ` · ${event.variant}` : ""}
            </span>
            <span className={event.status === "failed" ? "failed-text" : ""}>
              {event.status}
            </span>
          </div>
          <p>{event.message}</p>
          {Object.keys(event.data).length > 0 && (
            <details>
              <summary>Event data</summary>
              <JsonBlock value={event.data} />
            </details>
          )}
        </li>
      ))}
    </ol>
  ) : (
    <Empty>No retained events for this step.</Empty>
  );
}
const stepStateLabel = (state: string) =>
  state === "awaiting_judgment"
    ? "Awaiting final judgment"
    : state === "awaiting_results"
      ? "Awaiting results"
      : human(state);

function variantProgressLabel(variant: VariantRun): string | null {
  if (variant.status !== "RUNNING") return null;
  const state = ["awaiting_judgment", "awaiting_results"].find((state) =>
    variant.steps.some((step) => step.state === state),
  );
  return state ? stepStateLabel(state) : null;
}

export function VariantStatus({
  variant,
  parentStatus,
}: {
  variant: VariantRun;
  parentStatus?: string;
}) {
  if (
    variant.status === "RUNNING" &&
    parentStatus &&
    isTerminal(parentStatus)
  ) {
    return (
      <span
        className="pill"
        title="The parent run has ended; no final variant verdict was recorded."
      >
        Run ended
      </span>
    );
  }
  const progress = variantProgressLabel(variant);
  return progress ? (
    <span
      className="pill"
      title="The run remains active; no final judgment has been published."
    >
      {progress}
    </span>
  ) : (
    <StatusPill status={variant.status} />
  );
}

export function StepPipeline({ steps }: { steps: Step[] }) {
  const [selected, setSelected] = useState<string | null>(null);
  const step =
    steps.find((item) => item.id === selected) ??
    steps.find((item) => item.state === "running") ??
    steps.find((item) => item.state === "awaiting_judgment") ??
    steps.find((item) => item.state === "awaiting_results") ??
    steps.find((item) => item.state === "failed") ??
    steps[0];
  if (!step) return <Empty>No steps were recorded.</Empty>;
  return (
    <div className="step-pipeline">
      <div
        className="pipeline-nodes"
        role="tablist"
        aria-label="Pipeline stages"
      >
        {steps.map((item) => (
          <button
            key={item.id}
            role="tab"
            aria-selected={item.id === step.id}
            onClick={() => setSelected(item.id)}
            className={`pipeline-node ${item.state}`}
          >
            <span className="step-symbol" aria-hidden="true">
              {item.state === "failed"
                ? "×"
                : item.state === "pass" || item.state === "fixed"
                  ? "✓"
                  : item.state === "running"
                    ? "◌"
                    : "·"}
            </span>
            <strong>{item.label}</strong>
            <span className="caption">
              {stepStateLabel(item.state)}
              {item.kind === "heal" && item.attempts
                ? ` ${item.attempts}/${item.max_attempts ?? 3}`
                : ""}
            </span>
          </button>
        ))}
      </div>
      <section
        className={`step ${step.state}`}
        aria-label={`${step.label} details`}
      >
        <div className="row between step-detail-heading">
          <strong>{step.label}</strong>
          <Chip>{stepStateLabel(step.state)}</Chip>
        </div>
        <div className="step-details">
          {step.details.map((line, i) => (
            <p key={i}>{line}</p>
          ))}
          {step.logs.length > 0 && (
            <div className="log-scroll">
              <LogList events={step.logs} />
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
export function VariantCard({
  variant,
  parentStatus,
  audit = false,
  onSelect,
}: {
  variant: VariantRun;
  parentStatus?: string;
  audit?: boolean;
  onSelect?: () => void;
}) {
  const evals = variant.steps
    .filter(
      (s) => s.kind === "eval" && (s.state === "pass" || s.state === "failed"),
    )
    .map((s) => ({ n: s.number ?? 0, passed: s.state === "pass" }));
  return (
    <article
      className={`card variant-card ${variant.status === "VERIFIED" ? "verified-card" : ""}`}
    >
      <span className="lane-letter">{variant.variant}</span>
      <div className="variant-copy">
        <h2>
          {onSelect ? (
            <button className="text-button serif" onClick={onSelect}>
              {laneNames[variant.variant] ?? variant.variant}
            </button>
          ) : (
            (laneNames[variant.variant] ?? variant.variant)
          )}
        </h2>
        <p className="muted">{laneDescriptions[variant.variant]}</p>
        <p>{variant.summary}</p>
        <div className="inline-meta">
          <Chip>{variant.test_type}</Chip>
          <span className="caption">
            {variant.frequency} · {variant.profile} profile
          </span>
        </div>
        <Notes notes={variant.notes} />
      </div>
      <div className="variant-result">
        <EvalDots
          passed={variant.evals_passed}
          results={evals}
          verified={variant.status === "VERIFIED"}
        />
        <VariantStatus variant={variant} parentStatus={parentStatus} />
        <Link
          className="caption"
          to={`/variants/${variant.variant_id}${auditSuffix(audit)}`}
        >
          Tearsheet →
        </Link>
      </div>
    </article>
  );
}
export function DataNeedRow({ need }: { need: DataNeed }) {
  return (
    <div className="data-need">
      <div>
        <strong>{need.name}</strong>
        <span className="caption">
          {need.symbols.join(", ")} {need.frequency}
        </span>
      </div>
      <Chip>{human(need.status)}</Chip>
      {!["on_disk", "fetched", "fetching"].includes(need.status) && (
        <Unavailable
          label={
            need.status === "needs_provider"
              ? "Connect provider"
              : need.status === "needs_upload"
                ? "Upload dataset"
                : need.status === "candidates"
                  ? "Approve source"
                  : "Resolve need"
          }
        />
      )}
    </div>
  );
}
export function SpecPanel({
  source,
  children,
}: {
  source: Source | null;
  children?: ReactNode;
}) {
  if (!source)
    return (
      <section className="card">
        <span className="eyebrow">Paper spec · from extractor</span>
        <Empty>No strategy spec has been recorded.</Empty>
        {children}
      </section>
    );
  const spec = source.spec;
  const authors = source.provenance.authors;
  return (
    <section className="card spec-panel">
      <span className="eyebrow">Paper spec · recorded snapshot</span>
      <h2>{source.title}</h2>
      {Array.isArray(authors) && <p className="muted">{authors.join(", ")}</p>}
      {children}
      <div className="inline-meta">
        <Chip>{spec.test_type}</Chip>
        <Chip>{spec.frequency} tier</Chip>
      </div>
      <div className="symbol-list">
        {spec.universe.map((symbol) => (
          <Chip key={symbol}>{symbol}</Chip>
        ))}
      </div>
      <div className="spec-field">
        <span className="eyebrow">Claimed</span>
        <p className="mono">
          Sharpe{" "}
          {formatNumber(
            typeof spec.claimed_metrics.sharpe === "number"
              ? spec.claimed_metrics.sharpe
              : null,
          )}
        </p>
        {Object.entries(spec.claimed_metrics)
          .filter(([key, value]) => key !== "sharpe" && value != null)
          .map(([key, value]) => (
            <p key={key}>
              <span className="muted">{human(key)}: </span>
              {String(value)}
            </p>
          ))}
      </div>
      <div className="spec-field">
        <span className="eyebrow">Hypothesis</span>
        <p>{spec.hypothesis}</p>
      </div>
      <details>
        <summary>Signal rules ({spec.signal_rules.length})</summary>
        <ul>
          {spec.signal_rules.map((rule) => (
            <li key={rule}>{rule}</li>
          ))}
        </ul>
      </details>
      <details>
        <summary>Ambiguities ({spec.ambiguities.length})</summary>
        <ul>
          {spec.ambiguities.map((rule) => (
            <li key={rule}>{rule}</li>
          ))}
        </ul>
      </details>
      <Unavailable label="Edit spec / Re-extract" />
    </section>
  );
}
