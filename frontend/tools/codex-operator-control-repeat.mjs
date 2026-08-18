import { readFileSync } from "node:fs";
import path from "node:path";


const action = process.argv[2];
const payloadPath = process.argv[3];
const repeat = Number.parseInt(process.argv[4] ?? "1", 10);

if (!action || !payloadPath || !Number.isInteger(repeat) || repeat < 1) {
  process.stderr.write(
    "Usage: node tools/codex-operator-control-repeat.mjs ACTION PAYLOAD_JSON REPEAT\n",
  );
  process.exit(2);
}

const artifact = path.resolve(
  process.env.CODEX_OPERATOR_ARTIFACT ??
    "../research_artifacts/gold_blind_codex_operator_replay_v1",
);
const token = readFileSync(
  path.join(artifact, "operator_runtime", "control_token.txt"),
  "utf8",
).trim();
const payload = JSON.parse(readFileSync(path.resolve(payloadPath), "utf8"));

let lastBody = "";
for (let index = 0; index < repeat; index += 1) {
  const response = await fetch("http://127.0.0.1:43122", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ ...payload, action }),
  });
  lastBody = await response.text();
  if (!response.ok) {
    process.stderr.write(
      JSON.stringify({ repetition: index + 1, response: lastBody }) + "\n",
    );
    process.exit(1);
  }
}

process.stdout.write(lastBody + "\n");
