import { readFileSync } from "node:fs";
import path from "node:path";


const action = process.argv[2] ?? "status";
const payloadPath = process.argv[3];
const artifact = path.resolve(process.env.CODEX_OPERATOR_ARTIFACT ?? "../research_artifacts/gold_blind_codex_operator_replay_v1");
const token = readFileSync(path.join(artifact, "operator_runtime", "control_token.txt"), "utf8").trim();
const payload = payloadPath ? JSON.parse(readFileSync(path.resolve(payloadPath), "utf8")) : {};
const response = await fetch("http://127.0.0.1:43122", {
  method: "POST",
  headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
  body: JSON.stringify({ ...payload, action }),
});
const body = await response.text();
if (!response.ok) {
  process.stderr.write(`${body}\n`);
  process.exit(1);
}
process.stdout.write(`${body}\n`);
