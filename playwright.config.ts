import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "tests/browser",
  timeout: 60000,
  workers: 1,
  use: {
    baseURL: process.env.BASE_URL || "https://fleet.shvarev-demo.ru",
    headless: true,
    viewport: { width: 1440, height: 1000 },
    launchOptions: {
      executablePath: "/root/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome",
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    },
  },
  reporter: [["list"], ["json", { outputFile: "reports/browser-tests.json" }]],
});
