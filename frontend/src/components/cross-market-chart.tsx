"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export type CrossMarketChartRow = {
  date: string;
  gold_index: number | null;
  usd_index: number | null;
  equity_index: number | null;
  yield_2y: number | null;
  yield_10y: number | null;
  real_yield_10y: number | null;
  breakeven_10y: number | null;
  vix: number | null;
};

const tooltipStyle = {
  background: "#0d1916",
  border: "1px solid #203c33",
  borderRadius: 10,
};

export function CrossMarketChart({ rows }: { rows: CrossMarketChartRow[] }) {
  if (!rows.length) {
    return (
      <div className="rounded-xl border border-amber-300/20 bg-amber-300/5 p-5 text-sm text-amber-100">
        No point-in-time synchronized observations are available.
      </div>
    );
  }

  return (
    <div className="grid gap-6">
      <ChartPanel
        title="Gold, broad USD, and equities"
        note="Each series is indexed to 100 at its first eligible observation."
      >
        <LineChart data={rows}>
          <ChartFrame />
          <Line connectNulls dataKey="gold_index" dot={false} name="Gold" stroke="#e8bf64" strokeWidth={2} />
          <Line connectNulls dataKey="usd_index" dot={false} name="Broad USD" stroke="#74b9ff" strokeWidth={1.7} />
          <Line connectNulls dataKey="equity_index" dot={false} name="S&P 500" stroke="#77d9a8" strokeWidth={1.7} />
        </LineChart>
      </ChartPanel>

      <ChartPanel
        title="Nominal, real, and breakeven yields"
        note="Raw percentage levels; points are eligible only after their stored availability clock."
      >
        <LineChart data={rows}>
          <ChartFrame />
          <Line connectNulls dataKey="yield_2y" dot={false} name="2Y nominal" stroke="#ff8a80" strokeWidth={1.7} />
          <Line connectNulls dataKey="yield_10y" dot={false} name="10Y nominal" stroke="#ffb86c" strokeWidth={1.7} />
          <Line connectNulls dataKey="real_yield_10y" dot={false} name="10Y real" stroke="#c792ea" strokeWidth={1.7} />
          <Line connectNulls dataKey="breakeven_10y" dot={false} name="10Y breakeven" stroke="#82aaff" strokeWidth={1.7} />
        </LineChart>
      </ChartPanel>

      <ChartPanel
        title="Volatility"
        note="VIX is a public daily risk proxy, not a direct observation of gold safe-haven flow."
      >
        <LineChart data={rows}>
          <ChartFrame />
          <Line connectNulls dataKey="vix" dot={false} name="VIX" stroke="#f78c6c" strokeWidth={1.8} />
        </LineChart>
      </ChartPanel>
    </div>
  );
}

function ChartPanel({
  title,
  note,
  children,
}: {
  title: string;
  note: string;
  children: React.ReactElement;
}) {
  return (
    <article className="rounded-xl border border-[var(--border)] bg-black/10 p-4">
      <div className="mb-4">
        <h4 className="text-sm font-semibold">{title}</h4>
        <p className="mt-1 text-xs text-[var(--muted)]">{note}</p>
      </div>
      <div className="h-64">
        <ResponsiveContainer height="100%" width="100%">
          {children}
        </ResponsiveContainer>
      </div>
    </article>
  );
}

function ChartFrame() {
  return (
    <>
      <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
      <XAxis
        dataKey="date"
        minTickGap={32}
        stroke="#91a59d"
        tick={{ fontSize: 10 }}
      />
      <YAxis stroke="#91a59d" tick={{ fontSize: 10 }} width={52} />
      <Tooltip contentStyle={tooltipStyle} />
      <Legend wrapperStyle={{ fontSize: 11 }} />
    </>
  );
}
