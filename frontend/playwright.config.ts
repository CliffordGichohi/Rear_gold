import { defineConfig, devices } from "@playwright/test";


export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 300_000,
  reporter: [["line"], ["html", { open: "never", outputFolder: "playwright-report-v3" }]],
  outputDir: "test-results-v3",
  use: {
    baseURL: "http://localhost:3011",
    trace: "on",
    screenshot: "on",
    video: "off",
    viewport: { width: 1600, height: 1000 },
    actionTimeout: 12_000,
  },
  projects: [
    {
      name: "desktop-chrome",
      use: { ...devices["Desktop Chrome"], channel: "chrome" },
    },
  ],
});
