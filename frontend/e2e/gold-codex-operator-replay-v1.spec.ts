import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";


const API = "http://localhost:8012/api/v1/codex-operator-replay-v1";
const HOST_ARTIFACT = path.resolve(process.cwd(), "../.codex_runs/codex_operator_replay_e2e/artifact");
const LOGICAL_ARTIFACT = "research_artifacts/codex_operator_replay_v1_e2e";

type Snapshot = {
  case_alias: string;
  cursor_at: string;
  start_at: string;
  observation_terminal_at: string;
  visible_state_sha256: string;
  inspected_timeframes: string[];
  charts: Record<string, Array<{ close_at: string; available_at: string }>>;
};

function sha(pathname: string) {
  return createHash("sha256").update(readFileSync(pathname)).digest("hex");
}

function artifact(pathname: string, kind: string, timeframe?: string) {
  const relative = path.relative(HOST_ARTIFACT, pathname).replaceAll("\\", "/");
  return {
    kind,
    path: `${LOGICAL_ARTIFACT}/${relative}`,
    bytes: statSync(pathname).size,
    sha256: sha(pathname),
    ...(timeframe ? { timeframe } : {}),
  };
}

async function apiCase(request: APIRequestContext): Promise<Snapshot> {
  const response = await request.get(`${API}/next`);
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()).case as Snapshot;
}

async function inspectRequired(page: Page, request: APIRequestContext, directory: string, actions: Record<string, unknown>[]) {
  const items: ReturnType<typeof artifact>[] = [];
  for (const label of ["W1", "D1", "H4", "H1", "M15"] as const) {
    await page.getByRole("button", { name: `Inspect ${label} timeframe` }).click();
    await expect(page.getByRole("button", { name: `Inspect ${label} timeframe` })).toContainText("sealed");
    const filename = path.join(directory, `timeframe-${label.toLowerCase()}.png`);
    await page.screenshot({ path: filename, fullPage: true });
    items.push(artifact(filename, "TIMEFRAME_SCREENSHOT", ({ W1: "1w", D1: "1d", H4: "4h", H1: "1h", M15: "15m" } as const)[label]));
    const snapshot = await apiCase(request);
    actions.push({ action: "TIMEFRAME_INSPECTED", target: label, replay_timestamp: snapshot.cursor_at, visible_state_sha256: snapshot.visible_state_sha256 });
  }
  return items;
}

async function chartBox(page: Page) {
  const chart = page.getByTestId("synchronized-replay-chart");
  await chart.scrollIntoViewIfNeeded();
  const box = await chart.boundingBox();
  expect(box).not.toBeNull();
  return { chart, box: box! };
}

async function drawLong(page: Page) {
  const { box } = await chartBox(page);
  await page.getByRole("button", { name: "Long position" }).click();
  const x = box.x + box.width * 0.78;
  await page.mouse.click(x, box.y + box.height * 0.52);
  await page.mouse.click(x, box.y + box.height * 0.82);
  await page.mouse.click(x, box.y + box.height * 0.20);
  await expect(page.getByLabel("long position drawing")).toBeVisible();
}

async function fillTradeForm(page: Page) {
  await page.getByLabel("Setup class").selectOption("MACRO_NEUTRAL_AUCTION_TRADE");
  await page.getByLabel("Higher-timeframe state").selectOption("RANGE");
  await page.getByLabel("Codex trade thesis").fill("Synthetic browser certification: completed structure and visible session context align.");
  await page.getByLabel("Macro regime").fill("Synthetic neutral regime");
  await page.getByLabel("Macro directional pressure").fill("Neutral, context only");
  await page.getByLabel("Macro role").selectOption("NEUTRAL");
  await page.getByLabel("Macro freshness").fill("Available at the visible decision timestamp");
  await page.getByLabel("Codex dominant driver").fill("Synthetic rates context");
  await page.getByLabel("Catalyst risk").fill("Low synthetic event risk");
  await page.getByLabel("Codex higher-timeframe context").fill("Completed W1, D1, H4 and H1 candles show a bounded range.");
  await page.getByLabel("Pre-existing location").fill("Visible synthetic support existed before the decision.");
  await page.getByLabel("M15 transition").fill("The completed visible M15 state confirms the synthetic response.");
  await page.getByLabel("Codex session and liquidity context").fill("The decision is inside the visible London observation window.");
  await page.getByLabel("Codex invalidation condition").fill("A completed M15 break through the marked stop invalidates the setup.");
  await page.getByLabel("Codex target logic").fill("Target the pre-existing opposing synthetic liquidity.");
}

async function sealEvidence(
  page: Page,
  request: APIRequestContext,
  directory: string,
  initial: string,
  timeframeArtifacts: ReturnType<typeof artifact>[],
  actions: Record<string, unknown>[],
) {
  const snapshot = await apiCase(request);
  const finalPage = path.join(directory, "final-predecision-full-page.png");
  const chartCrop = path.join(directory, "final-predecision-chart.png");
  const form = path.join(directory, "completed-decision-form.png");
  await page.screenshot({ path: finalPage, fullPage: true });
  await page.getByTestId("synchronized-replay-chart").screenshot({ path: chartCrop });
  await page.getByLabel("Codex decision form", { exact: true }).screenshot({ path: form });
  actions.push({ action: "DECISION_FORM_COMPLETED", replay_timestamp: snapshot.cursor_at, visible_state_sha256: snapshot.visible_state_sha256 });
  const actionLog = path.join(directory, "chronological-actions.jsonl");
  writeFileSync(actionLog, actions.map((row, index) => JSON.stringify({ sequence: index + 1, wall_clock_at: new Date().toISOString(), ...row })).join("\n") + "\n");
  const manifest = {
    version: "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_PREDECISION_EVIDENCE_1_0",
    case_alias: snapshot.case_alias,
    cursor_at: snapshot.cursor_at,
    visible_state_sha256: snapshot.visible_state_sha256,
    inspected_timeframes: snapshot.inspected_timeframes,
    artifacts: [
      artifact(initial, "INITIAL_FULL_PAGE_SCREENSHOT"),
      ...timeframeArtifacts,
      artifact(finalPage, "FINAL_PREDECISION_FULL_PAGE_SCREENSHOT"),
      artifact(chartCrop, "FINAL_PREDECISION_CHART_CROP"),
      artifact(form, "COMPLETED_DECISION_FORM_SCREENSHOT"),
      artifact(actionLog, "CHRONOLOGICAL_ACTION_LOG"),
    ],
  };
  const manifestPath = path.join(directory, "predecision_evidence_manifest.json");
  writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  return sha(manifestPath);
}

test("Codex V1 browser pathway is isolated, evidence-bound, restartable, and outcome-blind", async ({ page, request }) => {
  test.setTimeout(180_000);
  const browserErrors: string[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") browserErrors.push(message.text()); });

  await expect.poll(async () => {
    try { return (await request.get("http://localhost:8012/api/v1/health/live")).ok(); } catch { return false; }
  }, { timeout: 30_000 }).toBeTruthy();
  await page.goto("/replay/codex");
  await expect(page.getByTestId("codex-operator-replay-lab")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Rendered pixels only")).toBeVisible();
  await expect(page.getByText(/No outcome, hit rate, PnL or interim feedback/)).toBeVisible();

  let snapshot = await apiCase(request);
  expect(snapshot.case_alias).toBe("CBR-2022-001");
  expect(snapshot.charts["1m"]).toHaveLength(1);
  for (const bars of Object.values(snapshot.charts)) {
    expect(bars.every((bar) => bar.close_at <= snapshot.cursor_at && bar.available_at <= snapshot.cursor_at)).toBeTruthy();
  }

  const directory = path.join(HOST_ARTIFACT, "evidence", "predecision", snapshot.case_alias);
  mkdirSync(directory, { recursive: true });
  const initial = path.join(directory, "initial-full-page.png");
  await page.screenshot({ path: initial, fullPage: true });
  const actions: Record<string, unknown>[] = [{ action: "CASE_OPENED", replay_timestamp: snapshot.cursor_at, visible_state_sha256: snapshot.visible_state_sha256 }];
  const timeframeArtifacts = await inspectRequired(page, request, directory, actions);

  await page.getByRole("button", { name: "Horizontal level" }).click();
  const { box } = await chartBox(page);
  await page.mouse.click(box.x + box.width * 0.55, box.y + box.height * 0.45);
  await expect(page.getByLabel("horizontal line drawing")).toBeVisible();
  await page.getByRole("button", { name: "Inspect H1 timeframe" }).click();
  await expect(page.getByLabel("horizontal line drawing")).toBeVisible();
  await page.getByRole("button", { name: "Inspect M15 timeframe" }).click();
  await page.getByLabel("horizontal line drawing").click();
  await page.keyboard.press("Backspace");
  await expect(page.getByLabel("horizontal line drawing")).toHaveCount(0);

  await drawLong(page);
  await page.getByRole("button", { name: "Open blind trade decision form" }).click();
  await expect(page.getByLabel("Codex decision form", { exact: true })).toBeVisible();
  await fillTradeForm(page);
  const evidenceSha = await sealEvidence(page, request, directory, initial, timeframeArtifacts, actions);
  await page.getByLabel("Pre-decision evidence SHA-256").fill(evidenceSha);
  await page.getByRole("button", { name: "Seal Codex decision" }).click();
  await expect(page.getByText(/CBR-2022-001 sealed. Its outcome is hidden/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("CBR-2022-002")).toBeVisible();
  await expect(page.getByText(/No outcome, hit rate, PnL or interim feedback/)).toBeVisible();

  const forbidden = await request.get(`${API}/outcomes`);
  expect(forbidden.status()).toBe(404);
  execFileSync("docker", ["restart", "gold-codex-operator-replay-e2e-api"], { stdio: "ignore" });
  await expect.poll(async () => {
    try { return (await request.get("http://localhost:8012/api/v1/health/live")).ok(); } catch { return false; }
  }, { timeout: 30_000 }).toBeTruthy();
  await page.reload();
  await expect(page.getByText("CBR-2022-002")).toBeVisible({ timeout: 30_000 });

  snapshot = await apiCase(request);
  const directory2 = path.join(HOST_ARTIFACT, "evidence", "predecision", snapshot.case_alias);
  mkdirSync(directory2, { recursive: true });
  const initial2 = path.join(directory2, "initial-full-page.png");
  await page.screenshot({ path: initial2, fullPage: true });
  const actions2: Record<string, unknown>[] = [{ action: "CASE_OPENED", replay_timestamp: snapshot.cursor_at, visible_state_sha256: snapshot.visible_state_sha256 }];
  const timeframes2 = await inspectRequired(page, request, directory2, actions2);
  await page.getByRole("button", { name: "Step Codex replay 15 minutes" }).click();
  await expect(page.getByRole("button", { name: "Open no-trade decision form" })).toBeEnabled();
  await page.getByRole("button", { name: "Open no-trade decision form" }).click();
  await page.getByLabel("No-trade reason").fill("No completed qualifying setup appeared before the exact terminal cursor.");
  const evidenceSha2 = await sealEvidence(page, request, directory2, initial2, timeframes2, actions2);
  await page.getByLabel("Pre-decision evidence SHA-256").fill(evidenceSha2);
  await page.getByRole("button", { name: "Seal Codex decision" }).click();
  await expect(page.getByText(/CBR-2022-002 sealed. Its outcome is hidden/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("CBR-2022-003")).toBeVisible();

  expect(browserErrors).toEqual([]);
});
