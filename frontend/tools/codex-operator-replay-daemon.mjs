import { spawnSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { appendFileSync, existsSync, mkdirSync, readFileSync, readdirSync, renameSync, statfsSync, statSync, writeFileSync } from "node:fs";
import http from "node:http";
import path from "node:path";

import { chromium } from "@playwright/test";


const argumentsMap = Object.fromEntries(process.argv.slice(2).flatMap((value, index, all) => value.startsWith("--") ? [[value.slice(2), all[index + 1]]] : []));
const artifact = path.resolve(argumentsMap.artifact ?? "../research_artifacts/gold_blind_codex_operator_replay_v1");
const repositoryRoot = path.resolve(artifact, "../..");
const pageUrl = argumentsMap.url ?? "http://localhost:3000/replay/codex";
const apiUrl = argumentsMap.api ?? "http://localhost:8000/api/v1/codex-operator-replay-v1";
const logicalRoot = argumentsMap["logical-root"] ?? null;
const port = Number(argumentsMap.port ?? 43122);
const renderer = path.resolve(process.cwd(), "tools/render-codex-operator-outcome-vault.mjs");
const runtime = path.join(artifact, "operator_runtime");
const tokenPath = path.join(runtime, "control_token.txt");
mkdirSync(runtime, { recursive: true });
const token = existsSync(tokenPath) ? readFileSync(tokenPath, "utf8").trim() : randomBytes(32).toString("hex");
if (!existsSync(tokenPath)) writeFileSync(tokenPath, `${token}\n`);

let browser;
let context;
let page;
let alias;
let browserDirectory;
let predecisionDirectory;
let segment;
let tracePath;
let actions = [];
let journalPath;
let busy = false;

function sha(filename) {
  return createHash("sha256").update(readFileSync(filename)).digest("hex");
}

function fileItem(filename) {
  const relative = logicalRoot
    ? `${logicalRoot.replace(/\/$/, "")}/${path.relative(artifact, filename).replaceAll("\\", "/")}`
    : path.relative(repositoryRoot, filename).replaceAll("\\", "/");
  return {
    path: relative,
    bytes: statSync(filename).size,
    sha256: sha(filename),
  };
}

function writeJson(filename, value) {
  writeFileSync(filename, `${JSON.stringify(value, null, 2)}\n`);
}

async function metadata() {
  const response = await fetch(`${apiUrl}/next`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Metadata recorder received HTTP ${response.status}`);
  const payload = await response.json();
  const value = payload.case;
  return {
    case_alias: value.case_alias,
    cursor_at: value.cursor_at,
    visible_state_sha256: value.visible_state_sha256,
    inspected_timeframes: value.inspected_timeframes,
    progress_completed: payload.progress.cases_completed,
  };
}

async function appendAction(action, target, extra = {}) {
  const state = await metadata();
  actions.push({
    sequence: actions.length + 1,
    wall_clock_at: new Date().toISOString(),
    replay_timestamp: state.cursor_at,
    action,
    target,
    selected_timeframe: extra.selected_timeframe ?? null,
    visible_state_sha256: state.visible_state_sha256,
    ...extra,
  });
  appendFileSync(journalPath, `${JSON.stringify(actions.at(-1))}\n`);
}

function nextSegment(directory) {
  let value = 1;
  while (existsSync(path.join(directory, `browser_interaction_segment_${String(value).padStart(3, "0")}.webm`))) value += 1;
  return value;
}

async function startCaseContext() {
  if (!browser) browser = await chromium.launch({ channel: "chrome", headless: true });
  const state = await metadata();
  alias = state.case_alias;
  browserDirectory = path.join(artifact, "evidence", "browser", alias);
  predecisionDirectory = path.join(artifact, "evidence", "predecision", alias);
  mkdirSync(browserDirectory, { recursive: true });
  mkdirSync(predecisionDirectory, { recursive: true });
  segment = nextSegment(browserDirectory);
  const staging = path.join(browserDirectory, `staging_${String(segment).padStart(3, "0")}`);
  mkdirSync(staging, { recursive: true });
  context = await browser.newContext({
    viewport: { width: 1600, height: 1000 },
    timezoneId: "UTC",
    recordVideo: { dir: staging, size: { width: 1600, height: 1000 } },
  });
  await context.tracing.start({ screenshots: true, snapshots: true, sources: false });
  page = await context.newPage();
  await page.goto(pageUrl, { waitUntil: "domcontentloaded" });
  await page.getByTestId("codex-operator-replay-lab").waitFor({ state: "visible", timeout: 60_000 });
  journalPath = path.join(browserDirectory, "operator_action_journal.jsonl");
  actions = existsSync(journalPath)
    ? readFileSync(journalPath, "utf8").split("\n").filter(Boolean).map(JSON.parse)
    : [];
  await appendAction("CASE_OPENED", alias);
}

async function closeCaseContext() {
  if (!context || !page) return [];
  tracePath = path.join(browserDirectory, `browser_trace_segment_${String(segment).padStart(3, "0")}.zip`);
  await context.tracing.stop({ path: tracePath });
  const video = page.video();
  await context.close();
  const recorded = await video.path();
  const videoPath = path.join(browserDirectory, `browser_interaction_segment_${String(segment).padStart(3, "0")}.webm`);
  renameSync(recorded, videoPath);
  context = undefined;
  page = undefined;
  return [videoPath, tracePath];
}

async function capture(filename, fullPage = true, locator = null) {
  const destination = path.join(predecisionDirectory, filename);
  if (locator) await locator.screenshot({ path: destination });
  else await page.screenshot({ path: destination, fullPage });
  if (filename.startsWith("timeframe_") || filename === "initial_full_page.png") indexFile(destination);
  return destination;
}

function timeframeCode(label) {
  return ({ W1: "1w", D1: "1d", H4: "4h", H1: "1h", M15: "15m", M5: "5m", M1: "1m" })[label];
}

async function captureInitial() {
  const filename = path.join(predecisionDirectory, "initial_full_page.png");
  if (!existsSync(filename)) await capture("initial_full_page.png");
  else indexFile(filename);
  await appendAction("INITIAL_SCREENSHOT_CAPTURED", "FULL_PAGE");
  return { case_alias: alias, artifact: fileItem(filename) };
}

async function inspectTimeframe(label) {
  const code = timeframeCode(label);
  if (!code) throw new Error("Unsupported visible timeframe label");
  await page.getByRole("button", { name: `Inspect ${label} timeframe` }).click();
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if ((await metadata()).inspected_timeframes.includes(code)) break;
    await page.waitForTimeout(50);
  }
  await appendAction("TIMEFRAME_INSPECTED", label, { selected_timeframe: code });
  const filename = await capture(`timeframe_${code}_${String(actions.length).padStart(4, "0")}.png`);
  return { case_alias: alias, timeframe: code, artifact: fileItem(filename) };
}

async function advance(minutes) {
  const before = await metadata();
  await page.getByRole("button", { name: `Step Codex replay ${minutes} minute${minutes === 1 ? "" : "s"}` }).click();
  let changed = false;
  for (let attempt = 0; attempt < 200; attempt += 1) {
    if ((await metadata()).cursor_at !== before.cursor_at) { changed = true; break; }
    await page.waitForTimeout(50);
  }
  if (!changed) throw new Error("Visible cursor did not advance");
  await appendAction("CURSOR_ADVANCED", `PLUS_${minutes}_MINUTES`, { selected_timeframe: "15m" });
  const filename = await capture(`checkpoint_${String(actions.length).padStart(4, "0")}.png`);
  return { case_alias: alias, artifact: fileItem(filename) };
}

async function screenshot() {
  const filename = await capture(`review_${String(actions.length + 1).padStart(4, "0")}.png`);
  await appendAction("OPERATOR_REVIEW_SCREENSHOT", "FULL_PAGE");
  return { case_alias: alias, artifact: fileItem(filename) };
}

async function openTrade(payload) {
  const direction = payload.direction;
  if (!["LONG", "SHORT"].includes(direction)) throw new Error("direction must be LONG or SHORT");
  const fractions = [payload.entry_y, payload.stop_y, payload.target_y].map(Number);
  if (fractions.some((value) => !(value > 0.08 && value < 0.92))) throw new Error("Position y fractions must be within the visible chart");
  const chart = page.getByTestId("synchronized-replay-chart");
  await chart.scrollIntoViewIfNeeded();
  const box = await chart.boundingBox();
  if (!box) throw new Error("Visible chart has no bounding box");
  await page.getByRole("button", { name: direction === "LONG" ? "Long position" : "Short position" }).click();
  const x = box.x + box.width * Number(payload.x ?? 0.78);
  for (const y of fractions) await page.mouse.click(x, box.y + box.height * y);
  await page.getByRole("button", { name: "Open blind trade decision form" }).click();
  await page.getByLabel("Codex decision form", { exact: true }).waitFor({ state: "visible" });
  await appendAction("TRADE_FORM_OPENED", direction, { selected_timeframe: "15m" });
  const filename = await capture(`trade_geometry_${String(actions.length).padStart(4, "0")}.png`);
  return { case_alias: alias, artifact: fileItem(filename) };
}

async function fillTradeForm(value) {
  const select = async (label, selected) => page.getByLabel(label).selectOption(selected);
  const fill = async (label, text) => page.getByLabel(label).fill(String(text));
  await select("Setup class", value.setup_class);
  await select("Higher-timeframe state", value.higher_timeframe_state);
  await fill("Codex trade thesis", value.thesis);
  await fill("Macro regime", value.macro_regime);
  await fill("Macro directional pressure", value.macro_directional_pressure);
  await select("Macro role", value.macro_role);
  await fill("Macro freshness", value.macro_freshness);
  await fill("Codex dominant driver", value.dominant_driver);
  await fill("Catalyst risk", value.catalyst_risk);
  await fill("Codex higher-timeframe context", value.higher_timeframe_context);
  await select("Location timeframe", value.location_timeframe);
  await fill("Pre-existing location", value.preexisting_location);
  await fill("M15 transition", value.m15_transition);
  await fill("Codex session and liquidity context", value.session_liquidity_context);
  await fill("Codex invalidation condition", value.invalidation_condition);
  await fill("Codex target logic", value.target_logic);
  await select("Target type", value.target_type);
  await page.getByLabel("Macro confidence").fill(String(value.macro_confidence));
  await page.getByLabel("Setup quality").fill(String(value.setup_quality));
  await page.getByLabel("Execution quality").fill(String(value.execution_quality));
  await appendAction("TRADE_FORM_COMPLETED", value.setup_class, { selected_timeframe: "15m" });
  return screenshot();
}

async function openNoTrade(reason) {
  await page.getByRole("button", { name: "Open no-trade decision form" }).click();
  await page.getByLabel("No-trade reason").fill(reason);
  await appendAction("NO_TRADE_FORM_COMPLETED", "NO_TRADE", { selected_timeframe: "15m" });
  return screenshot();
}

async function cancelForm() {
  await page.getByRole("button", { name: "Cancel Codex decision form" }).click();
  await appendAction("DECISION_FORM_CANCELLED", "RETURN_TO_CHART");
  return screenshot();
}

async function clearDrawings() {
  await page.getByRole("button", { name: "Clear all drawings" }).click();
  await appendAction("DRAWINGS_CLEARED", "VISIBLE_CHART");
  return screenshot();
}

function evidenceKind(filename) {
  if (filename.includes("initial_full_page")) return { kind: "INITIAL_FULL_PAGE_SCREENSHOT" };
  if (filename.includes("timeframe_")) {
    const match = path.basename(filename).match(/^timeframe_(1w|1d|4h|1h|15m|5m|1m)_/);
    return { kind: "TIMEFRAME_SCREENSHOT", timeframe: match?.[1] };
  }
  throw new Error(`Unregistered pre-decision screenshot: ${filename}`);
}

async function sealDecision() {
  const before = await metadata();
  if (before.case_alias !== alias) throw new Error("Active browser and server case differ");
  const finalPage = await capture("final_predecision_full_page.png");
  const chartCrop = await capture("final_predecision_chart_crop.png", false, page.getByTestId("synchronized-replay-chart"));
  const form = await capture("completed_decision_form.png", false, page.getByLabel("Codex decision form", { exact: true }));
  await appendAction("PREDECISION_EVIDENCE_FROZEN", "DECISION_FORM", { selected_timeframe: "15m" });
  const actionLog = path.join(predecisionDirectory, "predecision_chronological_actions.jsonl");
  writeFileSync(actionLog, `${actions.map((row) => JSON.stringify(row)).join("\n")}\n`);
  const screenshotFiles = [...new Set([
    path.join(predecisionDirectory, "initial_full_page.png"),
    ...readFileNames(predecisionDirectory).filter((filename) => path.basename(filename).startsWith("timeframe_")),
  ])];
  const artifacts = screenshotFiles.map((filename) => ({ ...fileItem(filename), ...evidenceKind(filename) }));
  artifacts.push(
    { ...fileItem(finalPage), kind: "FINAL_PREDECISION_FULL_PAGE_SCREENSHOT" },
    { ...fileItem(chartCrop), kind: "FINAL_PREDECISION_CHART_CROP" },
    { ...fileItem(form), kind: "COMPLETED_DECISION_FORM_SCREENSHOT" },
    { ...fileItem(actionLog), kind: "CHRONOLOGICAL_ACTION_LOG" },
  );
  const manifest = {
    version: "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_PREDECISION_EVIDENCE_1_0",
    case_alias: alias,
    cursor_at: before.cursor_at,
    visible_state_sha256: before.visible_state_sha256,
    inspected_timeframes: before.inspected_timeframes,
    artifacts,
  };
  const manifestPath = path.join(predecisionDirectory, "predecision_evidence_manifest.json");
  writeJson(manifestPath, manifest);
  const evidenceSha = sha(manifestPath);
  await page.getByLabel("Pre-decision evidence SHA-256").fill(evidenceSha);
  const completedAlias = alias;
  await page.getByRole("button", { name: "Seal Codex decision" }).click();
  await page.getByText(new RegExp(`${completedAlias} sealed\\. Its outcome is hidden`)).waitFor({ state: "visible", timeout: 60_000 });
  actions.push({ sequence: actions.length + 1, wall_clock_at: new Date().toISOString(), action: "DECISION_SEALED", target: completedAlias, outcome: "HIDDEN" });
  appendFileSync(journalPath, `${JSON.stringify(actions.at(-1))}\n`);
  const completeActions = path.join(browserDirectory, "complete_chronological_actions.jsonl");
  writeFileSync(completeActions, `${actions.map((row) => JSON.stringify(row)).join("\n")}\n`);
  await closeCaseContext();
  const outcomeRun = spawnSync(process.execPath, [renderer, "--artifact", artifact, "--alias", completedAlias], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  if (outcomeRun.status !== 0) throw new Error(`Sealed outcome recorder failed for ${completedAlias}`);
  const outcomeManifest = path.join(artifact, "outcome_vault", "evidence", completedAlias, "sealed_outcome_recording_manifest.json");
  if (!existsSync(outcomeManifest)) throw new Error("Sealed outcome recording manifest is absent");
  const caseManifest = path.join(browserDirectory, "complete_case_evidence_manifest.json");
  writeJson(caseManifest, {
    version: "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_COMPLETE_CASE_EVIDENCE_1_0",
    case_alias: completedAlias,
    predecision_manifest: fileItem(manifestPath),
    complete_action_log: fileItem(completeActions),
    browser_recordings: readdirSync(browserDirectory)
      .filter((filename) => /^browser_(interaction|trace)_segment_\d{3}\.(webm|zip)$/.test(filename))
      .sort()
      .map((filename) => fileItem(path.join(browserDirectory, filename))),
    sealed_outcome_recording_manifest: fileItem(outcomeManifest),
    outcome_access: "PROHIBITED_UNTIL_COMPLETE_SAMPLE_FINAL_OPEN",
  });
  let nextAlias = null;
  try {
    await startCaseContext();
    nextAlias = alias;
  } catch (error) {
    if (!String(error).includes("HTTP 404")) throw error;
    alias = null;
  }
  return {
    completed_case_alias: completedAlias,
    next_case_alias: nextAlias,
    predecision_manifest_sha256: evidenceSha,
    complete_case_manifest_sha256: sha(caseManifest),
    outcome_recording_manifest_sha256: sha(outcomeManifest),
    outcome_hidden: true,
  };
}

function readFileNames(directory) {
  return readFileSync(path.join(directory, ".file-index"), "utf8").split("\n").filter(Boolean);
}

function indexFile(filename) {
  const index = path.join(predecisionDirectory, ".file-index");
  const existing = existsSync(index) ? new Set(readFileSync(index, "utf8").split("\n").filter(Boolean)) : new Set();
  existing.add(filename);
  writeFileSync(index, `${[...existing].join("\n")}\n`);
}

async function dispatch(action, payload) {
  if (action === "capture_initial") return captureInitial();
  if (action === "inspect") return inspectTimeframe(payload.timeframe);
  if (action === "advance") return advance(Number(payload.minutes));
  if (action === "screenshot") return screenshot();
  if (action === "open_trade") return openTrade(payload);
  if (action === "fill_trade") return fillTradeForm(payload.annotation);
  if (action === "open_no_trade") return openNoTrade(payload.reason);
  if (action === "cancel_form") return cancelForm();
  if (action === "clear_drawings") return clearDrawings();
  if (action === "seal") return sealDecision();
  if (action === "status") {
    const state = await metadata();
    return { state: "READY", case_alias: alias, cursor_at: state.cursor_at, cases_completed: state.progress_completed, outcomes: "HIDDEN" };
  }
  throw new Error(`Unsupported operator control action: ${action}`);
}

const freeBytes = statfsSync(artifact).bavail * statfsSync(artifact).bsize;
if (freeBytes < 10 * 1024 ** 3) throw new Error("Runtime storage gate failed: less than 10 GiB free");
await startCaseContext();

const server = http.createServer(async (request, response) => {
  try {
    if (request.headers.authorization !== `Bearer ${token}`) {
      response.writeHead(401, { "Content-Type": "application/json" });
      response.end(JSON.stringify({ error: "UNAUTHORIZED" }));
      return;
    }
    if (busy) throw new Error("Operator daemon is processing another visible action");
    busy = true;
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    const payload = chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : {};
    const result = await dispatch(payload.action ?? "status", payload);
    response.writeHead(200, { "Content-Type": "application/json", "Cache-Control": "no-store" });
    response.end(JSON.stringify(result));
  } catch (error) {
    response.writeHead(409, { "Content-Type": "application/json", "Cache-Control": "no-store" });
    response.end(JSON.stringify({ error: error instanceof Error ? error.message : "Operator daemon failure" }));
  } finally {
    busy = false;
  }
});

server.listen(port, "127.0.0.1", () => {
  process.stdout.write(`${JSON.stringify({ status: "READY", port, case_alias: alias, token_path: tokenPath })}\n`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, async () => {
    server.close();
    try { await closeCaseContext(); } finally { if (browser) await browser.close(); }
    process.exit(0);
  });
}
