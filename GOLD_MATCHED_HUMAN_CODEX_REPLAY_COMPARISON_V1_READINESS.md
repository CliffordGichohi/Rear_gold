# Gold Matched Human–Codex Replay Comparison V1 — Readiness

## Status

`PASS_MATCHED_HUMAN_BROWSER_READINESS`

The matched comparison is ready at `http://localhost:3000/replay/matched`.

## Frozen comparison

- Cases: `CBR-2022-001` through `CBR-2022-030`.
- Dates: 2022-01-03 through 2022-02-16.
- Starting state: 0 of 30 complete.
- Same certified point-in-time streams, London/New York session windows, decision form, execution assumptions and $50 maximum planned risk as the Codex audit.
- Separate human visible ledger: `research_artifacts/gold_matched_human_replay_v1/ledgers/matched_human_visible_ledger.jsonl`.
- Separate hidden human outcome ledger: `research_artifacts/gold_matched_human_replay_v1/outcome_vault/matched_human_outcome_ledger.jsonl`.
- Codex decisions and per-case outcomes are not returned by the matched API or rendered by the page.

## Certification evidence

- Backend isolated replay tests: 5 passed.
- Frontend regression tests: 27 passed.
- Frontend lint: passed with zero warnings.
- Production frontend build: passed and includes `/replay/matched`.
- Browser readiness gates: all 9 passed.
- Initial browser readiness made one GET request to the matched endpoint and created no human ledger or outcome row.
- Certification: `research_artifacts/gold_matched_human_replay_v1/browser_readiness/browser_readiness_certification.json`.
- Initial screenshot: `research_artifacts/gold_matched_human_replay_v1/browser_readiness/initial_matched_replay.png`.

The exercise is a zero-credit matched-method diagnostic because the aggregate Codex result and sealed repository outcome artifacts already exist. It is designed to identify interpretation and execution differences, not to manufacture independent validation.
