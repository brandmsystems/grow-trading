import { defineConfig } from "vitest/config";

// Kept separate from vite.config.ts so build-only options (chunk splitting) never reach the test runner.
// jsdom for everything: the formatter/API tests don't mind, the component tests need it.
export default defineConfig({
  test: {
    include: ["src/**/*.test.{ts,tsx}"],
    environment: "jsdom",
    setupFiles: ["src/test/setup.ts"],
    css: false,
    restoreMocks: false,
  },
});
