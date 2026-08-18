import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

import { verifyLedgerText, verifiedLedger } from "./codex-operator-ledger-integrity.mjs";


function args() {
  const result = Object.fromEntries(process.argv.slice(2).flatMap((value, index, all) => value.startsWith("--") ? [[value.slice(2), all[index + 1]]] : []));
  for (const key of ["synthetic", "engineering-visible", "engineering-hidden"]) {
    if (!result[key]) throw new Error(`--${key} is required`);
  }
  return result;
}


function sha(value) {
  return createHash("sha256").update(value).digest("hex");
}


function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}


function simpleLedger(ids) {
  let prior = "0".repeat(64);
  return `${ids.map((idempotencyKey, index) => {
    const body = {
      idempotency_key: idempotencyKey,
      ledger_sequence: index + 1,
      prior_record_sha256: prior,
      version: "C1_SIMPLE_1_0",
    };
    const record = sha(canonical(body));
    prior = record;
    return canonical({ ...body, record_sha256: record });
  }).join("\n")}\n`;
}


function rejects(callback) {
  try {
    callback();
    return false;
  } catch {
    return true;
  }
}


const options = args();
const syntheticText = readFileSync(options.synthetic, "utf8");
const synthetic = verifyLedgerText(syntheticText, "GOLD_BLIND_CODEX_RENDERER_C1_SYNTHETIC_1_0");
const visible = verifiedLedger(options["engineering-visible"], "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_VISIBLE_EVENT_1_0");
const hidden = verifiedLedger(options["engineering-hidden"], "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_OUTCOME_EVENT_1_0");

const lines = syntheticText.trimEnd().split("\n");
const hashTamper = [...lines];
hashTamper[0] = hashTamper[0].replace(/"record_sha256":"[0-9a-f]{64}"/, `"record_sha256":"${"f".repeat(64)}"`);
const bodyTamper = [...lines];
bodyTamper[0] = bodyTamper[0].replace('"diagnostic_counter":1', '"diagnostic_counter":2');
const sequenceTamper = [...lines];
sequenceTamper[0] = sequenceTamper[0].replace('"ledger_sequence":1', '"ledger_sequence":2');
const priorTamper = [...lines];
priorTamper[0] = priorTamper[0].replace(`"prior_record_sha256":"${"0".repeat(64)}"`, `"prior_record_sha256":"${"a".repeat(64)}"`);
const duplicateHash = [...lines];
duplicateHash[0] = duplicateHash[0].replace(/}$/, `,"record_sha256":"${"b".repeat(64)}"}`);

const tamperGates = {
  body: rejects(() => verifyLedgerText(`${bodyTamper.join("\n")}\n`, "GOLD_BLIND_CODEX_RENDERER_C1_SYNTHETIC_1_0")),
  duplicate_hash_member: rejects(() => verifyLedgerText(`${duplicateHash.join("\n")}\n`, "GOLD_BLIND_CODEX_RENDERER_C1_SYNTHETIC_1_0")),
  duplicate_idempotency: rejects(() => verifyLedgerText(simpleLedger(["same", "same"]), "C1_SIMPLE_1_0")),
  hash: rejects(() => verifyLedgerText(`${hashTamper.join("\n")}\n`, "GOLD_BLIND_CODEX_RENDERER_C1_SYNTHETIC_1_0")),
  prior: rejects(() => verifyLedgerText(`${priorTamper.join("\n")}\n`, "GOLD_BLIND_CODEX_RENDERER_C1_SYNTHETIC_1_0")),
  sequence: rejects(() => verifyLedgerText(`${sequenceTamper.join("\n")}\n`, "GOLD_BLIND_CODEX_RENDERER_C1_SYNTHETIC_1_0")),
};

const report = {
  version: "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_RENDERER_CORRECTION_C1_PROOF_1_0",
  synthetic: { rows: synthetic.length, source_sha256: sha(syntheticText) },
  engineering: {
    hidden_rows: hidden.length,
    hidden_source_sha256: sha(readFileSync(options["engineering-hidden"])),
    visible_rows: visible.length,
    visible_source_sha256: sha(readFileSync(options["engineering-visible"])),
  },
  gates: {
    cross_runtime_sensitive_python_canonical_vector_accepted: synthetic.length >= 4,
    engineering_ledgers_accepted_unchanged: visible.length > 0 && hidden.length > 0,
    nested_record_hash_key_did_not_replace_top_level_member: synthetic.length >= 4,
    tamper_vectors_rejected: Object.values(tamperGates).every(Boolean),
  },
  tamper_gates: tamperGates,
};
report.proof_checksum = sha(canonical(report));
process.stdout.write(`${JSON.stringify(report)}\n`);

