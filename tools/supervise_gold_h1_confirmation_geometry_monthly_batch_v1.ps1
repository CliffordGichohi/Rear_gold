$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$artifactRoot = Join-Path $repositoryRoot "research_artifacts\gold_h1_confirmation_geometry_monthly_batch_v1"
$runLog = Join-Path $artifactRoot "unattended_run.log"
$supervisorStatus = Join-Path $artifactRoot "supervisor_status.json"

New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null

function Write-SupervisorStatus {
    param(
        [Parameter(Mandatory = $true)][string]$State,
        [Parameter(Mandatory = $true)][string]$Stage,
        [string]$Detail = ""
    )

    $payload = [ordered]@{
        version = "GOLD_H1_CONFIRMATION_GEOMETRY_MONTHLY_BATCH_V1_SUPERVISOR_STATUS"
        updated_at = [DateTime]::UtcNow.ToString("o")
        state = $State
        stage = $Stage
        detail = $Detail
        process_id = $PID
    }
    $temporary = "$supervisorStatus.tmp"
    $payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -Force -LiteralPath $temporary -Destination $supervisorStatus
}

function Invoke-LoggedNative {
    param(
        [Parameter(Mandatory = $true)][string]$Stage,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )

    Write-SupervisorStatus -State "RUNNING" -Stage $Stage
    & $Command 2>&1 | Tee-Object -FilePath $runLog -Append
    if ($LASTEXITCODE -ne 0) {
        throw "$Stage exited with code $LASTEXITCODE"
    }
}

try {
    "$([DateTime]::UtcNow.ToString('o')) supervisor start pid=$PID" | Set-Content -LiteralPath $runLog -Encoding UTF8
    Push-Location $repositoryRoot
    try {
        Invoke-LoggedNative -Stage "COMPUTE" -Command {
            python -u "tools\run_gold_h1_confirmation_geometry_monthly_batch_v1.py" all
        }
    }
    finally {
        Pop-Location
    }

    Push-Location (Join-Path $repositoryRoot "frontend")
    try {
        Invoke-LoggedNative -Stage "BROWSER_CERTIFICATION" -Command {
            node "tools\certify-gold-h1-confirmation-geometry-monthly-batch-v1.mjs"
        }
    }
    finally {
        Pop-Location
    }

    Push-Location $repositoryRoot
    try {
        Invoke-LoggedNative -Stage "FINAL_SEAL" -Command {
            python -u "tools\run_gold_h1_confirmation_geometry_monthly_batch_v1.py" seal-browser
        }
    }
    finally {
        Pop-Location
    }

    Write-SupervisorStatus -State "COMPLETE" -Stage "ALL" -Detail "Computation, monthly charts, browser regression and final seal completed."
}
catch {
    $message = $_.Exception.Message
    Write-SupervisorStatus -State "FAILED" -Stage "SUPERVISOR" -Detail $message
    "$([DateTime]::UtcNow.ToString('o')) FAILED $message" | Add-Content -LiteralPath $runLog -Encoding UTF8
    exit 1
}
