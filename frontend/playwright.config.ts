import { defineConfig, devices } from "@playwright/test";

/**
 * 1280×720 exactly, because that is the constraint Requirement 6 sets: what fits
 * on a shared screen in a Google Meet call. The viewport is not a rough guide
 * here, it is the thing being tested.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  reporter: "list",
  use: {
    // devices spread comes first, so the explicit viewport below wins. Order
    // matters: reversed, Desktop Chrome's 1280x720 default would silently
    // overwrite ours, and a check that measures the wrong viewport is worse
    // than no check.
    ...devices["Desktop Chrome"],
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    viewport: { width: 1280, height: 720 },
  },
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: "npm run dev",
        url: "http://localhost:3000",
        reuseExistingServer: true,
        timeout: 120_000,
      },
});
