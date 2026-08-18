import { createHash } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  statSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { verifiedLedger } from "./codex-operator-ledger-integrity.mjs";


const VISIBLE_VERSION = "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_VISIBLE_EVENT_1_0";
const OUTCOME_VERSION = "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_OUTCOME_EVENT_1_0";
const RESULT_VERSION = "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_EARLY_STOP_RESULT_1_0";
const BOOTSTRAP_SEED = 20260818;
const BOOTSTRAP_SAMPLES = 20_000;
const RISK_UNIT_USD = 50;
const ACCOUNT_USD = 10_000;
const EPSILON = 1e-10;

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(scriptDirectory, "../..");
const artifactRoot = path.join(
  repositoryRoot,
  "research_artifacts",
  "gold_blind_codex_operator_replay_v1",
);
const visibleLedgerPath = path.join(artifactRoot, "ledgers", "codex_blind_visible_ledger.jsonl");
const outcomeLedgerPath = path.join(artifactRoot, "outcome_vault", "codex_blind_outcome_ledger.jsonl");
const amendmentPath = path.join(repositoryRoot, "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_EARLY_STOP_AMENDMENT_E.md");
const preopenPath = path.join(artifactRoot, "early_stop_preopen_freeze.json");
const detailPath = path.join(artifactRoot, "early_stop_case_results.json");
const csvPath = path.join(artifactRoot, "early_stop_case_results.csv");
const evidenceIndexPath = path.join(repositoryRoot, "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_EXECUTION_INDEX.md");
const reportPath = path.join(repositoryRoot, "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_EARLY_STOP_RESULT.md");
const finalSealPath = path.join(artifactRoot, "early_stop_final_seal.json");

const aliases = Array.from({ length: 30 }, (_, index) => `CBR-2022-${String(index + 1).padStart(3, "0")}`);
const cleanAliases = aliases.filter((alias) => alias !== "CBR-2022-019");


function fail(message) {
  throw new Error(message);
}


function shaBuffer(value) {
  return createHash("sha256").update(value).digest("hex");
}


function shaFile(filename) {
  return shaBuffer(readFileSync(filename));
}


function shaJson(value) {
  return shaBuffer(JSON.stringify(value));
}


function relative(filename) {
  return path.relative(repositoryRoot, filename).replaceAll("\\", "/");
}


function fileSeal(filename) {
  const stats = statSync(filename);
  return { path: relative(filename), bytes: stats.size, sha256: shaFile(filename) };
}


function writeJson(filename, value) {
  mkdirSync(path.dirname(filename), { recursive: true });
  writeFileSync(filename, `${JSON.stringify(value, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
}


function check(condition, message) {
  if (!condition) fail(message);
}


function resolveArtifactItem(item) {
  check(item && typeof item.path === "string", "Evidence item has no path");
  const filename = path.resolve(repositoryRoot, item.path);
  check(filename.startsWith(repositoryRoot + path.sep), `Evidence path escapes repository: ${item.path}`);
  check(existsSync(filename), `Evidence file is absent: ${item.path}`);
  const stats = statSync(filename);
  check(stats.size === item.bytes, `Evidence byte count differs: ${item.path}`);
  check(shaFile(filename) === item.sha256, `Evidence hash differs: ${item.path}`);
  return filename;
}


function verifyPredecisionManifest(alias, filename) {
  const manifest = JSON.parse(readFileSync(filename, "utf8"));
  check(manifest.version === "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_PREDECISION_EVIDENCE_1_0", `Pre-decision version differs: ${alias}`);
  check(manifest.case_alias === alias, `Pre-decision alias differs: ${alias}`);
  check(Array.isArray(manifest.artifacts) && manifest.artifacts.length >= 9, `Pre-decision artifacts incomplete: ${alias}`);
  for (const item of manifest.artifacts) resolveArtifactItem(item);
  return { seal: fileSeal(filename), artifact_count: manifest.artifacts.length };
}


function verifyOutcomeRecordingManifest(alias, filename) {
  const manifest = JSON.parse(readFileSync(filename, "utf8"));
  check(manifest.version === "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_SEALED_OUTCOME_RECORDING_1_0", `Outcome-recording version differs: ${alias}`);
  check(manifest.case_alias === alias, `Outcome-recording alias differs: ${alias}`);
  check(Array.isArray(manifest.artifacts) && manifest.artifacts.length === 2, `Outcome-recording artifacts incomplete: ${alias}`);
  for (const item of manifest.artifacts) resolveArtifactItem(item);
  return { seal: fileSeal(filename), artifact_count: manifest.artifacts.length };
}


function verifyCompleteManifest(alias) {
  const filename = path.join(artifactRoot, "evidence", "browser", alias, "complete_case_evidence_manifest.json");
  check(existsSync(filename), `Complete-case manifest absent: ${alias}`);
  const manifest = JSON.parse(readFileSync(filename, "utf8"));
  check(manifest.version === "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_COMPLETE_CASE_EVIDENCE_1_0", `Complete-case version differs: ${alias}`);
  check(manifest.case_alias === alias, `Complete-case alias differs: ${alias}`);
  resolveArtifactItem(manifest.predecision_manifest);
  resolveArtifactItem(manifest.complete_action_log);
  check(Array.isArray(manifest.browser_recordings) && manifest.browser_recordings.length >= 2, `Browser recordings incomplete: ${alias}`);
  for (const item of manifest.browser_recordings) resolveArtifactItem(item);
  resolveArtifactItem(manifest.sealed_outcome_recording_manifest);
  const predecision = verifyPredecisionManifest(alias, path.resolve(repositoryRoot, manifest.predecision_manifest.path));
  const outcome = verifyOutcomeRecordingManifest(alias, path.resolve(repositoryRoot, manifest.sealed_outcome_recording_manifest.path));
  return {
    case_alias: alias,
    disposition: "CLEAN_COMPLETE_EVIDENCE_VERIFIED",
    complete_manifest: fileSeal(filename),
    predecision,
    outcome,
  };
}


function verifyCase019Exception() {
  const alias = "CBR-2022-019";
  const predecisionPath = path.join(artifactRoot, "evidence", "predecision", alias, "predecision_evidence_manifest.json");
  const browserPath = path.join(artifactRoot, "evidence", "browser", alias);
  const preservedNames = [
    "browser_trace_segment_001.zip",
    "complete_chronological_actions.jsonl",
    "operator_action_journal.jsonl",
  ];
  check(existsSync(predecisionPath), "Case 019 pre-decision manifest is absent");
  const preserved = preservedNames.map((name) => {
    const filename = path.join(browserPath, name);
    check(existsSync(filename), `Case 019 exception artifact is absent: ${name}`);
    return fileSeal(filename);
  });
  return {
    case_alias: alias,
    disposition: "POST_DECISION_CONTAMINATED_AND_RENDERER_ARTIFACT_EXCEPTION",
    primary_sample: false,
    predecision: verifyPredecisionManifest(alias, predecisionPath),
    preserved,
    absent_by_known_exception: [
      relative(path.join(browserPath, "complete_case_evidence_manifest.json")),
      relative(path.join(artifactRoot, "outcome_vault", "evidence", alias, "sealed_outcome_recording_manifest.json")),
    ],
  };
}


function one(rows, predicate, label) {
  const matches = rows.filter(predicate);
  check(matches.length === 1, `${label}: expected one row, found ${matches.length}`);
  return matches[0];
}


function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}


function average(values) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
}


function rounded(value, digits = 8) {
  if (value === null || value === undefined || !Number.isFinite(value)) return value ?? null;
  return Number(value.toFixed(digits));
}


function quantile(values, probability) {
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  const position = (sorted.length - 1) * probability;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) return sorted[lower];
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
}


function wilson(wins, count) {
  if (!count) return [null, null];
  const z = 1.959963984540054;
  const probability = wins / count;
  const denominator = 1 + z * z / count;
  const center = (probability + z * z / (2 * count)) / denominator;
  const margin = z * Math.sqrt(probability * (1 - probability) / count + z * z / (4 * count * count)) / denominator;
  return [rounded(center - margin, 6), rounded(center + margin, 6)];
}


function randomGenerator(seed) {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(1664525, state) + 1013904223) >>> 0;
    return state / 4294967296;
  };
}


function bootstrapExpectancy(trades) {
  if (!trades.length) return [null, null];
  const random = randomGenerator(BOOTSTRAP_SEED);
  const estimates = [];
  for (let iteration = 0; iteration < BOOTSTRAP_SAMPLES; iteration += 1) {
    let total = 0;
    for (let index = 0; index < trades.length; index += 1) {
      total += trades[Math.floor(random() * trades.length)].r50;
    }
    estimates.push(total / trades.length);
  }
  return [rounded(quantile(estimates, 0.025), 6), rounded(quantile(estimates, 0.975), 6)];
}


function classifySession(row) {
  if (row.action === "NO_TRADE") return "NO_TRADE_TERMINAL";
  const context = String(row.session_liquidity_context ?? "").toUpperCase();
  if (context.includes("LONDON") && (context.includes("NEW YORK") || context.includes("NEW_YORK"))) return "LONDON_NEW_YORK_OVERLAP";
  if (context.includes("NEW YORK") || context.includes("NEW_YORK")) return "NEW_YORK";
  if (context.includes("LONDON")) return "LONDON";
  const date = new Date(row.submitted_at);
  const hour = date.getUTCHours() + date.getUTCMinutes() / 60;
  if (hour >= 8 && hour <= 12) return "LONDON";
  if (hour >= 13 && hour <= 17) return "NEW_YORK";
  return "UNKNOWN";
}


function resolutionResult(row) {
  if (!row.is_trade) return "NO_TRADE";
  if (row.net_pnl_usd > EPSILON) return "WIN";
  if (row.net_pnl_usd < -EPSILON) return "LOSS";
  return "SCRATCH";
}


function summarize(rows) {
  const trades = rows.filter((row) => row.is_trade);
  const wins = trades.filter((row) => row.result === "WIN");
  const losses = trades.filter((row) => row.result === "LOSS");
  const scratches = trades.filter((row) => row.result === "SCRATCH");
  const rValues = trades.map((row) => row.r50);
  const winValues = wins.map((row) => row.r50);
  const lossValues = losses.map((row) => row.r50);
  const grossWin = wins.reduce((sum, row) => sum + row.net_pnl_usd, 0);
  const grossLoss = -losses.reduce((sum, row) => sum + row.net_pnl_usd, 0);
  let cumulative = 0;
  let peak = 0;
  let maximumDrawdown = 0;
  let longestWin = 0;
  let longestLoss = 0;
  let currentWin = 0;
  let currentLoss = 0;
  for (const row of [...trades].sort((left, right) => left.case_alias.localeCompare(right.case_alias))) {
    cumulative += row.r50;
    peak = Math.max(peak, cumulative);
    maximumDrawdown = Math.max(maximumDrawdown, peak - cumulative);
    if (row.result === "WIN") {
      currentWin += 1;
      currentLoss = 0;
    } else if (row.result === "LOSS") {
      currentLoss += 1;
      currentWin = 0;
    } else {
      currentWin = 0;
      currentLoss = 0;
    }
    longestWin = Math.max(longestWin, currentWin);
    longestLoss = Math.max(longestLoss, currentLoss);
  }
  const netPnl = trades.reduce((sum, row) => sum + row.net_pnl_usd, 0);
  const netR = rValues.reduce((sum, value) => sum + value, 0);
  const stressedPnl = trades.reduce((sum, row) => sum + row.stressed_1_5x_cost_pnl_usd, 0);
  const resolutionCounts = Object.fromEntries(
    [...new Set(rows.map((row) => row.resolution_state))].sort().map((state) => [state, rows.filter((row) => row.resolution_state === state).length]),
  );
  const directionCounts = Object.fromEntries(
    ["LONG", "SHORT"].map((direction) => [direction, trades.filter((row) => row.action === direction).length]),
  );
  return {
    cases: rows.length,
    trades: trades.length,
    no_trades: rows.length - trades.length,
    direction_counts: directionCounts,
    wins: wins.length,
    losses: losses.length,
    scratches: scratches.length,
    win_rate: trades.length ? rounded(wins.length / trades.length, 6) : null,
    win_rate_wilson_95: wilson(wins.length, trades.length),
    net_pnl_usd: rounded(netPnl),
    net_r50: rounded(netR),
    normalized_account_return_pct: rounded(netPnl / ACCOUNT_USD * 100, 6),
    expectancy_usd_per_trade: rounded(average(trades.map((row) => row.net_pnl_usd))),
    expectancy_r50_per_trade: rounded(average(rValues)),
    expectancy_r50_bootstrap_95: bootstrapExpectancy(trades),
    median_r50: rounded(median(rValues)),
    average_win_usd: rounded(average(wins.map((row) => row.net_pnl_usd))),
    average_loss_usd: rounded(average(losses.map((row) => row.net_pnl_usd))),
    average_win_r50: rounded(average(winValues)),
    average_loss_r50: rounded(average(lossValues)),
    profit_factor: grossLoss > 0 ? rounded(grossWin / grossLoss, 6) : null,
    gross_profit_usd: rounded(grossWin),
    gross_loss_usd: rounded(grossLoss),
    stressed_1_5x_cost_pnl_usd: rounded(stressedPnl),
    stressed_1_5x_cost_expectancy_r50: trades.length ? rounded(stressedPnl / RISK_UNIT_USD / trades.length) : null,
    maximum_drawdown_r50: rounded(maximumDrawdown),
    maximum_drawdown_usd: rounded(maximumDrawdown * RISK_UNIT_USD),
    maximum_drawdown_pct_of_10000: rounded(maximumDrawdown * RISK_UNIT_USD / ACCOUNT_USD * 100, 6),
    longest_win_streak: longestWin,
    longest_loss_streak: longestLoss,
    mean_mfe_r50: rounded(average(trades.map((row) => row.mfe_r50))),
    mean_mae_r50: rounded(average(trades.map((row) => row.mae_r50))),
    resolution_counts: resolutionCounts,
  };
}


function referenceSummary(rows) {
  const trades = [];
  for (const row of rows) if (row.is_trade) trades.push(row);
  let pnl = 0;
  let r = 0;
  let wins = 0;
  let losses = 0;
  let grossWin = 0;
  let grossLoss = 0;
  for (const trade of trades) {
    pnl += Number(trade.net_pnl_usd);
    r += Number(trade.r50);
    if (trade.net_pnl_usd > EPSILON) {
      wins += 1;
      grossWin += trade.net_pnl_usd;
    } else if (trade.net_pnl_usd < -EPSILON) {
      losses += 1;
      grossLoss -= trade.net_pnl_usd;
    }
  }
  return {
    cases: rows.length,
    trades: trades.length,
    no_trades: rows.length - trades.length,
    wins,
    losses,
    net_pnl_usd: rounded(pnl),
    net_r50: rounded(r),
    expectancy_r50_per_trade: rounded(trades.length ? r / trades.length : null),
    profit_factor: grossLoss > 0 ? rounded(grossWin / grossLoss, 6) : null,
  };
}


function verifyReproduction(primary, reference, label) {
  for (const key of Object.keys(reference)) {
    check(JSON.stringify(primary[key]) === JSON.stringify(reference[key]), `${label} metric reproduction differs: ${key}`);
  }
  return { exact_agreement: true, compared_fields: Object.keys(reference), checksum: shaJson(reference) };
}


function segment(rows, field) {
  const values = [...new Set(rows.map((row) => String(row[field] ?? "UNKNOWN")))].sort();
  return Object.fromEntries(values.map((value) => [value, summarize(rows.filter((row) => String(row[field] ?? "UNKNOWN") === value))]));
}


function confidenceDiagnostics(rows) {
  const trades = rows.filter((row) => row.is_trade && Number.isFinite(row.setup_quality));
  const bins = [[0, 50], [50, 60], [60, 70], [70, 80], [80, 101]];
  const calibration = {};
  for (const [lower, upper] of bins) {
    const values = trades.filter((row) => row.setup_quality >= lower && row.setup_quality < upper);
    if (!values.length) continue;
    calibration[`${lower}_${upper - 1}`] = {
      support: values.length,
      mean_setup_quality: rounded(average(values.map((row) => row.setup_quality)), 4),
      observed_win_rate: rounded(values.filter((row) => row.result === "WIN").length / values.length, 6),
      expectancy_r50: rounded(average(values.map((row) => row.r50))),
    };
  }
  return {
    support: trades.length,
    mean_setup_quality: rounded(average(trades.map((row) => row.setup_quality)), 4),
    observed_win_rate: trades.length ? rounded(trades.filter((row) => row.result === "WIN").length / trades.length, 6) : null,
    bins: calibration,
    brier_score: "NOT_CALCULATED_SETUP_QUALITY_WAS_NOT_DEFINED_AS_WIN_PROBABILITY",
  };
}


function csvEscape(value) {
  if (value === null || value === undefined) return "";
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}


function markdownNumber(value, digits = 3) {
  return Number.isFinite(value) ? Number(value).toFixed(digits) : "—";
}


function executionLinks(alias, action) {
  const predecisionDirectory = path.join(artifactRoot, "evidence", "predecision", alias);
  const browserDirectory = path.join(artifactRoot, "evidence", "browser", alias);
  const outcomeDirectory = path.join(artifactRoot, "outcome_vault", "evidence", alias);
  const geometry = existsSync(predecisionDirectory)
    ? readdirSync(predecisionDirectory).find((name) => name.startsWith("trade_geometry_") && name.endsWith(".png"))
    : null;
  return {
    decision_form: relative(path.join(predecisionDirectory, "completed_decision_form.png")),
    predecision_chart: relative(path.join(predecisionDirectory, "final_predecision_chart_crop.png")),
    trade_geometry: action === "NO_TRADE" || !geometry ? null : relative(path.join(predecisionDirectory, geometry)),
    browser_recording: existsSync(path.join(browserDirectory, "browser_interaction_segment_001.webm"))
      ? relative(path.join(browserDirectory, "browser_interaction_segment_001.webm"))
      : null,
    browser_trace: existsSync(path.join(browserDirectory, "browser_trace_segment_001.zip"))
      ? relative(path.join(browserDirectory, "browser_trace_segment_001.zip"))
      : null,
    outcome_image: existsSync(path.join(outcomeDirectory, "sealed_outcome_final.png"))
      ? relative(path.join(outcomeDirectory, "sealed_outcome_final.png"))
      : null,
    outcome_video: existsSync(path.join(outcomeDirectory, "sealed_outcome_replay.webm"))
      ? relative(path.join(outcomeDirectory, "sealed_outcome_replay.webm"))
      : null,
  };
}


function mdLink(label, item) {
  return item ? `[${label}](${item.replaceAll(" ", "%20")})` : "—";
}


async function main() {
  check(!existsSync(finalSealPath), "Early-stop finalization is already sealed; refusing a second outcome opening");
  check(!existsSync(preopenPath), "A pre-open freeze already exists without a final seal; manual integrity review is required");
  check(existsSync(amendmentPath), "Early-stop Amendment E is absent");

  const visibleRows = verifiedLedger(visibleLedgerPath, VISIBLE_VERSION);
  const decisions = new Map();
  for (const alias of aliases) {
    const decision = one(
      visibleRows,
      (row) => row.case_alias === alias && ["DECISION_SEALED", "NO_TRADE_SEALED"].includes(row.event_type),
      `${alias} decision`,
    );
    one(visibleRows, (row) => row.case_alias === alias && row.event_type === "CASE_TERMINAL_HIDDEN", `${alias} terminal`);
    decisions.set(alias, decision);
  }
  check(
    visibleRows.filter((row) => row.case_alias === "CBR-2022-031" && ["DECISION_SEALED", "NO_TRADE_SEALED", "CASE_TERMINAL_HIDDEN"].includes(row.event_type)).length === 0,
    "Excluded Case 031 unexpectedly contains a decision or terminal event",
  );

  const evidence = cleanAliases.map(verifyCompleteManifest);
  const exception019 = verifyCase019Exception();
  const rawOutcomeSeal = fileSeal(outcomeLedgerPath);
  const preopen = {
    version: "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_EARLY_STOP_PREOPEN_1_0",
    frozen_at: new Date().toISOString(),
    amendment: fileSeal(amendmentPath),
    frozen_aliases: aliases,
    clean_aliases: cleanAliases,
    excluded_unfinished_aliases: ["CBR-2022-031"],
    contaminated_sensitivity_only_aliases: ["CBR-2022-019"],
    visible_ledger: fileSeal(visibleLedgerPath),
    visible_ledger_rows: visibleRows.length,
    decisions_verified: aliases.length,
    clean_complete_evidence_verified: evidence.length,
    clean_evidence: evidence,
    case_019_exception: exception019,
    outcome_ledger_raw_preopen_seal: rawOutcomeSeal,
    outcome_ledger_access_before_this_record: "RAW_BYTES_HASHED_ONLY_NOT_JSON_PARSED",
    outcome_opening_authorization: "ONE_CONTROLLED_OPEN_FOR_CASES_001_THROUGH_030",
  };
  writeJson(preopenPath, preopen);

  // This is the single controlled outcome opening authorized by Amendment E.
  const outcomeRows = verifiedLedger(outcomeLedgerPath, OUTCOME_VERSION);
  check(shaFile(outcomeLedgerPath) === rawOutcomeSeal.sha256, "Outcome ledger changed during controlled opening");

  const publicRegistry = JSON.parse(readFileSync(path.join(artifactRoot, "population_registry.public.json"), "utf8"));
  const publicCases = new Map(publicRegistry.cases.map((row) => [row.case_alias, row]));
  const caseRows = [];
  for (const alias of aliases) {
    const decisionEvent = decisions.get(alias);
    const decision = decisionEvent.data.decision;
    const terminal = one(visibleRows, (row) => row.case_alias === alias && row.event_type === "CASE_TERMINAL_HIDDEN", `${alias} terminal join`);
    const sealed = one(outcomeRows, (row) => row.case_alias === alias && row.event_type === "CASE_OUTCOME_SEALED", `${alias} outcome seal`);
    check(sealed.data.decision_sha256 === terminal.data.decision_sha256, `${alias} decision/outcome hash differs`);
    const isTrade = decision.action !== "NO_TRADE";
    let outcome = null;
    if (isTrade) {
      one(outcomeRows, (row) => row.case_alias === alias && row.event_type === "ORDER_FILLED", `${alias} fill`);
      outcome = one(outcomeRows, (row) => row.case_alias === alias && row.event_type === "POSITION_RESOLVED", `${alias} resolution`).data;
      check(outcome.decision_sha256 === terminal.data.decision_sha256, `${alias} resolution decision hash differs`);
    } else {
      check(outcomeRows.filter((row) => row.case_alias === alias && ["ORDER_FILLED", "POSITION_RESOLVED"].includes(row.event_type)).length === 0, `${alias} NO_TRADE has fill or resolution`);
      check(sealed.data.state === "NO_TRADE", `${alias} NO_TRADE seal differs`);
    }
    const annotation = decision.annotation ?? {};
    const publicCase = publicCases.get(alias);
    check(publicCase, `${alias} absent from public population registry`);
    const rawGrossPnl = isTrade
      ? (decision.action === "LONG" ? 1 : -1) * (Number(outcome.resolution.raw_exit_price) - Number(outcome.fill.raw_price)) * Number(outcome.quantity_ounces)
      : 0;
    const baseCost = isTrade ? rawGrossPnl - Number(outcome.net_pnl_usd) : 0;
    const row = {
      case_alias: alias,
      trading_date_utc: publicCase.trading_date_utc,
      sample_disposition: alias === "CBR-2022-019" ? "CONTAMINATED_SENSITIVITY_ONLY" : "CLEAN_PRIMARY",
      action: decision.action,
      is_trade: isTrade,
      submitted_at: decision.expected_cursor_at,
      setup_class: annotation.setup_class ?? "NO_TRADE",
      setup_quality: Number.isFinite(annotation.setup_quality) ? Number(annotation.setup_quality) : null,
      execution_quality: Number.isFinite(annotation.execution_quality) ? Number(annotation.execution_quality) : null,
      macro_role: annotation.macro_role ?? "UNKNOWN",
      macro_directional_pressure: annotation.macro_directional_pressure ?? "UNKNOWN",
      higher_timeframe_state: annotation.higher_timeframe_state ?? "UNKNOWN",
      session_liquidity_context: annotation.session_liquidity_context ?? null,
      entry: isTrade ? Number(outcome.entry) : null,
      stop: isTrade ? Number(outcome.stop) : null,
      target: isTrade ? Number(outcome.target) : null,
      fill_at: isTrade ? outcome.fill.fill_at : null,
      fill_price: isTrade ? Number(outcome.fill.actual_price) : null,
      quantity_ounces: isTrade ? Number(outcome.quantity_ounces) : null,
      planned_risk_usd: isTrade ? Number(outcome.planned_risk_usd) : null,
      exit_at: isTrade ? outcome.resolution.exit_at : null,
      exit_price: isTrade ? Number(outcome.resolution.actual_exit_price) : null,
      resolution_state: isTrade ? outcome.resolution.state : "NO_TRADE",
      net_pnl_usd: isTrade ? Number(outcome.net_pnl_usd) : 0,
      r50: isTrade ? Number(outcome.r50) : 0,
      mfe_r50: isTrade ? Number(outcome.mfe_r50) : 0,
      mae_r50: isTrade ? Number(outcome.mae_r50) : 0,
      raw_gross_pnl_usd: rounded(rawGrossPnl),
      estimated_base_cost_usd: rounded(baseCost),
      stressed_1_5x_cost_pnl_usd: rounded(isTrade ? rawGrossPnl - 1.5 * baseCost : 0),
      post_fill_geometry_invalid: isTrade ? Boolean(outcome.post_fill_geometry_invalid) : false,
      evidence: executionLinks(alias, decision.action),
    };
    row.session = classifySession(row);
    row.result = resolutionResult(row);
    caseRows.push(row);
  }

  check(outcomeRows.filter((row) => row.case_alias === "CBR-2022-031").length === 0, "Excluded Case 031 unexpectedly has outcome rows");
  const cleanRows = caseRows.filter((row) => row.sample_disposition === "CLEAN_PRIMARY");
  const cleanSummary = summarize(cleanRows);
  const sensitivitySummary = summarize(caseRows);
  const reproduction = {
    clean: verifyReproduction(cleanSummary, referenceSummary(cleanRows), "clean sample"),
    all_30: verifyReproduction(sensitivitySummary, referenceSummary(caseRows), "all-30 sensitivity"),
    case_row_checksum: shaJson(caseRows),
  };
  const result = {
    version: RESULT_VERSION,
    opened_at: new Date().toISOString(),
    outcome_opening_count: 1,
    outcome_ledger: fileSeal(outcomeLedgerPath),
    preopen_freeze: fileSeal(preopenPath),
    primary_clean: cleanSummary,
    all_30_sensitivity: sensitivitySummary,
    verdict: "INCONCLUSIVE_EARLY_STOP_ZERO_CREDIT_CALIBRATION",
    verdict_reasons: [
      `Only ${cleanSummary.trades} clean filled trades versus the frozen minimum of 30.`,
      "The early-stop sample covers one calendar quarter, below the frozen three-positive-quarter requirement.",
      "Case 019 is post-decision contaminated and excluded from the primary result.",
      "This is blinded historical calibration, not independent forward validation.",
    ],
    frozen_gate_status: {
      minimum_30_clean_filled_trades: cleanSummary.trades >= 30,
      positive_net_expectancy: cleanSummary.expectancy_r50_per_trade > 0,
      profit_factor_gte_1_10: cleanSummary.profit_factor !== null && cleanSummary.profit_factor >= 1.1,
      positive_clustered_95pct_lower_bound: cleanSummary.expectancy_r50_bootstrap_95[0] > 0,
      positive_stressed_cost_expectancy: cleanSummary.stressed_1_5x_cost_expectancy_r50 > 0,
      minimum_3_positive_quarters: false,
      maximum_drawdown_lte_15pct: cleanSummary.maximum_drawdown_pct_of_10000 <= 15,
    },
    breakdowns_clean: {
      direction: segment(cleanRows.filter((row) => row.is_trade), "action"),
      setup_class: segment(cleanRows.filter((row) => row.is_trade), "setup_class"),
      session: segment(cleanRows, "session"),
      month: segment(cleanRows, "trading_date_utc"),
    },
    confidence_diagnostics_clean: confidenceDiagnostics(cleanRows),
    reproduction,
    cases: caseRows,
  };
  // Replace day-level month keys with calendar-month keys without changing case results.
  result.breakdowns_clean.month = segment(
    cleanRows.map((row) => ({ ...row, calendar_month: row.trading_date_utc.slice(0, 7) })),
    "calendar_month",
  );
  writeJson(detailPath, result);

  const csvFields = [
    "case_alias", "trading_date_utc", "sample_disposition", "action", "session", "setup_class", "setup_quality",
    "entry", "stop", "target", "fill_at", "fill_price", "quantity_ounces", "planned_risk_usd", "exit_at",
    "exit_price", "resolution_state", "result", "net_pnl_usd", "r50", "mfe_r50", "mae_r50",
    "stressed_1_5x_cost_pnl_usd", "post_fill_geometry_invalid",
  ];
  const csv = [
    csvFields.join(","),
    ...caseRows.map((row) => csvFields.map((field) => csvEscape(row[field])).join(",")),
  ].join("\n") + "\n";
  writeFileSync(csvPath, csv, { encoding: "utf8", flag: "wx" });

  const indexRows = caseRows.map((row) => {
    const links = row.evidence;
    const before = [mdLink("decision", links.decision_form), mdLink("chart", links.predecision_chart), mdLink("geometry", links.trade_geometry)].join(" · ");
    const recording = [mdLink("video", links.browser_recording), mdLink("trace", links.browser_trace)].join(" · ");
    const outcome = [mdLink("image", links.outcome_image), mdLink("replay", links.outcome_video)].join(" · ");
    return `| ${row.case_alias} | ${row.action} | ${row.result} | ${markdownNumber(row.r50)} | ${before} | ${recording} | ${outcome} |`;
  }).join("\n");
  const evidenceIndex = `# Gold Blind Codex-Operator Replay V1 — Execution Index\n\n` +
    `This index opens the sealed evidence for the early-stop sample. Case 019 is sensitivity-only and lacks its finalized renderer video/image because of the preserved technical exception.\n\n` +
    `| Case | Decision | Result | R | Pre-decision | Browser evidence | Outcome evidence |\n` +
    `|---|---:|---:|---:|---|---|---|\n${indexRows}\n`;
  writeFileSync(evidenceIndexPath, evidenceIndex, { encoding: "utf8", flag: "wx" });

  const clean = cleanSummary;
  const sensitivity = sensitivitySummary;
  const outcomeTable = caseRows.map((row) =>
    `| ${row.case_alias} | ${row.trading_date_utc} | ${row.action} | ${row.setup_class} | ${row.resolution_state} | ${row.result} | ${row.net_pnl_usd >= 0 ? "+" : ""}$${markdownNumber(row.net_pnl_usd, 2)} | ${row.r50 >= 0 ? "+" : ""}${markdownNumber(row.r50)} |`,
  ).join("\n");
  const report = `# Gold Blind Codex-Operator Replay V1 — Early-Stop Result\n\n` +
    `## Verdict\n\n` +
    `**INCONCLUSIVE — early-stop, zero-credit calibration.** The clean primary sample contains ${clean.cases} cases and ${clean.trades} filled trades, below the frozen 30-trade minimum. These numbers describe how Codex performed; they do not validate an edge.\n\n` +
    `## Primary clean performance\n\n` +
    `Case 019 is excluded. Across ${clean.cases} cases, Codex traded ${clean.trades} and passed on ${clean.no_trades}. It won ${clean.wins}, lost ${clean.losses}, and scratched ${clean.scratches}.\n\n` +
    `- Net: **${clean.net_r50 >= 0 ? "+" : ""}${markdownNumber(clean.net_r50)}R (${clean.net_pnl_usd >= 0 ? "+" : ""}$${markdownNumber(clean.net_pnl_usd, 2)})**.\n` +
    `- Win rate: **${markdownNumber(clean.win_rate * 100, 1)}%**; 95% Wilson interval ${markdownNumber(clean.win_rate_wilson_95[0] * 100, 1)}%–${markdownNumber(clean.win_rate_wilson_95[1] * 100, 1)}%.\n` +
    `- Expectancy: **${clean.expectancy_r50_per_trade >= 0 ? "+" : ""}${markdownNumber(clean.expectancy_r50_per_trade)}R/trade** (${clean.expectancy_usd_per_trade >= 0 ? "+" : ""}$${markdownNumber(clean.expectancy_usd_per_trade, 2)}); bootstrap 95% interval ${clean.expectancy_r50_bootstrap_95[0] >= 0 ? "+" : ""}${markdownNumber(clean.expectancy_r50_bootstrap_95[0])}R to ${clean.expectancy_r50_bootstrap_95[1] >= 0 ? "+" : ""}${markdownNumber(clean.expectancy_r50_bootstrap_95[1])}R.\n` +
    `- Profit factor: **${markdownNumber(clean.profit_factor, 2)}**. Average win/loss: ${clean.average_win_r50 >= 0 ? "+" : ""}${markdownNumber(clean.average_win_r50)}R / ${markdownNumber(clean.average_loss_r50)}R.\n` +
    `- Maximum drawdown: **${markdownNumber(clean.maximum_drawdown_r50)}R ($${markdownNumber(clean.maximum_drawdown_usd, 2)})**, ${markdownNumber(clean.maximum_drawdown_pct_of_10000, 2)}% of the frozen $10,000 account.\n` +
    `- Direction mix: ${clean.direction_counts.LONG} long and ${clean.direction_counts.SHORT} short.\n` +
    `- Mean MFE/MAE: ${markdownNumber(clean.mean_mfe_r50)}R / ${markdownNumber(clean.mean_mae_r50)}R.\n` +
    `- At 1.5× estimated execution costs: ${clean.stressed_1_5x_cost_pnl_usd >= 0 ? "+" : ""}$${markdownNumber(clean.stressed_1_5x_cost_pnl_usd, 2)}.\n\n` +
    `## All-30 sensitivity\n\n` +
    `Including contaminated Case 019 changes the descriptive total to **${sensitivity.net_r50 >= 0 ? "+" : ""}${markdownNumber(sensitivity.net_r50)}R (${sensitivity.net_pnl_usd >= 0 ? "+" : ""}$${markdownNumber(sensitivity.net_pnl_usd, 2)})**, with ${sensitivity.wins}/${sensitivity.trades} wins, ${markdownNumber(sensitivity.win_rate * 100, 1)}% win rate, ${markdownNumber(sensitivity.profit_factor, 2)} profit factor, and ${sensitivity.expectancy_r50_per_trade >= 0 ? "+" : ""}${markdownNumber(sensitivity.expectancy_r50_per_trade)}R/trade expectancy. This sensitivity receives no primary evidence credit.\n\n` +
    `## Gate disposition\n\n` +
    `The branch cannot PASS because the clean sample has only ${clean.trades} filled trades and one calendar quarter. The uncertainty and gate details are preserved in the machine-readable result. Calendar 2025 and 2026 were not opened. Case 031 was not decided and is excluded.\n\n` +
    `## Per-case results\n\n` +
    `| Case | Date | Action | Setup | Resolution | Result | PnL | R |\n` +
    `|---|---|---|---|---|---:|---:|---:|\n${outcomeTable}\n\n` +
    `## Evidence\n\n` +
    `Use [the execution index](${relative(evidenceIndexPath)}) for each pre-decision chart, trade geometry, browser recording, trace, sealed outcome image, and outcome replay. Machine-readable results are in [JSON](${relative(detailPath)}) and [CSV](${relative(csvPath)}).\n`;
  writeFileSync(reportPath, report, { encoding: "utf8", flag: "wx" });

  const finalSeal = {
    version: "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_EARLY_STOP_FINAL_SEAL_1_0",
    sealed_at: new Date().toISOString(),
    verdict: result.verdict,
    outcome_opening_count: 1,
    outcome_ledger_sha256: rawOutcomeSeal.sha256,
    files: [preopenPath, detailPath, csvPath, evidenceIndexPath, reportPath].map(fileSeal),
    independent_metric_reproduction: reproduction,
    calendar_2025: "LOCKED_NOT_INSPECTED",
    calendar_2026: "LOCKED_NOT_INSPECTED",
  };
  writeJson(finalSealPath, finalSeal);
  process.stdout.write(`${JSON.stringify({
    status: "SEALED",
    verdict: result.verdict,
    primary_clean: cleanSummary,
    all_30_sensitivity: sensitivitySummary,
    report: relative(reportPath),
    execution_index: relative(evidenceIndexPath),
    final_seal: fileSeal(finalSealPath),
  }, null, 2)}\n`);
}


await main();
