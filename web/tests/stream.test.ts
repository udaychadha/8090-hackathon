import { afterEach, expect, it, vi } from "vitest";
import { subscribeRun } from "../src/api";

afterEach(() => vi.unstubAllGlobals());
it("resumes at the supplied cursor, ignores duplicate replay and closes on terminal evidence", () => {
  let instance: FakeSource;
  class FakeSource {
    url: string;
    onopen: (() => void) | null = null;
    onmessage: ((message: { data: string }) => void) | null = null;
    onerror: (() => void) | null = null;
    closed = false;
    constructor(url: string) {
      this.url = url;
      instance = this;
    }
    close() {
      this.closed = true;
    }
  }
  vi.stubGlobal("EventSource", FakeSource);
  const recorded: number[] = [];
  const states: string[] = [];
  const stop = subscribeRun(
    "r_active",
    false,
    12,
    (e) => recorded.push(e.seq),
    (s) => states.push(s),
  );
  expect(instance!.url).toContain("after_seq=12");
  const send = (seq: number, stage = "eval") =>
    instance!.onmessage?.({ data: JSON.stringify({ seq, stage }) });
  send(12);
  send(13);
  send(13);
  send(14, "done");
  expect(recorded).toEqual([13, 14]);
  expect(instance!.closed).toBe(true);
  expect(states.at(-1)).toContain("Run finished");
  stop();
});
