import { expect, test, type Page } from "@playwright/test";

const WIDTHS: [number, number][] = [[1920, 1080], [1440, 900], [1280, 800], [1024, 768], [768, 1024], [430, 932], [390, 844], [360, 800]];
const ROUTES: [string, string][] = [
  ["/", "Overview"], ["/live", "Live Trading"], ["/signals", "Trading Signals"], ["/options", "Options Analysis"],
  ["/backtest", "Backtesting"], ["/compare", "Strategy Comparison"], ["/scalping", "5-Minute Scalping"],
  ["/data", "Market Data"], ["/history", "Historical Charts"], ["/account", "Account & Settings"],
];

/** Collects everything that would show up as a red flag in the browser console. */
function watch(page: Page) {
  const problems: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") problems.push(`console: ${m.text()}`); });
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("response", (r) => { if (r.url().includes("/api/") && r.status() >= 400) problems.push(`HTTP ${r.status()} ${r.url()}`); });
  page.on("requestfailed", (r) => { if (!r.url().includes("socket.io")) problems.push(`request failed: ${r.url()} ${r.failure()?.errorText}`); });
  return problems;
}
const overflow = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);

for (const [w, h] of WIDTHS) {
  test.describe(`${w}px`, () => {
    test.use({ viewport: { width: w, height: h } });

    for (const [route, name] of ROUTES) {
      test(`${name}: no overflow, no console errors, content present`, async ({ page }, info) => {
        const problems = watch(page);
        await page.goto(`/app${route}`);
        await expect(page.locator("main")).not.toBeEmpty();
        // The first dashboard after a server start takes ~9 s (cold Groww calls); wait for it, then settle.
        await expect(page.getByText(/^(Connecting to .*|Loading…)$/)).toHaveCount(0, { timeout: 45_000 });   // every page's loading text
        await page.waitForTimeout(1500);
        expect(await overflow(page), "horizontal overflow (px)").toBeLessThanOrEqual(0);
        await expect(page.getByText(/Something went wrong|Couldn't load/i)).toHaveCount(0);
        expect((await page.locator("main").innerText()).length).toBeGreaterThan(40);
        await page.screenshot({ path: info.outputPath(`${w}-${name.replace(/\W+/g, "_")}.png`), fullPage: true });
        expect(problems).toEqual([]);
      });
    }

    test("navigation reaches every page", async ({ page }) => {
      const problems = watch(page);
      await page.goto("/app/");
      for (const [route, name] of ROUTES.slice(1)) {
        if (w >= 768) {
          await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name, exact: true }).click();
        } else {
          const bar = page.getByRole("navigation", { name: "Main" });
          const short = bar.getByRole("link", { name: new RegExp(`^${name.split(" ")[0]}`) });
          if (await short.count()) await short.first().click();
          else {
            await page.getByRole("button", { name: "All pages" }).click();
            await page.getByRole("dialog", { name: "Navigation" }).getByRole("link", { name, exact: true }).click();
          }
        }
        await expect(page).toHaveURL(new RegExp(`/app${route}$`));
        await expect(page.locator("main")).not.toBeEmpty();
      }
      expect(problems).toEqual([]);
    });

    test("live page: chart is drawn and usable", async ({ page }) => {
      await page.goto("/app/live");
      const canvas = page.locator("canvas").first();
      await expect(canvas).toBeVisible({ timeout: 20_000 });
      const box = await canvas.boundingBox();
      expect(box!.width).toBeGreaterThan(Math.min(w, 400) * 0.6);
      expect(box!.height).toBeGreaterThan(120);
      expect(await overflow(page)).toBeLessThanOrEqual(0);
    });

    test("connection indicator: WebSocket push, then REST polling when the socket is blocked", async ({ page, context }) => {
      await page.goto("/app/");
      if (w >= 640) await expect(page.getByText("Live push", { exact: true })).toBeVisible({ timeout: 30_000 });
      else await expect(page.getByText("Polling", { exact: true })).toHaveCount(0);     // phone: green dot only while pushing
      const p2 = await context.newPage();
      await p2.routeWebSocket(/socket\.io/, (ws) => ws.close());      // the socket never opens: the app must fall back to REST
      await p2.setViewportSize({ width: w, height: h });
      await p2.goto("/app/");
      await expect(p2.getByText("Polling", { exact: true }).filter({ visible: true })).toHaveCount(1, { timeout: 45_000 });   // desktop pill or phone pill, never both
      expect(await overflow(p2)).toBeLessThanOrEqual(0);                                 // the phone pill must not break the header
    });
  });
}

test.describe("trading controls (paper mode)", () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test("start paper trading, see it running or waiting, then stop it", async ({ page }) => {
    const problems = watch(page);
    page.on("dialog", (d) => d.accept());
    await page.goto("/app/live");
    const start = page.getByRole("button", { name: /Start paper trading/ });
    await expect(start).toBeVisible({ timeout: 20_000 });
    await start.click();
    const card = page.locator("section,div").filter({ hasText: "Trading Controls" }).last();
    await expect(page.getByRole("button", { name: /^Stop$/ })).toBeVisible({ timeout: 20_000 });
    await expect(card).toContainText(/Waiting|Running/);
    await page.getByRole("button", { name: /^Stop$/ }).click();
    await expect(page.getByRole("button", { name: /Start paper trading/ })).toBeVisible({ timeout: 20_000 });
    expect(problems).toEqual([]);
  });

  test("starting live mode without the LIVE phrase is refused (no order path)", async ({ request }) => {
    const r = await request.post("/api/live/start", { data: { config: { trade_mode: "live" }, confirm: "" } });
    expect(r.status()).toBe(400);
  });
});
