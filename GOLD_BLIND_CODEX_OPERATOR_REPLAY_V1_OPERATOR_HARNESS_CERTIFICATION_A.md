# Gold Blind Codex-Operator Replay Audit V1 — Operator Harness Certification A

Status: frozen before the first real calendar-2022 browser render.

This bounded technical amendment preserves the original contract, population, display fields, decision rubric, execution rules, evidence requirements, evaluation gates, 2025/2026 locks, and all earlier artifacts.

The local-only operator harness:

- controls only visible browser buttons, labels, chart clicks and form fields;
- returns only case/cursor metadata and evidence file paths/hashes to Codex;
- records every browser interaction, screenshot and trace in append-only per-case evidence;
- supplies the server-required pre-decision evidence manifest before clicking `Seal Decision`;
- invokes a separate child recorder that writes outcome-bearing screenshots/videos directly into the sealed outcome vault without displaying them to Codex;
- supports restart only through additional recording segments and the existing durable cursor/ledger;
- binds all segments, traces, actions, pre-decision evidence and hidden outcome-recording manifest in one complete case-evidence manifest; and
- binds only to `127.0.0.1`, uploads nothing, acquires nothing and incurs no charge.

Synthetic certification exercised a complete terminal `NO_TRADE` path and a complete `LONG` path after the earlier browser-isolation test had exercised trade, no-trade, evidence binding and API restart. No real 2022 chart was rendered during these tests.
