import { expect, test, type Page } from "@playwright/test";

const WIDTHS: [number, number][] = [[1920, 1080], [1440, 900], [1280, 800], [1024, 768], [768, 1024], [430, 932], [390, 844], [360, 800]];
const ROUTES: [string, string][] = [
  ["/", "Overview"], ["/live", "Live Trading"], ["/auto", "Automated Paper Trading"], ["/premarket", "Pre-Market Analysis"], ["/signals", "Trading Signals"], ["/options", "Options Analysis"],
  ["/backtest", "Backtesting"], ["/compare", "Strategy Comparison"], ["/scalping", "5-Minute Scalping"],
  ["/data", "Market Data"], ["/history", "Historical Charts"], ["/range", "Daily Range"], ["/trading-settings", "Trading Settings"], ["/account", "Account & Settings"],
];

/** Collects everything that would show up as a red flag in the browser console. */
function watch(page: Page) {
  const problems: string[] = [];
  // Publisher thumbnails are best-effort (the card falls back to a letter tile), so a thumbnail that fails to load is not a problem.
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) problems.push(`console: ${m.text()}`); });
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("response", (r) => { if (r.url().includes("/api/") && r.status() >= 400) problems.push(`HTTP ${r.status()} ${r.url()}`); });
  page.on("requestfailed", (r) => { if (!r.url().includes("socket.io") && r.resourceType() !== "image") problems.push(`request failed: ${r.url()} ${r.failure()?.errorText}`); });
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

// The news section reads real feeds from this machine: it must show articles, or say plainly that no source answered.
for (const [w, h] of [[1280, 900], [768, 1024], [390, 844]] as [number, number][]) {
  test.describe(`pre-market news at ${w}px`, () => {
    test.use({ viewport: { width: w, height: h } });

    test("articles are readable here, filterable, and link to the original", async ({ page }, info) => {
      const problems = watch(page);
      await page.goto("/app/premarket");
      const section = page.getByTestId("news-section");
      await expect(section).toBeVisible({ timeout: 30_000 });
      await expect(page.getByText(/Fetching the latest news/)).toHaveCount(0, { timeout: 60_000 });
      if (await page.getByTestId("news-unavailable").count()) {
        await expect(page.getByTestId("article")).toHaveCount(0);        // no source answered: nothing is shown, nothing is made up
      } else {
        const cards = page.getByTestId("article");
        expect(await cards.count()).toBeGreaterThan(0);
        const first = cards.first();
        await expect(first.getByTestId("why")).toBeVisible();
        const link = first.getByRole("link", { name: /Read full news/ });
        await expect(link).toHaveAttribute("target", "_blank");
        expect(await link.getAttribute("href")).toMatch(/^https?:\/\//);
        await expect(page.getByRole("tab", { name: /Crude Oil/ })).toBeVisible();
        await page.getByRole("tab", { name: /Crude Oil/ }).click();
        await page.getByRole("tab", { name: /All News/ }).click();
        await page.getByLabel("Search news").fill("zzzzqqqq");
        await expect(page.getByText("No articles match")).toBeVisible();
        await page.getByLabel("Search news").fill("");
        expect(await page.getByTestId("article").count()).toBeGreaterThan(0);
      }
      expect(await overflow(page)).toBeLessThanOrEqual(1);
      await section.screenshot({ path: info.outputPath(`news-${w}.png`) });
      expect(problems).toEqual([]);
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

// ---------------------------------------------------------------------------------------------------------
// Privacy: no personal Groww account data anywhere (balance, funds, margin, profile, positions, orders, real trades).
// ---------------------------------------------------------------------------------------------------------
const FORBIDDEN_FIELDS = [
  "option_buy_balance", "clear_cash", "collateral_available", "net_margin_used", "fno_margin_details",
  "entry_order_id", "exit_order_id", "groww_order_id", "order_reference", "user_profile",
];
const FORBIDDEN_LABELS = [
  /^Funds$/, /^Profile$/, /Margin used/i, /Collateral available/i, /F&O option buying/i, /Groww margin/i,
  /Available margin/i, /Portfolio value/i, /Holdings/i, /Order history/i,
];
const REMOVED_ENDPOINTS = ["/api/funds", "/api/profile", "/api/live/broker"];

test.describe("privacy: no personal account data", () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test("no page shows it, no response carries it, no request asks for it", async ({ page }) => {
    const requested: string[] = [];
    const leaked: string[] = [];
    const scan = (where: string, body: string) => {
      for (const f of FORBIDDEN_FIELDS) if (body.includes(f)) leaked.push(`${where}: ${f}`);
    };
    page.on("request", (r) => { if (r.url().includes("/api/")) requested.push(new URL(r.url()).pathname); });
    page.on("response", async (r) => {
      if (r.url().includes("/api/") && (r.headers()["content-type"] ?? "").includes("json")) scan(new URL(r.url()).pathname, await r.text().catch(() => ""));
    });
    page.on("websocket", (ws) => ws.on("framereceived", (e) => scan("websocket", String(e.payload))));
    const consoleLines: string[] = [];
    page.on("console", (m) => consoleLines.push(m.text()));

    for (const [route, name] of ROUTES) {
      await page.goto(`/app${route}`);
      await expect(page.getByText(/^(Connecting to .*|Loading…)$/)).toHaveCount(0, { timeout: 45_000 });
      await page.waitForTimeout(1500);
      const text = await page.locator("body").innerText();
      for (const re of FORBIDDEN_LABELS) {
        for (const line of text.split("\n")) expect(line.trim(), `${name} shows "${line.trim()}"`).not.toMatch(re);
      }
      // hidden sections and tooltips: titles, aria labels and any element with display:none
      const attrs = await page.evaluate(() => Array.from(document.querySelectorAll("[title],[aria-label]")).map((e) => (e.getAttribute("title") ?? "") + " " + (e.getAttribute("aria-label") ?? "")).join("\n"));
      const hiddenText = await page.evaluate(() => Array.from(document.querySelectorAll("*")).filter((e) => getComputedStyle(e).display === "none" && e.children.length === 0).map((e) => e.textContent ?? "").join("\n"));
      for (const re of FORBIDDEN_LABELS) {
        expect(attrs, `${name}: tooltip or label`).not.toMatch(re);
        expect(hiddenText, `${name}: hidden element`).not.toMatch(re);
      }
    }
    for (const bad of REMOVED_ENDPOINTS) expect(requested, `requested ${bad}`).not.toContain(bad);
    expect(leaked, "account fields in responses").toEqual([]);
    expect(consoleLines.join("\n")).not.toMatch(/balance|margin|funds|order id/i);
  });

  test("the removed account endpoints answer 404 and the trades endpoint never returns real trades", async ({ request }) => {
    for (const url of REMOVED_ENDPOINTS) expect((await request.get(url)).status(), url).toBe(404);
    expect((await (await request.get("/api/live/trades?mode=live")).json()).data).toEqual([]);
    const all = (await (await request.get("/api/live/trades")).json()).data as { trade_mode: string }[];
    expect(all.every((x) => x.trade_mode !== "live")).toBe(true);
  });
});
