import { defineConfig } from "@playwright/test";

const baseURL = process.env.MEDIA_BRIDGE_PERSONAL_E2E_URL;
if (baseURL === undefined) throw new Error("MEDIA_BRIDGE_PERSONAL_E2E_URL is required");

export default defineConfig({
  testDir: "./e2e-personal",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL,
    trace: "off",
    screenshot: "off",
    video: "off",
  },
});
