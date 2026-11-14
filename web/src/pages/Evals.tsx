import { useId, useState } from "react";
import { api } from "../api";
import { useResource } from "../hooks";
import { checkExpression } from "../evidence";
import type { Check, Knob } from "../types";
import {
  Chip,
  ErrorState,
  JsonBlock,
  Loading,
  Notes,
  PageTitle,
  Unavailable,
} from "../components/common";

function KnobView({ knob }: { knob: Knob | Check }) {
  const inputId = useId();
  return (
    <div className="knob">
      <label htmlFor={inputId}>
        <strong>{knob.label}</strong>
        <Chip>Locked · {knob.default}</Chip>
      </label>
      {"metric" in knob && <p className="mono">{checkExpression(knob)}</p>}
      <input
        id={inputId}
        type="range"
        disabled
        min={knob.min}
        max={knob.max}
        value={knob.default}
        aria-label={`${knob.label} · read only`}
      />
      <div className="tooltip-lines">
        <p>{knob.tooltip.what_it_is}</p>
        <p>Raised: {knob.tooltip.if_raised}</p>
        <p>Lowered: {knob.tooltip.if_lowered}</p>
      </div>
    </div>
  );
}
export function EvalsPage() {
  const resource = useResource(api.evals, "evals");
  const profile = useResource(api.profile, "profile");
  const [selected, setSelected] = useState(1);
  const definition = resource.data?.evals.find((e) => e.n === selected);
  return (
    <>
      <PageTitle
        title="Evals"
        aside={
          <Chip>
            {resource.data
              ? `${resource.data.evals.length} active · default profile · read only`
              : "Loading eval definitions"}
          </Chip>
        }
      />
      {resource.error ? (
        <ErrorState
          message={resource.error}
          retry={() => void resource.reload()}
        />
      ) : resource.loading ? (
        <Loading />
      ) : (
        <>
          <Notes notes={resource.data?.notes ?? []} />
          <div className="two-col">
            <div className="stack">
              <div
                className="table-wrap eval-list"
                role="tablist"
                aria-label="Strategy evals"
              >
                {resource.data?.evals.map((e) => (
                  <button
                    key={e.n}
                    role="tab"
                    aria-selected={selected === e.n}
                    onClick={() => setSelected(e.n)}
                  >
                    <span>
                      <strong>
                        {e.n} {e.name}
                      </strong>
                      <span className="caption">{e.source_file}</span>
                      <span className="caption">{e.data_scope}</span>
                      {e.checks.map((check, index) => (
                        <span
                          key={`${check.key}:${check.metric}:${check.op}:${index}`}
                          className="caption"
                        >
                          {checkExpression(check)}
                        </span>
                      ))}
                    </span>
                    <Chip>Active · locked</Chip>
                  </button>
                ))}
              </div>
              <section className="card">
                <h2>Only code judges a strategy</h2>
                <p>
                  Model workers write implementations. The deterministic harness
                  computes every pass, failure and verdict.
                </p>
                <Unavailable label="Create draft eval / Promote" />
                <p className="caption">
                  Custom profiles and draft evals are not available yet.
                </p>
              </section>
              <details className="card">
                <summary>Default profile &amp; constants</summary>
                {profile.error ? (
                  <ErrorState message={profile.error} />
                ) : profile.loading ? (
                  <Loading />
                ) : (
                  <JsonBlock value={profile.data} />
                )}
                <JsonBlock value={resource.data?.constants} />
              </details>
            </div>
            {definition && (
              <div className="stack">
                <section className="card">
                  <div className="row between">
                    <h2>
                      {definition.n} {definition.name}
                    </h2>
                    <Chip>{definition.data_scope}</Chip>
                  </div>
                  <p>{definition.question}</p>
                  <Notes notes={definition.notes} />
                  <span className="eyebrow">
                    Checks · determine pass / fail
                  </span>
                  {definition.checks.map((knob, index) => (
                    <KnobView
                      key={`${knob.key}:${knob.metric}:${knob.op}:${index}`}
                      knob={knob}
                    />
                  ))}
                  {definition.settings.length > 0 && (
                    <>
                      <span className="eyebrow">
                        Settings · define the experiment
                      </span>
                      {definition.settings.map((knob) => (
                        <KnobView key={knob.key} knob={knob} />
                      ))}
                    </>
                  )}
                </section>
                <section className="card">
                  <div className="row between">
                    <span className="mono wrap">{definition.source_file}</span>
                    <Chip>Read-only source</Chip>
                  </div>
                  <pre className="code" tabIndex={0}>
                    {definition.source_code}
                  </pre>
                </section>
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}
