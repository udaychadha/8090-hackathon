import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../src/api";
import { DataPage } from "../src/pages/Data";
import type { Dataset } from "../src/types";

afterEach(() => vi.restoreAllMocks());

it("keeps a large event preview keyboard-scrollable and the full ticker list collapsed", async () => {
  const symbols = Array.from({ length: 2782 }, (_, index) => `TICKER${index}`);
  const dataset: Dataset = {
    id: "main-events-filings",
    name: "filings",
    kind: "events",
    symbols,
    frequency: null,
    start: "2024-01-02",
    end: "2024-06-03",
    rows: 10000,
    source: "user uploaded CSV",
    verified: false,
    scope: "main",
    schema_version: "1.0.0",
    feed: "user_supplied",
    adjustment: "not_applicable",
    fill_rate: 0,
    expected_rows: null,
    missing_rows: null,
    notes: ["unverified source"],
  };
  vi.spyOn(api, "catalog").mockResolvedValue({ datasets: [dataset] });
  vi.spyOn(api, "dataset").mockResolvedValue({
    dataset,
    manifest: {},
    metadata: {},
    splits: {},
    fields: {},
    artifacts: [],
  });
  vi.spyOn(api, "preview").mockResolvedValue({
    dataset_id: dataset.id,
    rows: Array.from({ length: 500 }, (_, index) => ({
      available_at: "2024-06-03T14:00:00Z",
      symbol: symbols[index],
      marker: index,
    })),
    splits: {},
    coverage: { observed_rows: 10000 },
    gaps: [],
    total_gaps: 0,
    holdout_sealed: true,
    downsampled: true,
  });
  vi.spyOn(api, "providers").mockResolvedValue({ providers: [] });
  render(
    <MemoryRouter>
      <DataPage />
    </MemoryRouter>,
  );
  const observations = await screen.findByRole("region", {
    name: "filings event observations",
  });
  expect(observations).toHaveAttribute("tabindex", "0");
  observations.focus();
  expect(observations).toHaveFocus();
  expect(within(observations).getAllByRole("row")).toHaveLength(501);
  expect(within(observations).getAllByRole("columnheader")).toHaveLength(3);
  expect(
    screen.getByText(
      "TICKER0, TICKER1, TICKER2, TICKER3, TICKER4 · +2,777 more",
    ),
  ).toBeVisible();
  const summary = screen.getByText("All 2,782 symbols");
  expect(summary.closest("details")).not.toHaveAttribute("open");
  expect(
    screen.getByRole("region", { name: "filings symbols" }),
  ).not.toBeVisible();
  fireEvent.click(summary);
  const fullList = screen.getByRole("region", { name: "filings symbols" });
  expect(fullList).toHaveAttribute("tabindex", "0");
  expect(fullList).toHaveTextContent("TICKER2781");
  expect(
    screen.getByRole("heading", { name: "Upload event CSV" }),
  ).toBeInTheDocument();
});
