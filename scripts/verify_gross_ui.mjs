/** Read-only browser/API evidence from real retained gross diagnostics. No fixtures. */
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
const require = createRequire(new URL("../web/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const root = fileURLToPath(new URL("..", import.meta.url));
const output = `${root}/report/gross-diagnostics-ui`;
const base = process.env.ARENA_UI_URL || "http://127.0.0.1:5173";
await mkdir(output, { recursive: true });
const proof = { started_at: new Date().toISOString(), base, data_source: "real local API; no request substitution", variants: [], checks: [], screenshots: [], writes: [], errors: [] };
const browser = await chromium.launch({headless: true, executablePath: process.env.ARENA_CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"});
async function api(context, route) {
  const response = await context.request.get(`${base}/api${route}`, {timeout: 30000});
  assert.equal(response.status(), 200, route);
  return response.json();
}
const format = value => typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "—";
async function checkPanel(panel, row, label) {
  const d = row.gross_diagnostics;
  await expect(panel).toContainText("Diagnostic · 0 bps");
  if (d.label) await expect(panel.getByText(d.label, {exact:true})).toBeVisible();
  const measurements = [
    ["Base Sharpe", d.eval_3.metrics.base_sharpe], ["Worst Sharpe", d.eval_3.metrics.worst_sharpe],
    ["Worst/base", d.eval_3.metrics.worst_ratio], ["IS Sharpe", d.eval_4.metrics.is_sharpe],
    ["OOS Sharpe", d.eval_4.metrics.oos_sharpe], ["OOS/IS", d.eval_4.metrics.oos_to_is_ratio],
    ["IS 5-day concentration", d.eval_4.metrics.is_max_window_share], ["OOS 5-day concentration", d.eval_4.metrics.oos_max_window_share],
  ];
  for (const [name, value] of measurements) await expect(panel).toContainText(`${name} ${format(value)}`);
  await expect(panel).toContainText(`Sensitivity · ${d.eval_3.passed ? "pass" : "failed"}`);
  await expect(panel).toContainText(`Decay · ${d.eval_4.passed ? "pass" : "failed"}`);
  assert.equal(await panel.locator(".verified-text, .status.verified").count(), 0, "Diagnostic must stay neutral");
  const colors = await panel.evaluate(el => ({label: getComputedStyle(el.querySelector(".gross-label") || el).color, foreground: getComputedStyle(document.querySelector("main h1")).color}));
  assert.equal(colors.label, colors.foreground, "Failed diagnostic label must use neutral foreground color");
  proof.checks.push({label, variant_id: row.variant_id, measurements: Object.fromEntries(measurements), neutral_colors: colors});
}
async function layout(page, label) {
  const value = await page.evaluate(() => ({width: innerWidth, scroll_width: document.documentElement.scrollWidth, diagnostic_overflows: [...document.querySelectorAll(".gross-diagnostics")].filter(el => el.scrollWidth > el.clientWidth + 1).length}));
  assert(value.scroll_width <= value.width, `${label}: page overflow`);
  assert.equal(value.diagnostic_overflows, 0, `${label}: diagnostic overflow`);
  proof.checks.push({label, layout:value});
}
async function shot(page, name) {
  await page.screenshot({path:`${output}/${name}.png`});
  proof.screenshots.push(`report/gross-diagnostics-ui/${name}.png`);
}
try {
  const discovery = await browser.newContext();
  const {rows} = await api(discovery, "/leaderboard");
  const complete = rows.filter(row => row.status.startsWith("FAILED_EVAL") && row.gross_diagnostics?.state === "complete" && !row.notes.some(note => /control/i.test(note)));
  assert(complete.length, "At least one real failed non-control variant must have complete gross diagnostics");
  const selected = [...new Set(complete.map(row => row.gross_diagnostics.label))].map(label => complete.find(row => row.gross_diagnostics.label === label));
  for (const row of selected) {
    const detail = await api(discovery, `/variants/${row.variant_id}`);
    assert.deepEqual(detail.gross_diagnostics, row.gross_diagnostics, "API board/detail diagnostic agreement");
    proof.variants.push({variant_id: row.variant_id, run_id: row.run_id, source_title: row.source_title, status: row.status, evals_passed: row.evals_passed, notes: row.notes, gross_diagnostics: row.gross_diagnostics});
  }
  await discovery.close();
  for (const viewport of [{width:1440,height:1000},{width:390,height:844}]) {
    const size = viewport.width === 390 ? "mobile" : "desktop";
    const context = await browser.newContext({viewport,reducedMotion:"reduce"});
    const page = await context.newPage();
    page.on("pageerror", error => proof.errors.push(error.message));
    page.on("request", request => {if (!["GET","HEAD","OPTIONS"].includes(request.method())) proof.writes.push({method:request.method(),url:request.url()});});
    for (const theme of ["dark", "light"]) {
      for (const row of selected) {
        await page.goto(`${base}/leaderboard`, {waitUntil:"domcontentloaded"});
        const toggle = page.getByRole("button", {name:`Switch to ${theme} theme`});
        if (await toggle.count()) await toggle.click();
        const sourceRow = page.locator("tbody tr").filter({has: page.locator(`a[href='/variants/${row.variant_id}']`)});
        await expect(sourceRow).toHaveCount(1, {timeout:30000});
        await expect(sourceRow).toContainText(row.status);
        await expect(sourceRow).toContainText(`${row.evals_passed}/5`);
        for(const note of row.notes) await expect(sourceRow).toContainText(note);
        const panel = sourceRow.locator("xpath=following-sibling::tr[1]").getByRole("region", {name:"Gross diagnostics"});
        await checkPanel(panel,row,`${size} ${theme} leaderboard`);
        await sourceRow.scrollIntoViewIfNeeded();
        await layout(page,`${size} ${theme} leaderboard`);
        const prefix = `${size}-${theme}-${row.variant_id}`;
        await shot(page,`${prefix}-leaderboard`);
        if (size === "mobile") {
          const table = page.getByRole("region",{name:"Leaderboard results"});
          await table.focus();
          await table.evaluate(el => el.scrollLeft = el.scrollWidth);
          const scroll = await table.evaluate(el => ({left:el.scrollLeft,max:el.scrollWidth-el.clientWidth}));
          assert(scroll.left > 0 && scroll.left === scroll.max);
          proof.checks.push({label:`${prefix}: mobile table scroll`,...scroll});
          await shot(page,`${prefix}-leaderboard-scrolled`);
        }
        await page.goto(`${base}/variants/${row.variant_id}`,{waitUntil:"domcontentloaded"});
        const detailPanel = page.getByRole("region",{name:"Gross diagnostics"});
        await expect(detailPanel).toBeVisible({timeout:30000});
        await checkPanel(detailPanel,row,`${size} ${theme} tearsheet`);
        await expect(page.locator("main .page-title")).toContainText(row.status);
        await expect(page.locator("main .page-title")).toContainText(`${row.evals_passed}/5`);
        for(const note of row.notes) await expect(page.locator("main")).toContainText(note);
        await layout(page,`${size} ${theme} tearsheet`);
        await page.evaluate(()=>scrollTo(0,0));
        await shot(page,`${prefix}-tearsheet-verdict`);
        await detailPanel.scrollIntoViewIfNeeded();
        await shot(page,`${prefix}-tearsheet-gross`);
      }
    }
    await context.close();
  }
  assert.deepEqual(proof.writes,[],"No API writes allowed");
  assert.deepEqual(proof.errors,[],"No browser errors allowed");
  proof.finished_at = new Date().toISOString();
  proof.passed = true;
} catch(error) {
  proof.passed = false;
  proof.errors.push(error.stack);
  process.exitCode = 1;
} finally {
  await writeFile(`${output}/proof.json`,JSON.stringify(proof,null,2)+"\n");
  console.log(JSON.stringify({passed:proof.passed,variants:proof.variants.map(v=>v.variant_id),checks:proof.checks.length,screenshots:proof.screenshots.length,errors:proof.errors,writes:proof.writes},null,2));
  await browser.close();
}
