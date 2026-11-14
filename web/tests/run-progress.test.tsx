import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import * as apiModule from "../src/api";
import { RunPage } from "../src/pages/Runs";
import { StepPipeline } from "../src/components/common";
import type { RunDetail, Step, VariantRun } from "../src/types";

const code: Step = {
  id: "A-code",
  kind: "code",
  label: "Generate strategy code",
  state: "recorded",
  number: null,
  attempts: 0,
  max_attempts: null,
  details: [],
  logs: [],
};
const check = (state: Step["state"]): Step => ({
  ...code,
  id: "A-eval-1",
  kind: "eval",
  label: "1. Lookahead",
  state,
  number: 1,
  details: [
    state === "awaiting_judgment"
      ? "Computation complete; awaiting final judgment"
      : "Harness active; individual outcomes not yet published.",
  ],
});

it.each([
  [
    "awaiting_judgment",
    "Waiting for trials",
    "Computation complete; awaiting final judgment",
  ],
  [
    "awaiting_results",
    "Not published",
    "Harness active; individual outcomes not yet published.",
  ],
] as const)(
  "selects and neutrally explains unpublished %s steps",
  (state, label, description) => {
    render(<StepPipeline steps={[code, check(state)]} />);
    const selected = screen.getByRole("tab", {
      name: new RegExp(`Lookahead.*${label}`),
    });
    expect(selected).toHaveAttribute("aria-selected", "true");
    expect(selected).not.toHaveClass("running", "pass", "failed");
    expect(selected).not.toHaveTextContent("✓");
    const detail = screen.getByRole("region", { name: "1. Lookahead details" });
    expect(within(detail).getByText(description)).toBeVisible();
    expect(within(detail).getByText(label)).toBeVisible();
  },
);

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const lane = (
  variant: string,
  state: Step["state"],
  status = "RUNNING",
): VariantRun => ({
  variant_id: `r_progress_${variant}`,
  run_id: "r_progress",
  source_id: "p_fixture",
  source_title: "Progress fixture",
  source_kind: "paper",
  variant,
  test_type: "transfer",
  frequency: "1day",
  claimed_sharpe: null,
  verified_sharpe: null,
  break_even_bps: null,
  evals_passed: status === "RUNNING" ? 0 : 2,
  status,
  profile: "default",
  default_status: status,
  default_evals_passed: status === "RUNNING" ? 0 : 2,
  summary: "Stored progress summary.",
  days_traded: null,
  notes: [],
  voided: false,
  void_reason: null,
  created_at: null,
  steps: [check(state)],
});

it.each([
  ["awaiting_judgment", "In progress", "RUNNING"],
  ["awaiting_results", "In progress", "RUNNING"],
  ["not_run", "Run ended", "FAILED"],
  ["awaiting_judgment", "Run ended", "FAILED"],
] as const)(
  "replaces RUNNING with the neutral %s badge in lane tabs and cards",
  async (state, label, parentStatus) => {
    const detail: RunDetail = {
      run_id: "r_progress",
      status: parentStatus,
      source: null,
      submission: null,
      variants: [
        lane("A", state),
        lane("B", state),
        lane("C", state, "FAILED_EVAL_2"),
      ],
      data_needs: [],
      created_at: null,
      started_at: null,
      wall_seconds: null,
      estimated_model_cost_usd: null,
      cost_complete: null,
      voided: false,
      void_reason: null,
      error_type: null,
      error: null,
      steps: [],
      usage: [],
      extraction_diagnostics: [],
      artifacts: [],
    };
    vi.spyOn(apiModule.api, "run").mockResolvedValue(detail);
    vi.spyOn(apiModule.api, "runs").mockResolvedValue({ runs: [detail] });
    vi.spyOn(apiModule.api, "events").mockResolvedValue({
      events: [],
      next_seq: 0,
    });
    vi.spyOn(apiModule, "subscribeRun").mockReturnValue(() => {});
    render(
      <MemoryRouter initialEntries={["/runs/r_progress"]}>
        <Routes>
          <Route path="/runs/:runId" element={<RunPage />} />
        </Routes>
      </MemoryRouter>,
    );
    const tabs = await screen.findByRole("tablist", { name: "Variant lanes" });
    const cards = screen.getAllByRole("article");
    for (const [index, letter] of ["A", "B"].entries()) {
      const tab = within(tabs).getByRole("tab", {
        name: new RegExp(`^${letter}`),
      });
      for (const surface of [tab, cards[index]]) {
        expect(
          within(surface).queryByText("RUNNING", { exact: true }),
        ).not.toBeInTheDocument();
        const badge = within(surface).getByText(label, { exact: true });
        expect(badge).toHaveClass("pill");
        expect(badge).not.toHaveClass("running", "verified", "failed");
        if (parentStatus === "FAILED")
          expect(surface).not.toHaveTextContent(/Awaiting/);
      }
    }
    for (const surface of [
      within(tabs).getByRole("tab", { name: /^C/ }),
      cards[2],
    ]) {
      expect(
        within(surface).getByText("FAILED_EVAL_2", { exact: true }),
      ).toBeVisible();
      expect(
        within(surface).queryByText(label, { exact: true }),
      ).not.toBeInTheDocument();
    }
    expect(detail.variants.map((v) => v.status)).toEqual([
      "RUNNING",
      "RUNNING",
      "FAILED_EVAL_2",
    ]);
  },
);
