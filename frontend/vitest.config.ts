import { defineConfig } from "vitest/config";

// Kept separate from vite.config.ts so build-only options (chunk splitting) never reach the test runner.
// jsdom for everything: the formatter/API tests don't mind, the component tests need it.
export default defineConfig({
  test: {
    include: ["src/**/*.test.{ts,tsx}"],
    environment: "jsdom",
    setupFiles: ["src/test/setup.ts"],
    testTimeout: 15000,             // the heavy pages (Trading Settings) take about 5 s when the whole suite runs in parallel on a busy machine
    css: false,
    restoreMocks: false,
  },
});
