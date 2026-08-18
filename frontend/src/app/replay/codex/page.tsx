import { CodexOperatorReplayLab } from "@/components/codex-operator-replay-lab";


export const dynamic = "force-dynamic";


export default function CodexOperatorReplayPage() {
  return (
    <div className="replay-light -m-5 min-h-screen bg-[#F4F5F7] p-5 text-[#131722] md:-m-8 md:p-8 xl:-m-10 xl:p-10">
      <div className="mx-auto max-w-[1700px]">
        <header>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[#8A6200]">
            Blind Codex operator audit | 2022
          </p>
          <h2 className="mt-2 max-w-5xl text-3xl font-semibold tracking-tight md:text-4xl">
            One-way browser replay with every decision sealed before the outcome exists for the operator.
          </h2>
          <p className="mt-3 max-w-5xl text-sm leading-6 text-[#5D606B]">
            Codex sees only rendered point-in-time charts and context. The 2022 population is frozen, human decisions are hidden, outcome feedback is disabled, and the $50-risk execution model cannot be changed during collection.
          </p>
          <div className="mt-5 flex flex-wrap gap-2 text-xs">
            <span className="rounded-full border border-[#A5DCCF] bg-[#EAF8F4] px-3 py-1.5 text-[#087363]">Rendered pixels only</span>
            <span className="rounded-full border border-[#D1D4DC] bg-white px-3 py-1.5 text-[#5D606B]">Fixed $50 maximum risk</span>
            <span className="rounded-full border border-[#D1D4DC] bg-white px-3 py-1.5 text-[#5D606B]">Append-only Codex ledger</span>
            <span className="rounded-full border border-[#E8D28A] bg-[#FFF9E6] px-3 py-1.5 text-[#785D00]">Outcomes sealed | 2025/2026 locked</span>
          </div>
        </header>
        <CodexOperatorReplayLab />
      </div>
    </div>
  );
}
