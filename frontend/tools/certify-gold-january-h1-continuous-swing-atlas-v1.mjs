import { chromium } from "@playwright/test";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..", "..");
const out = path.join(root, "research_artifacts", "gold_january_h1_continuous_swing_atlas_v1");
const htmlPath = path.join(out, "gold-january-h1-continuous-swing-atlas-standalone.html");
const certPath = path.join(out, "browser_certification.json");
const shots = path.join(out, "screenshots");
const sha256 = value => createHash("sha256").update(value).digest("hex");

await mkdir(shots, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1180, height: 920 } });
const errors = [];
page.on("pageerror", error => errors.push(String(error)));
page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "load" });
const inner = await page.locator("iframe").getAttribute("srcdoc");
if (!inner) throw new Error("Standalone inner visualization is absent");
await page.setContent(inner, { waitUntil: "load" });
const visual = page.locator("#gold-january-h1-continuous-swing-atlas-v1");
await visual.waitFor({ timeout: 15000 });
const data = JSON.parse(await page.locator("#h1-data").textContent());

if (data.summary.candles !== 436 || data.summary.swings !== 115 || data.summary.highs !== 55 || data.summary.lows !== 60) throw new Error("Frozen H1 counts differ");
if (data.definition.timeframe !== "H1" || data.definition.atrWindow !== 14 || data.definition.pivotLeft !== 2 || data.definition.pivotRight !== 2 || data.definition.prominenceAtr !== 0.25 || data.definition.tickFloor !== 0.02) throw new Error("Frozen swing definition differs");
for (const [key, expected] of Object.entries({ continuousNotCases: true, fixedLightTheme: true, pivotAndConfirmationSeparated: true, outcomesIncluded: false, pnlCalculated: false, laterYearsOpened: false })) {
  if (data.guards[key] !== expected) throw new Error(`Research guard differs: ${key}`);
}
if (await page.locator("#h1-continuous-svg").count() !== 1) throw new Error("Expected one continuous H1 chart");
if (await page.locator("[data-h1-candle]").count() !== 436) throw new Error("Expected all 436 H1 candles");
if (await page.locator("[data-swing-marker]").count() !== 115) throw new Error("Expected all 115 H1 swing markers");
if (await page.locator('[data-swing-marker][data-kind="HIGH"]').count() !== 55 || await page.locator('[data-swing-marker][data-kind="LOW"]').count() !== 60) throw new Error("High/low swing marker counts differ");
if (await page.locator("[data-relation-label]").count() !== 115) throw new Error("Expected 115 relation labels");
if (await page.locator("[data-confirmation-segment]").count() !== 115 || await page.locator("[data-confirmation-marker]").count() !== 115) throw new Error("Confirmation geometry differs");
if (await page.locator("#h1-swing-select option").count() !== 115) throw new Error("Swing selector differs");
const fixedTheme = await visual.evaluate(element => ({
  background: getComputedStyle(element).backgroundColor,
  color: getComputedStyle(element).color,
  frameFill: getComputedStyle(element.querySelector("[data-chart-frame]")).fill,
}));
if (fixedTheme.background !== "rgb(255, 255, 255)" || fixedTheme.frameFill !== "rgb(255, 255, 255)") throw new Error(`Chart is not fixed light theme: ${JSON.stringify(fixedTheme)}`);
const maxSegment = await page.locator("[data-confirmation-segment]").evaluateAll(nodes => Math.max(...nodes.map(node => Number(node.getAttribute("x2")) - Number(node.getAttribute("x1")))));
if (!(maxSegment >= 0 && maxSegment < 100)) throw new Error(`Confirmation segment is not bounded: ${maxSegment}`);

await page.locator("#h1-show-relations").uncheck();
if (await page.locator("[data-relation-label]").count() !== 0 || await page.locator("[data-swing-marker]").count() !== 115) throw new Error("Relation toggle altered swing population");
await page.locator("#h1-show-relations").check();
await page.locator("#h1-show-confirmation").uncheck();
if (await page.locator("[data-confirmation-segment]").count() !== 0 || await page.locator("[data-swing-marker]").count() !== 115) throw new Error("Confirmation toggle altered swing population");
await page.locator("#h1-show-confirmation").check();

await page.locator("#h1-swing-select").selectOption("0");
await page.locator("#h1-next").click();
if (await page.locator("#h1-swing-select").inputValue() !== "1") throw new Error("Next-swing navigation failed");
await page.locator("#h1-prev").click();
if (await page.locator("#h1-swing-select").inputValue() !== "0") throw new Error("Previous-swing navigation failed");
await page.locator("#h1-swing-select").selectOption("114");
if (!String(await page.locator("#h1-selected-title").textContent()).startsWith("#115")) throw new Error("Last-swing selection failed");
if (await page.locator("[data-selected-guide]").count() !== 1) throw new Error("Selected swing guide differs");
await page.locator("#h1-swing-select").selectOption("0");

const svg = page.locator("#h1-continuous-svg");
const widthBefore = Number(await svg.getAttribute("width"));
await page.locator("#h1-zoom-in").click();
const widthAfter = Number(await svg.getAttribute("width"));
if (!(widthAfter > widthBefore)) throw new Error("Zoom-in failed");
const scroller = page.locator("#h1-scroll");
await scroller.evaluate(element => { element.scrollLeft = 0; });
await page.locator("#h1-pan-right").click();
await page.waitForTimeout(450);
if (await scroller.evaluate(element => element.scrollLeft) <= 0) throw new Error("Pan-right failed");

const responsive = [];
for (const viewport of [
  { width: 1180, height: 920 },
  { width: 736, height: 900 },
  { width: 360, height: 860 },
]) {
  await page.setViewportSize(viewport);
  await page.locator("#h1-swing-select").selectOption("0");
  await page.waitForTimeout(180);
  const documentState = await page.evaluate(() => ({ width: innerWidth, scrollWidth: document.documentElement.scrollWidth }));
  const state = await visual.evaluate(element => ({
    width: element.getBoundingClientRect().width,
    background: getComputedStyle(element).backgroundColor,
    charts: element.querySelectorAll("#h1-chart svg").length,
    candles: element.querySelectorAll("[data-h1-candle]").length,
    swings: element.querySelectorAll("[data-swing-marker]").length,
  }));
  if (documentState.scrollWidth > documentState.width + 1 || state.background !== "rgb(255, 255, 255)" || state.charts !== 1 || state.candles !== 436 || state.swings !== 115) throw new Error(`Responsive failure ${viewport.width}: ${JSON.stringify({ documentState, state })}`);
  const shot = path.join(shots, `h1-continuous-atlas-${viewport.width}.png`);
  await visual.screenshot({ path: shot });
  responsive.push({ viewport, documentState, state, screenshot: path.relative(root, shot).replaceAll("\\", "/"), screenshot_sha256: sha256(await readFile(shot)) });
}

await browser.close();
if (errors.length) throw new Error(errors.join(" | "));
const cert = {
  version: "GOLD_JANUARY_H1_CONTINUOUS_SWING_ATLAS_V1_BROWSER_CERT",
  verdict: "PASS_CONTINUOUS_H1_LIGHT_BROWSER_REGRESSION",
  html: path.relative(root, htmlPath).replaceAll("\\", "/"),
  html_sha256: sha256(await readFile(htmlPath)),
  candles: 436,
  swings: 115,
  highs: 55,
  lows: 60,
  maximum_confirmation_segment_pixels_at_default_scale: maxSegment,
  fixed_theme: fixedTheme,
  controls_verified: ["swing-select", "previous", "next", "pan-right", "zoom-in", "relations-toggle", "confirmation-toggle"],
  responsive,
  browser_errors: errors,
  continuous_not_cases: true,
  outcomes_included: false,
  pnl_calculated: false,
};
cert.certification_sha256 = sha256(Buffer.from(JSON.stringify(cert)));
await writeFile(certPath, `${JSON.stringify(cert, null, 2)}\n`, { encoding: "utf8", flag: "w" });
console.log(JSON.stringify({ verdict: cert.verdict, candles: cert.candles, swings: cert.swings, highs: cert.highs, lows: cert.lows, fixed_light: cert.fixed_theme.background }, null, 2));
