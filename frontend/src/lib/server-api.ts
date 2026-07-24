import "server-only";

import {
  backtestDataRangeSchema,
  backtestRunSchema,
  dataHealthSchema,
  decisionSnapshotSchema,
  economicEventSchema,
  economicSurpriseSchema,
  eventStudyRunSchema,
  factorCoverageSchema,
  fundamentalSnapshotSchema,
  intelligenceSnapshotSchema,
  licensedProviderHealthSchema,
  marketObservationSchema,
  marketStructureSnapshotSchema,
  type BacktestDataRange,
  type BacktestRun,
  type DataHealth,
  type DecisionSnapshot,
  type EconomicEvent,
  type EconomicSurprise,
  type EventStudyRun,
  type FactorCoverage,
  type FundamentalSnapshot,
  type IntelligenceSnapshot,
  type LicensedProviderHealth,
  type MarketObservation,
  type MarketStructureSnapshot,
} from "@/lib/api";

const internalApiUrl =
  process.env.API_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000/api/v1";

async function getJson(path: string): Promise<unknown> {
  const response = await fetch(`${internalApiUrl}${path}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`API request failed with HTTP ${response.status}`);
  }
  return response.json();
}

export async function getLatestSnapshot(): Promise<IntelligenceSnapshot> {
  return intelligenceSnapshotSchema.parse(
    await getJson("/intelligence/snapshots/latest"),
  );
}

export async function getDataHealth(): Promise<DataHealth> {
  return dataHealthSchema.parse(await getJson("/data-health/summary"));
}

export async function getLatestFundamental(): Promise<FundamentalSnapshot> {
  return fundamentalSnapshotSchema.parse(
    await getJson("/fundamentals/snapshots/latest?instrument=XAUUSD"),
  );
}

export async function getLatestDecision(): Promise<DecisionSnapshot> {
  return decisionSnapshotSchema.parse(
    await getJson("/decisions/snapshots/latest?instrument=XAUUSD"),
  );
}

export async function getFactorCoverage(): Promise<FactorCoverage> {
  return factorCoverageSchema.parse(await getJson("/factors/coverage"));
}

export async function getBacktestDataRange(): Promise<BacktestDataRange> {
  return backtestDataRangeSchema.parse(
    await getJson(
      "/backtests/data-range?instrument=XAUUSD&provider_code=IC_MARKETS_MT5",
    ),
  );
}

export async function getRecentBacktests(): Promise<BacktestRun[]> {
  return backtestRunSchema.array().parse(await getJson("/backtests/runs?limit=5"));
}

export async function getEconomicEvents(): Promise<EconomicEvent[]> {
  return economicEventSchema.array().parse(
    await getJson("/events?data_mode=REAL_ONLY&limit=100"),
  );
}

export async function getEconomicSurprises(): Promise<EconomicSurprise[]> {
  return economicSurpriseSchema.array().parse(
    await getJson("/events/surprises?data_mode=REAL_ONLY&limit=100"),
  );
}

export async function getRecentEventStudies(): Promise<EventStudyRun[]> {
  return eventStudyRunSchema.array().parse(
    await getJson("/event-studies/runs?limit=10"),
  );
}

export async function getTradingEconomicsHealth(): Promise<LicensedProviderHealth> {
  return licensedProviderHealthSchema.parse(
    await getJson("/providers/trading-economics/health"),
  );
}

export async function getCmeFedWatchHealth(): Promise<LicensedProviderHealth> {
  return licensedProviderHealthSchema.parse(
    await getJson("/providers/cme-fedwatch/health"),
  );
}

export async function getAtlantaFedMptHealth(): Promise<LicensedProviderHealth> {
  return licensedProviderHealthSchema.parse(
    await getJson("/providers/atlanta-fed-mpt/health"),
  );
}

export async function getMarketStructure(): Promise<MarketStructureSnapshot> {
  return marketStructureSnapshotSchema.parse(
    await getJson(
      "/market-structure/snapshot?instrument=XAUUSD&data_mode=AUTO&chart_timeframe=5m",
    ),
  );
}

export async function getDailyMarketStructure(): Promise<MarketStructureSnapshot> {
  return marketStructureSnapshotSchema.parse(
    await getJson(
      "/market-structure/snapshot?instrument=XAUUSD&data_mode=REAL_ONLY&chart_timeframe=1d&max_source_bars=100000",
    ),
  );
}

export async function getCrossMarketObservations(
  asOf: string,
): Promise<MarketObservation[]> {
  const end = new Date(asOf);
  const start = new Date(end.getTime() - 180 * 86_400_000);
  const parameters = new URLSearchParams({
    start: start.toISOString(),
    end: end.toISOString(),
    as_of: end.toISOString(),
    limit_per_series: "500",
  });
  return marketObservationSchema.array().parse(
    await getJson(`/market-data/observations?${parameters.toString()}`),
  );
}
