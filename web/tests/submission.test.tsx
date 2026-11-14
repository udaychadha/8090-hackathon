import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { NewRunPage } from "../src/pages/Runs";

afterEach(() => vi.unstubAllGlobals());
function Destination() {
  return <p>Opened {useParams().runId}</p>;
}
function page() {
  render(
    <MemoryRouter initialEntries={["/new"]}>
      <Routes>
        <Route path="/new" element={<NewRunPage />} />
        <Route path="/runs/:runId" element={<Destination />} />
      </Routes>
    </MemoryRouter>,
  );
}
describe("paper submission", () => {
  it("rejects non-PDF and over-limit files before sending anything", () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    page();
    fireEvent.change(screen.getByLabelText("Choose paper PDF"), {
      target: { files: [new File(["text"], "idea.csv")] },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a PDF file.");
    expect(
      screen.getByRole("button", { name: "▷ Test in arena" }),
    ).toBeDisabled();
    const large = new File(["pdf"], "large.pdf");
    Object.defineProperty(large, "size", { value: 30_000_001 });
    fireEvent.change(screen.getByLabelText("Choose paper PDF"), {
      target: { files: [large] },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("30 MB or smaller");
    expect(fetch).not.toHaveBeenCalled();
  });
  it("posts the selected PDF once and navigates using the durable run ID", async () => {
    let sent: FormData | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path: string, init: RequestInit) => {
        expect(path).toBe("/api/runs");
        expect(init.method).toBe("POST");
        sent = init.body as FormData;
        return new Response(JSON.stringify({ run_id: "r_acceptance" }), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
    page();
    const file = new File(["%PDF-1.7"], "source.pdf", {
      type: "application/pdf",
    });
    fireEvent.change(screen.getByLabelText("Choose paper PDF"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: "▷ Test in arena" }));
    await screen.findByText("Opened r_acceptance");
    expect(sent?.get("pdf")).toBe(file);
  });
  it("keeps the selected paper and surfaces an API conflict without claiming a run", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ detail: "A local run is already active" }),
            { status: 409, headers: { "Content-Type": "application/json" } },
          ),
      ),
    );
    page();
    fireEvent.change(screen.getByLabelText("Choose paper PDF"), {
      target: { files: [new File(["pdf"], "source.pdf")] },
    });
    fireEvent.click(screen.getByRole("button", { name: "▷ Test in arena" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "A local run is already active",
      ),
    );
    expect(screen.getByText("source.pdf")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "▷ Test in arena" }),
    ).toBeEnabled();
  });
});
