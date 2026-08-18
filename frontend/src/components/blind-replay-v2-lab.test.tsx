import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BlindReplayV2Lab, classifyReplayPositionLifecycle, mapReplayPosition } from "./blind-replay-v2-lab";


afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  Object.defineProperty(document, "fullscreenElement", { configurable: true, value: null });
});


const hash = "a".repeat(64);
const zeroHash = "0".repeat(64);
const timeframes = ["1w", "1d", "4h", "1h", "15m", "5m", "1m"];

function bar(offset: number) {
  return {
    bar_id: `${Math.abs(offset)}`.padEnd(64, "b").slice(0, 64),
    close_offset_minutes: offset,
    available_offset_minutes: offset,
    open: 99.95,
    high: 100.2,
    low: 99.8,
    close: 100,
    volume: 10,
  };
}

function snapshot(cursor = 0) {
  const charts = Object.fromEntries(timeframes.map((timeframe) => [
    timeframe,
    [bar(-15), bar(0), ...(cursor > 0 ? [bar(cursor)] : [])],
  ]));
  const visibility = Object.fromEntries(timeframes.map((timeframe) => [timeframe, {
    count: charts[timeframe].length,
    terminal_bar_id: charts[timeframe].at(-1)?.bar_id ?? null,
    sha256: hash,
  }]));
  return {
    version: "GOLD_BLIND_SYNCHRONIZED_SETUP_REPLAY_V2_SNAPSHOT_1_0",
    case_alias: "P-001",
    mode: "PRACTICE",
    mode_sequence: 1,
    session_code: "LONDON",
    cursor_minute: cursor,
    maximum_cursor_minute: 180,
    selected_timeframe_default: "15m",
    reference_index: 100,
    latest_visible_m1_close_index: 100,
    latest_point_in_time_m15_atr_index: 0.2,
    context_frozen_at_cursor_minute: 0,
    context_staleness_minutes: cursor,
    context: {
      fundamental: {
        bias_label: "BULLISH",
        directional_score: 45,
        confidence: 72,
        regime_label: "SLOWDOWN",
        dominant_driver: "REAL_YIELD",
        main_contradiction: "POSITIONING",
        event_risk: "LOW",
        summary: "Falling real yields support gold.",
        components: [{
          code: "REAL_YIELD",
          direction: 1,
          explanation: "Real yields are falling.",
        }],
      },
      cross_market: { status: "CONFIRMING" },
      positioning: { crowding_state: "NEUTRAL" },
      liquidity: { status: "NORMAL" },
      session: { known_levels: [{ code: "ASIA_HIGH", level: 100.15 }] },
      structure: { timeframes: [{ timeframe: "1h", trend: "UP", status: "AVAILABLE" }] },
      released_events: [],
    },
    context_sha256: hash,
    charts,
    visible_timeframes: visibility,
    visible_charts_sha256: hash,
    display_policy: {
      one_way_cursor: true,
      future_values_in_response: false,
      timeframe_switch_changes_cursor: false,
      drawings_case_global: true,
      scored_labeling_closed: true,
      context_frozen_at_t0: true,
    },
  };
}

function status(cursor = 0, completed = 0) {
  return {
    protocol: "GOLD_BLIND_SYNCHRONIZED_SETUP_REPLAY_V2_PROTOCOL_1_0",
    ready: true,
    phase: "PRACTICE",
    practice_completed: completed,
    practice_total: 20,
    total_locked: completed,
    next_case_alias: "P-001",
    cursor_minute: cursor,
    cursor_ledger_head_sha256: zeroHash,
    setup_ledger_head_sha256: zeroHash,
    scored_labeling: "CLOSED_V2_PRACTICE_ONLY_CERTIFIED",
    research_credit: "ZERO_PRACTICE_ONLY",
  };
}

function chartBounds(chart: HTMLElement) {
  Object.defineProperty(chart, "getBoundingClientRect", {
    configurable: true,
    value: () => ({
      bottom: 585,
      height: 585,
      left: 0,
      right: 1180,
      top: 0,
      width: 1180,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    }),
  });
}


describe("BlindReplayV2Lab", () => {
  it("keeps a pending order editable before seal and applies stop-first lifecycle after entry activation", () => {
    const ticket = {
      drawingId: "lifecycle",
      direction: "LONG" as const,
      entryIndex: 100,
      stopIndex: 99.8,
      targetIndex: 100.4,
      entryTrigger: "PULLBACK_LIMIT" as const,
      entryOffsetAtr: -0.5,
      stopDistanceAtr: 1,
      targetR: 2,
    };
    expect(classifyReplayPositionLifecycle(ticket, [], false)).toBe("PENDING_ENTRY");
    expect(classifyReplayPositionLifecycle(ticket, [{ ...bar(1), low: 99.95, high: 100.1 }], false)).toBe("ACTIVE");
    expect(classifyReplayPositionLifecycle(ticket, [{ ...bar(1), low: 99.7, high: 100.5 }], false)).toBe("STOPPED");
    expect(classifyReplayPositionLifecycle(ticket, [
      { ...bar(1), low: 99.95, high: 100.1 },
      { ...bar(2), low: 100.1, high: 100.5 },
    ], false)).toBe("TARGET_HIT");
  });

  it("maps position geometry against Replay Now without changing frozen limits", () => {
    expect(mapReplayPosition({
      drawingId: "one",
      direction: "LONG",
      entryIndex: 99.9,
      stopIndex: 99.8,
      targetIndex: 100.1,
    }, 100, 0.2)).toEqual({
      error: null,
      ticket: {
        drawingId: "one",
        direction: "LONG",
        entryIndex: 99.9,
        stopIndex: 99.8,
        targetIndex: 100.1,
        entryTrigger: "PULLBACK_LIMIT",
        entryOffsetAtr: expect.closeTo(-0.5),
        stopDistanceAtr: expect.closeTo(0.5),
        targetR: expect.closeTo(2),
      },
    });
  });

  it("keeps cursor controls and the visible trade-reason ticket across timeframe changes", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/next")) {
        return { ok: true, status: 200, json: async () => ({ case: snapshot(0), progress: status(0) }) };
      }
      if (url.endsWith("/advance")) {
        expect(JSON.parse(String(init?.body)).expected_cursor_minute).toBe(0);
        return { ok: true, status: 200, json: async () => ({ case: snapshot(5), progress: status(5) }) };
      }
      throw new Error(`Unexpected URL ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<BlindReplayV2Lab />);

    expect(await screen.findByText(/Case P-001/)).toBeInTheDocument();
    expect(screen.getByLabelText("WHY THIS TRADE NOW?")).toBeVisible();
    expect(screen.getByText(/CONTEXT FROZEN AT T0/)).toBeInTheDocument();
    expect(screen.getByText("FALLING")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Play synchronized replay" })).toBeEnabled();

    fireEvent.change(screen.getByLabelText("WHY THIS TRADE NOW?"), { target: { value: "Rates and structure align." } });
    fireEvent.click(screen.getByRole("tab", { name: /1H/ }));
    expect(screen.getByLabelText("WHY THIS TRADE NOW?")).toHaveValue("Rates and structure align.");
    expect(screen.getByRole("button", { name: "Play synchronized replay" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Advance 5 minutes" }));
    await waitFor(() => expect(screen.getByText("T+5 / 180m")).toBeInTheDocument());
    expect(screen.getByTestId("synchronized-replay-chart")).toHaveAttribute("data-cursor-minute", "5");
  });

  it("keeps Play actionable at the blind-window limit and explains the next valid action", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/next")) {
        return { ok: true, status: 200, json: async () => ({ case: snapshot(180), progress: status(180) }) };
      }
      throw new Error(`Unexpected URL ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<BlindReplayV2Lab />);
    await screen.findByText(/Case P-001/);

    const play = screen.getByRole("button", { name: "Play synchronized replay" });
    expect(play).toBeEnabled();
    fireEvent.click(play);
    expect(screen.getByText(/blind replay window has reached T\+180/i)).toBeInTheDocument();
  });

  it("seals an explicit no-trade record before practice feedback is rendered", async () => {
    let submitted: Record<string, unknown> | null = null;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/next")) {
        return { ok: true, status: 200, json: async () => ({ case: snapshot(0), progress: status(0) }) };
      }
      if (url.endsWith("/decisions")) {
        submitted = JSON.parse(String(init?.body));
        return {
          ok: true,
          status: 201,
          json: async () => ({
            locked: true,
            idempotent_replay: false,
            record_sha256: "c".repeat(64),
            case_alias: "P-001",
            locked_cursor_minute: 0,
            progress: status(0, 1),
            practice_feedback: {
              status: "PRACTICE_RESOLUTION_REVEALED_ZERO_RESEARCH_CREDIT",
              locked_cursor_minute: 0,
              bars: [bar(1)],
              economic_result: "NOT_CALCULATED_DURING_V2_PRACTICE",
            },
          }),
        };
      }
      throw new Error(`Unexpected URL ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<BlindReplayV2Lab />);
    await screen.findByText(/Case P-001/);

    fireEvent.click(screen.getByRole("button", { name: "NO TRADE" }));
    fireEvent.click(screen.getByText("OTHER"));
    fireEvent.change(screen.getByLabelText("WHY THIS TRADE NOW?"), { target: { value: "The evidence conflicts at this cursor." } });
    fireEvent.change(screen.getByLabelText("Observable trigger"), { target: { value: "Wait for a completed reclaim." } });
    fireEvent.change(screen.getByLabelText("Invalidation"), { target: { value: "A clean structural break changes the abstention." } });
    fireEvent.change(screen.getByLabelText("Target rationale"), { target: { value: "No clean opposing liquidity target exists." } });
    const place = screen.getByRole("button", { name: "Place & Play" });
    expect(place).toBeEnabled();
    fireEvent.click(place);

    expect(await screen.findByText(/Setup sealed before reveal/)).toBeInTheDocument();
    expect(submitted).toMatchObject({
      case_alias: "P-001",
      expected_cursor_minute: 0,
      action: "NO_TRADE",
      client_visible_charts_sha256: hash,
      drawings: [],
      trade_reason: "The evidence conflicts at this cursor.",
    });
    expect(screen.getByText(/resumes one completed M1 candle at a time/)).toBeInTheDocument();
  });

  it("supports replay, timeframe switching and Done & Play from the full-screen chart", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/next")) {
        return { ok: true, status: 200, json: async () => ({ case: snapshot(0), progress: status(0) }) };
      }
      if (url.endsWith("/decisions")) {
        return {
          ok: true,
          status: 201,
          json: async () => ({
            locked: true,
            idempotent_replay: false,
            record_sha256: "d".repeat(64),
            case_alias: "P-001",
            locked_cursor_minute: 0,
            progress: status(0, 1),
            practice_feedback: {
              status: "PRACTICE_RESOLUTION_REVEALED_ZERO_RESEARCH_CREDIT",
              locked_cursor_minute: 0,
              bars: [bar(1)],
              economic_result: "NOT_CALCULATED_DURING_V2_PRACTICE",
            },
          }),
        };
      }
      throw new Error(`Unexpected URL ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<BlindReplayV2Lab />);
    await screen.findByText(/Case P-001/);

    const replayWindow = screen.getByTestId("synchronized-replay-window");
    Object.defineProperty(replayWindow, "requestFullscreen", {
      configurable: true,
      value: vi.fn().mockResolvedValue(undefined),
    });
    fireEvent.click(screen.getByRole("button", { name: "Enter full screen" }));
    Object.defineProperty(document, "fullscreenElement", { configurable: true, value: replayWindow });
    fireEvent(document, new Event("fullscreenchange"));

    expect(await screen.findByRole("button", { name: "Play full-screen replay" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show H1 in full screen" })).toBeInTheDocument();

    const chart = screen.getByTestId("synchronized-replay-chart");
    chartBounds(chart);
    fireEvent.click(screen.getByRole("button", { name: "Long position" }));
    fireEvent.click(chart, { clientX: 900, clientY: 285 });
    fireEvent.click(chart, { clientX: 900, clientY: 120 });
    fireEvent.click(chart, { clientX: 900, clientY: 390 });
    expect(screen.getByLabelText("long position drawing")).toBeInTheDocument();

    const mainPlay = screen.getByRole("button", { name: "Play synchronized replay" });
    expect(mainPlay).toBeEnabled();
    fireEvent.click(mainPlay);
    expect(screen.getByRole("dialog", { name: "Complete Place & Play details" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close setup details" }));

    fireEvent.click(screen.getByRole("button", { name: "Place & Play · add annotation" }));
    const dialog = screen.getByRole("dialog", { name: "Complete Place & Play details" });
    expect(dialog).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("WHY THIS TRADE NOW?"), {
      target: { value: "Fundamentals, location and reclaim align at Replay Now." },
    });
    fireEvent.click(within(dialog).getByText("OTHER"));
    const done = within(dialog).getByRole("button", { name: "Done & Play" });
    expect(done).toBeEnabled();
    fireEvent.click(done);

    expect(await screen.findByText(/Setup sealed before reveal/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Resize long position stop")).not.toBeInTheDocument();
    expect(await screen.findByText(/revealed 1\/1 post-decision minute bars/)).toBeInTheDocument();
  });
});
