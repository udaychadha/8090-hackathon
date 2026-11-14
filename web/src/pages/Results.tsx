import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useResource } from "../hooks";
import {
  auditSuffix,
  evalMetricSummary,
  formatNumber,
  human,
  laneNames,
} from "../evidence";
import { ArtifactLinks } from "../components/Artifacts";
import { EquityChart } from "../components/Charts";
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
  SpecPanel,
  Stat,
  StatusPill,
  StepPipeline,
} from "../components/common";

export function LeaderboardPage() {
  const [params, setParams] = useSearchParams();
  const audit = params.get("include_voided") === "true";
  const [source, setSource] = useState("");
  const [status, setStatus] = useState("");
  const [testType, setTestType] = useState("");
  const [frequency, setFrequency] = useState("");
  const [kind, setKind] = useState("");
  const [sort, setSort] = useState("evals_passed");
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  const resource = useResource(
    () =>
      api.leaderboard({
        include_voided: audit,
        source_id: source,
        status,
        test_type: testType,
        frequency,
        sort_by: sort,
        direction,
      }),
    JSON.stringify([
      audit,
      source,
      status,
      testType,
      frequency,
      sort,
      direction,
    ]),
  );
  const sources = useResource(api.sources, "sources");
  const rows =
    resource.data?.rows.filter((row) => !kind || row.source_kind === kind) ??
    [];
  function changeSort(key: string) {
    if (key === sort) setDirection(direction === "desc" ? "asc" : "desc");
    else {
      setSort(key);
      setDirection("desc");
    }
  }
  const heading = (label: string, key: string) => (
    <button className="sort-button" onClick={() => changeSort(key)}>
      {label}
      {sort === key ? (direction === "desc" ? " ↓" : " ↑") : ""}
    </button>
  );
  return (
    <>
      <PageTitle
        title="Leaderboard"
        aside={
          <AuditToggle
            value={audit}
            onChange={(value) =>
              setParams(value ? { include_voided: "true" } : {})
            }
          />
        }
      />
      {resource.data ? (
        <div className="stats">
          <Stat
            label="Verified"
            value={`${rows.filter((r) => r.status === "VERIFIED").length} of ${rows.length}`}
            detail="variants in this view"
            verified={rows.some((r) => r.status === "VERIFIED")}
          />
          <Stat
            label="Failed an eval"
            value={
              rows.filter((r) => r.status.startsWith("FAILED_EVAL")).length
            }
            detail="later evals still recorded"
          />
          <Stat
            label="Inactive / bugs"
            value={
              rows.filter((r) =>
                ["INACTIVE", "BUG_UNRESOLVED"].includes(r.status),
              ).length
            }
            detail="activity or unresolved code failure"
          />
          <Stat
            label="Running / blocked"
            value={
              rows.filter((r) => ["RUNNING", "BLOCKED_DATA"].includes(r.status))
                .length
            }
            detail="running or blocked on data"
          />
        </div>
      ) : null}
      <div className="filters">
        <label>
          Source
          <select
            aria-label="Source kind"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
          >
            <option value="">All</option>
            <option value="paper">Paper</option>
            <option value="described">Described</option>
          </select>
        </label>
        <label>
          Paper
          <select
            aria-label="Source"
            value={source}
            onChange={(e) => setSource(e.target.value)}
          >
            <option value="">All sources</option>
            {sources.data?.sources.map((s) => (
              <option key={s.source_id} value={s.source_id}>
                {s.title}
              </option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            {[
              "VERIFIED",
              "FAILED_EVAL_1",
              "FAILED_EVAL_2",
              "FAILED_EVAL_3",
              "FAILED_EVAL_4",
              "FAILED_EVAL_5",
              "INACTIVE",
              "BUG_UNRESOLVED",
              "BLOCKED_DATA",
              "RUNNING",
              ...(audit ? ["VOID"] : []),
            ].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label>
          Test type
          <select
            value={testType}
            onChange={(e) => setTestType(e.target.value)}
          >
            <option value="">All</option>
            {["replication", "transfer", "original"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label>
          Tier
          <select
            value={frequency}
            onChange={(e) => setFrequency(e.target.value)}
          >
            <option value="">All</option>
            <option>1min</option>
            <option>1day</option>
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
                  <th>{heading("Source", "source_title")}</th>
                  <th>{heading("Var", "variant")}</th>
                  <th>Test type</th>
                  <th
                    aria-sort={
                      sort === "claimed_sharpe"
                        ? direction === "asc"
                          ? "ascending"
                          : "descending"
                        : "none"
                    }
                  >
                    {heading("Claimed Sharpe", "claimed_sharpe")}
                  </th>
                  <th
                    aria-sort={
                      sort === "verified_sharpe"
                        ? direction === "asc"
                          ? "ascending"
                          : "descending"
                        : "none"
                    }
                  >
                    {heading("Verified Sharpe · OOS, 5 bps", "verified_sharpe")}
                  </th>
                  <th>{heading("Break-even bps", "break_even_bps")}</th>
                  <th>{heading("Evals passed", "evals_passed")}</th>
                  <th>{heading("Status", "status")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.variant_id}>
                    <td className="source-cell">
                      <Link
                        to={`/variants/${row.variant_id}${auditSuffix(audit)}`}
                      >
                        {row.source_title}
                      </Link>
                      <p className="caption">
                        {row.frequency} · {row.profile} profile
                      </p>
                      <Notes
                        notes={[
                          ...row.notes,
                          ...(row.void_reason ? [row.void_reason] : []),
                        ]}
                      />
                    </td>
                    <td className="mono">{row.variant}</td>
                    <td>
                      <Chip>{row.test_type}</Chip>
                    </td>
                    <td className="number">
                      {formatNumber(row.claimed_sharpe)}
                    </td>
                    <td
                      className={`number ${row.status === "VERIFIED" ? "verified-text" : ""}`}
                    >
                      {formatNumber(row.verified_sharpe)}
                    </td>
                    <td className="number">
                      {formatNumber(row.break_even_bps, 1)}
                    </td>
                    <td className="number">{row.evals_passed}/5</td>
                    <td>
                      <StatusPill status={row.status} />
                      {row.profile !== "default" && (
                        <p className="caption">
                          Default: {row.default_status} ·{" "}
                          {row.default_evals_passed}/5
                        </p>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length === 0 && (
              <Empty>No variants match these filters.</Empty>
            )}
          </div>
          <p className="caption">
            “Verified Sharpe” is the recorded OOS metric, net of 5 bps. A metric
            alone does not confer VERIFIED status. — means not recorded.
          </p>
        </>
      )}
    </>
  );
}

export function TearsheetPage() {
  const { variantId = "" } = useParams();
  const [params] = useSearchParams();
  const audit = params.get("include_voided") === "true";
  const resource = useResource(
    () => api.variant(variantId, audit),
    `${variantId}:${audit}`,
  );
  if (resource.loading) return <Loading label="Loading tearsheet…" />;
  if (!resource.data)
    return (
      <ErrorState
        message={resource.error ?? "Variant not found."}
        retry={() => void resource.reload()}
      />
    );
  const variant = resource.data;
  return (
    <>
      <div className="row between">
        <Link className="eyebrow" to={`/leaderboard${auditSuffix(audit)}`}>
          ← Leaderboard
        </Link>
        <Link
          className="caption"
          to={`/runs/${variant.run_id}${auditSuffix(audit)}`}
        >
          Open run {variant.run_id} →
        </Link>
      </div>
      <PageTitle
        title={`${variant.source_title} · ${variant.variant}`}
        aside={
          <div className="row">
            <Chip>{variant.test_type}</Chip>
            <Chip>{variant.frequency} tier</Chip>
            <Chip>{variant.evals_passed}/5 evals</Chip>
            <StatusPill status={variant.status} />
          </div>
        }
      />
      <Notes
        notes={[
          ...variant.notes,
          ...(variant.void_reason ? [variant.void_reason] : []),
        ]}
      />
      <div className="stats">
        <Stat
          label="Claimed Sharpe"
          value={formatNumber(variant.claimed_sharpe)}
          detail="reported by source"
        />
        <Stat
          label="Verified Sharpe"
          value={formatNumber(variant.verified_sharpe)}
          detail="OOS, net of 5 bps"
          verified={variant.status === "VERIFIED"}
        />
        <Stat
          label="Break-even cost"
          value={
            variant.break_even_bps == null
              ? "—"
              : `${formatNumber(variant.break_even_bps, 1)} bps`
          }
          detail="round trip"
        />
        <Stat
          label="Evals passed"
          value={`${variant.evals_passed} / 5`}
          detail={`${variant.profile} profile`}
        />
      </div>
      <p>{variant.summary}</p>
      {variant.profile !== "default" && (
        <div className="notice">
          Default verdict: {variant.default_status} ·{" "}
          {variant.default_evals_passed}/5
        </div>
      )}
      <section className="card">
        <div className="row between">
          <h2>Equity</h2>
        </div>
        <EquityChart
          equity={variant.equity}
          title={`${variant.source_title} · ${variant.variant} · Equity`}
        />
        {variant.equity_boundaries && (
          <p className="caption">
            Exact boundaries (UTC): IS {variant.equity_boundaries.is_end} · OOS{" "}
            {variant.equity_boundaries.oos_end}
          </p>
        )}
      </section>
      <section className="stack">
        <h2>Strategy evals</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Strategy eval</th>
                <th>Result</th>
                <th>Recorded metrics</th>
              </tr>
            </thead>
            <tbody>
              {[1, 2, 3, 4, 5].map((n) => {
                const result = variant.evals.find((e) => e.n === n);
                return (
                  <tr key={n}>
                    <td>
                      <strong>
                        {n}{" "}
                        {result?.name ??
                          [
                            "Lookahead",
                            "Friction",
                            "Sensitivity",
                            "Decay",
                            "Deflated Sharpe",
                          ][n - 1]}
                      </strong>
                    </td>
                    <td
                      className={
                        result && !result.passed
                          ? "failed-text"
                          : variant.status === "VERIFIED"
                            ? "verified-text"
                            : ""
                      }
                    >
                      {result
                        ? result.passed
                          ? "✓ pass"
                          : "× failed"
                        : "Not run / not recorded"}
                    </td>
                    <td>
                      {result ? (
                        <div className="metric-list">
                          {evalMetricSummary(result).map((line, index) => (
                            <p key={index} className="mono">
                              {line}
                            </p>
                          ))}
                          <details>
                            <summary>Full recorded metrics</summary>
                            <JsonBlock value={result.metrics} />
                          </details>
                        </div>
                      ) : (
                        <span className="muted">
                          No completed harness result
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
      <div className="two-col">
        <div className="stack">
          <section className="card">
            <div className="row between">
              <h2>Critic post-mortem</h2>
              <Chip>Narrative only · decides nothing</Chip>
            </div>
            <p className="caption">
              Authoritative verdict and metrics are shown above. Any historical
              model narrative below is unverified.
            </p>
            {variant.critique ? (
              <Prose text={variant.critique} />
            ) : (
              <Empty>No critique was recorded.</Empty>
            )}
            <Link
              className="button"
              to={`/graveyard${auditSuffix(audit)}${audit ? "&" : "?"}variant=${variant.variant_id}`}
            >
              Open graveyard entry →
            </Link>
          </section>
          <section className="card">
            <h2>Activity</h2>
            <p>
              IS days with nonzero target weights:{" "}
              <strong>{variant.days_traded ?? "—"}</strong>
            </p>
            {variant.activity ? (
              <JsonBlock value={variant.activity} />
            ) : (
              <p className="muted">No activity detail was retained.</p>
            )}
          </section>
          <details className="card">
            <summary>Recorded source specification</summary>
            <SpecPanel source={variant.source} />
          </details>
        </div>
        <div className="stack">
          <section className="card">
            <div className="row between">
              <h2>Code</h2>
              <span className="caption">{laneNames[variant.variant]}</span>
            </div>
            {variant.code ? (
              <pre className="code" tabIndex={0}>
                {variant.code}
              </pre>
            ) : (
              <Empty>No strategy code was retained.</Empty>
            )}
            <details>
              <summary>Parameters</summary>
              {variant.params ? (
                <JsonBlock value={variant.params} />
              ) : (
                <Empty>No parameters recorded.</Empty>
              )}
            </details>
            <div className="spec-field">
              <span className="eyebrow">Heal history</span>
              {variant.heal_attempts.length ? (
                variant.heal_attempts.map((heal) => (
                  <details key={heal.attempt}>
                    <summary>
                      Attempt {heal.attempt}/3 ·{" "}
                      {heal.fixed ? "fixed" : "not fixed"}
                    </summary>
                    <pre className="code">{heal.error}</pre>
                    {heal.result_error && (
                      <>
                        <p>Resulting error</p>
                        <pre className="code">{heal.result_error}</pre>
                      </>
                    )}
                  </details>
                ))
              ) : (
                <p className="muted">No repair attempts recorded.</p>
              )}
            </div>
          </section>
          <section className="card">
            <h2>Recorded steps</h2>
            <StepPipeline steps={variant.steps} />
          </section>
        </div>
      </div>
      <section className="card">
        <h2>Related evidence</h2>
        <ArtifactLinks artifacts={variant.artifacts} audit={audit} />
        {variant.original_result && (
          <details>
            <summary>Original result · preserved audit evidence</summary>
            <JsonBlock value={variant.original_result} />
          </details>
        )}
      </section>
    </>
  );
}

export function GraveyardPage() {
  const [params, setParams] = useSearchParams();
  const audit = params.get("include_voided") === "true";
  const target = params.get("variant");
  const [search, setSearch] = useState("");
  const [cause, setCause] = useState("");
  const [type, setType] = useState("");
  const resource = useResource(
    () => api.graveyard(audit),
    `graveyard:${audit}`,
  );
  const entries = resource.data?.entries ?? [];
  const causes = [...new Set(entries.map((e) => e.status))];
  const filtered = entries.filter(
    (e) =>
      (!cause || e.status === cause) &&
      (!type || e.test_type === type) &&
      (!target || e.variant_id === target) &&
      `${e.source_title} ${e.cause} ${e.summary}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  const groups = [...new Set(filtered.map((e) => e.status))];
  return (
    <>
      <PageTitle
        title="Graveyard"
        aside={
          <AuditToggle
            value={audit}
            onChange={(value) => {
              const next = new URLSearchParams(params);
              value
                ? next.set("include_voided", "true")
                : next.delete("include_voided");
              setParams(next);
            }}
          />
        }
      >
        <span className="caption">Recorded post-mortems</span>
      </PageTitle>
      <div className="card filters">
        <input
          type="search"
          aria-label="Search post-mortems"
          placeholder="Search post-mortems…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <label>
          Test type
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">All</option>
            {["replication", "transfer", "original"].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
        {target && (
          <button
            onClick={() => {
              const next = new URLSearchParams(params);
              next.delete("variant");
              setParams(next);
            }}
          >
            Show all entries
          </button>
        )}
      </div>
      {resource.loading ? (
        <Loading />
      ) : resource.error ? (
        <ErrorState
          message={resource.error}
          retry={() => void resource.reload()}
        />
      ) : (
        <div className="graveyard-layout">
          <aside className="stack">
            <div className="table-wrap">
              <div className="row between" style={{ padding: "var(--s4)" }}>
                <span className="eyebrow">Cause of death</span>
                <span className="eyebrow">Recorded</span>
              </div>
              <button
                className="cause-button"
                aria-pressed={!cause}
                onClick={() => setCause("")}
              >
                <span>All outcomes</span>
                <span>{entries.length}</span>
              </button>
              {causes.map((s) => (
                <button
                  key={s}
                  className="cause-button"
                  aria-pressed={cause === s}
                  onClick={() => setCause(s)}
                >
                  <span>{human(s)}</span>
                  <span>{entries.filter((e) => e.status === s).length}</span>
                </button>
              ))}
            </div>
            <section className="card">
              <span className="eyebrow">Evidence, not a second verdict</span>
              <p className="muted">
                Causes and summaries come from deterministic templates over
                stored results. Historical model narrative remains separately
                labelled and unverified.
              </p>
            </section>
            <details className="card">
              <summary>Rendered graveyard record</summary>
              <Prose text={resource.data?.markdown ?? ""} />
            </details>
          </aside>
          <div className="graveyard-columns">
            {groups.map((group) => (
              <section className="stack" key={group}>
                <h2 className="row between">
                  <span>{human(group)}</span>
                  <span className="caption">
                    {filtered.filter((e) => e.status === group).length}
                  </span>
                </h2>
                {filtered
                  .filter((e) => e.status === group)
                  .map((entry) => (
                    <article
                      id={entry.variant_id}
                      className="card graveyard-card"
                      key={entry.variant_id}
                    >
                      <h3>
                        {entry.source_title} · {entry.variant}{" "}
                        {laneNames[entry.variant]}
                      </h3>
                      <div className="caption">
                        {entry.test_type.toUpperCase()} · {entry.frequency} ·{" "}
                        {entry.evals_passed}/5 EVALS
                      </div>
                      <StatusPill status={entry.status} />
                      <p>{entry.summary}</p>
                      <p className="mono">{entry.cause}</p>
                      <Notes
                        notes={[
                          ...entry.notes,
                          ...(entry.void_reason ? [entry.void_reason] : []),
                        ]}
                      />
                      <div className="row">
                        <Link
                          className="button"
                          to={`/variants/${entry.variant_id}${auditSuffix(audit)}`}
                        >
                          Tearsheet
                        </Link>
                        <Link
                          className="caption"
                          to={`/runs/${entry.run_id}${auditSuffix(audit)}`}
                        >
                          Run →
                        </Link>
                      </div>
                      {entry.critique && (
                        <details>
                          <summary>Post-mortem · narrative</summary>
                          <p className="caption">
                            Historical model narrative is unverified and cannot
                            change the verdict.
                          </p>
                          <Prose text={entry.critique} />
                        </details>
                      )}
                    </article>
                  ))}
              </section>
            ))}
            {!filtered.length && (
              <Empty>No post-mortems match these filters.</Empty>
            )}
          </div>
        </div>
      )}
    </>
  );
}
