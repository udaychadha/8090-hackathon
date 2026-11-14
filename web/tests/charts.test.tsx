import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { DatasetChart, EquityChart } from "../src/components/Charts";

it("does not invent an equity curve when execution produced none", () => {
  render(<EquityChart equity={null} />);
  expect(
    screen.getByText("No equity curve was recorded for this variant."),
  ).toBeVisible();
  expect(document.querySelector("svg")).toBeNull();
});
it("seals the holdout region and draws prices only from returned visible observations", () => {
  render(
    <DatasetChart
      preview={{
        dataset_id: "data",
        rows: [
          { timestamp: "2020-01-01", close: 10, volume: 2 },
          { timestamp: "2020-01-02", close: 20, volume: 3 },
        ],
        splits: { IS: { end: "2020-01-01" }, HOLDOUT: { start: "2020-01-03" } },
        coverage: { split: "visible" },
        gaps: [],
        total_gaps: 0,
        holdout_sealed: true,
        downsampled: false,
      }}
    />,
  );
  expect(screen.getByText("HOLDOUT")).toBeVisible();
  expect(screen.getByText("sealed")).toBeVisible();
  const d = document.querySelector(".line-net")?.getAttribute("d") ?? "";
  expect(d).toContain("395.00");
  expect(d).not.toContain("410.00");
});
