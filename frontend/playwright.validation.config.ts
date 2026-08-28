import { defineConfig, devices } from "@playwright/test";


export default defineConfig({
  testDir: "./e2e",
  testMatch: "gold-coherent-auction-validation-ui.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  reporter: "line",
  outputDir: "test-results-validation",
  use: {
    baseURL: "http://localhost:3000",
    trace: "on",
    screenshot: "on",
    video: "off",
    viewport: { width: 1600, height: 1000 },
    actionTimeout: 15_000,
  },
  projects: [
    {
      name: "desktop-chrome",
      use: { ...devices["Desktop Chrome"], channel: "chrome" },
    },
  ],
});
