import { chromium } from "@playwright/test";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..", "..");
const base = path.join(root, "research_artifacts", "gold_mar_apr_may_h1_confirmation_only_reclaim_v1");
const months = [
  { key: "march_2022", label: "March 2022", slug: "march-2022" },
  { key: "april_2022", label: "April 2022", slug: "april-2022" },
  { key: "may_2022", label: "May 2022", slug: "may-2022" },
];
const sha256 = value => createHash("sha256").update(value).digest("hex");
const browser = await chromium.launch({ headless: true });

for (const month of months) {
  const out = path.join(base, month.key);
  const htmlPath = path.join(out, `gold-${month.slug}-h1-confirmation-only-continuous-chart.html`);
  const certPath = path.join(out, "browser_certification.json");
  const shots = path.join(out, "screenshots");
  await mkdir(shots, { recursive: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
  const errors = [];
  page.on("pageerror", error => errors.push(String(error)));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "load" });

  const visual = page.locator(`#gold-${month.slug}-h1-confirmation-only-v1`);
  await visual.waitFor({ timeout: 15000 });
  const data = JSON.parse(await page.locator("#jgo-data").textContent());
  const expectedTrades = Number(data.summary.plans);
  const expectedR = Number(data.summary.gross_r_sum);
  if (!Number.isFinite(expectedR)) throw new Error(`${month.label}: invalid R`);
  if (data.plans.length !== expectedTrades) throw new Error(`${month.label}: trade count differs`);
  if (await page.locator("#jgo-ledger tr").count() !== expectedTrades) throw new Error(`${month.label}: ledger count differs`);
  if (!(await page.locator("h2").first().textContent()).startsWith(month.label)) throw new Error(`${month.label}: title differs`);
  if (await page.locator('button[data-timeframe="H1"]').getAttribute("aria-pressed") !== "true") throw new Error(`${month.label}: H1 not initial`);
  if (await page.locator('[data-candle="H1"]').count() !== Math.min(144, data.bars.H1.length)) throw new Error(`${month.label}: H1 default ratio differs`);
  if (await page.locator("[data-plan-line]").count() < 3) throw new Error(`${month.label}: no visible trade lines`);

  const theme = await visual.evaluate(element => ({
    background: getComputedStyle(element).backgroundColor,
    color: getComputedStyle(element).color,
    frameFill: getComputedStyle(element.querySelector("[data-chart-frame]")).fill,
  }));
  if (theme.background !== "rgb(255, 255, 255)" || theme.frameFill !== "rgb(255, 255, 255)") throw new Error(`${month.label}: chart is not white`);

  await page.locator("#jgo-right").click();
  if (Number(await visual.getAttribute("data-view-start")) <= 0) throw new Error(`${month.label}: pan-right failed`);
  await page.locator("#jgo-zoom-in").click();
  await page.locator("#jgo-full").click();
  if (await page.locator('[data-candle="H1"]').count() !== data.bars.H1.length) throw new Error(`${month.label}: full-month H1 failed`);
  if (await page.locator("[data-plan-marker]").count() !== expectedTrades) throw new Error(`${month.label}: full-month markers differ`);

  const lineGeometry = await visual.evaluate(element => {
    const frame = element.querySelector("[data-chart-frame]");
    const left = Number(frame.getAttribute("x"));
    const right = left + Number(frame.getAttribute("width"));
    const entries = [...element.querySelectorAll('[data-plan-line="ENTRY"]')].map(line => ({
      x1: Number(line.getAttribute("x1")), x2: Number(line.getAttribute("x2")),
    }));
    return { left, right, entries };
  });
  if (lineGeometry.entries.some(line => Math.abs(line.x1 - lineGeometry.left) < 0.01 && Math.abs(line.x2 - lineGeometry.right) < 0.01)) {
    throw new Error(`${month.label}: a trade line spans the entire chart`);
  }

  await page.locator('button[data-timeframe="M15"]').click();
  if (await page.locator('[data-candle="M15"]').count() !== Math.min(288, data.bars.M15.length)) throw new Error(`${month.label}: M15 switch differs`);
  await page.locator('button[data-timeframe="M5"]').click();
  if (await page.locator('[data-candle="M5"]').count() !== Math.min(432, data.bars.M5.length)) throw new Error(`${month.label}: M5 switch differs`);
  await page.locator('button[data-timeframe="H1"]').click();
  await page.locator("#jgo-ledger tr").first().locator("button").click();
  if (await visual.getAttribute("data-selected-plan") === "NONE") throw new Error(`${month.label}: row selection failed`);

  const responsive = [];
  for (const viewport of [
    { width: 1180, height: 920 },
    { width: 736, height: 900 },
    { width: 360, height: 860 },
  ]) {
    await page.setViewportSize(viewport);
    await page.waitForTimeout(180);
    const state = await page.evaluate(() => ({ width: innerWidth, scrollWidth: document.documentElement.scrollWidth }));
    if (state.scrollWidth > state.width + 1) throw new Error(`${month.label}: overflow at ${viewport.width}px`);
    if (await page.locator("#jgo-chart svg").count() !== 1) throw new Error(`${month.label}: chart missing at ${viewport.width}px`);
    const shot = path.join(shots, `${month.slug}-chart-${viewport.width}.png`);
    await visual.screenshot({ path: shot, fullPage: true });
    responsive.push({
      viewport,
      screenshot: path.relative(root, shot).replaceAll("\\", "/"),
      screenshot_sha256: sha256(await readFile(shot)),
    });
  }
  if (errors.length) throw new Error(`${month.label}: ${errors.join(" | ")}`);
  const cert = {
    version: `GOLD_${month.key.toUpperCase()}_H1_CONFIRMATION_ONLY_CONTINUOUS_CHART_V1_BROWSER_CERT`,
    verdict: "PASS_WHITE_CONTINUOUS_MONTH_BROWSER_REGRESSION",
    month: month.label,
    html: path.relative(root, htmlPath).replaceAll("\\", "/"),
    html_sha256: sha256(await readFile(htmlPath)),
    executed_trades: expectedTrades,
    net_r: expectedR,
    bars: { H1: data.bars.H1.length, M15: data.bars.M15.length, M5: data.bars.M5.length },
    theme,
    controls_verified: ["H1", "M15", "M5", "pan-right", "zoom-in", "full-month", "ledger-selection"],
    local_trade_line_gate: true,
    responsive,
    browser_errors: errors,
  };
  cert.certification_sha256 = sha256(Buffer.from(JSON.stringify(cert)));
  await writeFile(certPath, `${JSON.stringify(cert, null, 2)}\n`, { encoding: "utf8", flag: "w" });
  console.log(JSON.stringify({ month: month.label, verdict: cert.verdict, trades: expectedTrades, net_r: expectedR }, null, 2));
  await page.close();
}

await browser.close();
