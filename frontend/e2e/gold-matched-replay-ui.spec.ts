import { expect, test, type APIRequestContext, type Page } from "@playwright/test";


const API = "http://localhost:8011/api/v1/matched-human-replay-v1";


function key() {
  return `matched-ui-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}


async function advanceToEntrySession(request: APIRequestContext) {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const currentResponse = await request.get(`${API}/next`);
    expect(currentResponse.ok()).toBeTruthy();
    const current = (await currentResponse.json()).case as Record<string, unknown>;
    if (current.active_entry_session) return current;
    const response = await request.post(`${API}/advance`, {
      data: {
        case_alias: current.case_alias,
        expected_cursor_at: current.cursor_at,
        increment_minutes: 15,
        selected_timeframe: "15m",
      },
      headers: { "Idempotency-Key": key() },
    });
    expect(response.ok(), await response.text()).toBeTruthy();
  }
  throw new Error("No frozen eligible entry session became active");
}


async function advanceToTerminal(request: APIRequestContext) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const currentResponse = await request.get(`${API}/next`);
    expect(currentResponse.ok()).toBeTruthy();
    const current = (await currentResponse.json()).case as Record<string, unknown>;
    if (current.cursor_at === current.observation_terminal_at) return current;
    const response = await request.post(`${API}/advance`, {
      data: {
        case_alias: current.case_alias,
        expected_cursor_at: current.cursor_at,
        increment_minutes: 15,
        selected_timeframe: "15m",
      },
      headers: { "Idempotency-Key": key() },
    });
    expect(response.ok(), await response.text()).toBeTruthy();
  }
  throw new Error("Frozen terminal did not become reachable");
}


async function chartBox(page: Page) {
  const chart = page.getByTestId("synchronized-replay-chart");
  await chart.scrollIntoViewIfNeeded();
  const box = await chart.boundingBox();
  expect(box).not.toBeNull();
  return { chart, box: box! };
}


async function drawEditableLong(page: Page) {
  const { box } = await chartBox(page);
  const x = box.x + box.width * 0.78;
  await page.getByRole("button", { name: "Long position" }).click();
  await page.mouse.click(x, box.y + box.height * 0.52);
  await page.mouse.click(x, box.y + box.height * 0.78);
  await page.mouse.click(x, box.y + box.height * 0.25);
  await expect(page.getByLabel("long position drawing")).toBeVisible();
}


test("matched replay keeps controls stable and permits fullscreen trade preparation", async ({ page, request }) => {
  test.setTimeout(300_000);
  const browserErrors: string[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });

  await page.goto("/replay/matched");
  await expect(page.getByTestId("codex-operator-replay-lab")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Complete: 0 / 30")).toBeVisible();
  const schedule = page.getByLabel("Frozen session schedule");
  await expect(schedule).toBeVisible();
  await expect(schedule.locator('[data-session-code="LONDON"]')).toContainText(/LONDON.*UPCOMING/);
  await expect(schedule.locator('[data-session-code="NEW_YORK"]')).toContainText(/NEW YORK.*UPCOMING/);

  const order = await page.evaluate(() => {
    const controls = document.querySelector('[aria-label="Replay controls and timeframe inspection"]');
    const chart = document.querySelector('[data-testid="synchronized-replay-window"]');
    const fundamentals = document.querySelector('[aria-label="Point-in-time fundamental context"]');
    if (!controls || !chart || !fundamentals) return null;
    return {
      controlsBeforeChart: Boolean(controls.compareDocumentPosition(chart) & Node.DOCUMENT_POSITION_FOLLOWING),
      chartBeforeFundamentals: Boolean(chart.compareDocumentPosition(fundamentals) & Node.DOCUMENT_POSITION_FOLLOWING),
    };
  });
  expect(order).toEqual({ controlsBeforeChart: true, chartBeforeFundamentals: true });

  const chart = page.getByTestId("synchronized-replay-chart");
  await expect(chart).toHaveAttribute("data-session-window-count", "2");
  await expect(chart).toHaveAttribute("data-chart-height", "585");
  await expect(chart).toHaveAttribute("data-automatic-level-count", "0");
  await page.getByRole("button", { name: "Increase chart height" }).click();
  await expect(chart).toHaveAttribute("data-chart-height", "665");
  await page.getByRole("button", { name: "Decrease chart height" }).click();
  await expect(chart).toHaveAttribute("data-chart-height", "585");

  const replayWindow = page.getByTestId("synchronized-replay-window");
  const fullWidth = await replayWindow.boundingBox();
  expect(fullWidth).not.toBeNull();
  await expect(replayWindow).toHaveAttribute("data-chart-width-percent", "100");
  await page.getByRole("button", { name: "Decrease chart width" }).click();
  await expect(replayWindow).toHaveAttribute("data-chart-width-percent", "90");
  const reducedWidth = await replayWindow.boundingBox();
  expect(reducedWidth).not.toBeNull();
  expect(reducedWidth!.width).toBeLessThan(fullWidth!.width);
  await page.getByRole("button", { name: "Increase chart width" }).click();
  await expect(replayWindow).toHaveAttribute("data-chart-width-percent", "100");

  await advanceToEntrySession(request);
  await page.reload();
  await expect(page.getByTestId("codex-operator-replay-lab")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/Session: (?:LONDON|LONDON NY OVERLAP|NEW YORK)/)).toBeVisible();
  await page.getByLabel("Codex replay interval").selectOption("15");
  await page.getByLabel("Codex replay speed").selectOption("8");

  await drawEditableLong(page);
  await page.getByRole("button", { name: "Crosshair" }).click();
  await expect(page.getByLabel("Resize long position entry")).toBeVisible();
  await expect(page.getByLabel("Resize long position stop")).toBeVisible();
  await expect(page.getByLabel("Resize long position target")).toBeVisible();

  const stopText = await page.getByLabel("long position drawing").locator("text").filter({ hasText: /^SL/ }).textContent();
  const stopHandle = page.getByLabel("Resize long position stop");
  const stopBox = await stopHandle.boundingBox();
  expect(stopBox).not.toBeNull();
  await page.mouse.move(stopBox!.x + stopBox!.width / 2, stopBox!.y + stopBox!.height / 2);
  await page.mouse.down();
  await page.mouse.move(stopBox!.x + stopBox!.width / 2, stopBox!.y + stopBox!.height / 2 + 22);
  await page.mouse.up();
  await expect(page.getByLabel("long position drawing").locator("text").filter({ hasText: /^SL/ })).not.toHaveText(stopText!);

  await page.getByRole("button", { name: "Enter full screen" }).click();
  await expect.poll(() => page.evaluate(() => Boolean(document.fullscreenElement))).toBeTruthy();
  const fullscreenPlace = page.getByRole("button", { name: "Full-screen Prepare Trade Decision" });
  await expect(fullscreenPlace).toBeVisible();
  await expect(fullscreenPlace).toBeEnabled();

  await page.getByRole("button", { name: "Play full-screen replay" }).click();
  const fullscreenPause = page.getByRole("button", { name: "Pause full-screen replay" });
  for (let sample = 0; sample < 4; sample += 1) {
    await expect(fullscreenPause).toBeVisible();
    await expect(fullscreenPause).toBeEnabled();
    await page.waitForTimeout(150);
  }
  await fullscreenPause.click();
  await expect(page.getByRole("button", { name: "Play full-screen replay" })).toBeEnabled();

  await expect(fullscreenPlace).toBeEnabled();
  await fullscreenPlace.click();
  const tradeForm = page.getByLabel("Human matched decision form", { exact: true });
  await expect(tradeForm).toBeVisible();
  await expect(page.getByLabel("Auto-populated point-in-time fundamentals")).toBeVisible();
  await expect(page.getByLabel("Macro regime")).toHaveCount(0);
  await expect(page.getByLabel("Codex invalidation condition")).not.toHaveValue("");
  await expect(page.getByLabel("Codex target logic")).not.toHaveValue("");
  await page.getByRole("button", { name: "Cancel Human matched decision form" }).click();
  await page.getByRole("button", { name: "Exit full screen" }).click();
  await expect.poll(() => page.evaluate(() => Boolean(document.fullscreenElement))).toBeFalsy();

  await advanceToTerminal(request);
  await page.reload();
  await expect(page.getByTestId("codex-operator-replay-lab")).toBeVisible({ timeout: 30_000 });
  const terminalPlay = page.getByRole("button", { name: "Play Human matched replay" });
  await expect(terminalPlay).toBeEnabled();
  await terminalPlay.click();
  await expect(page.getByText(/No further candles may be revealed/)).toBeVisible();
  const noTrade = page.getByRole("button", { name: "Open no-trade decision form" });
  await expect(noTrade).toBeEnabled();
  await noTrade.click();
  const noTradeForm = page.getByLabel("Human matched decision form", { exact: true });
  await expect(noTradeForm).toBeVisible();
  await page.getByLabel("No-trade reason").fill("The replay reached terminal before a valid setup was sealed.");
  await page.getByRole("button", { name: "Seal Human matched decision" }).click();
  await expect(page.getByLabel("Decision submission readiness")).toContainText(/inspect .* before sealing/i);
  await expect(noTradeForm.getByText(/Complete: inspect .* before sealing/i)).toBeVisible();
  await noTradeForm.getByRole("button", { name: "Return to chart" }).click();

  for (const label of ["W1", "D1", "H4", "H1", "M15"]) {
    const inspectButton = page.getByRole("button", { name: `Inspect ${label} timeframe` });
    if (!(await inspectButton.textContent())?.includes("sealed")) {
      await inspectButton.click();
      await expect(inspectButton).toContainText("sealed");
    }
  }

  await noTrade.click();
  await expect(page.getByLabel("Decision submission readiness")).toContainText("Ready to seal");
  await page.getByRole("button", { name: "Seal Human matched decision" }).click();
  await expect(page.getByText("CBR-2022-002", { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Complete: 1 / 30")).toBeVisible();

  const status = await (await request.get(`${API}/status`)).json();
  expect(status.cases_completed).toBe(1);
  expect(browserErrors).toEqual([]);
});
