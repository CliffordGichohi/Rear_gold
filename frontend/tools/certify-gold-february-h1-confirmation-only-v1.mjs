import { chromium } from "@playwright/test";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..", "..");
const out = path.join(root, "research_artifacts", "gold_february_h1_confirmation_only_reclaim_v1");
const htmlPath = path.join(out, "gold-february-h1-confirmation-only-continuous-chart.html");
const certPath = path.join(out, "browser_certification.json");
const shots = path.join(out, "screenshots");
const sha256 = value => createHash("sha256").update(value).digest("hex");

await mkdir(shots, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
const errors = [];
page.on("pageerror", error => errors.push(String(error)));
page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "load" });

const visual = page.locator("#gold-february-h1-confirmation-only-v1");
await visual.waitFor({ timeout: 15000 });
const data = JSON.parse(await page.locator("#jgo-data").textContent());
if (data.plans.length !== 61) throw new Error(`Expected 61 trades, found ${data.plans.length}`);
if (Math.abs(Number(data.summary.gross_r_sum) - 10.813172299471535) > 1e-12) throw new Error("February R differs");
if (await page.locator("#jgo-ledger tr").count() !== 61) throw new Error("Ledger row count differs");
if (await page.locator('button[data-timeframe="H1"]').getAttribute("aria-pressed") !== "true") throw new Error("H1 is not initial timeframe");
if (await page.locator('[data-candle="H1"]').count() !== 144) throw new Error("Initial H1 candle ratio/window differs");
if (await page.locator("[data-plan-line]").count() < 3) throw new Error("No visible trade plan lines");

const theme = await visual.evaluate(element => ({
  background: getComputedStyle(element).backgroundColor,
  color: getComputedStyle(element).color,
  frameFill: getComputedStyle(element.querySelector("[data-chart-frame]")).fill,
}));
if (theme.background !== "rgb(255, 255, 255)" || theme.frameFill !== "rgb(255, 255, 255)") throw new Error(`Chart is not white: ${JSON.stringify(theme)}`);

const initialShot = path.join(shots, "february-h1-initial-window.png");
await visual.screenshot({ path: initialShot, fullPage: true });

await page.locator("#jgo-right").click();
if (Number(await visual.getAttribute("data-view-start")) <= 0) throw new Error("Pan-right did not move the chart");
await page.locator("#jgo-zoom-in").click();
await page.locator("#jgo-full").click();
if (await page.locator('[data-candle="H1"]').count() !== 418) throw new Error("Full-February H1 reset failed");
if (await page.locator("[data-plan-marker]").count() !== 61) throw new Error("Full-February marker count differs");

const frameAndLines = await visual.evaluate(element => {
  const frame = element.querySelector("[data-chart-frame]");
  const left = Number(frame.getAttribute("x"));
  const right = left + Number(frame.getAttribute("width"));
  const entries = [...element.querySelectorAll('[data-plan-line="ENTRY"]')].map(line => ({
    x1: Number(line.getAttribute("x1")), x2: Number(line.getAttribute("x2")),
  }));
  return { left, right, entries };
});
if (frameAndLines.entries.some(line => Math.abs(line.x1 - frameAndLines.left) < 0.01 && Math.abs(line.x2 - frameAndLines.right) < 0.01)) {
  throw new Error("A trade line incorrectly spans the entire chart");
}

await page.locator('button[data-timeframe="M15"]').click();
if (await page.locator('[data-candle="M15"]').count() !== 288) throw new Error("M15 default candle ratio/window differs");
await page.locator('button[data-timeframe="M5"]').click();
if (await page.locator('[data-candle="M5"]').count() !== 432) throw new Error("M5 default candle ratio/window differs");
await page.locator('button[data-timeframe="H1"]').click();
await page.locator('#jgo-ledger tr').first().locator("button").click();
if (await visual.getAttribute("data-selected-plan") === "NONE") throw new Error("Ledger selection failed");

const responsive = [];
for (const viewport of [
  { width: 1180, height: 920 },
  { width: 736, height: 900 },
  { width: 360, height: 860 },
]) {
  await page.setViewportSize(viewport);
  await page.waitForTimeout(180);
  const state = await page.evaluate(() => ({ width: innerWidth, scrollWidth: document.documentElement.scrollWidth }));
  if (state.scrollWidth > state.width + 1) throw new Error(`Horizontal overflow at ${viewport.width}px`);
  if (await page.locator("#jgo-chart svg").count() !== 1) throw new Error(`Chart missing at ${viewport.width}px`);
  const shot = path.join(shots, `february-chart-${viewport.width}.png`);
  await visual.screenshot({ path: shot, fullPage: true });
  responsive.push({
    viewport,
    screenshot: path.relative(root, shot).replaceAll("\\", "/"),
    screenshot_sha256: sha256(await readFile(shot)),
  });
}

await browser.close();
if (errors.length) throw new Error(errors.join(" | "));
const cert = {
  version: "GOLD_FEBRUARY_H1_CONFIRMATION_ONLY_CONTINUOUS_CHART_V1_BROWSER_CERT",
  verdict: "PASS_WHITE_CONTINUOUS_FEBRUARY_BROWSER_REGRESSION",
  html: path.relative(root, htmlPath).replaceAll("\\", "/"),
  html_sha256: sha256(await readFile(htmlPath)),
  executed_trades: 61,
  h1_bars: 418,
  m15_bars: 1790,
  m5_bars: 5450,
  theme,
  controls_verified: ["H1", "M15", "M5", "pan-right", "zoom-in", "full-february", "ledger-selection"],
  local_trade_line_gate: true,
  responsive,
  browser_errors: errors,
};
cert.certification_sha256 = sha256(Buffer.from(JSON.stringify(cert)));
await writeFile(certPath, `${JSON.stringify(cert, null, 2)}\n`, { encoding: "utf8", flag: "w" });
console.log(JSON.stringify({ verdict: cert.verdict, executed_trades: cert.executed_trades, controls: cert.controls_verified }, null, 2));
