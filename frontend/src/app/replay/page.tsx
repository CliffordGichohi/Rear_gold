import { AnnotatedReplayV3Lab } from "@/components/annotated-replay-v3-lab";


export const dynamic = "force-dynamic";


export default function ReplayPage() {
  return (
    <div className="replay-light -m-5 min-h-screen bg-[#F4F5F7] p-5 text-[#131722] md:-m-8 md:p-8 xl:-m-10 xl:p-10">
      <div className="mx-auto max-w-[1600px]">
        <header>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[#8A6200]">
            Annotated TradingView-style replay · V3
          </p>
          <h2 className="mt-2 max-w-4xl text-3xl font-semibold tracking-tight md:text-4xl">
            Replay the real historical day, trade when you choose, and annotate exactly what you saw.
          </h2>
          <p className="mt-3 max-w-4xl text-sm leading-6 text-[#5D606B]">
            One server-controlled clock drives every timeframe. Draw freely, keep replay running with an unsubmitted plan, place market/limit/stop orders at any visible time, and let the broker journal fill and resolve them. Only twenty zero-credit practice days are open; the one-year collection and 2025/2026 remain closed.
          </p>
          <div className="mt-5 flex flex-wrap gap-2 text-xs">
            <span className="rounded-full border border-[#A5DCCF] bg-[#EAF8F4] px-3 py-1.5 text-[#087363]">Certified full-day practice streams</span>
            <span className="rounded-full border border-[#D1D4DC] bg-white px-3 py-1.5 text-[#5D606B]">Fixed $50 maximum risk</span>
            <span className="rounded-full border border-[#D1D4DC] bg-white px-3 py-1.5 text-[#5D606B]">Append-only order lifecycle</span>
            <span className="rounded-full border border-[#E8D28A] bg-[#FFF9E6] px-3 py-1.5 text-[#785D00]">Practice only · collection closed</span>
          </div>
        </header>
        <AnnotatedReplayV3Lab />
      </div>
    </div>
  );
}
