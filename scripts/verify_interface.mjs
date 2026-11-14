/** Real-browser acceptance against the local API. No fabricated research fixtures.
 * Usage: node scripts/verify_interface.mjs [--submit papers/approved-paper.pdf]
 * The default is read-only. --submit starts one real, billable pipeline run.
 */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const require = createRequire(new URL("../web/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const base = process.env.ARENA_UI_URL || "http://127.0.0.1:5173";
const output = path.join(root, "report", "wo08-browser");
const submitIndex = process.argv.indexOf("--submit");
const paper = submitIndex < 0 ? null : process.argv[submitIndex + 1];
assert(
  submitIndex < 0 || paper,
  "--submit requires an approved local PDF path",
);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  executablePath:
    process.env.ARENA_CHROME ||
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1060 },
  reducedMotion: "reduce",
});
await context.addInitScript(() => {
  window.__arenaStreamProof = [];
  const NativeEventSource = window.EventSource;
  window.EventSource = class extends NativeEventSource {
    constructor(...args) {
      super(...args);
      this.addEventListener("message", (message) => {
        try {
          const event = JSON.parse(message.data);
          window.__arenaStreamProof.push({
            seq: event.seq,
            run_id: event.run_id,
            stage: event.stage,
            status: event.status,
            variant: event.variant,
          });
        } catch {
          /* The application reports malformed events separately. */
        }
      });
    }
  };
});
const page = await context.newPage();
const errors = [];
page.on("pageerror", (error) =>
  errors.push({ kind: "pageerror", message: error.message }),
);
page.on("console", (message) => {
  if (message.type() === "error")
    errors.push({ kind: "console", message: message.text() });
});
page.on("response", (response) => {
  if (response.url().includes("/api/") && response.status() >= 400)
    errors.push({
      kind: "http",
      status: response.status(),
      path: new URL(response.url()).pathname,
    });
});
const proof = {
  started_at: new Date().toISOString(),
  base,
  screens: [],
  runs: [],
  errors,
};
async function api(route) {
  const response = await context.request.get(`${base}/api${route}`);
  assert.equal(response.status(), 200, `${route}: HTTP ${response.status()}`);
  return response.json();
}
async function settled(route) {
  await page.goto(`${base}${route}`, { waitUntil: "domcontentloaded" });
  await expect(page.locator("main h1").first()).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByRole("status")).toHaveCount(0, { timeout: 60_000 });
  await expect(page.getByRole("alert")).toHaveCount(0);
}
async function shot(name, fullPage = true) {
  const filename = `${name}.png`;
  await page.screenshot({ path: path.join(output, filename), fullPage });
  return `report/wo08-browser/${filename}`;
}
async function assertVariant(row) {
  await expect(page.locator("main")).toContainText(row.status);
  await expect(page.locator("main")).toContainText(row.test_type);
  await expect(page.locator("main")).toContainText(`${row.evals_passed}/5`);
  for (const note of row.notes)
    await expect(page.locator("main")).toContainText(note);
}

try {
  const [{ runs }, { runs: allRuns }, { rows }] = await Promise.all([
    api("/runs"),
    api("/runs?include_voided=true"),
    api("/leaderboard"),
  ]);
  assert(runs.every((run) => !run.voided));
  assert(rows.every((row) => !row.voided));
  const sampleRun =
    runs.find((run) =>
      run.variants.some((v) => v.status === "FAILED_EVAL_2"),
    ) || runs.find((run) => run.variants.length);
  const sampleVariant =
    sampleRun.variants.find((v) => v.status === "FAILED_EVAL_2") ||
    sampleRun.variants[0];
  assert(sampleVariant, "Acceptance requires retained variants");
  proof.baseline = {
    visible_runs: runs.length,
    retained_runs: allRuns.length,
    visible_variants: rows.length,
    verified: rows.filter((row) => row.status === "VERIFIED").length,
  };

  for (const [name, route] of [
    ["1-run", `/runs/${sampleRun.run_id}`],
    ["2-leaderboard", "/leaderboard"],
    ["3-tearsheet", `/variants/${sampleVariant.variant_id}`],
    ["4-graveyard", "/graveyard"],
    ["5-new-run", "/new"],
    ["6-evals", "/evals"],
    ["7-data", "/data"],
  ]) {
    await settled(route);
    if (name === "1-run" || name === "3-tearsheet")
      await assertVariant(sampleVariant);
    if (name === "5-new-run") {
      await expect(page.getByLabel("Choose paper PDF")).toBeEnabled();
      await expect(
        page.getByRole("button", { name: "▷ Test in arena", exact: true }),
      ).toBeDisabled();
      await expect(page.getByLabel("Describe a strategy")).toBeDisabled();
    }
    if (name === "6-evals") {
      await expect(page.locator("main")).toContainText("Not available yet");
      assert.equal(await page.locator("input[type=range]:enabled").count(), 0);
    }
    if (name === "7-data") {
      await expect(page.locator("main")).toContainText("HOLDOUT");
      await page.getByRole("tab", { name: "Evidence", exact: true }).click();
      await expect(
        page.getByRole("heading", { name: "Evidence browser" }),
      ).toBeVisible();
      await expect(page.getByRole("status")).toHaveCount(0, {
        timeout: 60_000,
      });
      await expect(
        page.locator(".evidence-browser tbody tr").first(),
      ).toBeVisible();
      await shot("data-evidence");
      await page.getByRole("tab", { name: "Catalog", exact: true }).click();
      await expect(
        page.getByRole("button", { name: "main/1min/SPY", exact: true }),
      ).toBeVisible();
      await expect(
        page.getByRole("img", { name: /^Visible IS and OOS prices from / }),
      ).toBeVisible({ timeout: 60_000 });
      await expect(page.getByRole("status")).toHaveCount(0, {
        timeout: 60_000,
      });
    }
    for (const pill of await page.locator(".status.verified").all())
      await expect(pill).toHaveText("VERIFIED");
    proof.screens.push({
      name,
      route,
      title: await page.locator("main h1").first().innerText(),
      screenshot: await shot(name),
    });
    console.log(`Checked ${name}: ${route}`);
  }
  await settled("/leaderboard");
  await page
    .getByRole("combobox", { name: "Status", exact: true })
    .selectOption("VERIFIED");
  if (!rows.some((row) => row.status === "VERIFIED"))
    await expect(
      page.getByText("No variants match these filters."),
    ).toBeVisible();
  await page
    .getByRole("combobox", { name: "Status", exact: true })
    .selectOption("INACTIVE");
  await expect(page.locator("tbody tr")).toHaveCount(
    rows.filter((row) => row.status === "INACTIVE").length,
  );
  await settled("/evals");
  const evals = await api("/evals/schema");
  for (let i = 0; i < evals.evals.length; i++) {
    await page.locator(".eval-list button").nth(i).click();
    await expect(page.locator("main")).toContainText(evals.evals[i].question);
  }
  await settled("/data?tab=evidence");
  await page.getByLabel("Search evidence").fill("docs/DATA.md");
  await page.getByRole("button", { name: "docs/DATA.md", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("dialog").locator("pre")).toContainText(
    "session_date",
  );
  await page.getByRole("button", { name: "Close artifact preview" }).click();
  for (const tab of ["Ingest log", "Audits", "Data contract", "Universe"]) {
    await page.getByRole("tab", { name: tab, exact: true }).click();
    await expect(page.getByRole("status")).toHaveCount(0, { timeout: 60_000 });
    await expect(page.getByRole("alert")).toHaveCount(0);
  }
  proof.filters_and_evidence_checked = true;
  for (const run of allRuns) {
    const detail = await api(
      `/runs/${run.run_id}?include_voided=${run.voided}`,
    );
    await settled(
      `/runs/${run.run_id}${run.voided ? "?include_voided=true" : ""}`,
    );
    await expect(page.locator("main")).toContainText(run.status);
    if (detail.source)
      await expect(
        page
          .getByRole("combobox", { name: "Open run", exact: true })
          .locator("option:checked"),
      ).toContainText(detail.source.title);
    for (const variant of run.variants) await assertVariant(variant);
    if (run.voided)
      await expect(page.locator("main")).toContainText(run.void_reason);
    for (const variant of run.variants) {
      await page
        .getByRole("tab", { name: new RegExp(`^${variant.variant}\\s`) })
        .click();
      await expect(page.locator("main")).toContainText("steps & repairs");
      const steps = detail.variants.find(
        (row) => row.variant_id === variant.variant_id,
      ).steps;
      for (let i = 0; i < steps.length; i++) {
        await page.locator(".pipeline-nodes button").nth(i).click();
        const panel = page.getByRole("region", {
          name: `${steps[i].label} details`,
          exact: true,
        });
        await expect(panel).toBeVisible();
        for (const line of steps[i].details)
          await expect(panel).toContainText(line);
      }
      await page.getByRole("tab", { name: /^Overview/ }).click();
    }
    proof.runs.push({
      run_id: run.run_id,
      status: run.status,
      variants: run.variants.length,
      voided: run.voided,
      screenshot: await shot(`run-${run.run_id}`, false),
    });
    console.log(`Checked historical run ${run.run_id}`);
  }
  await settled("/runs");
  await expect(page.locator("tbody tr")).toHaveCount(runs.length);
  await page.getByRole("checkbox", { name: /Include voided records/ }).click();
  await expect(
    page.getByRole("checkbox", { name: /Include voided records/ }),
  ).toBeChecked();
  await expect(page.locator("tbody tr")).toHaveCount(allRuns.length);
  proof.audit_toggle_verified = true;

  await page.setViewportSize({ width: 390, height: 844 });
  for (const route of ["/new", "/data", `/runs/${sampleRun.run_id}`]) {
    await settled(route);
    const width = await page.evaluate(() => ({
      content: document.documentElement.scrollWidth,
      viewport: innerWidth,
    }));
    assert(
      width.content <= width.viewport + 1,
      `${route} overflows the mobile viewport: ${JSON.stringify(width)}`,
    );
    await shot(`mobile-${route.split("/")[1]}`, false);
  }
  proof.mobile_checked = true;
  await page.setViewportSize({ width: 1440, height: 1060 });

  if (paper) {
    await settled("/new");
    await page
      .getByLabel("Choose paper PDF")
      .setInputFiles(path.resolve(root, paper));
    await page
      .getByRole("button", { name: "▷ Test in arena", exact: true })
      .click();
    await page.waitForURL(/\/runs\/r_[a-f0-9]+$/, { timeout: 60_000 });
    const runId = new URL(page.url()).pathname.split("/").at(-1);
    const started = Date.now();
    proof.submission = {
      run_id: runId,
      paper: path.basename(paper),
      started_at: new Date().toISOString(),
      observations: [],
    };
    await expect(page.locator("main h1")).toContainText(runId, {
      timeout: 30_000,
    });
    await shot("8-new-run-started", false);
    let previous = "",
      final;
    for (;;) {
      const run = await api(`/runs/${runId}`);
      const signature = JSON.stringify({
        status: run.status,
        variants: run.variants.map((v) => ({
          variant: v.variant,
          status: v.status,
          evals_passed: v.evals_passed,
        })),
      });
      if (signature !== previous) {
        console.log(`Live ${runId}: ${signature}`);
        proof.submission.observations.push({
          elapsed_seconds: (Date.now() - started) / 1000,
          ...JSON.parse(signature),
        });
        previous = signature;
        await shot("9-new-run-progress", false);
      }
      if (run.status !== "RUNNING") {
        final = run;
        break;
      }
      assert(
        Date.now() - started < 60 * 60 * 1000,
        "Real run exceeded the one-hour observation limit; it remains running server-side",
      );
      await new Promise((resolve) => setTimeout(resolve, 5000));
    }
    await expect(page.locator(".page-title .status")).toHaveText(final.status, {
      timeout: 30_000,
    });
    await expect(
      page
        .getByRole("combobox", { name: "Open run", exact: true })
        .locator("option:checked"),
    ).toContainText(final.source?.title ?? final.submission.upload_name);
    for (const variant of final.variants) await assertVariant(variant);
    const stream = await page.evaluate(() => window.__arenaStreamProof);
    assert(
      stream.some(
        (event) => event.run_id === runId && event.stage !== "intake",
      ),
      "The browser must receive live pipeline events",
    );
    assert(
      stream.some((event) => event.run_id === runId && event.stage === "done"),
      "The browser must receive the terminal event",
    );
    proof.submission.stream = stream;
    proof.submission.status = final.status;
    proof.submission.wall_seconds = final.wall_seconds;
    proof.submission.estimated_model_cost_usd = final.estimated_model_cost_usd;
    proof.submission.cost_complete = final.cost_complete;
    proof.submission.variants = await Promise.all(
      final.variants.map(async (row) => {
        const detail = await api(`/variants/${row.variant_id}`);
        return {
          variant: row.variant,
          status: row.status,
          evals_passed: row.evals_passed,
          test_type: row.test_type,
          days_traded: row.days_traded,
          activity: detail.activity,
        };
      }),
    );
    proof.submission.screenshot = await shot("10-new-run-completed");
    assert.equal(
      final.status,
      "COMPLETED",
      "The real paper must complete its pipeline, regardless of research verdicts",
    );
  }
  assert.deepEqual(errors, [], "Browser errors or failed API requests");
  proof.finished_at = new Date().toISOString();
  proof.passed = true;
} catch (error) {
  proof.passed = false;
  proof.failure = String(error.stack).slice(0, 4000);
  await shot("failure", false).catch(() => {});
  process.exitCode = 1;
} finally {
  await writeFile(
    path.join(output, paper ? "real-run-proof.json" : "read-only-proof.json"),
    JSON.stringify(proof, null, 2) + "\n",
  );
  await browser.close();
}
console.log(
  JSON.stringify(
    {
      passed: proof.passed,
      screens: proof.screens.length,
      historical_runs: proof.runs.length,
      new_run: proof.submission?.run_id,
      failure: proof.failure?.slice(0, 1500),
    },
    null,
    2,
  ),
);
