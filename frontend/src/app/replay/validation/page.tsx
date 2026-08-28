import { AnnotatedReplayV3Lab } from "@/components/annotated-replay-v3-lab";


export const dynamic = "force-dynamic";


export default function CoherentAuctionValidationPage() {
  return (
    <div className="replay-light -m-5 min-h-screen bg-[#F4F5F7] p-5 text-[#131722] md:-m-8 md:p-8 xl:-m-10 xl:p-10">
      <div className="mx-auto max-w-[1600px]">
        <header>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[#8A6200]">
            Coherent-auction blind validation · Block 1
          </p>
          <h2 className="mt-2 max-w-5xl text-3xl font-semibold tracking-tight md:text-4xl">
            Trade fifty fresh London and New York sessions using the refined auction process.
          </h2>
          <p className="mt-3 max-w-5xl text-sm leading-6 text-[#5D606B]">
            The block contains 25 London and 25 New York sessions that neither of us previously replayed. Classify the auction, place the stop behind the structure controlling your entry, and target opposing H1 liquidity. Future candles remain server-side; aggregate results stay sealed until all fifty sessions are complete.
          </p>
          <div className="mt-5 flex flex-wrap gap-2 text-xs">
            <span className="rounded-full border border-[#A5DCCF] bg-[#EAF8F4] px-3 py-1.5 text-[#087363]">50 independently reproduced streams</span>
            <span className="rounded-full border border-[#D1D4DC] bg-white px-3 py-1.5 text-[#5D606B]">One order maximum per session</span>
            <span className="rounded-full border border-[#D1D4DC] bg-white px-3 py-1.5 text-[#5D606B]">Fixed $50 maximum risk</span>
            <span className="rounded-full border border-[#E8D28A] bg-[#FFF9E6] px-3 py-1.5 text-[#785D00]">2025 / 2026 locked</span>
          </div>
        </header>
        <AnnotatedReplayV3Lab
          apiBasePath="/coherent-auction-validation"
          draftPrefix="gold-coherent-auction-validation-v1-draft"
          validationMode
        />
      </div>
    </div>
  );
}
