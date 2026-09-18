# Rick UJ/GJ entry-model and zone-formation audit

Start with [FINDINGS.md](FINDINGS.md); [REPORT.md](REPORT.md) contains the detailed comparison results. The audit preserves all 1,512 original trades and makes no strategy or execution change. All evidence is exposed historical analysis, not independent validation.

## Repository snapshot

This directory contains text exports of the sealed local reports, protocol and seal records. Line endings are normalized to LF for these exports. Hashes inside the seals refer to the original paths and bytes under `research_artifacts/`, not the exported copies. The original sealed files remain untouched.

Following the repository's existing data policy, raw prices, detailed trade/feature ledgers and predecessor research payloads remain local and are not uploaded. Their expected paths and hashes are recorded in `protocol.json` and the seals. This commit is a code/report checkpoint, not a complete off-machine backup of the research data.

The audit's local Python helper dependencies are included without modifications. Their presence does not authorize running their acquisition or strategy entrypoints.

## Verification

From the repository root, with NumPy, pandas and PyArrow installed:

```powershell
python -m unittest discover -s tests -p "test_rick_entry_zone_quality_v1.py"
python -m unittest discover -s tests -p "test_rick_preentry*.py"
```

With the original sealed local research artifacts present, verify the completed audit without rerunning it:

```powershell
python tools\seal_rick_entry_zone_findings_v1.py
```

Do not regenerate sealed outputs or reacquire missing sources as part of verification. A fresh checkout without the local research artifacts can run synthetic tests, but cannot independently recompute the historical audit from this report snapshot alone.
