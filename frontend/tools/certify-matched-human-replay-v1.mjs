import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";


const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const artifact = path.join(root, "research_artifacts", "gold_matched_human_replay_v1");
const destination = path.join(artifact, "browser_readiness");
const visibleLedger = path.join(artifact, "ledgers", "matched_human_visible_ledger.jsonl");
const outcomeLedger = path.join(artifact, "outcome_vault", "matched_human_outcome_ledger.jsonl");
const certificationPath = path.join(destination, "browser_readiness_certification.json");
const screenshotPath = path.join(destination, "initial_matched_replay.png");


function shaFile(filename) {
  return createHash("sha256").update(readFileSync(filename)).digest("hex");
}


function check(condition, message) {
  if (!condition) throw new Error(message);
}


check(!existsSync(visibleLedger), "Human visible ledger already exists; readiness must precede collection");
check(!existsSync(outcomeLedger), "Human outcome ledger already exists; readiness must precede collection");
check(!existsSync(certificationPath), "Matched browser readiness is already certified");
mkdirSync(destination, { recursive: true });

const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
const apiRequests = [];
const browserErrors = [];
page.on("request", (request) => {
  if (request.url().includes("/api/v1/")) apiRequests.push({ method: request.method(), url: request.url() });
});
page.on("pageerror", (error) => browserErrors.push(error.message));
page.on("console", (message) => {
  if (message.type() === "error") browserErrors.push(message.text());
});
await page.goto("http://localhost:3000/replay/matched", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(2_000);
if (await page.getByTestId("codex-operator-replay-lab").count() !== 1) {
  const diagnosticPath = path.join(destination, "failed_initial_render.png");
  await page.screenshot({ path: diagnosticPath, fullPage: true });
  const body = await page.locator("body").innerText();
  await browser.close();
  throw new Error(`Matched lab did not render. Body: ${body.slice(0, 2000)} Browser errors: ${browserErrors.join(" | ")}`);
}
await page.getByTestId("codex-operator-replay-lab").waitFor({ state: "visible", timeout: 10_000 });

const text = await page.locator("body").innerText();
check(text.includes("CBR-2022-001"), "First frozen matched case is not visible");
check(text.includes("Complete: 0 / 30"), "Matched progress is not 0 / 30");
check(text.includes("Codex decisions: HIDDEN"), "Codex-decision isolation label is absent");
check(text.includes("No outcome, hit rate, PnL or interim feedback is available."), "Outcome-isolation warning is absent");
check(!text.includes("-90.71") && !text.includes("27.3%") && !text.includes("CBR-2022-030 |"), "A prior result leaked into the matched interface");
check(await page.getByRole("button", { name: "Play Human matched replay" }).isVisible(), "Matched play control is absent");
check(await page.getByRole("button", { name: "Open blind trade decision form" }).isVisible(), "Matched trade control is absent");
check(await page.getByRole("button", { name: "Open no-trade decision form" }).isVisible(), "Matched no-trade control is absent");
check(apiRequests.length === 1, `Unexpected initial API request count: ${apiRequests.length}`);
check(apiRequests[0].method === "GET" && apiRequests[0].url.endsWith("/matched-human-replay-v1/next"), "Initial page used an unexpected API route");

await page.screenshot({ path: screenshotPath, fullPage: true });
await browser.close();
check(!existsSync(visibleLedger), "Browser readiness mutated the visible ledger");
check(!existsSync(outcomeLedger), "Browser readiness mutated the outcome ledger");

const certification = {
  version: "GOLD_MATCHED_HUMAN_REPLAY_V1_BROWSER_READINESS_1_0",
  verdict: "PASS_MATCHED_HUMAN_BROWSER_READINESS",
  certified_at: new Date().toISOString(),
  page: "http://localhost:3000/replay/matched",
  initial_case_alias: "CBR-2022-001",
  cases_completed: 0,
  cases_total: 30,
  gates: {
    exact_first_case_visible: true,
    matched_progress_visible: true,
    play_control_visible: true,
    trade_control_visible: true,
    no_trade_control_visible: true,
    codex_decisions_hidden: true,
    outcomes_hidden: true,
    matched_api_route_only: true,
    readiness_created_no_ledger_rows: true,
  },
  screenshot: {
    path: path.relative(root, screenshotPath).replaceAll("\\", "/"),
    bytes: statSync(screenshotPath).size,
    sha256: shaFile(screenshotPath),
  },
  api_requests: apiRequests,
};
writeFileSync(certificationPath, `${JSON.stringify(certification, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
process.stdout.write(`${JSON.stringify(certification, null, 2)}\n`);
