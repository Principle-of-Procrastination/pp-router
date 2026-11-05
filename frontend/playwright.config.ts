import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  use: {
    baseURL: "http://127.0.0.1:5174",
    viewport: { width: 1440, height: 1080 },
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "uv run python scripts/e2e_server.py",
      cwd: "..",
      url: "http://127.0.0.1:4001/health",
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5174 --strictPort",
      url: "http://127.0.0.1:5174",
      env: { PPROUTER_PROXY_TARGET: "http://127.0.0.1:4001" },
      reuseExistingServer: false,
    },
  ],
});
