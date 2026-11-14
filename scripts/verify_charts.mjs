/** Read-only interaction checks against actual local API records. */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
const require = createRequire(new URL("../web/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const root = fileURLToPath(new URL("..", import.meta.url));
const output = `${root}/report/interactive-charts`;
await mkdir(output, { recursive: true });
const base = process.env.ARENA_UI_URL || "http://127.0.0.1:5173";
const browser = await chromium.launch({
  executablePath:
    process.env.ARENA_CHROME ||
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  headless: true,
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1060 },
  reducedMotion: "reduce",
});
const page = await context.newPage();
const errors = [];
const requests = [];
page.on("pageerror", (error) => errors.push(error.message));
page.on("request", (req) =>
  requests.push({ method: req.method(), url: req.url() }),
);
page.on("response", (res) => {
  if (res.status() >= 400 && res.url().includes("/api/"))
    errors.push(`${res.status()} ${res.url()}`);
});
const proof = { screenshots: [], checks: [], errors };
async function api(route) {
  const response = await context.request.get(base + "/api" + route);
  assert.equal(response.status(), 200);
  return response.json();
}
async function shot(name, locator = page) {
  await locator.screenshot({ path: `${output}/${name}.png` });
  proof.screenshots.push(`report/interactive-charts/${name}.png`);
}
async function hover(chart, fraction = 0.55) {
  await chart.scrollIntoViewIfNeeded();
  const box = await chart.boundingBox();
  await chart.hover({
    position: { x: 58 + (box.width - 82) * fraction, y: box.height * 0.7 },
  });
  await expect(chart.locator(".chart-crosshair")).toHaveCount(2);
  const index = Number(await chart.getAttribute("aria-valuenow"));
  return index;
}
try {
  const { rows } = await api("/leaderboard");
  let variant;
  for (const row of rows) {
    const candidate = await api(`/variants/${row.variant_id}`);
    if (candidate.equity?.dates?.length) {
      variant = candidate;
      break;
    }
  }
  assert(variant, "Recorded equity required");
  proof.variant_id = variant.variant_id;
  await page.goto(`${base}/variants/${variant.variant_id}`);
  const equity = page.getByRole("slider", { name: "Equity chart" });
  await expect(equity).toBeVisible();
  let i = await hover(equity);
  await expect(page.getByRole("status")).toContainText(variant.equity.dates[i]);
  await expect(page.getByRole("status")).toContainText(
    variant.equity.net[i].toFixed(4),
  );
  await expect(equity.locator(".chart-point")).toHaveCount(2);
  await shot("equity-hover");
  const equityWidth = (await equity.boundingBox()).width;
  const expandEquity = page.getByRole("button", {
    name: "Expand equity chart",
  });
  await expandEquity.click();
  let dialog = page.getByRole("dialog");
  const largeEquity = dialog.getByRole("slider");
  await expect(largeEquity).toBeVisible();
  assert((await largeEquity.boundingBox()).width >= equityWidth);
  await largeEquity.focus();
  await largeEquity.press("End");
  await expect(dialog.getByRole("status")).toContainText(
    variant.equity.dates.at(-1),
  );
  await largeEquity.press("ArrowLeft");
  await expect(dialog.getByRole("status")).toContainText(
    variant.equity.dates.at(-2),
  );
  await shot("equity-expanded", dialog);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(expandEquity).toBeFocused();
  proof.checks.push(
    "equity pointer values match recorded indices",
    "crosshairs and both series markers",
    "expanded equity keyboard navigation and Escape focus restoration",
  );

  await page.goto(`${base}/data`);
  const dataset = page.getByRole("slider", { name: "Dataset price chart" });
  await expect(dataset).toBeVisible({ timeout: 60000 });
  const preview = await api(
    "/data/datasets/main-1min-SPY/preview?split=visible&limit=500",
  );
  i = await hover(dataset);
  await expect(page.getByRole("status")).toContainText(
    Number(preview.rows[i].close).toLocaleString("en-US", {
      minimumFractionDigits: 4,
      maximumFractionDigits: 4,
    }),
  );
  await expect(page.getByRole("status")).toContainText("UTC");
  await shot("dataset-hover");
  const smallWidth = (await dataset.boundingBox()).width;
  const expandData = page.getByRole("button", { name: "Expand dataset chart" });
  await expandData.click();
  dialog = page.getByRole("dialog");
  const largeData = dialog.getByRole("slider");
  assert((await largeData.boundingBox()).width > smallWidth * 2);
  await hover(largeData, 0.78);
  await expect(dialog).toContainText("HOLDOUT remains sealed");
  await shot("dataset-expanded", dialog);
  await dialog.getByRole("button", { name: "Close expanded chart" }).click();
  await expect(expandData).toBeFocused();
  // A different split cannot retain the old readout.
  await page.getByLabel("Preview split").selectOption("OOS");
  await expect(page.locator('.empty[role="status"]')).toHaveCount(0, {
    timeout: 60000,
  });
  await expect(page.locator(".chart-tooltip")).toHaveCount(0);
  await dataset.focus();
  await dataset.press("Home");
  const oos = await api(
    "/data/datasets/main-1min-SPY/preview?split=OOS&limit=500",
  );
  await expect(page.getByRole("status")).toContainText(
    String(oos.rows[0].timestamp).slice(0, 10),
  );
  proof.checks.push(
    "dataset hover matches real downsampled prices",
    "dataset expansion more than doubles chart width",
    "split switch resets inspection and uses new observations",
  );

  const mobile = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 1,
  });
  const phone = await mobile.newPage();
  phone.on("pageerror", (error) => errors.push(error.message));
  await phone.goto(`${base}/data`);
  await expect(phone.getByRole("slider")).toBeVisible({ timeout: 60000 });
  await phone.getByRole("button", { name: "Switch to light theme" }).click();
  await phone.getByRole("button", { name: "Expand dataset chart" }).click();
  const mobileDialog = phone.getByRole("dialog");
  const mobileChart = mobileDialog.getByRole("slider");
  await mobileChart.tap({ position: { x: 140, y: 150 } });
  await expect(mobileDialog.getByRole("status")).toBeVisible();
  const tooltip = await mobileDialog.getByRole("status").boundingBox();
  assert(tooltip.x >= 0 && tooltip.x + tooltip.width <= 390);
  assert(
    await phone.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await shot("mobile-light-expanded", mobileDialog);
  await mobileDialog
    .getByRole("button", { name: "Close expanded chart" })
    .click();
  await expect(
    phone.getByRole("button", { name: "Expand dataset chart" }),
  ).toBeFocused();
  proof.checks.push(
    "mobile touch readout persists after tap",
    "light-theme tooltip fits viewport",
    "native dialog close restores focus on touch device",
  );
  await mobile.close();
  assert.deepEqual(errors, []);
  assert(
    requests.every((req) => req.method === "GET"),
    "Chart inspection must be read-only",
  );
  proof.checks.push("no API writes or browser errors");
  await writeFile(
    `${output}/proof.json`,
    JSON.stringify(proof, null, 2) + "\n",
  );
  console.log(JSON.stringify(proof, null, 2));
} finally {
  await browser.close();
}
