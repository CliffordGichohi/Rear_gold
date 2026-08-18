import { execFileSync } from "node:child_process";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";


const API = "http://localhost:8011/api/v1/blind-replay-v3";

type Snapshot = {
  case_alias: string;
  cursor_at: string;
  start_at: string;
  end_at: string;
  visible_state_sha256: string;
  charts: Record<string, Array<Record<string, unknown>>>;
  live_order: Record<string, unknown> | null;
  order_history: Array<Record<string, unknown>>;
};

function key(label: string) {
  return `${label}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function apiCase(request: APIRequestContext): Promise<Snapshot> {
  const response = await request.get(`${API}/next?case_alias=V3-P-001`);
  expect(response.ok()).toBeTruthy();
  return (await response.json()).case as Snapshot;
}

async function apiPost(
  request: APIRequestContext,
  path: string,
  payload: Record<string, unknown>,
  expectedStatus = 200,
) {
  const response = await request.post(`${API}${path}`, {
    data: payload,
    headers: { "Idempotency-Key": key(path.replaceAll("/", "-")) },
  });
  const text = await response.text();
  expect(response.status(), text).toBe(expectedStatus);
  return JSON.parse(text) as Record<string, unknown>;
}

function apiDrawing(snapshot: Snapshot, direction: "LONG" | "SHORT", entry: number, stop: number, target: number) {
  return [{
    drawing_id: `api-${direction.toLowerCase()}-${Date.now()}`,
    kind: direction === "LONG" ? "LONG_POSITION" : "SHORT_POSITION",
    created_at_cursor: snapshot.cursor_at,
    anchors: [
      { anchor_at: snapshot.cursor_at, price: entry, source_timeframe: "1m" },
      { anchor_at: snapshot.cursor_at, price: stop, source_timeframe: "1m" },
      { anchor_at: snapshot.cursor_at, price: target, source_timeframe: "1m" },
    ],
  }];
}

function apiAnnotation() {
  return {
    thesis: "Browser certification lifecycle order using only visible information.",
    fundamental_direction: "NEUTRAL_OR_CONFLICTED",
    dominant_driver: "Point-in-time rates and dollar context",
    higher_timeframe_context: "Completed higher-timeframe bars define the location.",
    session_liquidity_context: "The visible session path defines current liquidity.",
    entry_trigger: "A completed visible candle defines the deterministic trigger.",
    invalidation_logic: "The submitted structural stop invalidates the premise.",
    target_logic: "The submitted target is the frozen opposing objective.",
    event_risk: "No hidden future event information used.",
    confidence: 60,
  };
}

async function submitApiOrder(
  request: APIRequestContext,
  snapshot: Snapshot,
  orderType: "MARKET" | "LIMIT" | "STOP",
  entry: number,
  stop: number,
  target: number,
  expiryAt = snapshot.end_at,
) {
  return apiPost(request, "/orders", {
    case_alias: snapshot.case_alias,
    expected_cursor_at: snapshot.cursor_at,
    selected_timeframe: "1m",
    client_visible_state_sha256: snapshot.visible_state_sha256,
    direction: "LONG",
    order_type: orderType,
    entry,
    stop,
    target,
    expiry_at: expiryAt,
    drawings: apiDrawing(snapshot, "LONG", entry, stop, target),
    annotation: apiAnnotation(),
  }, 201);
}

async function advanceApi(request: APIRequestContext, snapshot: Snapshot, minutes: 1 | 5 | 15) {
  return apiPost(request, "/advance", {
    case_alias: snapshot.case_alias,
    expected_cursor_at: snapshot.cursor_at,
    increment_minutes: minutes,
    selected_timeframe: "1m",
  });
}

async function chartBox(page: Page) {
  const chart = page.getByTestId("synchronized-replay-chart");
  await chart.scrollIntoViewIfNeeded();
  const box = await chart.boundingBox();
  expect(box).not.toBeNull();
  return { chart, box: box! };
}

async function drawLong(page: Page, geometry: "far-limit" | "wide-market" = "wide-market") {
  const { box } = await chartBox(page);
  await page.getByRole("button", { name: "Long position" }).click();
  const x = box.x + box.width * 0.78;
  if (geometry === "far-limit") {
    await page.mouse.click(x, box.y + box.height * 0.78);
    await page.mouse.click(x, box.y + box.height * 0.88);
    await page.mouse.click(x, box.y + box.height * 0.45);
  } else {
    await page.mouse.click(x, box.y + box.height * 0.52);
    await page.mouse.click(x, box.y + box.height * 0.88);
    await page.mouse.click(x, box.y + box.height * 0.16);
  }
  await expect(page.getByLabel("long position drawing")).toBeVisible();
}

async function completeAnnotation(page: Page) {
  await page.getByLabel("Why this trade exists now").fill("Rates, structure, location, and the completed response align at this replay timestamp.");
  await page.getByLabel("Fundamental direction").selectOption("NEUTRAL_OR_CONFLICTED");
  await page.getByLabel("Dominant driver").fill("Falling real yield versus conflicting inflation pressure");
  await page.getByLabel("Higher-timeframe context").fill("Daily and H4 location are known from completed candles only.");
  await page.getByLabel("Session and liquidity context").fill("Price is responding near a pre-existing session liquidity level.");
  await page.getByLabel("Observable entry trigger").fill("The completed lower-timeframe candle confirms the response.");
  await page.getByLabel("Invalidation logic").fill("A completed move through the submitted structural stop invalidates the setup.");
  await page.getByLabel("Target logic").fill("The submitted target is the next known opposing liquidity area.");
  await page.getByLabel("Event risk").fill("No imminent unacknowledged event risk.");
}

async function waitForOrderState(request: APIRequestContext, state: string) {
  await expect.poll(async () => {
    const snapshot = await apiCase(request);
    return snapshot.live_order?.state
      ?? snapshot.order_history.at(-1)?.state;
  }, { timeout: 20_000 }).toBe(state);
}

async function ensureReplayPaused(page: Page) {
  const play = page.getByRole("button", { name: "Play replay" });
  if (await play.isVisible()) return;
  const pause = page.getByRole("button", { name: "Pause replay" });
  await expect(pause).toBeEnabled({ timeout: 12_000 });
  await pause.click();
  await expect(play).toBeVisible({ timeout: 12_000 });
}


test("V3 TradingView-style replay passes the isolated browser lifecycle matrix", async ({ page, request }, testInfo) => {
  test.setTimeout(240_000);
  const browserErrors: string[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });

  await expect.poll(async () => {
    try {
      return (await request.get("http://localhost:8011/api/v1/health/live")).ok();
    } catch {
      return false;
    }
  }, { timeout: 30_000 }).toBeTruthy();
  await page.goto("/replay");
  await expect(page.getByTestId("annotated-replay-v3-lab")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Annotated TradingView-style replay · V3")).toBeVisible();
  await expect(page.getByText("Collection year 2022: CLOSED")).toBeVisible();

  const initialStatus = await (await request.get(`${API}/status`)).json();
  expect(initialStatus.practice_total).toBe(20);
  expect(initialStatus.practice_completed).toBe(0);
  expect(initialStatus.collection_state).toBe("CLOSED_NOT_MATERIALIZED_OR_ACCESSIBLE");
  expect(initialStatus.calendar_2025).toBe("LOCKED");
  expect(initialStatus.calendar_2026).toBe("LOCKED");

  const initial = await apiCase(request);
  for (const bars of Object.values(initial.charts)) {
    expect(bars.every((bar) => String(bar.close_at) <= initial.cursor_at && String(bar.available_at) <= initial.cursor_at)).toBeTruthy();
  }
  expect(JSON.stringify(initial)).not.toContain("fixed_horizon_reactions");
  expect(JSON.stringify(initial)).not.toContain("subsequent_observation");

  await page.getByLabel("Initial replay time").fill("01:00");
  await page.getByRole("button", { name: "Start selected historical replay" }).click();
  await expect.poll(async () => (await apiCase(request)).cursor_at).toBe("2021-08-02T01:00:00Z");
  await expect(page.getByText(/02 Aug 2021.*01:00 UTC/).first()).toBeVisible();

  const { chart } = await chartBox(page);
  const viewportBefore = await chart.getAttribute("data-viewport-bars");
  await chart.dispatchEvent("wheel", { deltaY: -120 });
  expect(await chart.getAttribute("data-viewport-bars")).toBe(viewportBefore);
  await page.getByRole("button", { name: "Zoom in" }).click();
  expect(await chart.getAttribute("data-viewport-bars")).not.toBe(viewportBefore);
  await page.getByRole("button", { name: "Move chart left" }).click();
  await page.getByRole("button", { name: "Move chart up" }).click();
  await page.getByRole("button", { name: "Reset chart camera" }).click();

  await page.getByRole("button", { name: "Horizontal level" }).click();
  const horizontalBox = (await chart.boundingBox())!;
  await page.mouse.click(horizontalBox.x + horizontalBox.width * 0.55, horizontalBox.y + horizontalBox.height * 0.45);
  await expect(page.getByLabel("horizontal line drawing")).toBeVisible();
  await page.getByRole("button", { name: "Show H1 timeframe" }).click();
  await expect(page.getByLabel("horizontal line drawing")).toBeVisible();
  await page.getByRole("button", { name: "Show M15 timeframe" }).click();
  await page.keyboard.press("Backspace");
  await expect(page.getByLabel("horizontal line drawing")).toHaveCount(0);

  await page.getByLabel("Order type").selectOption("LIMIT");
  await drawLong(page, "far-limit");
  const entryBeforeResize = await page.getByLabel("long position drawing").locator("text").filter({ hasText: /^ENTRY/ }).textContent();
  const targetBeforeResize = await page.getByLabel("long position drawing").locator("text").filter({ hasText: /^TP/ }).textContent();
  const stopBeforeResize = await page.getByLabel("long position drawing").locator("text").filter({ hasText: /^SL/ }).textContent();
  const targetPriceBeforeResize = targetBeforeResize?.match(/-?\d+(?:\.\d+)?/)?.[0];
  const stopHandle = page.getByLabel("Resize long position stop");
  const stopBox = (await stopHandle.boundingBox())!;
  await page.mouse.move(stopBox.x + stopBox.width / 2, stopBox.y + stopBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(stopBox.x + stopBox.width / 2, stopBox.y + stopBox.height / 2 - 18);
  await page.mouse.up();
  await expect(page.getByLabel("long position drawing").locator("text").filter({ hasText: /^ENTRY/ })).toHaveText(entryBeforeResize!);
  const targetAfterResize = await page.getByLabel("long position drawing").locator("text").filter({ hasText: /^TP/ }).textContent();
  expect(targetAfterResize?.match(/-?\d+(?:\.\d+)?/)?.[0]).toBe(targetPriceBeforeResize);
  expect(await page.getByLabel("long position drawing").locator("text").filter({ hasText: /^SL/ }).textContent()).not.toBe(stopBeforeResize);

  await page.getByRole("button", { name: "Show H4 timeframe" }).click();
  await expect(page.getByLabel("long position drawing")).toBeVisible();
  await page.getByRole("button", { name: "Show M15 timeframe" }).click();
  const cursorBeforePlanPlay = (await apiCase(request)).cursor_at;
  await page.getByRole("button", { name: "Play replay" }).click();
  await page.waitForTimeout(1_100);
  await ensureReplayPaused(page);
  expect((await apiCase(request)).cursor_at).not.toBe(cursorBeforePlanPlay);
  expect((await apiCase(request)).live_order).toBeNull();

  await page.getByLabel("Replay interval").selectOption("5");
  await page.getByLabel("Replay speed").selectOption("8");
  await ensureReplayPaused(page);
  await page.getByRole("button", { name: "Play replay" }).click();
  await page.waitForTimeout(350);
  await ensureReplayPaused(page);
  await page.getByRole("button", { name: "Enter full screen" }).click();
  await expect.poll(() => page.evaluate(() => Boolean(document.fullscreenElement))).toBeTruthy();
  await expect(page.getByLabel("Full-screen synchronized replay controls")).toBeVisible();
  const fullscreenPlayToggle = page.getByRole("button", { name: /^(Play|Pause) full-screen replay$/ });
  await expect(fullscreenPlayToggle).toBeEnabled();
  if ((await fullscreenPlayToggle.getAttribute("aria-label")) === "Pause full-screen replay") {
    await fullscreenPlayToggle.click();
    await expect(page.getByRole("button", { name: "Play full-screen replay" })).toBeEnabled();
  }
  await page.getByRole("button", { name: "Show H1 in full screen" }).click();
  await page.getByRole("button", { name: "Exit full screen" }).click();
  await expect.poll(() => page.evaluate(() => Boolean(document.fullscreenElement))).toBeFalsy();

  // The earlier drawing intentionally survived replay. Re-anchor a fresh buy
  // limit at the current cursor so this section tests the pending lifecycle,
  // not the valid immediate fill of a stale, now-marketable limit.
  await page.getByRole("button", { name: "Clear all drawings" }).click();
  await page.getByRole("button", { name: "Show M15 timeframe" }).click();
  await drawLong(page, "far-limit");
  await page.getByLabel("Replay interval").selectOption("1");
  await page.getByLabel("Replay speed").selectOption("1");

  const cursorBeforeDialog = (await apiCase(request)).cursor_at;
  const drawingCountBeforeDialog = await chart.getAttribute("data-drawing-count");
  await page.getByRole("button", { name: "Place Order" }).click();
  await expect(page.getByLabel("Trade annotation dialog")).toBeVisible();
  expect((await apiCase(request)).cursor_at).toBe(cursorBeforeDialog);
  await page.getByRole("button", { name: "Cancel annotation and return to chart" }).click();
  await expect(page.getByLabel("Trade annotation dialog")).toHaveCount(0);
  expect(await chart.getAttribute("data-drawing-count")).toBe(drawingCountBeforeDialog);

  await page.getByRole("button", { name: "Place Order" }).click();
  await completeAnnotation(page);
  await page.getByRole("button", { name: "Confirm order and resume" }).click();
  await expect.poll(async () => (await apiCase(request)).live_order?.state).toBe("PENDING_ORDER");
  await ensureReplayPaused(page);
  await page.getByRole("button", { name: "Show H1 timeframe" }).click();
  await expect(page.getByText(/PENDING ENTRY/).first()).toBeVisible();

  await page.reload();
  await expect(page.getByTestId("annotated-replay-v3-lab")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/PENDING ENTRY/).first()).toBeVisible();
  execFileSync("docker", ["restart", "gold-replay-v3-e2e-api"], { stdio: "ignore" });
  await expect.poll(async () => {
    try {
      return (await request.get("http://localhost:8011/api/v1/health/live")).ok();
    } catch {
      return false;
    }
  }, { timeout: 30_000 }).toBeTruthy();
  await page.reload();
  await expect(page.getByText(/PENDING ENTRY/).first()).toBeVisible({ timeout: 30_000 });

  const pendingBefore = await apiCase(request);
  const originalPendingEntry = Number(pendingBefore.live_order?.entry);
  await page.getByLabel("long position drawing").click();
  const entryHandle = page.getByLabel("Resize long position entry");
  const entryBox = (await entryHandle.boundingBox())!;
  await page.mouse.move(entryBox.x + entryBox.width / 2, entryBox.y + entryBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(entryBox.x + entryBox.width / 2, entryBox.y + entryBox.height / 2 + 14);
  await page.mouse.up();
  await page.getByRole("button", { name: "Review Amendment" }).click();
  await page.getByLabel("Pending amendment reason").fill("A new completed candle changed the still-pending entry location.");
  await page.getByRole("button", { name: "Confirm pending amendment and resume" }).click();
  await expect.poll(async () => Number((await apiCase(request)).live_order?.entry)).not.toBe(originalPendingEntry);
  await ensureReplayPaused(page);

  await page.getByRole("button", { name: "Amend or cancel pending order" }).click();
  await page.getByLabel("Pending amendment reason").fill("The pending premise is withdrawn before activation.");
  await page.getByRole("button", { name: "Cancel pending order", exact: true }).click();
  await expect.poll(async () => (await apiCase(request)).live_order).toBeNull();

  await page.getByLabel("Order type").selectOption("MARKET");
  await drawLong(page, "wide-market");
  await page.getByRole("button", { name: "Place Order" }).click();
  await completeAnnotation(page);
  await page.getByRole("button", { name: "Confirm order and resume" }).click();
  await ensureReplayPaused(page);
  for (let attempt = 0; attempt < 8; attempt += 1) {
    const current = await apiCase(request);
    if (current.live_order?.state === "ACTIVE_POSITION") break;
    expect(current.live_order?.state).toBe("PENDING_ORDER");
    await advanceApi(request, current, 15);
  }
  await waitForOrderState(request, "ACTIVE_POSITION");
  await page.reload();
  await expect(page.getByText(/ACTIVE/).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: "Long position" })).toBeDisabled();
  await expect(page.getByLabel("Resize long position entry")).toHaveCount(0);
  await page.getByRole("button", { name: "Show H4 timeframe" }).click();
  await page.getByRole("button", { name: "Show M1 timeframe" }).click();

  const active = await apiCase(request);
  const activeOrder = active.live_order!;
  const forbiddenAmend = await request.post(`${API}/orders/${activeOrder.order_id}/amend`, {
    headers: { "Idempotency-Key": key("forbidden-active-amend") },
    data: {
      case_alias: active.case_alias,
      expected_cursor_at: active.cursor_at,
      client_visible_state_sha256: active.visible_state_sha256,
      order_type: activeOrder.order_type,
      entry: Number(activeOrder.entry) + 1,
      stop: activeOrder.stop,
      target: activeOrder.target,
      expiry_at: active.end_at,
      drawings: activeOrder.drawings,
      reason: "This must be rejected after fill.",
    },
  });
  expect(forbiddenAmend.status()).toBe(409);
  const concurrent = await request.post(`${API}/orders`, {
    headers: { "Idempotency-Key": key("forbidden-concurrent") },
    data: {
      case_alias: active.case_alias,
      expected_cursor_at: active.cursor_at,
      selected_timeframe: "1m",
      client_visible_state_sha256: active.visible_state_sha256,
      direction: "LONG",
      order_type: "MARKET",
      entry: activeOrder.entry,
      stop: activeOrder.stop,
      target: activeOrder.target,
      expiry_at: active.end_at,
      drawings: activeOrder.drawings,
      annotation: apiAnnotation(),
    },
  });
  expect(concurrent.status()).toBe(409);
  expect(Number(activeOrder.quantity_ounces) % 1).toBe(0);
  expect(Number(activeOrder.risk_usd)).toBeLessThanOrEqual(50);
  expect(Number((activeOrder.fill as Record<string, unknown>).slippage_price)).toBe(0.05);

  execFileSync("docker", ["restart", "gold-replay-v3-e2e-api"], { stdio: "ignore" });
  await expect.poll(async () => {
    try { return (await request.get("http://localhost:8011/api/v1/health/live")).ok(); } catch { return false; }
  }, { timeout: 30_000 }).toBeTruthy();
  await page.reload();
  await expect(page.getByText(/ACTIVE/).first()).toBeVisible({ timeout: 30_000 });
  await page.getByLabel("Manual close reason").fill("The visible premise has failed; close without rewriting the original plan.");
  await page.getByRole("button", { name: "Close Position Now" }).click();
  await expect.poll(async () => (await apiCase(request)).live_order).toBeNull();
  const manuallyClosed = await apiCase(request);
  expect(manuallyClosed.order_history.at(-1)?.resolution).toMatchObject({ state: "MANUAL_CLOSE", original_geometry_preserved: true });
  expect(manuallyClosed.order_history.at(-1)?.entry).toBe(activeOrder.entry);
  await page.getByRole("button", { name: "Show H1 timeframe" }).click();

  let snapshot = await apiCase(request);
  let price = Number(snapshot.charts["1m"].at(-1)?.close);
  const expiry = new Date(Date.parse(snapshot.cursor_at) + 5 * 60_000).toISOString().replace(".000Z", "Z");
  await submitApiOrder(request, snapshot, "LIMIT", price - 40, price - 45, price + 5, expiry);
  snapshot = await apiCase(request);
  await advanceApi(request, snapshot, 5);
  await expect.poll(async () => (await apiCase(request)).order_history.at(-1)?.state).toBe("EXPIRED");

  snapshot = await apiCase(request);
  price = Number(snapshot.charts["1m"].at(-1)?.close);
  await submitApiOrder(request, snapshot, "STOP", price + 0.01, price - 35, price + 35);
  for (let attempt = 0; attempt < 4; attempt += 1) {
    snapshot = await apiCase(request);
    if (snapshot.live_order?.state === "ACTIVE_POSITION" || snapshot.live_order === null) break;
    await advanceApi(request, snapshot, 15);
  }
  snapshot = await apiCase(request);
  const stopOrder = snapshot.live_order ?? snapshot.order_history.at(-1)!;
  expect((stopOrder.fill as Record<string, unknown>)?.rule).toContain("BUY_STOP");
  if (snapshot.live_order?.state === "ACTIVE_POSITION") {
    await apiPost(request, `/orders/${snapshot.live_order.order_id}/manual-close`, {
      case_alias: snapshot.case_alias,
      expected_cursor_at: snapshot.cursor_at,
      client_visible_state_sha256: snapshot.visible_state_sha256,
      reason: "Close the browser-certification stop-order path.",
    });
  }

  snapshot = await apiCase(request);
  price = Number(snapshot.charts["1m"].at(-1)?.close);
  await submitApiOrder(request, snapshot, "MARKET", price, price - 40, price + 0.01);
  await advanceApi(request, await apiCase(request), 15);
  snapshot = await apiCase(request);
  expect(snapshot.order_history.at(-1)?.state).toBe("RESOLVED");
  expect((snapshot.order_history.at(-1)?.resolution as Record<string, unknown>).state).toBe("TARGET_HIT");

  snapshot = await apiCase(request);
  price = Number(snapshot.charts["1m"].at(-1)?.close);
  await submitApiOrder(request, snapshot, "LIMIT", price + 20, price - 20, price + 40);
  for (let attempt = 0; attempt < 4; attempt += 1) {
    snapshot = await apiCase(request);
    if (snapshot.live_order?.fill || snapshot.order_history.at(-1)?.fill) break;
    await advanceApi(request, snapshot, 15);
  }
  snapshot = await apiCase(request);
  const filledLimit = snapshot.live_order ?? snapshot.order_history.at(-1)!;
  expect((filledLimit.fill as Record<string, unknown>)?.rule).toBe("LIMIT_EXCEEDED_BY_ONE_TICK");
  if (snapshot.live_order?.state === "ACTIVE_POSITION") {
    await apiPost(request, `/orders/${snapshot.live_order.order_id}/manual-close`, {
      case_alias: snapshot.case_alias,
      expected_cursor_at: snapshot.cursor_at,
      client_visible_state_sha256: snapshot.visible_state_sha256,
      reason: "Close the browser-certification limit-fill path.",
    });
  }

  snapshot = await apiCase(request);
  price = Number(snapshot.charts["1m"].at(-1)?.close);
  await submitApiOrder(request, snapshot, "MARKET", price, price - 0.01, price + 40);
  for (let attempt = 0; attempt < 4; attempt += 1) {
    snapshot = await apiCase(request);
    if (snapshot.live_order === null && snapshot.order_history.at(-1)?.state === "RESOLVED") break;
    await advanceApi(request, snapshot, 15);
  }
  snapshot = await apiCase(request);
  expect(snapshot.order_history.at(-1)?.state).toBe("RESOLVED");
  expect((snapshot.order_history.at(-1)?.resolution as Record<string, unknown>).state).toBe("STOPPED");

  const beforeIdempotentAdvance = await apiCase(request);
  const idempotencyKey = key("browser-idempotent-advance");
  const idempotentPayload = {
    case_alias: beforeIdempotentAdvance.case_alias,
    expected_cursor_at: beforeIdempotentAdvance.cursor_at,
    increment_minutes: 1,
    selected_timeframe: "1m",
  };
  const firstIdempotent = await request.post(`${API}/advance`, {
    data: idempotentPayload,
    headers: { "Idempotency-Key": idempotencyKey },
  });
  const repeatedIdempotent = await request.post(`${API}/advance`, {
    data: idempotentPayload,
    headers: { "Idempotency-Key": idempotencyKey },
  });
  expect(firstIdempotent.status()).toBe(200);
  expect(repeatedIdempotent.status()).toBe(200);
  const firstIdempotentBody = await firstIdempotent.json();
  const repeatedIdempotentBody = await repeatedIdempotent.json();
  expect(firstIdempotentBody.idempotent_replay).toBe(false);
  expect(repeatedIdempotentBody.idempotent_replay).toBe(true);
  expect(repeatedIdempotentBody.event_sha256).toBe(firstIdempotentBody.event_sha256);
  expect(repeatedIdempotentBody.case).toEqual(firstIdempotentBody.case);
  expect(repeatedIdempotentBody.progress).toEqual(firstIdempotentBody.progress);
  expect(Date.parse((await apiCase(request)).cursor_at) - Date.parse(beforeIdempotentAdvance.cursor_at)).toBe(60_000);

  const beforeFinish = await apiCase(request);
  if (beforeFinish.live_order?.state === "ACTIVE_POSITION") {
    await apiPost(request, `/orders/${beforeFinish.live_order.order_id}/manual-close`, {
      case_alias: beforeFinish.case_alias,
      expected_cursor_at: beforeFinish.cursor_at,
      client_visible_state_sha256: beforeFinish.visible_state_sha256,
      reason: "Flat before the frozen finish-day skip.",
    });
  }
  await page.reload();
  await page.getByRole("button", { name: "Finish day" }).click();
  await expect(page.getByText(/Practice day completed|All practice days complete/)).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Choose another practice day" }).click();
  await expect(page.getByLabel("Select practice date")).toBeEnabled();
  await page.getByLabel("Select practice date").selectOption("V3-P-013");
  await page.getByLabel("Initial replay time").fill("21:55");
  await page.getByRole("button", { name: "Start selected historical replay" }).click();
  await expect.poll(async () => {
    const response = await request.get(`${API}/next?case_alias=V3-P-013`);
    return (await response.json()).case.cursor_at;
  }).toBe("2021-11-10T21:55:00Z");
  await page.getByRole("button", { name: "Step replay 15 minutes" }).click();
  await expect(page.getByText(/10 Nov 2021.*22:10 UTC/).first()).toBeVisible();
  await expect(page.getByText("ROLLOVER").first()).toBeVisible();
  await expect(page.getByText("Replay controls available.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Play replay" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Step replay 1 minute" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Step replay 5 minutes" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Step replay 15 minutes" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Start selected historical replay" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Go to London" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Go to New York" })).toBeDisabled();
  await expect(page.getByText(/Released: US Initial Jobless Claims/).first()).toBeVisible();
  const unexpectedBrowserErrors = browserErrors.filter(
    (message) => !/Failed to load resource: the server responded with a status of 409 \(Conflict\)/.test(message),
  );
  expect(unexpectedBrowserErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("gold-replay-v3-certified.png"), fullPage: true });
});
