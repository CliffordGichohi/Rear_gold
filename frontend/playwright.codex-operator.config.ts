import { defineConfig, devices } from "@playwright/test";


export default defineConfig({
  testDir: "./e2e",
  testMatch: "gold-codex-operator-replay-v1.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  reporter: [["line"]],
  outputDir: "../.codex_runs/codex_operator_replay_e2e/browser-certification",
  use: {
    baseURL: "http://localhost:3012",
    trace: "on",
    screenshot: "on",
    video: "on",
    viewport: { width: 1600, height: 1000 },
    actionTimeout: 12_000,
  },
  projects: [{
    name: "desktop-chrome",
    use: { ...devices["Desktop Chrome"], channel: "chrome" },
  }],
});
