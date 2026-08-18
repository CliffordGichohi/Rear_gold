param(
    [Parameter(Mandatory = $true)]
    [string]$Start,

    [Parameter(Mandatory = $true)]
    [string]$End,

    [string]$ApiBase = "http://localhost:8000/api/v1",

    [switch]$PriceOnly
)

$request = @{
    instrument = "XAUUSD"
    provider_code = "IC_MARKETS_MT5"
    start = $Start
    end = $End
    include_fundamentals = -not $PriceOnly.IsPresent
    config = @{}
} | ConvertTo-Json -Depth 5

$response = Invoke-RestMethod `
    -Method Post `
    -Uri "$ApiBase/session-edge-studies/runs?detail_limit=0" `
    -ContentType "application/json" `
    -Body $request

[pscustomobject]@{
    id = $response.id
    status = $response.status
    start = $response.start
    end = $response.end
    sessions = $response.session_count
    complete_sessions = $response.results.complete_session_count
    triggers = $response.trigger_count
    trigger_rate_pct = $response.results.trigger_rate_pct
    research_status = $response.results.research_status
    funnel = $response.results.status_funnel
    all_triggered = $response.results.cohorts.ALL_TRIGGERED
    fundamental_aligned = $response.results.cohorts.FUNDAMENTAL_ALIGNED
    fundamental_opposed = $response.results.cohorts.FUNDAMENTAL_OPPOSED
    fundamental_neutral_or_insufficient = (
        $response.results.cohorts.FUNDAMENTAL_NEUTRAL_OR_INSUFFICIENT
    )
    catalyst_known_low = $response.results.cohorts.CATALYST_KNOWN_LOW
    catalyst_unknown = $response.results.cohorts.CATALYST_UNKNOWN
    compressed_asia = $response.results.cohorts.COMPRESSED_ASIA
    non_compressed_asia = $response.results.cohorts.NON_COMPRESSED_ASIA
    volume_expansion = $response.results.cohorts.VOLUME_EXPANSION
    volume_not_expanded = $response.results.cohorts.VOLUME_NOT_EXPANDED
    normal_spread = $response.results.cohorts.NORMAL_SPREAD
    elevated_spread = $response.results.cohorts.ELEVATED_SPREAD
    reference_level_confluence = (
        $response.results.cohorts.REFERENCE_LEVEL_CONFLUENCE
    )
    quality_price_liquidity = (
        $response.results.cohorts.QUALITY_PRICE_LIQUIDITY
    )
    fundamental_aligned_quality = (
        $response.results.cohorts.FUNDAMENTAL_ALIGNED_QUALITY_PRICE_LIQUIDITY
    )
    same_bar_reclaim = $response.results.cohorts.SAME_BAR_RECLAIM
    delayed_reclaim = $response.results.cohorts.DELAYED_RECLAIM
    long = $response.results.cohorts.LONG
    short = $response.results.cohorts.SHORT
    data_hash = $response.data_hash
} | ConvertTo-Json -Depth 10
