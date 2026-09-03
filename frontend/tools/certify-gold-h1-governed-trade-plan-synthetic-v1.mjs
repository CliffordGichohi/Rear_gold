import { chromium } from "@playwright/test";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..", "..");
const out = path.join(root, "research_artifacts", "gold_h1_governed_trade_plan_synthetic_v1");
const htmlPath = path.join(out, "gold-h1-governed-trade-samples-standalone.html");
const certPath = path.join(out, "browser_certification.json");
const shots = path.join(out, "screenshots");
const sha256 = value => createHash("sha256").update(value).digest("hex");

await mkdir(shots, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1024, height: 1500 } });
const errors = [];
page.on("pageerror", error => errors.push(String(error)));
page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "load" });
const inner = await page.locator("iframe").getAttribute("srcdoc");
if (!inner) throw new Error("Standalone visualization iframe is absent");
await page.setContent(inner, { waitUntil: "load" });

const visual = page.locator("#gold-h1-governed-trade-plan-synthetic-v1");
await visual.waitFor({ timeout: 15000 });
const data = JSON.parse(await page.locator("#h1-governed-plan-data").textContent());
if (data.summary.samples !== 4 || data.summary.trendSamples !== 2 || data.summary.rangeSamples !== 2) throw new Error("Synthetic population differs");
for (const [key, expected] of Object.entries({
  syntheticOnly: true,
  fixedLightTheme: true,
  h1Governs: true,
  m15SetsUp: true,
  m5Executes: true,
  trendTargetsH1Swing: true,
  rangeTargetsInternalLiquidity: true,
  rangeTargetsOppositeExtreme: false,
  outcomesIncluded: false,
  pnlCalculated: false,
})) {
  if (data.guards[key] !== expected) throw new Error(`Guard differs: ${key}`);
}
if (await page.locator("#h1p-tabs button").count() !== 4) throw new Error("Expected four sample controls");

const expected = {
  SYN_TREND_SHORT: { family: "TREND", direction: "SHORT", destinationTimeframe: "H1", destinationKind: "LOW" },
  SYN_TREND_LONG: { family: "TREND", direction: "LONG", destinationTimeframe: "H1", destinationKind: "HIGH" },
  SYN_RANGE_SHORT: { family: "RANGE", direction: "SHORT", destinationTimeframe: "M15", destinationKind: "LOW" },
  SYN_RANGE_LONG: { family: "RANGE", direction: "LONG", destinationTimeframe: "M15", destinationKind: "HIGH" },
};

const sampleChecks = [];
for (const [sampleId, rule] of Object.entries(expected)) {
  await page.locator(`#h1p-tabs button[data-sample-id="${sampleId}"]`).click();
  await page.waitForFunction(id => document.getElementById("gold-h1-governed-trade-plan-synthetic-v1")?.dataset.selectedSample === id, sampleId);
  const sample = data.samples.find(item => item.plan.sample_id === sampleId);
  if (!sample) throw new Error(`Dataset sample absent: ${sampleId}`);
  if (sample.plan.family !== rule.family || sample.plan.direction !== rule.direction) throw new Error(`Family/direction differs: ${sampleId}`);
  if (sample.plan.destination.timeframe !== rule.destinationTimeframe || sample.plan.destination.kind !== rule.destinationKind) throw new Error(`Destination routing differs: ${sampleId}`);
  if (await page.locator(".h1p-chart svg").count() !== 3) throw new Error(`Expected three charts: ${sampleId}`);
  if (await page.locator('[data-candle="H1"]').count() !== 81 || await page.locator('[data-candle="M15"]').count() !== 67 || await page.locator('[data-candle="M5"]').count() !== 64) throw new Error(`Candle population differs: ${sampleId}`);
  if (await page.locator('[data-plan-line="ENTRY"]').count() !== 1 || await page.locator('[data-plan-line="STOP"]').count() !== 1) throw new Error(`Entry/stop geometry differs: ${sampleId}`);
  if (await page.locator("[data-m5-turn]").count() !== 1 || await page.locator("[data-m5-retest]").count() !== 1) throw new Error(`M5 turn/retest differs: ${sampleId}`);
  if (await page.locator("[data-location-zone]").count() !== 1) throw new Error(`M15 location differs: ${sampleId}`);
  const destinationRole = rule.family === "TREND" ? "H1_LIQUIDITY_SWING" : "RANGE_INTERNAL_LIQUIDITY";
  if (await page.locator(`[data-destination-role="${destinationRole}"]`).count() !== 1) throw new Error(`M5 destination label differs: ${sampleId}`);
  if (await page.locator(`[data-destination-marker="${destinationRole}"]`).count() !== 1) throw new Error(`Destination source marker differs: ${sampleId}`);
  if (rule.family === "TREND") {
    if (sample.plan.destination.target_policy !== "PREEXISTING_UNCONSUMED_H1_LIQUIDITY_SWING") throw new Error(`Trend target policy differs: ${sampleId}`);
    if (await page.locator("[data-range-boundary]").count() !== 0) throw new Error(`Trend rendered range boundaries: ${sampleId}`);
  } else {
    const range = sample.plan.governing_h1_auction.range;
    if (!(range.lower_boundary < sample.plan.destination.level && sample.plan.destination.level < range.upper_boundary)) throw new Error(`Range destination is not internal: ${sampleId}`);
    if (sample.plan.destination.target_policy !== "PREEXISTING_INTERNAL_M15_LIQUIDITY_NOT_RANGE_EXTREME") throw new Error(`Range target policy differs: ${sampleId}`);
    if (await page.locator("[data-range-boundary]").count() !== 2) throw new Error(`Range boundaries differ: ${sampleId}`);
  }
  sampleChecks.push({ sample_id: sampleId, family: rule.family, direction: rule.direction, destination_timeframe: rule.destinationTimeframe, destination_kind: rule.destinationKind });
}

const fixedTheme = await visual.evaluate(element => ({
  background: getComputedStyle(element).backgroundColor,
  color: getComputedStyle(element).color,
  frameFills: [...element.querySelectorAll("[data-chart-frame]")].map(node => getComputedStyle(node).fill),
}));
if (fixedTheme.background !== "rgb(255, 255, 255)" || fixedTheme.frameFills.some(value => value !== "rgb(255, 255, 255)")) throw new Error(`Fixed light theme differs: ${JSON.stringify(fixedTheme)}`);

const responsive = [];
for (const viewport of [
  { width: 1024, height: 1500 },
  { width: 736, height: 1400 },
  { width: 360, height: 1250 },
]) {
  await page.setViewportSize(viewport);
  for (const sampleId of ["SYN_TREND_SHORT", "SYN_RANGE_SHORT"]) {
    await page.locator(`#h1p-tabs button[data-sample-id="${sampleId}"]`).click();
    await page.waitForTimeout(140);
    const documentState = await page.evaluate(() => ({ width: innerWidth, scrollWidth: document.documentElement.scrollWidth }));
    const state = await visual.evaluate(element => ({
      width: element.getBoundingClientRect().width,
      background: getComputedStyle(element).backgroundColor,
      charts: element.querySelectorAll(".h1p-chart svg").length,
      selected: element.dataset.selectedSample,
      maximumCandleWidth: Math.max(...[...element.querySelectorAll("[data-candle]")].map(node => Number(node.getAttribute("width")))),
      textOutside: [...element.querySelectorAll(".h1p-chart svg text")].filter(node => {
        const svg = node.ownerSVGElement;
        const box = node.getBBox();
        const viewWidth = svg.viewBox.baseVal.width;
        const viewHeight = svg.viewBox.baseVal.height;
        return box.x < -1 || box.y < -1 || box.x + box.width > viewWidth + 1 || box.y + box.height > viewHeight + 1;
      }).length,
      outsideLabels: [...element.querySelectorAll(".h1p-chart svg text")].filter(node => {
        const svg = node.ownerSVGElement;
        const box = node.getBBox();
        const viewWidth = svg.viewBox.baseVal.width;
        const viewHeight = svg.viewBox.baseVal.height;
        return box.x < -1 || box.y < -1 || box.x + box.width > viewWidth + 1 || box.y + box.height > viewHeight + 1;
      }).map(node => node.textContent),
    }));
    if (documentState.scrollWidth > documentState.width + 1 || state.background !== "rgb(255, 255, 255)" || state.charts !== 3 || state.selected !== sampleId || state.maximumCandleWidth > 6.5 || state.maximumCandleWidth < 1.6 || state.textOutside !== 0) throw new Error(`Responsive failure ${viewport.width}/${sampleId}: ${JSON.stringify({ documentState, state })}`);
    const shot = path.join(shots, `h1-plan-${sampleId.toLowerCase()}-${viewport.width}.png`);
    await visual.screenshot({ path: shot });
    responsive.push({
      viewport,
      sample_id: sampleId,
      state,
      screenshot: path.relative(root, shot).replaceAll("\\", "/"),
      screenshot_sha256: sha256(await readFile(shot)),
    });
  }
}

await browser.close();
if (errors.length) throw new Error(errors.join(" | "));
const cert = {
  version: "GOLD_H1_GOVERNED_TRADE_PLAN_SYNTHETIC_V1_BROWSER_CERT",
  verdict: "PASS_H1_GOVERNED_SYNTHETIC_PLAN_BROWSER_REGRESSION",
  html: path.relative(root, htmlPath).replaceAll("\\", "/"),
  html_sha256: sha256(await readFile(htmlPath)),
  sample_checks: sampleChecks,
  fixed_theme: fixedTheme,
  responsive,
  browser_errors: errors,
  outcomes_included: false,
  pnl_calculated: false,
};
cert.certification_sha256 = sha256(Buffer.from(JSON.stringify(cert)));
await writeFile(certPath, `${JSON.stringify(cert, null, 2)}\n`, { encoding: "utf8", flag: "w" });
console.log(JSON.stringify({ verdict: cert.verdict, samples: cert.sample_checks.length, responsive_checks: responsive.length, fixed_light: cert.fixed_theme.background }, null, 2));
