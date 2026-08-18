import { CodexOperatorReplayLab } from "@/components/codex-operator-replay-lab";


export const dynamic = "force-dynamic";


export default function MatchedHumanReplayPage() {
  return (
    <div className="replay-light -m-5 min-h-screen bg-[#F4F5F7] p-5 text-[#131722] md:-m-8 md:p-8 xl:-m-10 xl:p-10">
      <div className="mx-auto max-w-[1700px]">
        <header>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[#8A6200]">
            Matched human–Codex diagnostic | 30 identical 2022 cases
          </p>
          <h2 className="mt-2 max-w-5xl text-3xl font-semibold tracking-tight md:text-4xl">
            Trade the exact dates Codex traded and show how you apply the method.
          </h2>
          <p className="mt-3 max-w-5xl text-sm leading-6 text-[#5D606B]">
            The charts, fundamentals, sessions, execution and $50 risk model are identical to the Codex audit. Your decisions are written to a separate append-only ledger. Codex decisions and per-case outcomes stay hidden until all 30 cases are complete.
          </p>
          <div className="mt-5 flex flex-wrap gap-2 text-xs">
            <span className="rounded-full border border-[#A5DCCF] bg-[#EAF8F4] px-3 py-1.5 text-[#087363]">3 Jan–16 Feb 2022</span>
            <span className="rounded-full border border-[#D1D4DC] bg-white px-3 py-1.5 text-[#5D606B]">Same London / New York windows</span>
            <span className="rounded-full border border-[#D1D4DC] bg-white px-3 py-1.5 text-[#5D606B]">Fixed $50 maximum risk</span>
            <span className="rounded-full border border-[#E8D28A] bg-[#FFF9E6] px-3 py-1.5 text-[#785D00]">Matched diagnostic—not fresh validation</span>
          </div>
        </header>
        <CodexOperatorReplayLab
          apiPath="/matched-human-replay-v1"
          matchedHuman
          operatorLabel="Human matched"
        />
      </div>
    </div>
  );
}
