import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  EvalDots,
  StatusPill,
  Notes,
  StepPipeline,
} from "../src/components/common";
import {
  formatNumber,
  checkExpression,
  mergeEvents,
  evalMetricSummary,
} from "../src/evidence";

describe("evidence presentation", () => {
  it("describes decay as a comparison to IS without substituting the stored ratio", () => {
    const lines = evalMetricSummary({
      n: 4,
      name: "Decay",
      passed: false,
      metrics: {
        oos_sharpe: -0.2,
        is_sharpe: -0.4,
        min_ratio: 0.5,
        oos_to_is_ratio: 0.5,
      },
    });
    expect(lines[0]).toContain("≥ 0.500 × IS -0.400");
    expect(lines[0]).toContain("must exceed 0");
    expect(lines.join("\n")).toContain("IS Sharpe -0.400 · must exceed 0");
    expect(lines.join("\n")).toContain("not applicable / unavailable");
  });
  it("labels the retained global trial cohort and incomplete-accounting reason", () => {
    const lines = evalMetricSummary({
      n: 5,
      name: "Deflated Sharpe",
      passed: false,
      metrics: {
        n_trials: 13,
        trial_scope: "all_runs",
        reason: "Undefined trial Sharpe in selected population",
      },
    });
    expect(lines.join("\n")).toContain("13.000 trials across all runs");
    expect(lines.join("\n")).toContain(
      "Undefined trial Sharpe in selected population",
    );
  });
  it("opens actual pipeline evidence and retains not-run states", () => {
    render(
      <StepPipeline
        steps={[
          {
            id: "code",
            kind: "code",
            label: "Code",
            state: "failed",
            number: null,
            attempts: 1,
            max_attempts: null,
            details: ["Contract error: gross exposure"],
            logs: [],
          },
          {
            id: "eval",
            kind: "eval",
            label: "Eval 2",
            state: "not_run",
            number: 2,
            attempts: 0,
            max_attempts: null,
            details: ["No completed harness result"],
            logs: [],
          },
        ]}
      />,
    );
    expect(screen.getByText("Contract error: gross exposure")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: /Eval 2/ }));
    expect(screen.getByText("No completed harness result")).toBeVisible();
    expect(screen.getByRole("tab", { name: /Eval 2/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
  it("distinguishes a missing metric from an observed zero", () => {
    expect(formatNumber(null)).toBe("—");
    expect(formatNumber(undefined)).toBe("—");
    expect(formatNumber(0)).toBe("0.00");
  });
  it("shows actual eval positions, never inventing passes from a count", () => {
    render(
      <EvalDots
        passed={2}
        results={[
          { n: 1, passed: true },
          { n: 4, passed: true },
          { n: 2, passed: false },
        ]}
      />,
    );
    expect(screen.getByLabelText("Eval 1: pass")).toBeInTheDocument();
    expect(screen.getByLabelText("Eval 2: failed")).toBeInTheDocument();
    expect(screen.getByLabelText("Eval 3: not recorded")).toBeInTheDocument();
    expect(screen.getByLabelText("Eval 4: pass")).toBeInTheDocument();
    expect(screen.getByText("2/5")).toBeInTheDocument();
  });
  it("does not color a completed run as verified", () => {
    render(<StatusPill status="COMPLETED" />);
    expect(screen.getByText("COMPLETED")).not.toHaveClass("verified");
  });
  it("renders the OOS versus IS check as multiplication, including negative IS", () => {
    expect(
      checkExpression({
        metric: "oos_sharpe",
        op: ">=",
        default: 0.5,
        relative_to: "is_sharpe",
      }),
    ).toBe("oos_sharpe ≥ 0.5 × is_sharpe");
  });
  it("keeps notes visible and renders untrusted text without HTML execution", () => {
    render(
      <Notes
        notes={[
          "Survivorship bias: current membership.",
          "<img src=x onerror=alert(1)>",
        ]}
      />,
    );
    expect(
      screen.getByText("Survivorship bias: current membership."),
    ).toBeVisible();
    expect(document.querySelector("img")).toBeNull();
  });
  it("deduplicates a replay by global event sequence and keeps sequence order", () => {
    const event = (seq: number) => ({
      seq,
      ts: "2026-11-14T00:00:00Z",
      run_id: "r_test",
      stage: "eval",
      status: "info",
      variant: null,
      message: String(seq),
      data: {},
    });
    expect(
      mergeEvents([event(9), event(11)], [event(11), event(10)]).map(
        (e) => e.seq,
      ),
    ).toEqual([9, 10, 11]);
  });
});
