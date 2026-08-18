param(
    [Parameter(Mandatory = $true)]
    [int]$TapeProcessId
)

$ErrorActionPreference = "Stop"
$workspace = Split-Path -Parent $PSScriptRoot
$finalFreeze = Join-Path $workspace "research_manifests\gold_point_in_time_auction_state_adaptive_management_v1_tape_freeze.json"
$outcomeScript = Join-Path $workspace "tools\materialize_gold_point_in_time_auction_state_v1_outcomes.py"

while (Get-Process -Id $TapeProcessId -ErrorAction SilentlyContinue) {
    Start-Sleep -Seconds 15
}

if (-not (Test-Path -LiteralPath $finalFreeze)) {
    throw "Tape process ended without a final freeze. Outcome opening was not attempted."
}

$freeze = Get-Content -LiteralPath $finalFreeze -Raw | ConvertFrom-Json
if ($freeze.status -ne "PASS_OUTCOME_BLIND_DECISION_TAPE_MATERIALIZATION" -or -not $freeze.byte_identical) {
    throw "Tape did not pass exact reproduction. Outcome opening was not attempted."
}

& python $outcomeScript
if ($LASTEXITCODE -ne 0) {
    throw "Outcome materialization failed with exit code $LASTEXITCODE."
}
