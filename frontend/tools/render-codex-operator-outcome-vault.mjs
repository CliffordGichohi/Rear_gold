import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, renameSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { gunzipSync } from "node:zlib";

import { chromium } from "@playwright/test";

import { verifiedLedger } from "./codex-operator-ledger-integrity.mjs";


function args() {
  const values = Object.fromEntries(process.argv.slice(2).flatMap((value, index, all) => value.startsWith("--") ? [[value.slice(2), all[index + 1]]] : []));
  if (!values.artifact || !values.alias) throw new Error("--artifact and --alias are required");
  return values;
}

function shaFile(filename) {
  return createHash("sha256").update(readFileSync(filename)).digest("hex");
}

function fileItem(filename, repositoryRoot) {
  return {
    path: path.relative(repositoryRoot, filename).replaceAll("\\", "/"),
    bytes: statSync(filename).size,
    sha256: shaFile(filename),
  };
}

async function main() {
  const options = args();
  const artifact = path.resolve(options.artifact);
  const repositoryRoot = path.resolve(artifact, "../..");
  const destination = path.join(artifact, "outcome_vault", "evidence", options.alias);
  const manifestPath = path.join(destination, "sealed_outcome_recording_manifest.json");
  if (existsSync(manifestPath)) {
    process.stdout.write(`${JSON.stringify({ status: "ALREADY_SEALED", case_alias: options.alias, manifest_sha256: shaFile(manifestPath) })}\n`);
    return;
  }
  mkdirSync(destination, { recursive: true });
  const certification = JSON.parse(readFileSync(path.join(artifact, "stream_materialization_certification.json"), "utf8"));
  const source = certification.case_files.find((item) => item.case_alias === options.alias)?.primary;
  if (!source) throw new Error("Certified private stream is absent");
  let sourcePath = path.resolve(repositoryRoot, source.path);
  if (!existsSync(sourcePath)) {
    const privateIndex = source.path.indexOf("private_streams");
    if (privateIndex < 0) throw new Error("Certified stream path is not relocatable");
    sourcePath = path.resolve(artifact, source.path.slice(privateIndex));
  }
  if (statSync(sourcePath).size !== source.bytes || shaFile(sourcePath) !== source.sha256) throw new Error("Certified private stream differs");
  const stream = JSON.parse(gunzipSync(readFileSync(sourcePath)).toString("utf8"));
  const visible = verifiedLedger(
    path.join(artifact, "ledgers", "codex_blind_visible_ledger.jsonl"),
    "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_VISIBLE_EVENT_1_0",
  );
  const hidden = verifiedLedger(
    path.join(artifact, "outcome_vault", "codex_blind_outcome_ledger.jsonl"),
    "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_OUTCOME_EVENT_1_0",
  );
  const decisionEvent = visible.find((row) => row.case_alias === options.alias && ["DECISION_SEALED", "NO_TRADE_SEALED"].includes(row.event_type));
  const terminal = visible.find((row) => row.case_alias === options.alias && row.event_type === "CASE_TERMINAL_HIDDEN");
  const sealed = hidden.find((row) => row.case_alias === options.alias && row.event_type === "CASE_OUTCOME_SEALED");
  if (!decisionEvent || !terminal || !sealed) throw new Error("Case is not terminal in both ledgers");
  const decision = decisionEvent.data.decision;
  const resolutionEvent = hidden.find((row) => row.case_alias === options.alias && row.event_type === "POSITION_RESOLVED");
  const outcome = resolutionEvent?.data ?? null;
  const finishAt = outcome?.resolution?.exit_at ?? stream.end_exclusive;
  const bars = stream.timeframes["1m"].filter((bar) => bar.close_at > decision.expected_cursor_at && bar.open_at <= finishAt);
  const displayBars = bars.length > 240 ? bars.filter((_, index) => index % Math.ceil(bars.length / 240) === 0 || index === bars.length - 1) : bars;
  const payload = {
    alias: options.alias,
    action: decision.action,
    cursor: decision.expected_cursor_at,
    bars: displayBars.map((bar) => ({ t: bar.close_at, o: bar.open, h: bar.high, l: bar.low, c: bar.close })),
    entry: decision.entry,
    stop: decision.stop,
    target: decision.target,
    fill: outcome?.fill?.actual_price ?? null,
    exit: outcome?.resolution?.actual_exit_price ?? null,
    exitState: outcome?.resolution?.state ?? "NO_TRADE",
  };
  const html = `<!doctype html><html><body style="margin:0;background:#f4f5f7;font-family:Arial;color:#131722"><canvas id="c" width="1280" height="720"></canvas><script>
    const p=${JSON.stringify(payload)}; const c=document.getElementById('c'),x=c.getContext('2d');
    window.draw=(count)=>{x.fillStyle='#f4f5f7';x.fillRect(0,0,1280,720);x.fillStyle='#131722';x.font='bold 22px Arial';x.fillText(p.alias+' | SEALED OUTCOME REPLAY',30,40);x.font='14px Arial';x.fillText('Decision '+p.action+' at '+p.cursor,30,66);const b=p.bars.slice(0,count);if(!b.length)return;const vals=b.flatMap(v=>[v.h,v.l]).concat([p.entry,p.stop,p.target,p.fill,p.exit].filter(Number.isFinite));let lo=Math.min(...vals),hi=Math.max(...vals),span=Math.max(hi-lo,.01);lo-=span*.08;hi+=span*.08;const top=95,bottom=650,left=40,right=1240;const yy=v=>top+(hi-v)/(hi-lo)*(bottom-top),step=(right-left)/Math.max(1,b.length);b.forEach((v,i)=>{const xx=left+(i+.5)*step;x.strokeStyle=v.c>=v.o?'#089981':'#f23645';x.fillStyle=x.strokeStyle;x.beginPath();x.moveTo(xx,yy(v.h));x.lineTo(xx,yy(v.l));x.stroke();x.fillRect(xx-Math.max(1,step*.28),Math.min(yy(v.o),yy(v.c)),Math.max(2,step*.56),Math.max(1,Math.abs(yy(v.o)-yy(v.c))))});[[p.entry,'#2962ff','ENTRY'],[p.stop,'#f23645','SL'],[p.target,'#089981','TP'],[p.fill,'#7e57c2','FILL'],[p.exit,'#d97706','EXIT']].forEach(([v,col,label])=>{if(!Number.isFinite(v))return;x.strokeStyle=col;x.setLineDash([6,4]);x.beginPath();x.moveTo(left,yy(v));x.lineTo(right,yy(v));x.stroke();x.setLineDash([]);x.fillStyle=col;x.fillText(label+' '+Number(v).toFixed(2),1050,yy(v)-4)});x.fillStyle='#131722';x.font='bold 18px Arial';x.fillText('Resolution: '+p.exitState,30,690)}; window.draw(1);
  </script></body></html>`;
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const staging = path.join(destination, "staging-video");
  mkdirSync(staging, { recursive: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 }, recordVideo: { dir: staging, size: { width: 1280, height: 720 } } });
  const page = await context.newPage();
  await page.setContent(html, { waitUntil: "load" });
  const frames = Math.max(2, Math.min(120, payload.bars.length));
  for (let index = 1; index <= frames; index += 1) {
    const count = Math.max(1, Math.ceil(payload.bars.length * index / frames));
    await page.evaluate((value) => window.draw(value), count);
    await page.waitForTimeout(30);
  }
  const screenshot = path.join(destination, "sealed_outcome_final.png");
  await page.screenshot({ path: screenshot });
  const video = page.video();
  await context.close();
  const recorded = await video.path();
  const finalVideo = path.join(destination, "sealed_outcome_replay.webm");
  renameSync(recorded, finalVideo);
  await browser.close();
  const manifest = {
    version: "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_SEALED_OUTCOME_RECORDING_1_0",
    case_alias: options.alias,
    decision_sha256: terminal.data.decision_sha256,
    outcome_vault_record_sha256: terminal.data.outcome_vault_record_sha256,
    source_stream_sha256: source.stream_sha256,
    artifacts: [fileItem(screenshot, repositoryRoot), fileItem(finalVideo, repositoryRoot)],
    operator_access: "PROHIBITED_UNTIL_COMPLETE_SAMPLE_FINAL_OPEN",
  };
  writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify({ status: "SEALED", case_alias: options.alias, manifest_sha256: shaFile(manifestPath) })}\n`);
}

await main();
