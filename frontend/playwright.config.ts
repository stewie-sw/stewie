import { defineConfig, devices } from "@playwright/test";

// [REQ:RF-01] boot the real FastAPI backend (DEV_OPEN loopback -> dev-open director, so all 13 panes are
// visible) serving the built /app bundle, and drive it with a real Chromium. The vite build must exist
// (npm run build) before this runs; CI builds then tests.
export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  fullyParallel: false,
  use: { baseURL: "http://127.0.0.1:8391" },
  webServer: {
    command:
      "DEV_OPEN=1 STEWIE_DEV_OPEN=1 PYTHONNOUSERSITE=1 ${STEWIE_PY:-.venv/bin/python} -m uvicorn " +
      "stewie.server.server:app --host 127.0.0.1 --port 8391 --log-level warning",
    cwd: "..",
    url: "http://127.0.0.1:8391/healthz",
    reuseExistingServer: true,
    timeout: 30_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
