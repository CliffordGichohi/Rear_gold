import { expect, test, type Page } from "@playwright/test";


const LIVE_API = "http://localhost:8000/api/v1/coherent-auction-validation";
const ISOLATED_API = "http://localhost:8012/api/v1/coherent-auction-validation";


async function proxyIsolatedLedger(page: Page) {
  await page.route(`${LIVE_API}/**`, async (route) => {
    const request = route.request();
    const response = await route.fetch({
      url: request.url().replace(LIVE_API, ISOLATED_API),
    });
    await route.fulfill({ response });
  });
}


async function drawLongPosition(page: Page) {
  const chart = page.getByTestId("synchronized-replay-chart");
  await page.getByRole("button", { name: "Long position" }).click();
  await chart.scrollIntoViewIfNeeded();
  const box = await chart.boundingBox();
  expect(box).not.toBeNull();
  const x = box!.x + box!.width * 0.77;
  await page.mouse.click(x, box!.y + box!.height * 0.54);
  await page.waitForTimeout(150);
  await page.mouse.click(x, box!.y + box!.height * 0.72);
  await expect(page.getByLabel("long position draft")).toBeVisible();
  await page.waitForTimeout(150);
  await page.mouse.click(x, box!.y + box!.height * 0.34);
  await expect(page.getByLabel("long position drawing")).toBeVisible();
}


test("blind validation UI seals a classified order against an isolated ledger", async ({ page }) => {
  const browserErrors: string[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  await proxyIsolatedLedger(page);
  await page.goto("/replay/validation");

  await expect(page.getByTestId("annotated-replay-v3-lab")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("50 independently reproduced streams")).toBeVisible();
  await expect(page.getByLabel("Select practice date")).toContainText(/NEW_YORK|LONDON/);
  await expect(page.getByTestId("synchronized-replay-chart")).toHaveAttribute(
    "data-session-window-count",
    "1",
  );
  await expect(page.getByRole("button", { name: "Play replay" })).toBeDisabled();
  await page.getByRole("button", { name: "Start selected historical replay" }).click();
  await expect(page.getByRole("button", { name: "Play replay" })).toBeEnabled();

  await drawLongPosition(page);
  await page.getByRole("button", { name: "Crosshair" }).click();
  await expect(page.getByLabel("Resize long position entry")).toBeVisible();
  await expect(page.getByLabel("Resize long position stop")).toBeVisible();
  await expect(page.getByLabel("Resize long position target")).toBeVisible();

  await page.getByRole("button", { name: "Show H1 timeframe" }).click();
  await expect(page.getByLabel("long position drawing")).toBeVisible();
  await page.getByRole("button", { name: "Show M15 timeframe" }).click();
  await expect(page.getByLabel("long position drawing")).toBeVisible();

  await page.getByRole("button", { name: "Place Order" }).click();
  const dialog = page.getByLabel("Trade annotation dialog");
  await expect(dialog).toBeVisible();
  await expect(page.getByLabel("Auction family")).toHaveValue("CONTINUATION_WITH_ROOM");
  await expect(page.getByLabel("Target timeframe")).toHaveValue("H1_OPPOSING_LIQUIDITY");
  await page.getByLabel("Why this trade exists now").fill(
    "Macro support, H4 room, and a completed M15 transition align at known liquidity.",
  );
  await page.getByLabel("Dominant driver").fill("Falling real yields");
  await page.getByLabel("Higher-timeframe context").fill(
    "H4 pullback remains structurally intact with room to opposing H1 liquidity.",
  );
  await page.getByLabel("Session and liquidity context").fill(
    "The active session reclaimed a pre-existing liquidity level.",
  );
  await page.getByLabel("Observable entry trigger").fill(
    "Completed M15 transition followed by the first observable retest.",
  );
  await page.getByLabel("Invalidation logic").fill(
    "Opposite break through the active protected M15 swing.",
  );
  await page.getByLabel("Target logic").fill("Next opposing H1 liquidity area.");
  await page.getByRole("button", { name: "Confirm order and resume" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText("Orders today: 1")).toBeVisible();
  await expect(page.getByText(/HISTORICAL BLIND ROBUSTNESS/)).toBeVisible();

  const statusResponse = await page.request.get(`${ISOLATED_API}/status`);
  expect(statusResponse.ok()).toBeTruthy();
  const status = await statusResponse.json();
  expect(status.current_case_alias).toBe("GAV-2022-001");
  expect(status.practice_completed).toBe(0);
  expect(browserErrors).toEqual([]);
});
