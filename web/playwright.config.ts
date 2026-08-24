import { defineConfig } from "@playwright/test";

const baseURL = "https://127.0.0.1:18443";
const stateFile = "/tmp/media_bridge_p2a_tools_01a02e88/e2e-state.json";
const runtimeDirectory = "/tmp/media_bridge_p2a_tools_01a02e88/e2e-runtime";
const chromiumExecutable = process.env.MEDIA_BRIDGE_E2E_CHROMIUM;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  outputDir: "test-results",
  globalTeardown: "./e2e/global-teardown.ts",
  use: {
    baseURL,
    ignoreHTTPSErrors: true,
    trace: "off",
    screenshot: "off",
    video: "off",
    launchOptions: chromiumExecutable === undefined
      ? undefined
      : { executablePath: chromiumExecutable },
  },
  webServer: {
    command: `.venv/bin/python -m tests.e2e_support.control_server --static-root web/dist --state-file ${stateFile} --runtime-dir ${runtimeDirectory} --port 18443`,
    cwd: "..",
    url: `${baseURL}/admin/v1/health`,
    ignoreHTTPSErrors: true,
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
