import type { MarketStructureSnapshot } from "@/lib/api";

type Props = {
  snapshot: MarketStructureSnapshot;
};

const WIDTH = 1100;
const HEIGHT = 390;
const PAD = { left: 66, right: 22, top: 24, bottom: 38 };

const compactTime = (value: string) =>
  new Intl.DateTimeFormat("en", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  }).format(new Date(value));

export function MarketStructureChart({ snapshot }: Props) {
  const bars = snapshot.chart_bars.slice(-150);
  if (bars.length < 2) {
    return (
      <div className="grid min-h-72 place-items-center rounded-xl border border-dashed border-[var(--border)] text-sm text-[var(--muted)]">
        At least two complete chart bars are required.
      </div>
    );
  }

  const fiveMinute = snapshot.timeframes.find((item) => item.timeframe === "5m");
  const visibleLevels = (fiveMinute?.detections ?? [])
    .filter((item) =>
      [
        "SUPPORT",
        "RESISTANCE",
        "ACCEPTANCE_ABOVE_RESISTANCE",
        "ACCEPTANCE_BELOW_SUPPORT",
        "FAILED_BREAKOUT",
      ].includes(item.kind),
    )
    .slice(-8);
  const rawLow = Math.min(...bars.map((bar) => bar.low));
  const rawHigh = Math.max(...bars.map((bar) => bar.high));
  const padding = Math.max((rawHigh - rawLow) * 0.08, 0.01);
  const priceLow = rawLow - padding;
  const priceHigh = rawHigh + padding;
  const plotWidth = WIDTH - PAD.left - PAD.right;
  const plotHeight = HEIGHT - PAD.top - PAD.bottom;
  const x = (index: number) =>
    PAD.left + (index / Math.max(1, bars.length - 1)) * plotWidth;
  const y = (price: number) =>
    PAD.top + ((priceHigh - price) / Math.max(0.000001, priceHigh - priceLow)) * plotHeight;
  const candleWidth = Math.max(1.5, Math.min(6, (plotWidth / bars.length) * 0.62));
  const firstTime = new Date(bars[0].open_time).getTime();
  const lastTime = new Date(bars.at(-1)?.close_time ?? bars[0].close_time).getTime();
  const timeX = (value: string) =>
    PAD.left +
    ((new Date(value).getTime() - firstTime) / Math.max(1, lastTime - firstTime)) *
      plotWidth;
  const visibleZones = snapshot.auction_automation.zones
    .filter((zone) => {
      const start = new Date(zone.created_at).getTime();
      const terminal = new Date(zone.invalidated_at ?? zone.expires_at ?? snapshot.as_of).getTime();
      return (
        start <= lastTime
        && terminal >= firstTime
        && zone.upper_bound >= priceLow
        && zone.lower_bound <= priceHigh
      );
    })
    .slice(-6);
  const visibleSwings = snapshot.auction_automation.swings
    .filter((swing) => {
      const timestamp = new Date(swing.pivot_at).getTime();
      return (
        ["15m", "1h", "4h"].includes(swing.timeframe)
        && timestamp >= firstTime
        && timestamp <= lastTime
        && swing.price_level >= priceLow
        && swing.price_level <= priceHigh
      );
    })
    .slice(-18);
  const visibleProposals = snapshot.auction_automation.proposals
    .filter((proposal) => {
      if (!proposal.triggered_at || proposal.entry_reference === null) return false;
      const timestamp = new Date(proposal.triggered_at).getTime();
      return timestamp >= firstTime && timestamp <= lastTime;
    })
    .slice(-8);

  return (
    <div>
      <svg
        aria-label="Five-minute XAUUSD candlestick chart with sessions, confirmed swings, and inferred auction-shift zones"
        className="h-auto w-full overflow-visible"
        role="img"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      >
        <rect
          fill="rgb(0 0 0 / 16%)"
          height={plotHeight}
          rx="10"
          width={plotWidth}
          x={PAD.left}
          y={PAD.top}
        />

        {snapshot.session.ranges.map((range) => {
          const start = Math.max(PAD.left, timeX(range.start_at));
          const end = Math.min(PAD.left + plotWidth, timeX(range.end_at));
          if (end <= PAD.left || start >= PAD.left + plotWidth || end <= start) return null;
          const fill =
            range.name === "ASIA"
              ? "rgb(96 165 250 / 8%)"
              : range.name === "LONDON"
                ? "rgb(232 191 100 / 8%)"
                : "rgb(52 211 153 / 7%)";
          return (
            <g key={range.name}>
              <rect fill={fill} height={plotHeight} width={end - start} x={start} y={PAD.top} />
              <text fill="rgb(145 165 157 / 70%)" fontSize="10" x={start + 5} y={PAD.top + 14}>
                {range.name}
              </text>
            </g>
          );
        })}

        {visibleZones.map((zone) => {
          const start = Math.max(PAD.left, timeX(zone.created_at));
          const endTime = zone.invalidated_at ?? zone.expires_at ?? snapshot.as_of;
          const end = Math.min(PAD.left + plotWidth, timeX(endTime));
          const bullish = zone.direction === "BULLISH";
          const upper = Math.min(zone.upper_bound, priceHigh);
          const lower = Math.max(zone.lower_bound, priceLow);
          if (end <= start || upper <= lower) return null;
          return (
            <g data-zone-state={zone.state} key={zone.identity}>
              <rect
                fill={bullish ? "#089981" : "#F23645"}
                fillOpacity={zone.state === "INVALIDATED" || zone.state === "EXPIRED" ? "0.035" : "0.11"}
                height={Math.max(2, y(lower) - y(upper))}
                stroke={bullish ? "#4FD1B5" : "#FF7A86"}
                strokeDasharray={zone.state === "ACTIVE_UNTOUCHED" ? "5 3" : undefined}
                strokeOpacity="0.75"
                width={Math.max(1, end - start)}
                x={start}
                y={y(upper)}
              />
              <text
                fill={bullish ? "#7BE0C7" : "#FF9AA4"}
                fontSize="9"
                fontWeight="700"
                x={start + 4}
                y={Math.max(PAD.top + 10, y(upper) - 3)}
              >
                {bullish ? "BULL" : "BEAR"} SHIFT · {zone.state.replaceAll("_", " ")}
              </text>
            </g>
          );
        })}

        {Array.from({ length: 5 }, (_, index) => {
          const price = priceHigh - ((priceHigh - priceLow) * index) / 4;
          const lineY = y(price);
          return (
            <g key={price}>
              <line
                stroke="rgb(255 255 255 / 7%)"
                strokeWidth="1"
                x1={PAD.left}
                x2={WIDTH - PAD.right}
                y1={lineY}
                y2={lineY}
              />
              <text fill="#91a59d" fontSize="11" textAnchor="end" x={PAD.left - 9} y={lineY + 4}>
                {price.toFixed(2)}
              </text>
            </g>
          );
        })}

        {visibleLevels.map((level) => {
          if (level.price_level < priceLow || level.price_level > priceHigh) return null;
          const levelY = y(level.price_level);
          const bullish = level.direction === "BULLISH";
          return (
            <g key={`${level.kind}-${level.detected_at}-${level.price_level}`}>
              <line
                stroke={bullish ? "#6ee7b7" : "#fca5a5"}
                strokeDasharray="5 5"
                strokeOpacity="0.65"
                x1={PAD.left}
                x2={WIDTH - PAD.right}
                y1={levelY}
                y2={levelY}
              />
              <text
                fill={bullish ? "#6ee7b7" : "#fca5a5"}
                fontSize="10"
                textAnchor="end"
                x={WIDTH - PAD.right - 4}
                y={levelY - 4}
              >
                {level.kind.replaceAll("_", " ")} {level.price_level.toFixed(2)}
              </text>
            </g>
          );
        })}

        {bars.map((bar, index) => {
          const bullish = bar.close >= bar.open;
          const color = bullish ? "#52d6a4" : "#f07d7d";
          const center = x(index);
          const bodyTop = y(Math.max(bar.open, bar.close));
          const bodyBottom = y(Math.min(bar.open, bar.close));
          return (
            <g key={bar.open_time}>
              <line
                stroke={color}
                strokeWidth="1"
                x1={center}
                x2={center}
                y1={y(bar.high)}
                y2={y(bar.low)}
              />
              <rect
                fill={bullish ? color : "rgb(240 125 125 / 30%)"}
                height={Math.max(1, bodyBottom - bodyTop)}
                stroke={color}
                strokeWidth="0.8"
                width={candleWidth}
                x={center - candleWidth / 2}
                y={bodyTop}
              />
            </g>
          );
        })}

        {visibleSwings.map((swing) => {
          const markerX = timeX(swing.pivot_at);
          const markerY = y(swing.price_level);
          const high = swing.base_kind === "HIGH";
          return (
            <g data-swing-classification={swing.classification} key={swing.identity}>
              <path
                d={high
                  ? `M ${markerX - 4} ${markerY - 7} L ${markerX + 4} ${markerY - 7} L ${markerX} ${markerY - 1} Z`
                  : `M ${markerX - 4} ${markerY + 7} L ${markerX + 4} ${markerY + 7} L ${markerX} ${markerY + 1} Z`}
                fill={high ? "#F6AD55" : "#63B3ED"}
                stroke="#0B1220"
                strokeWidth="0.6"
              >
                <title>{`${swing.timeframe} ${swing.classification} · confirmed ${compactTime(swing.detected_at)} UTC`}</title>
              </path>
            </g>
          );
        })}

        {visibleProposals.map((proposal) => {
          const markerX = timeX(proposal.triggered_at as string);
          const markerY = y(proposal.entry_reference as number);
          const color = proposal.disposition === "PAPER_READY" ? "#F7C948" : "#A0AEC0";
          return (
            <g data-proposal-disposition={proposal.disposition} key={proposal.identity}>
              <path
                d={`M ${markerX} ${markerY - 6} L ${markerX + 6} ${markerY} L ${markerX} ${markerY + 6} L ${markerX - 6} ${markerY} Z`}
                fill={color}
                stroke="#0B1220"
                strokeWidth="0.8"
              >
                <title>{`${proposal.family} · ${proposal.disposition} · ${proposal.direction}`}</title>
              </path>
            </g>
          );
        })}

        {[0, Math.floor((bars.length - 1) / 2), bars.length - 1].map((index) => (
          <text
            fill="#91a59d"
            fontSize="11"
            key={bars[index].open_time}
            textAnchor={index === 0 ? "start" : index === bars.length - 1 ? "end" : "middle"}
            x={x(index)}
            y={HEIGHT - 12}
          >
            {compactTime(bars[index].open_time)} UTC
          </text>
        ))}
      </svg>
      <div className="mt-3 flex flex-wrap gap-4 text-[11px] text-[var(--muted)]">
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-blue-300/70" />Asia</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-[var(--gold)]/70" />London</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-emerald-300/70" />New York</span>
        <span><i className="mr-1 inline-block h-2 w-4 border border-emerald-300/70 bg-emerald-300/10" />Bullish inferred shift zone</span>
        <span><i className="mr-1 inline-block h-2 w-4 border border-red-300/70 bg-red-300/10" />Bearish inferred shift zone</span>
        <span>Orange/blue triangles are confirmed swing highs/lows; diamonds are paper proposals.</span>
      </div>
    </div>
  );
}
