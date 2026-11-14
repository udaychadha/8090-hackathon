import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeAll, expect, it, vi } from "vitest";
import { DatasetChart, EquityChart } from "../src/components/Charts";
import type { DatasetPreview, Equity } from "../src/types";

beforeAll(() => {
  // jsdom has no modal implementation; native focus containment is browser-tested.
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  window.PointerEvent = MouseEvent as typeof PointerEvent;
});
const equity: Equity = {
  dates: ["2024-01-02", "2024-01-03", "2024-01-12"],
  gross: [1, 1.2, 1.1],
  net: [1, 1.1, 0.9],
  is_end: "2024-01-03",
  oos_end: "2024-01-12",
};
const preview: DatasetPreview = {
  dataset_id: "SPY",
  rows: [
    {
      timestamp: "2024-01-02T14:30:00Z",
      close: 100,
      volume: 0,
      is_filled: true,
    },
    {
      timestamp: "2024-01-03T14:30:00Z",
      close: 110,
      volume: 1234,
      is_filled: false,
    },
    { timestamp: "2024-01-12T14:30:00Z", close: 90 },
  ],
  splits: {
    IS: { end: "2024-01-03T14:30:00Z" },
    HOLDOUT: { start: "2024-01-13" },
  },
  coverage: { split: "visible" },
  gaps: [],
  total_gaps: 0,
  holdout_sealed: true,
  downsampled: true,
};
function selectLast(name: string) {
  const chart = screen.getByRole("slider", { name });
  fireEvent.focus(chart);
  fireEvent.keyDown(chart, { key: "End" });
  return chart;
}
it("inspects actual gross/net equity, deltas and solid markers with keyboard", () => {
  render(<EquityChart equity={equity} />);
  const chart = selectLast("Equity chart");
  const detail = screen.getByRole("status");
  expect(detail).toHaveTextContent("2024-01-12");
  expect(detail).toHaveTextContent("0.9000");
  expect(detail).toHaveTextContent("−10.00%");
  expect(detail).toHaveTextContent("0.2000");
  expect(chart).toHaveAttribute("aria-valuenow", "2");
  expect(chart.querySelectorAll(".chart-crosshair")).toHaveLength(2);
  expect(chart.querySelectorAll(".chart-point")).toHaveLength(2);
  fireEvent.keyDown(chart, { key: "ArrowLeft" });
  expect(detail).toHaveTextContent("2024-01-03");
  expect(detail).toHaveTextContent("+10.00%");
  fireEvent.keyDown(chart, { key: "Home" });
  expect(detail).toHaveTextContent("2024-01-02");
  expect(detail).toHaveTextContent("Unavailable");
});
it("snaps by timestamp across irregular gaps and clears mouse inspection on leave", () => {
  render(<EquityChart equity={equity} />);
  const chart = screen.getByRole("slider", { name: "Equity chart" });
  vi.spyOn(chart, "getBoundingClientRect").mockReturnValue({
    left: 0,
    top: 0,
    width: 960,
    height: 360,
    right: 960,
    bottom: 360,
    x: 0,
    y: 0,
    toJSON() {},
  });
  // Around the midpoint of time, Jan 3 is closer than Jan 12.
  fireEvent.pointerMove(chart, { clientX: 400, clientY: 160 });
  expect(screen.getByRole("status")).toHaveTextContent("2024-01-03");
  fireEvent.pointerLeave(chart);
  expect(screen.queryByRole("status")).toBeNull();
});
it("labels a daily equity point at the split as a boundary day, not pure IS", () => {
  render(<EquityChart equity={equity} />);
  const chart = selectLast("Equity chart");
  fireEvent.keyDown(chart, { key: "ArrowLeft" });
  expect(screen.getByRole("status")).toHaveTextContent("IS/OOS boundary day");
});
it("enlarges the chart and restores focus when closed", () => {
  render(<EquityChart equity={equity} />);
  const expand = screen.getByRole("button", { name: "Expand equity chart" });
  expand.focus();
  fireEvent.click(expand);
  const dialog = screen.getByRole("dialog", { name: "Equity" });
  expect(within(dialog).getByRole("slider")).toBeVisible();
  fireEvent(dialog, new Event("cancel", { bubbles: true, cancelable: true }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(expand).toHaveFocus();
});
it("displays sampled data units, exact UTC time and missing volume honestly", () => {
  render(<DatasetChart preview={preview} />);
  const chart = selectLast("Dataset price chart");
  expect(screen.getByRole("status")).toHaveTextContent(
    "2024-01-12 14:30:00 UTC",
  );
  expect(screen.getByRole("status")).toHaveTextContent("90.0000");
  expect(screen.getByRole("status")).toHaveTextContent("Previous shown");
  expect(screen.getByRole("status")).toHaveTextContent("Unavailable");
  expect(screen.getByText(/Downsampled/)).toBeVisible();
  expect(screen.getByText(/HOLDOUT remains sealed/)).toBeVisible();
  fireEvent.keyDown(chart, { key: "Home" });
  expect(screen.getByRole("status")).toHaveTextContent("Locally filled");
  expect(screen.getByRole("status")).toHaveTextContent("0 shares");
});
it("handles one flat point without NaN or imaginary deltas", () => {
  render(<DatasetChart preview={{ ...preview, rows: [preview.rows[0]] }} />);
  const chart = selectLast("Dataset price chart");
  expect(chart.innerHTML).not.toMatch(/NaN|Infinity/);
  expect(chart.querySelector(".chart-point")).not.toBeNull();
  expect(screen.getByRole("status")).toHaveTextContent("Unavailable");
  fireEvent.keyDown(chart, { key: "ArrowRight" });
  expect(chart).toHaveAttribute("aria-valuenow", "0");
});
it("resets inspection when the dataset or visible split changes", () => {
  const { rerender } = render(<DatasetChart preview={preview} />);
  selectLast("Dataset price chart");
  rerender(
    <DatasetChart
      preview={{ ...preview, dataset_id: "QQQ", rows: [preview.rows[0]] }}
    />,
  );
  expect(screen.queryByRole("status")).toBeNull();
});
it("never selects a time in the sealed holdout beyond the returned points", () => {
  render(<DatasetChart preview={preview} />);
  const chart = selectLast("Dataset price chart");
  fireEvent.keyDown(chart, { key: "ArrowRight" });
  expect(chart).toHaveAttribute("aria-valuenow", "2");
  expect(screen.getByRole("status")).not.toHaveTextContent("2024-01-13");
});
