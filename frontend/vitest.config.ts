import { defineConfig } from "vitest/config";

// Kept separate from vite.config.ts so build-only options (chunk splitting) never reach the test runner.
export default defineConfig({
  test: { include: ["src/**/*.test.ts"], environment: "node" },
});
