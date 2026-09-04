import { chromium } from "@playwright/test";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..", "..");
const base = path.join(root, "research_artifacts", "gold_h1_confirmation_geometry_monthly_batch_v1");

const canonical = value => {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
};
const sha256 = value => createHash("sha256").update(value).digest("hex");
const months = [];
for (let year = 2022, month = 6; year < 2025;) {
  const key = `${year}_${String(month).padStart(2, "0")}`;
  const label = new Date(Date.UTC(year, month - 1, 1)).toLocaleString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
  months.push({ key, label });
  month += 1;
  if (month === 13) { year += 1; month = 1; }
}
if (months.length !== 31) throw new Error(`Frozen month count differs: ${months.length}`);

const browser = await chromium.launch({ headless: true });
const results = [];
try {
  for (const month of months) {
    const out = path.join(base, "monthly", month.key);
    const htmlPath = path.join(out, "continuous_chart.html");
    const certPath = path.join(out, "browser_certification.json");
    const shotPath = path.join(out, "chart_1440.png");
    await mkdir(out, { recursive: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
    const errors = [];
    page.on("pageerror", error => errors.push(String(error)));
    page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
    await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "load" });
    const id = `#gold-${month.key.replaceAll("_", "-")}-h1-confirmation-only-v1`;
    const visual = page.locator(id);
    await visual.waitFor({ timeout: 15000 });
    const data = JSON.parse(await page.locator("#jgo-data").textContent());
    const expectedTrades = Number(data.summary.plans);
    if (data.plans.length !== expectedTrades) throw new Error(`${month.label}: plan count differs`);
    if (await page.locator("#jgo-ledger tr").count() !== expectedTrades) throw new Error(`${month.label}: ledger count differs`);
    if (await page.locator('button[data-timeframe="H1"]').getAttribute("aria-pressed") !== "true") throw new Error(`${month.label}: H1 not initial`);
    if (await page.locator('[data-candle="H1"]').count() !== Math.min(144, data.bars.H1.length)) throw new Error(`${month.label}: H1 ratio differs`);
    const theme = await visual.evaluate(element => ({
      background: getComputedStyle(element).backgroundColor,
      frameFill: getComputedStyle(element.querySelector("[data-chart-frame]")).fill,
    }));
    if (theme.background !== "rgb(255, 255, 255)" || theme.frameFill !== "rgb(255, 255, 255)") throw new Error(`${month.label}: chart is not white`);
    await page.locator("#jgo-right").click();
    if (Number(await visual.getAttribute("data-view-start")) <= 0) throw new Error(`${month.label}: pan-right failed`);
    await page.locator("#jgo-zoom-in").click();
    await page.locator("#jgo-full").click();
    if (await page.locator('[data-candle="H1"]').count() !== data.bars.H1.length) throw new Error(`${month.label}: full-month H1 failed`);
    if (expectedTrades && await page.locator("[data-plan-marker]").count() !== expectedTrades) throw new Error(`${month.label}: marker count differs`);
    const geometry = await visual.evaluate(element => {
      const frame = element.querySelector("[data-chart-frame]");
      const left = Number(frame.getAttribute("x"));
      const right = left + Number(frame.getAttribute("width"));
      const entries = [...element.querySelectorAll('[data-plan-line="ENTRY"]')].map(line => ({ x1: Number(line.getAttribute("x1")), x2: Number(line.getAttribute("x2")) }));
      return { left, right, entries };
    });
    if (geometry.entries.some(line => Math.abs(line.x1 - geometry.left) < 0.01 && Math.abs(line.x2 - geometry.right) < 0.01)) throw new Error(`${month.label}: trade line spans chart`);
    await page.locator('button[data-timeframe="M15"]').click();
    if (await page.locator('[data-candle="M15"]').count() !== Math.min(288, data.bars.M15.length)) throw new Error(`${month.label}: M15 switch differs`);
    await page.locator('button[data-timeframe="M5"]').click();
    if (await page.locator('[data-candle="M5"]').count() !== Math.min(432, data.bars.M5.length)) throw new Error(`${month.label}: M5 switch differs`);
    await page.locator('button[data-timeframe="H1"]').click();
    await visual.screenshot({ path: shotPath });
    if (errors.length) throw new Error(`${month.label}: ${errors.join(" | ")}`);
    const cert = {
      version: "GOLD_H1_CONFIRMATION_GEOMETRY_MONTHLY_BATCH_V1_BROWSER_CERT",
      verdict: "PASS_WHITE_CONTINUOUS_MONTH_BROWSER_REGRESSION",
      month: month.key,
      label: month.label,
      html: path.relative(root, htmlPath).replaceAll("\\", "/"),
      html_sha256: sha256(await readFile(htmlPath)),
      screenshot: path.relative(root, shotPath).replaceAll("\\", "/"),
      screenshot_sha256: sha256(await readFile(shotPath)),
      executed_trades: expectedTrades,
      bars: { H1: data.bars.H1.length, M15: data.bars.M15.length, M5: data.bars.M5.length },
      controls_verified: ["H1", "M15", "M5", "pan-right", "zoom-in", "full-month"],
      theme,
      browser_errors: errors,
    };
    cert.certification_sha256 = sha256(canonical(cert));
    await writeFile(certPath, `${JSON.stringify(cert, null, 2)}\n`, "utf8");
    results.push({ month: month.key, certification_sha256: cert.certification_sha256, html_sha256: cert.html_sha256, screenshot_sha256: cert.screenshot_sha256 });
    console.log(JSON.stringify({ month: month.label, verdict: cert.verdict, trades: expectedTrades }));
    await page.close();
  }
} finally {
  await browser.close();
}

const summary = {
  version: "GOLD_H1_CONFIRMATION_GEOMETRY_MONTHLY_BATCH_V1_BROWSER_CERTIFICATION_SUMMARY",
  verdict: "PASS_ALL_31_MONTHLY_CHARTS",
  month_count: results.length,
  results,
};
summary.summary_sha256 = sha256(canonical(summary));
await writeFile(path.join(base, "browser_certification_summary.json"), `${JSON.stringify(summary, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ verdict: summary.verdict, month_count: summary.month_count }));
