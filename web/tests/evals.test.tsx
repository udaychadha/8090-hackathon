import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../src/api";
import { EvalsPage } from "../src/pages/Evals";
import type { Check } from "../src/types";

afterEach(() => vi.restoreAllMocks());

it("renders distinct IS and OOS checks sharing one threshold without duplicate identities", async () => {
  const errors = vi.spyOn(console, "error").mockImplementation(() => {});
  const check = (scope: string): Check => ({
    key: "CONCENTRATION_MAX_SHARE",
    label: `${scope} concentration`,
    metric: `${scope.toLowerCase()}_max_window_share`,
    op: "<=",
    relative_to: null,
    default: 0.6,
    min: 0.6,
    max: 0.6,
    locked: true,
    tooltip: {
      what_it_is: `${scope} PnL concentration`,
      if_raised: "Allows a larger share.",
      if_lowered: "Allows a smaller share.",
    },
  });
  vi.spyOn(api, "evals").mockResolvedValue({
    evals: [
      {
        n: 4,
        name: "Decay",
        question: "Does it hold up out of sample?",
        settings: [],
        checks: [check("IS"), check("OOS")],
        data_scope: "IS / OOS",
        notes: [],
        source_file: "factory/evals/decay.py",
        source_code: "# retained source",
      },
    ],
    readonly: true,
    constants: { CONCENTRATION_MAX_SHARE: 0.6 },
    notes: [],
  });
  vi.spyOn(api, "profile").mockResolvedValue({
    name: "default",
    editable: false,
    values: {},
    stale: false,
  });
  render(<EvalsPage />);
  fireEvent.click(await screen.findByRole("tab", { name: /4 Decay/ }));
  const is = screen.getByRole("slider", {
    name: "IS concentration · read only",
  });
  const oos = screen.getByRole("slider", {
    name: "OOS concentration · read only",
  });
  expect(is).toBeDisabled();
  expect(oos).toBeDisabled();
  expect(is.id).not.toBe(oos.id);
  expect(document.querySelector(`label[for="${is.id}"]`)).toHaveTextContent(
    "IS concentration",
  );
  expect(document.querySelector(`label[for="${oos.id}"]`)).toHaveTextContent(
    "OOS concentration",
  );
  expect(errors).not.toHaveBeenCalled();
});
