import { EventResearchLab } from "@/components/event-research-lab";
import type {
  BacktestDataRange,
  EconomicEvent,
  EconomicSurprise,
  EventStudyRun,
  LicensedProviderHealth,
} from "@/lib/api";
import {
  getAtlantaFedMptHealth,
  getBacktestDataRange,
  getCmeFedWatchHealth,
  getEconomicEvents,
  getEconomicSurprises,
  getRecentEventStudies,
  getTradingEconomicsHealth,
} from "@/lib/server-api";

export const dynamic = "force-dynamic";

const unavailableRange: BacktestDataRange = {
  instrument: "XAUUSD",
  provider_code: "IC_MARKETS_MT5",
  earliest: null,
  latest: null,
  bar_count: 0,
  ready: false,
};

const unavailableProvider = (
  provider: LicensedProviderHealth["provider"],
): LicensedProviderHealth => ({
  provider,
  configured: false,
  connection_status: "not_configured",
  note: "Provider status is unavailable.",
});

export default async function EventsPage() {
  const [
    eventsResult,
    surprisesResult,
    runsResult,
    rangeResult,
    tradingEconomicsResult,
    cmeResult,
    atlantaFedResult,
  ] =
    await Promise.allSettled([
      getEconomicEvents(),
      getEconomicSurprises(),
      getRecentEventStudies(),
      getBacktestDataRange(),
      getTradingEconomicsHealth(),
      getCmeFedWatchHealth(),
      getAtlantaFedMptHealth(),
    ]);
  const events: EconomicEvent[] =
    eventsResult.status === "fulfilled" ? eventsResult.value : [];
  const surprises: EconomicSurprise[] =
    surprisesResult.status === "fulfilled" ? surprisesResult.value : [];
  const runs: EventStudyRun[] =
    runsResult.status === "fulfilled" ? runsResult.value : [];
  const range =
    rangeResult.status === "fulfilled" ? rangeResult.value : unavailableRange;
  const tradingEconomics =
    tradingEconomicsResult.status === "fulfilled"
      ? tradingEconomicsResult.value
      : unavailableProvider("trading_economics");
  const cmeFedWatch =
    cmeResult.status === "fulfilled"
      ? cmeResult.value
      : unavailableProvider("cme_fedwatch");
  const atlantaFedMpt =
    atlantaFedResult.status === "fulfilled"
      ? atlantaFedResult.value
      : unavailableProvider("atlanta_fed_mpt");

  return (
    <div className="mx-auto max-w-[1500px]">
      <header>
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--gold)]">
          Expectations and events
        </p>
        <h2 className="mt-2 text-3xl font-semibold tracking-tight md:text-4xl">
          What was expected, what arrived, and what gold did next.
        </h2>
        <p className="mt-3 max-w-4xl text-sm leading-6 text-[var(--muted)]">
          The engine separates schedule knowledge, pre-release consensus,
          original releases, later revisions, and ingestion time. Every event
          reaction is measured from observed one-minute gold bars and remains
          reproducible at an explicit research cutoff.
        </p>
      </header>
      <div className="mt-8">
        <EventResearchLab
          initialEvents={events}
          initialSurprises={surprises}
          initialRuns={runs}
          priceRange={range}
          tradingEconomics={tradingEconomics}
          cmeFedWatch={cmeFedWatch}
          atlantaFedMpt={atlantaFedMpt}
        />
      </div>
    </div>
  );
}
