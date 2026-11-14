import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import * as apiModule from "../src/api";
import { RunPage } from "../src/pages/Runs";
import { StepPipeline } from "../src/components/common";
import type { RunDetail, Step, VariantRun } from "../src/types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});
const step = (n: number, state: Step["state"], details: string[]): Step => ({
  id: `A-eval-${n}`,
  kind: "eval",
  label: `${n}. ${["Lookahead", "Friction", "Sensitivity", "Decay", "Deflated Sharpe"][n - 1]}`,
  state,
  number: n,
  attempts: 0,
  max_attempts: null,
  details,
  logs: [],
});
const steps = [
  step(1, "pass", [
    "Recorded verdict: pass.",
    "Maximum difference 0.000 at 5 cut points.",
  ]),
  step(2, "failed", [
    "Recorded verdict: fail.",
    "Net Sharpe at 5 bps: 0.210.",
    "Recovered from saved IS cost grid; original result not published.",
  ]),
  step(3, "awaiting_results", ["Sensitivity result was not published."]),
  step(4, "recorded", [
    "Recorded metrics; verdict not published.",
    "IS Sharpe 0.90; OOS Sharpe 0.70.",
  ]),
  step(5, "awaiting_judgment", [
    "Waiting for C to finish; compares all trials.",
  ]),
];
const variant: VariantRun = {
  variant_id: "r_progress_A",
  run_id: "r_progress",
  source_id: "p_fixture",
  source_title: "Progress fixture",
  source_kind: "paper",
  variant: "A",
  test_type: "transfer",
  frequency: "1day",
  claimed_sharpe: null,
  verified_sharpe: null,
  break_even_bps: null,
  evals_passed: 1,
  status: "RUNNING",
  profile: "default",
  default_status: "RUNNING",
  default_evals_passed: 1,
  summary: "Results arrive as each check completes.",
  days_traded: null,
  notes: [],
  voided: false,
  void_reason: null,
  created_at: null,
  steps,
};
const detail: RunDetail = {
  run_id: "r_progress",
  status: "RUNNING",
  source: null,
  submission: null,
  variants: [variant],
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

it("shows partial outcomes and recorded metrics on overview and opens the clicked eval", async () => {
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
  const overview = await screen.findByRole("article");
  expect(within(overview).getByText("2/5 results available")).toBeVisible();
  expect(within(overview).getByText("1/5 passed")).toBeVisible();
  expect(
    within(overview).getByText("Maximum difference 0.000 at 5 cut points."),
  ).toBeVisible();
  expect(
    within(overview).getByText("IS Sharpe 0.90; OOS Sharpe 0.70."),
  ).toBeVisible();
  expect(
    within(overview).getByText("Recovered: saved IS cost grid"),
  ).toBeVisible();
  const missing = within(overview).getByRole("button", {
    name: /3. Sensitivity/,
  });
  expect(missing).toHaveTextContent("Not published");
  expect(missing).not.toHaveTextContent(/pass|failed/);
  expect(
    within(overview).getByRole("button", { name: /5. Deflated Sharpe/ }),
  ).toHaveTextContent("Waiting for C to finish; compares all trials.");
  fireEvent.click(
    within(overview).getByRole("button", { name: /2. Friction/ }),
  );
  const result = await screen.findByRole("region", {
    name: "2. Friction details",
  });
  expect(within(result).getByText("Net Sharpe at 5 bps: 0.210.")).toBeVisible();
  expect(screen.getByRole("tab", { name: /2. Friction/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
});

it("shows elapsed time only from a real matching eval start event", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-14T22:00:30Z"));
  const active = {
    ...step(3, "running", ["Testing parameter sensitivity."]),
    logs: [
      {
        seq: 1,
        ts: "2026-11-14T22:00:00Z",
        run_id: "r_progress",
        stage: "eval",
        variant: "A",
        status: "started",
        message: "Sensitivity started",
        data: { eval: 3 },
      },
    ],
  };
  const { rerender } = render(<StepPipeline steps={[active]} />);
  expect(screen.getAllByText("30s elapsed").length).toBeGreaterThan(0);
  act(() => vi.advanceTimersByTime(2000));
  expect(screen.getAllByText("32s elapsed").length).toBeGreaterThan(0);
  rerender(
    <StepPipeline
      steps={[{ ...active, logs: [{ ...active.logs[0], data: {} }] }]}
    />,
  );
  expect(screen.queryByText(/elapsed/)).not.toBeInTheDocument();
});

it("updates the selected eval and counts when a streamed result triggers reload", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-14T22:00:30Z"));
  const start = {
    seq: 1,
    ts: "2026-11-14T22:00:00Z",
    run_id: "r_progress",
    stage: "eval",
    variant: "A",
    status: "started",
    message: "Lookahead started",
    data: { eval: 1 },
  };
  const initialSteps = [
    { ...step(1, "running", ["Checking truncated signals."]), logs: [start] },
    ...[2, 3, 4, 5].map((n) => step(n, "pending", ["Not started."])),
  ];
  const completion = {
    ...start,
    seq: 2,
    ts: "2026-11-14T22:00:30Z",
    status: "passed",
    message: "Lookahead passed",
  };
  const finalSteps = [
    {
      ...step(1, "pass", ["Maximum difference 0.000 at 5 cut points."]),
      logs: [start, completion],
    },
    {
      ...step(2, "running", ["Testing trading costs."]),
      logs: [
        {
          ...start,
          seq: 3,
          ts: "2026-11-14T22:00:30Z",
          data: { eval: 2 },
          message: "Friction started",
        },
      ],
    },
    ...initialSteps.slice(2),
  ];
  const run = vi
    .spyOn(apiModule.api, "run")
    .mockResolvedValueOnce({
      ...detail,
      variants: [{ ...variant, evals_passed: 0, steps: initialSteps }],
    })
    .mockResolvedValue({
      ...detail,
      variants: [{ ...variant, steps: finalSteps }],
    });
  vi.spyOn(apiModule.api, "runs").mockResolvedValue({ runs: [detail] });
  vi.spyOn(apiModule.api, "events").mockResolvedValue({
    events: [],
    next_seq: 0,
  });
  let publish: Parameters<typeof apiModule.subscribeRun>[3] = () => {};
  vi.spyOn(apiModule, "subscribeRun").mockImplementation(
    (_id, _audit, _after, onEvent) => {
      publish = onEvent;
      return () => {};
    },
  );
  await act(async () => {
    render(
      <MemoryRouter initialEntries={["/runs/r_progress"]}>
        <Routes>
          <Route path="/runs/:runId" element={<RunPage />} />
        </Routes>
      </MemoryRouter>,
    );
  });
  const overview = screen.getByRole("article");
  expect(within(overview).getByText("0/5 results available")).toBeVisible();
  fireEvent.click(
    within(overview).getByRole("button", { name: /1. Lookahead/ }),
  );
  expect(
    screen.getByRole("region", { name: "1. Lookahead details" }),
  ).toHaveTextContent("30s elapsed");
  act(() => publish(completion));
  await act(async () => {
    vi.advanceTimersByTime(349);
  });
  expect(run).toHaveBeenCalledTimes(1);
  await act(async () => {
    vi.advanceTimersByTime(1);
  });
  expect(run).toHaveBeenCalledTimes(2);
  const card = screen.getByRole("article");
  expect(within(card).getByText("1/5 results available")).toBeVisible();
  expect(within(card).getByText("1/5 passed")).toBeVisible();
  const selected = screen.getByRole("region", { name: "1. Lookahead details" });
  expect(selected).toHaveTextContent(
    "Maximum difference 0.000 at 5 cut points.",
  );
  expect(selected).not.toHaveTextContent("elapsed");
  expect(screen.getByRole("tab", { name: /1. Lookahead/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(
    within(card).getByRole("button", { name: /1. Lookahead/ }),
  ).not.toHaveTextContent("elapsed");
  expect(
    within(card).getByRole("button", { name: /2. Friction/ }),
  ).toHaveTextContent("0s elapsed");
  expect(screen.getByRole("tab", { name: /2. Friction/ })).toHaveTextContent(
    "0s elapsed",
  );
});
