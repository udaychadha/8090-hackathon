import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../src/api";
import { RunPage } from "../src/pages/Runs";
import type { RunDetail, Source } from "../src/types";

afterEach(() => vi.restoreAllMocks());

const source: Source = {
  source_id: "p_test",
  title: "Freshly extracted source",
  source_kind: "paper",
  provenance: {},
  spec: {
    paper_id: "p_test",
    title: "Freshly extracted source",
    category: "Test",
    hypothesis: "Recorded hypothesis",
    universe: ["SPY"],
    frequency: "1day",
    signal_rules: ["Recorded rule"],
    claimed_metrics: {},
    ambiguities: ["Recorded ambiguity"],
    test_type: "transfer",
  },
};

it.each([
  {
    historyPresent: true,
    extracted: true,
    expected: "Freshly extracted source",
  },
  { historyPresent: false, extracted: false, expected: "uploaded-paper.pdf" },
])(
  "labels the current run from fresh detail when historyPresent=$historyPresent, extracted=$extracted",
  async ({ historyPresent, extracted, expected }) => {
    const detail: RunDetail = {
      run_id: "r_current",
      status: extracted ? "COMPLETED" : "FAILED",
      source: extracted ? source : null,
      submission: {
        upload_name: "uploaded-paper.pdf",
        accepted_at: "2026-11-14T12:00:00Z",
      },
      variants: [],
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
    vi.spyOn(api, "runs").mockResolvedValue({
      runs: historyPresent
        ? [{ ...detail, source: null, status: "RUNNING" }]
        : [],
    });
    vi.spyOn(api, "run").mockResolvedValue(detail);
    vi.spyOn(api, "events").mockResolvedValue({ events: [], next_seq: 0 });
    render(
      <MemoryRouter initialEntries={["/runs/r_current"]}>
        <Routes>
          <Route path="/runs/:runId" element={<RunPage />} />
        </Routes>
      </MemoryRouter>,
    );
    const selector = await screen.findByRole("combobox", { name: "Open run" });
    expect(selector).toHaveDisplayValue(`r_current · ${expected}`);
    expect(selector.querySelectorAll("option")).toHaveLength(1);
  },
);
