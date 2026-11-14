/** Read-only checks of actual WO-12 event data and control records. */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
const require = createRequire(new URL("../web/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const root = fileURLToPath(new URL("..", import.meta.url));
const output = `${root}/report/wo12-ui`;
await mkdir(output, { recursive: true });
const base = process.env.ARENA_UI_URL || "http://127.0.0.1:5173";
const browser = await chromium.launch({ executablePath: process.env.ARENA_CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
const proof = { checks: [], findings: [], screenshots: [], errors: [], writes: [] };
async function api(context, route) {
  let error;
  for (let attempt = 0; attempt < 6; attempt++) {
    try {
      const response = await context.request.get(`${base}/api${route}`, { timeout: 15000 });
      assert.equal(response.status(), 200, route);
      return await response.json();
    } catch (e) { error = e; await new Promise(r => setTimeout(r, 2000)); }
  }
  throw error;
}
async function capture(page, name) {
  await page.screenshot({ path: `${output}/${name}.png` });
  proof.screenshots.push(`report/wo12-ui/${name}.png`);
}
async function checkOverflow(page, label) {
  const result = await page.evaluate(() => ({ width: innerWidth, scrollWidth: document.documentElement.scrollWidth, offenders: [...document.querySelectorAll("main *")].filter(e => { const r = e.getBoundingClientRect(); return r.right > innerWidth + 1 && !e.closest(".table-wrap, pre"); }).slice(0, 8).map(e => ({ tag: e.tagName, class: e.className, text: e.textContent.slice(0, 100) })) }));
  if (result.scrollWidth > result.width) proof.findings.push({ label, ...result });
  else proof.checks.push(`${label}: no page overflow`);
}
try {
  for (const viewport of [{ width: 1440, height: 1060 }, { width: 390, height: 844 }]) {
    const size = viewport.width === 390 ? "mobile" : "desktop";
    const context = await browser.newContext({ viewport, reducedMotion: "reduce", isMobile: size === "mobile", hasTouch: size === "mobile" });
    const page = await context.newPage();
    page.on("pageerror", e => proof.errors.push(e.message));
    page.on("request", req => { if (!["GET", "HEAD", "OPTIONS"].includes(req.method())) proof.writes.push({ method: req.method(), url: req.url() }); });
    const catalog = await api(context, "/data/catalog");
    const event = catalog.datasets.find(d => d.name === "congress_trades");
    assert(event, "Real Congress event dataset must exist");
    assert.equal(event.kind, "events");
    assert.equal(event.verified, false);
    const preview = await api(context, `/data/datasets/${event.id}/preview?split=visible&limit=500`);
    assert(preview.holdout_sealed);
    assert(preview.rows.length <= 500);
    const cutoff = preview.splits.HOLDOUT.start;
    assert(preview.rows.every(r => Date.parse(r.available_at) < Date.parse(cutoff)), "No HOLDOUT event rows");
    proof.dataset = { id: event.id, preview_rows: preview.rows.length, holdout_start: cutoff, first_available_at: preview.rows[0]?.available_at, last_available_at: preview.rows.at(-1)?.available_at };
    await page.goto(`${base}/data`);
    await page.getByLabel("Search datasets").fill("congress_trades");
    await page.getByRole("button", { name: "congress_trades", exact: true }).click();
    const panel = page.locator(".dataset-preview");
    await expect(panel.getByRole("heading", { name: "congress_trades", exact: true })).toBeVisible();
    await expect(panel.locator("tbody tr")).toHaveCount(preview.rows.length, { timeout: 60000 });
    await expect(panel.getByText("Unverified source", { exact: true })).toBeVisible();
    await expect(panel.getByRole("slider")).toHaveCount(0);
    await expect(panel).toContainText("HOLDOUT is sealed");
    await expect(panel).toContainText("available_at");
    const tableLayout = await panel.locator(".table-wrap").first().evaluate(e => ({ height: e.getBoundingClientRect().height, scrollHeight: e.scrollHeight, maxHeight: getComputedStyle(e).maxHeight, pageHeight: document.documentElement.scrollHeight }));
    proof[`${size}_event_table_layout`] = tableLayout;
    if (tableLayout.height > 5000) proof.findings.push({ label: `${size}: event table has no vertical bound; upload form follows all 500 rows`, ...tableLayout });
    for (const theme of ["dark", "light"]) {
      const toggle = page.getByRole("button", { name: `Switch to ${theme} theme` });
      if (await toggle.count()) await toggle.click();
      await page.evaluate(() => scrollTo(0, 0));
      await checkOverflow(page, `${size} ${theme} data`);
      await capture(page, `${size}-${theme}-data-overview`);
      await panel.getByRole("heading").scrollIntoViewIfNeeded();
      await capture(page, `${size}-${theme}-event-preview`);
      await panel.locator("table").evaluate(e => scrollTo(0, scrollY + e.getBoundingClientRect().top - 24));
      await capture(page, `${size}-${theme}-event-rows`);
      const upload = page.getByRole("heading", { name: "Upload event CSV" });
      await upload.scrollIntoViewIfNeeded();
      await expect(page.getByLabel("Event CSV file")).toBeVisible();
      await expect(page.getByLabel("Event dataset name")).toBeVisible();
      await expect(page.getByLabel("Availability column")).toHaveValue("available_at");
      await expect(page.getByLabel("Symbol column")).toHaveValue("symbol");
      await expect(page.getByRole("button", { name: "Upload event data" })).toBeDisabled();
      await page.getByLabel("Event dataset name").fill("invalid-name");
      assert(await page.getByLabel("Event dataset name").evaluate(e => e.validity.patternMismatch));
      await page.getByLabel("Event dataset name").fill("");
      await capture(page, `${size}-${theme}-upload-form`);
    }
    proof.checks.push(`${size}: real bounded event table; no price chart; unverified source and sealed holdout labels; upload required fields and name pattern`);
    const control = await api(context, "/variants/r_75d07564e86a_A");
    proof.control = { variant_id: control.variant_id, status: control.status, evals_passed: control.evals_passed, notes: control.notes };
    await page.goto(`${base}/variants/r_75d07564e86a_A`);
    await expect(page.getByRole("slider", { name: "Equity chart" })).toBeVisible({ timeout: 60000 });
    await expect(page.locator("main")).toContainText(/control/i);
    for (const theme of ["dark", "light"]) {
      const toggle = page.getByRole("button", { name: `Switch to ${theme} theme` });
      if (await toggle.count()) await toggle.click();
      await checkOverflow(page, `${size} ${theme} control tearsheet`);
      await capture(page, `${size}-${theme}-control-tearsheet`);
    }
    const runs = await api(context, "/runs");
    const active = runs.runs.find(r => !r.voided && /congress/i.test(r.source?.title || "") && r.status === "RUNNING");
    proof.active_run = active ? { run_id: active.run_id, status: active.status } : null;
    if (active) {
      await page.goto(`${base}/runs/${active.run_id}`);
      await expect(page.locator("main")).toContainText(active.source.title, { timeout: 60000 });
      await checkOverflow(page, `${size} active Congress run`);
      await capture(page, `${size}-live-congress-run`);
    }
    await page.goto(`${base}/new`);
    await expect(page.locator("main")).toContainText(/paper/i);
    await checkOverflow(page, `${size} new run`);
    await capture(page, `${size}-new-run`);
    await context.close();
  }
  assert.deepEqual(proof.writes, [], "UI verification must not write data");
} catch (error) {
  proof.errors.push(error.stack);
  process.exitCode = 1;
} finally {
  await writeFile(`${output}/proof.json`, JSON.stringify(proof, null, 2) + "\n");
  console.log(JSON.stringify(proof, null, 2));
  await browser.close();
}
