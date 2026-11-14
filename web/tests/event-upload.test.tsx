import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../src/api";
import { EventUpload } from "../src/pages/Data";
import type { Dataset } from "../src/types";

afterEach(() => vi.restoreAllMocks());

it("uploads an explicit mapping and refreshes the returned dataset", async () => {
  const dataset = {
    id: "main-events-filings",
    name: "filings",
    rows: 2,
  } as Dataset;
  const submit = vi.spyOn(api, "uploadEvents").mockResolvedValue(dataset);
  const onUploaded = vi.fn().mockResolvedValue(undefined);
  render(<EventUpload onUploaded={onUploaded} />);
  const file = new File(
    ["released,ticker,amount\n2024-06-03T14:00Z,SPY,2"],
    "filings.csv",
    { type: "text/csv" },
  );
  fireEvent.change(screen.getByLabelText("Event CSV file"), {
    target: { files: [file] },
  });
  fireEvent.change(screen.getByLabelText("Event dataset name"), {
    target: { value: "filings" },
  });
  fireEvent.change(screen.getByLabelText("Availability column"), {
    target: { value: "released" },
  });
  fireEvent.change(screen.getByLabelText("Symbol column"), {
    target: { value: "ticker" },
  });
  fireEvent.submit(
    screen.getByRole("button", { name: "Upload event data" }).closest("form")!,
  );
  await waitFor(() => expect(onUploaded).toHaveBeenCalledWith(dataset));
  expect(submit).toHaveBeenCalledWith(file, "filings", {
    available_at: "released",
    symbol: "ticker",
  });
  expect(screen.getByRole("status")).toHaveTextContent("Unverified source");
});

it("shows server validation errors without reporting a saved dataset", async () => {
  vi.spyOn(api, "uploadEvents").mockRejectedValue(
    new Error("Availability must include a timezone"),
  );
  const onUploaded = vi.fn();
  render(<EventUpload onUploaded={onUploaded} />);
  fireEvent.change(screen.getByLabelText("Event CSV file"), {
    target: { files: [new File(["x"], "events.csv")] },
  });
  fireEvent.change(screen.getByLabelText("Event dataset name"), {
    target: { value: "events" },
  });
  fireEvent.submit(
    screen.getByRole("button", { name: "Upload event data" }).closest("form")!,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("timezone");
  expect(onUploaded).not.toHaveBeenCalled();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
