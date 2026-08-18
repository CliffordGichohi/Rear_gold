import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";


const GENESIS = "0".repeat(64);


function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}


export function splitTopLevelMembers(line) {
  if (typeof line !== "string" || line.length < 2 || line[0] !== "{" || line.at(-1) !== "}") {
    throw new Error("Ledger record is not a JSON object");
  }
  if (line === "{}") return [];

  const members = [];
  let start = 1;
  let depth = 1;
  let inString = false;
  let escaped = false;

  for (let index = 1; index < line.length - 1; index += 1) {
    const character = line[index];
    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (character === "\\") {
        escaped = true;
      } else if (character === '"') {
        inString = false;
      }
      continue;
    }
    if (character === '"') {
      inString = true;
    } else if (character === "{" || character === "[") {
      depth += 1;
    } else if (character === "}" || character === "]") {
      depth -= 1;
      if (depth < 1) throw new Error("Ledger record nesting is malformed");
    } else if (character === "," && depth === 1) {
      members.push(line.slice(start, index));
      start = index + 1;
    }
  }
  if (inString || escaped || depth !== 1) throw new Error("Ledger record is incomplete");
  members.push(line.slice(start, -1));
  if (members.some((member) => member.length === 0)) throw new Error("Ledger record contains an empty member");
  return members;
}


function memberKey(member) {
  if (!member.startsWith('"')) throw new Error("Ledger member key is not canonical JSON");
  let escaped = false;
  for (let index = 1; index < member.length; index += 1) {
    const character = member[index];
    if (escaped) {
      escaped = false;
    } else if (character === "\\") {
      escaped = true;
    } else if (character === '"') {
      if (member[index + 1] !== ":") throw new Error("Ledger member separator is not canonical JSON");
      return JSON.parse(member.slice(0, index + 1));
    }
  }
  throw new Error("Ledger member key is incomplete");
}


export function originalCanonicalBody(line) {
  const members = splitTopLevelMembers(line);
  const indexed = members.map((member, index) => ({ index, key: memberKey(member) }));
  const hashMembers = indexed.filter((item) => item.key === "record_sha256");
  if (hashMembers.length !== 1) throw new Error("Ledger record must contain exactly one top-level record hash");
  return `{${members.filter((_, index) => index !== hashMembers[0].index).join(",")}}`;
}


export function verifyLedgerText(text, version) {
  if (typeof text !== "string") throw new Error("Ledger payload must be UTF-8 text");
  const split = text.split("\n");
  if (split.at(-1) === "") split.pop();
  if (split.some((line) => line.length === 0 || line.endsWith("\r"))) {
    throw new Error("Ledger contains a non-canonical line boundary");
  }

  let prior = GENESIS;
  const seenKeys = new Set();
  const rows = split.map((line, index) => {
    let row;
    try {
      row = JSON.parse(line);
    } catch {
      throw new Error(`Outcome-vault ledger integrity failure at sequence ${index + 1}`);
    }
    const submitted = row.record_sha256;
    let calculated;
    try {
      calculated = sha256(originalCanonicalBody(line));
    } catch {
      throw new Error(`Outcome-vault ledger integrity failure at sequence ${index + 1}`);
    }
    const key = String(row.idempotency_key);
    if (
      row.version !== version
      || row.ledger_sequence !== index + 1
      || row.prior_record_sha256 !== prior
      || typeof submitted !== "string"
      || submitted !== calculated
      || seenKeys.has(key)
    ) {
      throw new Error(`Outcome-vault ledger integrity failure at sequence ${index + 1}`);
    }
    seenKeys.add(key);
    prior = submitted;
    return row;
  });
  return rows;
}


export function verifiedLedger(filename, version) {
  return verifyLedgerText(readFileSync(filename, "utf8"), version);
}

