import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "tests/browser",
  testMatch: "miniapp.spec.ts",
  timeout: 120000,
  expect: { timeout: 20000 },
  workers: 1,
  use: {
    baseURL: process.env.BASE_URL || "https://fleet.shvarev-demo.ru",
    viewport: { width: 1440, height: 1000 },
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  outputDir: "reports/miniapp/playwright",
  reporter: [["list"], ["json", { outputFile: "reports/miniapp/browser-results.json" }]],
});
