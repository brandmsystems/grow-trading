import { defineConfig } from "@playwright/test";

// Browser tests run against the real app: Flask serving frontend/dist (build it first: npm run build).
// They use the installed Microsoft Edge (no browser download) and are READ-ONLY apart from one paper-engine
// start/stop on the Live page. Nothing here can place a real order (paper mode only).
// Windows only as written: the web server command uses the project's virtual environment.
const PORT = process.env.E2E_PORT ?? "5001";   // not 5000, so a running app on 5000 is left alone

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["json", { outputFile: "e2e/results.json" }]],
  use: { baseURL: `http://127.0.0.1:${PORT}`, channel: "msedge", headless: true },
  webServer: {
    command: "..\\.venv\\Scripts\\python.exe app.py",
    cwd: "../backend",
    url: `http://127.0.0.1:${PORT}/api/status`,
    env: { PORT },
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
