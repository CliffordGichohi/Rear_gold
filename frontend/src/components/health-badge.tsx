"use client";

import { useEffect, useState } from "react";

import { getLiveness } from "@/lib/api";

type State = "checking" | "online" | "offline";

export function HealthBadge() {
  const [state, setState] = useState<State>("checking");

  useEffect(() => {
    const controller = new AbortController();
    getLiveness(controller.signal)
      .then(() => setState("online"))
      .catch(() => setState("offline"));
    return () => controller.abort();
  }, []);

  const color = state === "online" ? "bg-emerald-400" : state === "offline" ? "bg-red-400" : "bg-amber-300";

  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-black/20 px-3 py-1.5 text-xs text-[var(--muted)]">
      <span aria-hidden="true" className={`h-2 w-2 rounded-full ${color}`} />
      API {state}
    </div>
  );
}

