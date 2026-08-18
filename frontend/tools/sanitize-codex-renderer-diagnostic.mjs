import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";


const forbidden = new Set(["price", "bar", "direction", "entry", "stop", "target", "fill", "exit", "resolution", "pnl", "return", "outcome"]);

function shaBytes(value) {
  return createHash("sha256").update(value).digest("hex");
}

function sanitizeMessage(value) {
  let result = value;
  result = result.replace(/(?:file:\/\/\/)?[A-Za-z]:[\\/][^'"\r\n]+/g, "<PATH>");
  result = result.replace(/\/(?:[^\s:'"]+\/)+[^\s:'"]+/g, "<PATH>");
  result = result.replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z/g, "<TIMESTAMP>");
  result = result.replace(/(?<![A-Za-z])[-+]?\d+\.\d+(?![A-Za-z])/g, "<DECIMAL>");
  result = result.replace(/\b(?:price|bar|direction|entry|stop|target|fill|exit|resolution|pnl|return|outcome)\b/gi, "<REDACTED_TOKEN>");
  return result.trim().slice(0, 400);
}

function exceptionClass(lines) {
  for (const line of lines) {
    const match = line.match(/\b([A-Z][A-Za-z]*(?:Error|Exception))\b/);
    if (match) return match[1];
  }
  return "Error";
}

function exceptionCode(lines) {
  for (const line of lines) {
    const property = line.match(/\bcode\s*:\s*['"]([A-Z][A-Z0-9_]*)['"]/);
    if (property) return property[1];
    const prefix = line.match(/\b(?:Error|Exception)\s*:\s*([A-Z][A-Z0-9_]+)\b/);
    if (prefix) return prefix[1];
  }
  return "UNSPECIFIED";
}

function sourceAlias(value) {
  const normalized = value.replaceAll("\\", "/").toLowerCase();
  if (normalized.includes("render-codex-operator")) return "RENDERER_SOURCE";
  if (normalized.includes("playwright")) return "PLAYWRIGHT_RUNTIME";
  if (normalized.includes("node:")) return "NODE_RUNTIME";
  return "RUNTIME_SOURCE";
}

function primary(raw) {
  const lines = raw.split(/\r?\n/).filter(Boolean);
  const stack = [];
  for (const line of lines) {
    const match = line.match(/^\s*at\s+(?:(.*?)\s+\()?(.+?):(\d+):(\d+)\)?\s*$/);
    if (!match) continue;
    stack.push({ function: (match[1] || "anonymous").replace(/[^A-Za-z0-9_.<>]/g, "").slice(0, 80), source: sourceAlias(match[2]), line: Number(match[3]), column: Number(match[4]) });
  }
  const messageLine = lines.find((line) => /(?:Error|Exception)\s*:/.test(line)) ?? lines[0] ?? "Error";
  return { exception_class: exceptionClass(lines), exception_code: exceptionCode(lines), message_template: sanitizeMessage(messageLine), stack };
}

function reference(raw) {
  const lines = raw.split("\n").map((line) => line.replace(/\r$/, "")).filter((line) => line.length > 0);
  const stack = lines.filter((line) => line.trimStart().startsWith("at ")).map((line) => {
    const tail = line.trim().slice(3);
    const coordinate = tail.match(/(.*):(\d+):(\d+)\)?$/);
    if (!coordinate) return null;
    const prefix = coordinate[1];
    const open = prefix.lastIndexOf("(");
    const functionName = open >= 0 ? prefix.slice(0, open).trim() : "anonymous";
    const sourceName = open >= 0 ? prefix.slice(open + 1) : prefix;
    return { function: functionName.replace(/[^A-Za-z0-9_.<>]/g, "").slice(0, 80), source: sourceAlias(sourceName), line: Number(coordinate[2]), column: Number(coordinate[3]) };
  }).filter(Boolean);
  const messageLine = lines.filter((line) => line.includes("Error:") || line.includes("Exception:")).at(0) ?? lines.at(0) ?? "Error";
  return { exception_class: exceptionClass(lines), exception_code: exceptionCode(lines), message_template: sanitizeMessage(messageLine), stack };
}

function lifecycle(parsed) {
  const text = `${parsed.exception_code} ${parsed.message_template} ${parsed.stack.map((item) => item.function).join(" ")}`.toLowerCase();
  if (/rename|video|recording|videopath/.test(text)) return "VIDEO_FINALIZATION";
  if (/launch|executable|browserType/i.test(text)) return "DEPENDENCY_OR_BROWSER_LAUNCH";
  if (/ledger|canonical/.test(text)) return "LEDGER_INTEGRITY";
  if (/gunzip|private.*stream|certified.*stream/.test(text)) return "PRIVATE_STREAM_INTEGRITY";
  if (/setcontent|evaluate|screenshot|page\./.test(text)) return "BROWSER_PAGE_LIFECYCLE";
  if (/manifest|writefilesync/.test(text)) return "MANIFEST_FINALIZATION";
  return "UNRESOLVED";
}

function normalized(parsed) {
  return {
    exception_class: parsed.exception_class,
    exception_code: parsed.exception_code,
    lifecycle_classification: lifecycle(parsed),
    source_locations: parsed.stack.map(({ source, line, column }) => ({ source, line, column })),
  };
}

function validateReport(report) {
  const serialized = JSON.stringify(report);
  for (const token of forbidden) {
    const pattern = new RegExp(`(?:^|[^A-Za-z])${token}(?:$|[^A-Za-z])`, "i");
    if (pattern.test(serialized)) throw new Error(`Sanitized report retained forbidden token: ${token}`);
  }
  if (/\d+\.\d+/.test(serialized)) throw new Error("Sanitized report retained a decimal value");
}

function run(raw, expectedSha, rawBytes = Buffer.from(raw, "utf8")) {
  if (expectedSha && shaBytes(rawBytes) !== expectedSha) throw new Error("Sealed exception hash differs from frozen protocol");
  const a = primary(raw);
  const b = reference(raw);
  const na = normalized(a);
  const nb = normalized(b);
  if (JSON.stringify(na) !== JSON.stringify(nb)) throw new Error("Independent diagnostic parsers disagree");
  const report = {
    version: "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_SANITIZED_RENDERER_DIAGNOSTIC_1_0",
    sealed_input_sha256: shaBytes(rawBytes),
    exception_class: a.exception_class,
    exception_code: a.exception_code,
    message_template: a.message_template,
    lifecycle_classification: na.lifecycle_classification,
    stack_functions: a.stack.map((item) => item.function),
    source_locations: na.source_locations,
    parser_agreement: true,
    sensitive_values_exposed: false,
  };
  validateReport(report);
  return report;
}

const args = Object.fromEntries(process.argv.slice(2).flatMap((value, index, all) => value.startsWith("--") ? [[value.slice(2), all[index + 1]]] : []));
if (args["self-test"] !== undefined) {
  const planted = [
    "Error: ENOENT: renderer failed price 1793.47 entry 1793.47 stop 1797.03 target 1785.90 outcome LOSS at 2022-01-10T10:15:00Z",
    "    at main (C:/repo/frontend/tools/render-codex-operator-outcome-vault.mjs:121:7)",
    "  code: 'ENOENT'",
  ].join("\n");
  const report = run(planted);
  if (!report.message_template.includes("<REDACTED_TOKEN>") || !report.message_template.includes("<DECIMAL>") || !report.message_template.includes("<TIMESTAMP>")) throw new Error("Synthetic redaction proof failed");
  process.stdout.write(`${JSON.stringify({ status: "PASS_SYNTHETIC_REDACTION", parser_agreement: true, report_sha256: shaBytes(JSON.stringify(report)) })}\n`);
} else {
  if (!args.input || !args.output || !args.sha256) throw new Error("--input, --output and --sha256 are required");
  const rawBytes = readFileSync(path.resolve(args.input));
  const isUtf16Le = (rawBytes[0] === 0xff && rawBytes[1] === 0xfe) || rawBytes.subarray(0, Math.min(rawBytes.length, 200)).filter((value) => value === 0).length > 20;
  const raw = rawBytes.toString(isUtf16Le ? "utf16le" : "utf8").replace(/^\uFEFF/, "");
  const report = run(raw, args.sha256, rawBytes);
  writeFileSync(path.resolve(args.output), `${JSON.stringify(report, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify({ status: "PASS_SANITIZED_DIAGNOSTIC", report_sha256: shaBytes(readFileSync(path.resolve(args.output))) })}\n`);
}
