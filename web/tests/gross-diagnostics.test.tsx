import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../src/api";
import { LeaderboardPage, TearsheetPage } from "../src/pages/Results";
import type { VariantDetail } from "../src/types";

afterEach(() => vi.restoreAllMocks());
const gross = {
  schema_version: "1.0.0",
  state: "complete" as const,
  cost_bps: 0 as const,
  label: "signal before costs" as const,
  reason: null,
  eval_3: {
    number: 3,
    name: "sensitivity",
    passed: true,
    metrics: {
      cost_bps: 0,
      base_sharpe: 1.2,
      worst_sharpe: 0.9,
      worst_ratio: 0.75,
    },
  },
  eval_4: {
    number: 4,
    name: "decay",
    passed: true,
    metrics: {
      cost_bps: 0,
      is_sharpe: 1.2,
      oos_sharpe: 0.8,
      oos_to_is_ratio: 0.67,
      is_max_window_share: 0.2,
      oos_max_window_share: 0.3,
    },
  },
};
const variant: VariantDetail = {
  variant_id: "r_gross_A",
  run_id: "r_gross",
  source_id: "s_gross",
  source_title: "Gross example",
  source_kind: "paper",
  variant: "A",
  test_type: "transfer",
  frequency: "1day",
  claimed_sharpe: null,
  verified_sharpe: 0.2,
  break_even_bps: 1,
  evals_passed: 2,
  status: "FAILED_EVAL_2",
  profile: "default",
  default_status: "FAILED_EVAL_2",
  default_evals_passed: 2,
  summary: "Failed Eval 2; 2/5 evaluations passed.",
  days_traded: 100,
  notes: ["survivorship bias", "unverified source"],
  voided: false,
  void_reason: null,
  created_at: null,
  code: null,
  params: null,
  evals: [],
  equity: null,
  heal_attempts: [],
  critique: null,
  steps: [],
  activity: null,
  equity_boundaries: null,
  source: null,
  artifacts: [],
  original_result: null,
};

it("shows gross signal on the leaderboard without promoting the failed row or counts", async () => {
  vi.spyOn(api, "leaderboard").mockResolvedValue({
    rows: [{ ...variant, gross_diagnostics: gross }],
  });
  vi.spyOn(api, "sources").mockResolvedValue({ sources: [] });
  render(
    <MemoryRouter>
      <LeaderboardPage />
    </MemoryRouter>,
  );
  const label = await screen.findByText("signal before costs");
  expect(label.closest(".verified-text, .status.verified")).toBeNull();
  expect(screen.getByText("0 of 1")).toBeVisible();
  expect(screen.getByText("FAILED_EVAL_2", { selector: "span" })).toBeVisible();
  expect(screen.getByText("2/5")).toBeVisible();
  expect(screen.getByText("Diagnostic · 0 bps")).toBeVisible();
  expect(screen.getByText(/Sensitivity · pass/)).toBeVisible();
  expect(screen.getByText(/Decay · pass/)).toBeVisible();
});

it("shows both gross checks and numbers separately from the five authoritative evals", async () => {
  vi.spyOn(api, "variant").mockResolvedValue({
    ...variant,
    gross_diagnostics: gross,
  });
  render(
    <MemoryRouter>
      <TearsheetPage />
    </MemoryRouter>,
  );
  const region = await screen.findByRole("region", {
    name: "Gross diagnostics",
  });
  expect(within(region).getByText("signal before costs")).toBeVisible();
  expect(region).toHaveTextContent("Base Sharpe 1.20");
  expect(region).toHaveTextContent("Worst Sharpe 0.90");
  expect(region).toHaveTextContent("Worst/base 0.75");
  expect(region).toHaveTextContent("IS Sharpe 1.20");
  expect(region).toHaveTextContent("OOS Sharpe 0.80");
  expect(region).toHaveTextContent("OOS/IS 0.67");
  expect(region).toHaveTextContent("IS 5-day concentration 0.20");
  expect(region).toHaveTextContent("OOS 5-day concentration 0.30");
  expect(screen.getByText("survivorship bias")).toBeVisible();
  expect(screen.getByText("unverified source")).toBeVisible();
  expect(screen.getAllByRole("row")).toHaveLength(6);
});

it.each([
  [null, "FAILED_EVAL_2", "Not recorded"],
  [null, "RUNNING", "Pending"],
  [
    { ...gross, state: "pending", eval_3: null, eval_4: null, label: null },
    "RUNNING",
    "Pending",
  ],
  [
    {
      ...gross,
      state: "unavailable",
      eval_3: null,
      eval_4: null,
      label: "no signal before costs",
      reason: "No valid signals were retained.",
    },
    "INACTIVE",
    "No valid signals were retained.",
  ],
  [
    {
      ...gross,
      eval_4: {
        ...gross.eval_4,
        passed: false,
        metrics: { ...gross.eval_4.metrics, is_max_window_share: null },
      },
      label: "no signal before costs",
    },
    "FAILED_EVAL_4",
    "IS 5-day concentration —",
  ],
] as const)(
  "keeps missing, pending and failed diagnostics truthful (%#)",
  async (diagnostic, status, expected) => {
    vi.spyOn(api, "variant").mockResolvedValue({
      ...variant,
      status,
      gross_diagnostics: diagnostic,
    });
    render(
      <MemoryRouter>
        <TearsheetPage />
      </MemoryRouter>,
    );
    const region = await screen.findByRole("region", {
      name: "Gross diagnostics",
    });
    expect(region).toHaveTextContent(expected);
    expect(region.querySelector(".verified-text, .status.verified")).toBeNull();
  },
);

it("uses live step evidence for unpublished tearsheet evals without replacing completed results", async () => {
  vi.spyOn(api, "variant").mockResolvedValue({
    ...variant,
    status: "RUNNING",
    evals: [
      {
        n: 2,
        name: "Friction",
        passed: false,
        metrics: {
          sharpe_by_bps: { "5": 0.049 },
          pass_bps: 5,
          min_sharpe: 0.5,
        },
      },
    ],
    steps: [
      {
        number: 1,
        state: "awaiting_results" as const,
        details: [
          "Legacy runner does not report its current individual check.",
        ],
      },
      {
        number: 2,
        state: "pending" as const,
        details: ["Stale step fallback must not replace actual result."],
      },
      {
        number: 3,
        state: "recorded" as const,
        details: [
          "Computation finished; sensitivity details have not been published.",
        ],
      },
      {
        number: 5,
        state: "awaiting_judgment" as const,
        details: [
          "Waiting for C to finish its checks.",
          "Eval 5 compares all eligible trials together.",
        ],
      },
    ].map((s) => ({
      ...s,
      id: `eval-${s.number}`,
      kind: "eval" as const,
      label: `Eval ${s.number}`,
      attempts: 0,
      max_attempts: null,
      logs: [],
    })),
  });
  render(
    <MemoryRouter>
      <TearsheetPage />
    </MemoryRouter>,
  );
  const row = (n: number) => screen.getAllByRole("row")[n];
  await screen.findByRole("heading", { name: "Strategy evals" });
  expect(row(1)).toHaveTextContent("Not published");
  expect(row(1)).toHaveTextContent(
    "Legacy runner does not report its current individual check.",
  );
  expect(row(2)).toHaveTextContent("× failed");
  expect(row(2)).toHaveTextContent("0.049");
  expect(row(2)).not.toHaveTextContent("Stale step fallback");
  expect(row(3)).toHaveTextContent("Details not published");
  expect(row(3)).toHaveTextContent(
    "Computation finished; sensitivity details have not been published.",
  );
  expect(row(5)).toHaveTextContent("Waiting for trials");
  expect(row(5)).toHaveTextContent("Waiting for C to finish its checks.");
  expect(row(5)).toHaveTextContent(
    "Eval 5 compares all eligible trials together.",
  );
  for (const n of [1, 3, 5])
    expect(row(n)).not.toHaveTextContent("Not run / not recorded");
  expect(row(4)).toHaveTextContent("Not run / not recorded");
});
