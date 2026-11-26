import { screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LearningCentre from "../../pages/LearningCentre";
import { mlSummary } from "../../components/learn/LearnNews";
import { CHAIN, EXAMPLES, POSITIONS, PLAN, breakEvenWinRate, breakeven, chainTotals, expiryPnl, inr, intrinsic, planLots, planRatio, planReward, planRisk, tradePnl } from "../../components/learn/examples";
import { GLOSSARY } from "../../components/learn/glossary";
import { DIAGRAM_META, LESSONS, LEVELS, ROADMAP_ORDER, type DiagramKey } from "../../components/learn/lessons";
import { UI } from "../../components/learn/ui";
import { fail, mockApi, type MockApi } from "../../test/mockApi";
import { renderWithProviders } from "../../test/render";
import { makePmArticle, makePmFeed } from "../../test/fixtures";

const ML = /[ഀ-ൿ]/;
const page = (api: MockApi = mockApi()) => ({ ...renderWithProviders(<LearningCentre />, { api }), api });
const nav = () => within(screen.getByRole("navigation", { name: /^(Lessons|പാഠങ്ങൾ)$/ }));
const open = async (user: ReturnType<typeof page>["user"], name: RegExp | string) => user.click(nav().getByRole("button", { name }));
const toMl = async (user: ReturnType<typeof page>["user"]) => user.click(screen.getByRole("radio", { name: "മലയാളം" }));

beforeEach(() => { window.localStorage.clear(); window.scrollTo = vi.fn(); });

describe("every figure on the page is calculated, and agrees with the lessons", () => {
  it("computes expiry profit and loss for the four positions", () => {
    const { buyCE, buyPE, sellCE, sellPE } = POSITIONS;
    expect(intrinsic("CE", 24000, 24100)).toBe(100);
    expect(intrinsic("CE", 24200, 24100)).toBe(0);
    expect(intrinsic("PE", 24000, 23700)).toBe(300);
    // Buy CE 24,000 @120 (cost 9,000)
    expect(expiryPnl(buyCE, 23900)).toBe(-9000);
    expect(expiryPnl(buyCE, 24120)).toBe(0);
    expect(expiryPnl(buyCE, 24300)).toBe(13500);
    expect(breakeven(buyCE)).toBe(24120);
    // Buy PE 24,000 @110 (cost 8,250)
    expect(expiryPnl(buyPE, 24100)).toBe(-8250);
    expect(expiryPnl(buyPE, 23890)).toBe(0);
    expect(expiryPnl(buyPE, 23700)).toBe(14250);
    expect(breakeven(buyPE)).toBe(23890);
    // Sell CE 24,200 @60 (receive 4,500)
    expect(expiryPnl(sellCE, 24100)).toBe(4500);
    expect(expiryPnl(sellCE, 24260)).toBe(0);
    expect(expiryPnl(sellCE, 24400)).toBe(-10500);
    expect(breakeven(sellCE)).toBe(24260);
    // Sell PE 23,800 @55 (receive 4,125)
    expect(expiryPnl(sellPE, 23900)).toBe(4125);
    expect(expiryPnl(sellPE, 23745)).toBe(0);
    expect(expiryPnl(sellPE, 23500)).toBe(-18375);
    expect(breakeven(sellPE)).toBe(23745);
  });

  it("computes the stop loss, target, risk/reward and position size", () => {
    expect(tradePnl("buy", PLAN.entry, PLAN.target)).toBe(5400);
    expect(tradePnl("buy", PLAN.entry, PLAN.stop)).toBe(-2700);
    expect(planRisk()).toBe(2700);
    expect(planReward()).toBe(5400);
    expect(planRatio()).toBe(2);
    expect(Math.round(breakEvenWinRate() * 100)).toBe(33);
    expect(planLots()).toBe(1);                                  // 1% of 3,00,000 = 3,000; one lot risks 2,700
    expect(tradePnl("buy", 150, 110)).toBe(-3000);              // IV crush example
    expect(tradePnl("sell", 100, 80)).toBe(1500);
  });

  it("computes the sample option chain totals and PCR", () => {
    expect(chainTotals()).toEqual({ ce: 91.2, pe: 84.6, pcr: 0.93 });
    expect(CHAIN.filter((r) => r.strike === 24000)).toHaveLength(1);
  });

  it("the lesson text quotes exactly the numbers the calculator gives", () => {
    const en = LESSONS.find((x) => x.id === "positions")!.points.map((p) => p.text.en).join(" ");
    const ml = LESSONS.find((x) => x.id === "positions")!.points.map((p) => p.text.ml).join(" ");
    const { buyCE, buyPE, sellCE, sellPE } = POSITIONS;
    const quoted = [expiryPnl(buyCE, 24300), expiryPnl(buyPE, 23700), -expiryPnl(sellCE, 24400), -expiryPnl(sellPE, 23500),
      buyCE.premium * 75, buyPE.premium * 75, sellCE.premium * 75, sellPE.premium * 75].map((n) => n.toLocaleString("en-IN"));
    for (const q of quoted) { expect(en).toContain(q); expect(ml).toContain(q); }
    for (const b of [breakeven(buyCE), breakeven(buyPE), breakeven(sellCE), breakeven(sellPE)]) expect(en).toContain(b.toLocaleString("en-IN"));
    const risk = LESSONS.find((x) => x.id === "risk")!.points.map((p) => p.text.en).join(" ");
    expect(risk).toContain("2,700"); expect(risk).toContain("5,400"); expect(risk).toContain("33%"); expect(risk).toContain("3,00,000");
    const chain = LESSONS.find((x) => x.id === "chain")!.points.map((p) => p.text.en).join(" ");
    expect(chain).toContain("0.93"); expect(chain).toContain("84.6"); expect(chain).toContain("91.2");
  });

  it("every worked example row is calculated, not typed", () => {
    const values = EXAMPLES.flatMap((e) => e.rows.map((r) => r.value));
    for (const v of ["+₹5,400", "-₹2,700", "-₹9,000", "+₹13,500", "+₹14,250", "-₹10,500", "-₹3,000"]) expect(values).toContain(v);
    expect(inr(0)).toBe("₹0");
    expect(EXAMPLES.map((e) => e.id)).toEqual(["buyce-trade", "buyce-expiry", "buype-expiry", "sellce-expiry", "iv-crush", "sizing"]);
  });
});

describe("content is complete in English and Malayalam", () => {
  const texts = () => LESSONS.flatMap((x) => [x.title, x.intro, x.key, ...(x.warning ? [x.warning] : []), ...x.points.flatMap((p) => [p.term, p.text])]);

  it("has all eleven topics: eight lessons, examples, glossary and roadmap", () => {
    expect(LESSONS.map((x) => x.id)).toEqual(["basics", "positions", "premium", "volatility", "chain", "greeks", "analysis", "risk", "examples"]);
    expect([...ROADMAP_ORDER].sort()).toEqual(LESSONS.map((x) => x.id).sort());
    expect(LEVELS.map((x) => x.key)).toEqual(["beginner", "intermediate", "advanced"]);
    expect(GLOSSARY.length).toBeGreaterThanOrEqual(50);
  });

  it("translates every title, intro, key idea, warning, point and glossary entry into Malayalam", () => {
    for (const t of texts()) { expect(t.en.trim().length).toBeGreaterThan(2); expect(t.ml).toMatch(ML); expect(t.ml).not.toBe(t.en); }
    for (const g of GLOSSARY) { expect(g.def.en.length).toBeGreaterThan(5); expect(g.def.ml).toMatch(ML); }
    for (const e of EXAMPLES) for (const t of [e.title, e.setup, e.note, ...e.rows.map((r) => r.label)]) expect(t.ml).toMatch(ML);
    for (const m of Object.values(DIAGRAM_META)) { expect(m.title.ml).toMatch(ML); expect(m.caption.ml).toMatch(ML); }
    const walk = (o: unknown): void => { if (o && typeof o === "object") { const v = o as Record<string, unknown>; if (typeof v.en === "string" && typeof v.ml === "string") { expect(v.ml.length).toBeGreaterThan(0); } else Object.values(v).forEach(walk); } };
    walk(UI);
  });

  it("keeps the financial terms in English inside the Malayalam text", () => {
    const g = LESSONS.find((x) => x.id === "greeks")!;
    const ml = g.points.map((p) => p.text.ml).join(" ");
    for (const w of ["IV", "NIFTY"]) expect(ml).toContain(w);
    expect(LESSONS.find((x) => x.id === "positions")!.points.map((p) => p.term.ml).join(" ")).toMatch(/Buy CE[\s\S]*Buy PE[\s\S]*Sell CE[\s\S]*Sell PE/);
    expect(LESSONS.find((x) => x.id === "chain")!.points.map((p) => p.term.ml).join(" ")).toMatch(/OI[\s\S]*PCR/);
    for (const k of ["CE", "PE", "Delta", "Gamma", "Theta", "Vega", "IV", "OI"]) expect(GLOSSARY.some((x) => x.term.includes(k))).toBe(true);
  });

  it("covers the required topic lists", () => {
    const all = (id: string) => LESSONS.find((x) => x.id === id)!.points.map((p) => p.term.en).join(" | ").toLowerCase();
    for (const w of ["option", "derivative", "underlying", "nifty", "call", "put", "buy", "expiry", "strike", "lot size", "premium"]) expect(all("basics")).toContain(w);
    for (const w of ["buy ce", "buy pe", "sell ce", "sell pe"]) expect(all("positions")).toContain(w);
    for (const w of ["intrinsic", "time value", "factors"]) expect(all("premium")).toContain(w);
    for (const w of ["historical", "implied", "vix", "iv crush"]) expect(all("volatility")).toContain(w);
    for (const w of ["strike", "ltp", "volume", "open interest", "oi change", "pcr", "call writing"]) expect(all("chain")).toContain(w);
    for (const w of ["delta", "gamma", "theta", "vega", "rho"]) expect(all("greeks")).toContain(w);
    for (const w of ["support", "resistance", "trend", "breakout", "liquidity", "volume", "price action", "market structure"]) expect(all("analysis")).toContain(w);
    for (const w of ["stop loss", "target", "position sizing", "risk / reward", "capital protection", "common mistakes"]) expect(all("risk")).toContain(w);
  });

  it("every diagram used by a lesson has a title and an explanation", () => {
    const used = new Set(LESSONS.flatMap((x) => x.diagrams));
    const all: DiagramKey[] = ["cepe", "positions", "moneyness", "premium", "decay", "volatility", "chain", "greeks", "structure", "risk"];
    expect([...used].sort()).toEqual([...all].sort());
    for (const k of all) { expect(DIAGRAM_META[k].title.en.length).toBeGreaterThan(5); expect(DIAGRAM_META[k].caption.en.length).toBeGreaterThan(40); }
  });
});

describe("Learning Centre page", () => {
  it("opens on Start learning with the disclaimer and the language switch at the top", async () => {
    page();
    expect(screen.getByRole("heading", { level: 1, name: "Options Trading Learning Centre" })).toBeInTheDocument();
    expect(screen.getByTestId("disclaimer")).toHaveTextContent(/Not investment advice/);
    expect(screen.getByRole("radio", { name: "English" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "മലയാളം" })).not.toBeChecked();
    const home = within(screen.getByTestId("home"));
    expect(home.getAllByText("Start learning").length).toBeGreaterThan(0);
    expect(home.getByText(/0 \/ 9 lessons completed/)).toBeInTheDocument();
    expect(home.getByText("Beginner")).toBeInTheDocument();
    expect(home.getByText("Intermediate")).toBeInTheDocument();
    expect(home.getByText("Advanced")).toBeInTheDocument();
  });

  it("switches the whole page to Malayalam and back without a reload, and remembers it", async () => {
    const { user, unmount } = page();
    await open(user, /^1\. Options Trading Basics/);
    expect(screen.getByTestId("lesson-title")).toHaveTextContent("Options Trading Basics");
    await toMl(user);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("ഓപ്ഷൻ ട്രേഡിംഗ് ലേണിംഗ് സെന്റർ");
    expect(screen.getByTestId("lesson-title")).toHaveTextContent("ഓപ്ഷൻ ട്രേഡിംഗ് അടിസ്ഥാനങ്ങൾ");
    expect(screen.getByTestId("disclaimer")).toHaveTextContent("വിദ്യാഭ്യാസത്തിന് മാത്രം");
    expect(nav().getByRole("button", { name: /പദാവലി/ })).toBeInTheDocument();
    expect(screen.getByTestId("key-idea")).toHaveTextContent("പ്രധാന ആശയം");
    expect(screen.getByTestId("risk-warning")).toHaveTextContent("റിസ്ക് മുന്നറിയിപ്പ്");
    expect(screen.getByTestId("diagram-cepe")).toBeInTheDocument();
    expect(screen.getByTestId("caption-cepe")).toHaveTextContent("CE (കോൾ)");
    expect(screen.getByTestId("learning-centre")).toHaveAttribute("lang", "ml");
    // still on the same lesson (navigation inside the page keeps the language)
    await open(user, /2\. നാല്/);
    expect(screen.getByTestId("lesson-title")).toHaveTextContent("നാല് ട്രേഡിംഗ് പൊസിഷനുകൾ");
    await open(user, /പദാവലി/);
    expect(screen.getByTestId("glossary")).toHaveTextContent("ഓപ്പൺ ഇന്ററസ്റ്റ് (OI)");
    unmount();
    page();                                                      // a new visit remembers the choice
    expect(screen.getByRole("radio", { name: "മലയാളം" })).toBeChecked();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("ഓപ്ഷൻ ട്രേഡിംഗ്");
  });

  it("every part of the page has Malayalam: lessons, glossary, roadmap, examples and news", async () => {
    const { user } = page();
    await toMl(user);
    for (const ls of LESSONS) {
      await open(user, new RegExp(`^${ls.title.ml.slice(0, 6).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`));
      expect(screen.getByTestId("lesson-title")).toHaveTextContent(ls.title.ml);
      const body = screen.getByTestId("lesson").textContent ?? "";
      expect(body).toContain(ls.intro.ml);
      expect(body).toContain(ls.key.ml);
      for (const p of ls.points) expect(body).toContain(p.term.ml);
      for (const k of ls.diagrams) expect(body).toContain(DIAGRAM_META[k].caption.ml);
    }
    await open(user, /റോഡ്മാപ്പ്/);
    expect(screen.getByTestId("roadmap")).toHaveTextContent("തുടക്കക്കാർ");
    await open(user, /വാർത്തകൾ/);
    await screen.findByTestId("learn-news");
    expect(screen.getAllByText(UI.news.ml).length).toBeGreaterThan(1);               // the sidebar item and the card title
  });

  it("opens each lesson from the sidebar with its key idea, expandable points, risk warning and figures", async () => {
    const { user } = page();
    for (const ls of LESSONS) {
      await open(user, new RegExp(`^${ls.title.en.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`));
      expect(screen.getByTestId("lesson-title")).toHaveTextContent(ls.title.en);
      expect(screen.getByTestId("key-idea")).toHaveTextContent(ls.key.en);
      for (const k of ls.diagrams) { expect(screen.getByTestId(`diagram-${k}`)).toBeInTheDocument(); expect(screen.getByTestId(`caption-${k}`)).toHaveTextContent(DIAGRAM_META[k].caption.en); }
      if (ls.warning) expect(screen.getByTestId("risk-warning")).toHaveTextContent(ls.warning.en);
      expect(screen.queryAllByTestId("point")).toHaveLength(ls.points.length);
    }
  });

  it("explanations expand and collapse", async () => {
    const { user } = page();
    await open(user, /^1\. Options Trading Basics/);
    const points = screen.getAllByTestId("point") as HTMLDetailsElement[];
    expect(points[0].open).toBe(true);
    expect(points[points.length - 1].open).toBe(false);
    await user.click(within(points[points.length - 1]).getByText("Premium"));
    expect(points[points.length - 1].open).toBe(true);
  });

  it("draws the four payoff boxes, the ATM/ITM/OTM labels and the chain with its PCR", async () => {
    const { user } = page();
    await open(user, /^2\. The Four/);
    for (const k of ["buyCE", "buyPE", "sellCE", "sellPE"]) expect(screen.getByTestId(`payoff-${k}`)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Buy CE: Loss limited to the premium/ })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Sell PE: Gain limited to the premium/ })).toBeInTheDocument();
    await open(user, /^3\. Option Premium/);
    expect(within(screen.getByTestId("ce-23800")).getByText("ITM")).toBeInTheDocument();
    expect(within(screen.getByTestId("ce-24000")).getByText("ATM")).toBeInTheDocument();
    expect(within(screen.getByTestId("ce-24200")).getByText("OTM")).toBeInTheDocument();
    expect(within(screen.getByTestId("pe-23800")).getByText("OTM")).toBeInTheDocument();
    expect(within(screen.getByTestId("pe-24200")).getByText("ITM")).toBeInTheDocument();
    await open(user, /^5\. Option Chain/);
    expect(screen.getByTestId("chain-table")).toBeInTheDocument();
    expect(screen.getByTestId("chain-pcr")).toHaveTextContent("PCR = 84.6 / 91.2 = 0.93");
    await open(user, /^6\. Option Greeks/);
    for (const g of ["delta", "gamma", "theta", "vega"]) expect(screen.getByTestId(`greek-${g}`)).toBeInTheDocument();
  });

  it("shows the worked examples with calculated profit and loss, labelled illustrative", async () => {
    const { user } = page();
    await open(user, /^10\. Practical/);
    const ex = within(screen.getByTestId("examples"));
    expect(ex.getAllByText("Illustrative values, not live prices.")).toHaveLength(EXAMPLES.length);
    const first = within(screen.getByTestId("example-buyce-trade"));
    expect(first.getByText("+₹5,400")).toBeInTheDocument();
    expect(first.getByText("-₹2,700")).toBeInTheDocument();
    expect(first.getByText("1 : 2")).toBeInTheDocument();
    expect(within(screen.getByTestId("example-sellce-expiry")).getAllByTestId("example-value").map((e) => e.textContent)).toEqual(["+₹4,500", "+₹4,500", "₹0", "-₹10,500", "-₹25,500"]);
    expect(within(screen.getByTestId("example-sizing")).getByText("1")).toBeInTheDocument();
  });
});

describe("progress, continue learning and the roadmap", () => {
  it("marks lessons complete, updates progress and continues from the next lesson", async () => {
    const { user } = page();
    await open(user, /^1\. Options Trading Basics/);
    await user.click(screen.getByRole("button", { name: "Mark as complete" }));
    expect(screen.getByRole("button", { name: /Completed/ })).toBeInTheDocument();
    await user.click(nav().getByRole("button", { name: /Start here/ }));
    const home = within(screen.getByTestId("home"));
    expect(home.getByText(/1 \/ 9 lessons completed/)).toBeInTheDocument();
    expect(home.getAllByText("Continue learning").length).toBeGreaterThan(0);
    await user.click(home.getByRole("button", { name: "Continue learning" }));
    expect(screen.getByTestId("lesson-title")).toHaveTextContent("The Four Trading Positions");     // the next lesson in the roadmap
  });

  it("continues with the lesson that was opened last if it is not finished", async () => {
    const { user } = page();
    await open(user, /^8\. Risk Management/);
    await user.click(nav().getByRole("button", { name: /Start here/ }));
    await user.click(screen.getByRole("button", { name: "Continue learning" }));
    expect(screen.getByTestId("lesson-title")).toHaveTextContent("Risk Management");
  });

  it("remembers progress after leaving and coming back, and can reset it", async () => {
    const first = page();
    await open(first.user, /^3\. Option Premium/);
    await first.user.click(screen.getByRole("button", { name: "Mark as complete" }));
    first.unmount();
    const { user } = page();
    expect(nav().getByRole("button", { name: /^3\. Option Premium/ })).toBeInTheDocument();
    await user.click(nav().getByRole("button", { name: /Learning roadmap/ }));
    const rm = within(screen.getByTestId("roadmap"));
    expect(rm.getAllByText("Done")).toHaveLength(1);
    expect(rm.getByText("1 / 4")).toBeInTheDocument();             // beginner: 4 lessons
    await user.click(rm.getByRole("button", { name: "Reset progress" }));
    expect(rm.queryAllByText("Done")).toHaveLength(0);
  });

  it("finishing everything says so", async () => {
    window.localStorage.setItem("learn.v1", JSON.stringify({ lang: "en", done: ROADMAP_ORDER, last: null }));
    page();
    expect(screen.getByText(/You have finished every lesson/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue learning" })).not.toBeInTheDocument();
  });

  it("ignores damaged saved data", () => {
    window.localStorage.setItem("learn.v1", "{not json");
    page();
    expect(screen.getByRole("radio", { name: "English" })).toBeChecked();
    expect(screen.getAllByText(/0 \/ 9 lessons completed/).length).toBeGreaterThan(0);
  });

  it("previous / next buttons walk the roadmap order", async () => {
    const { user } = page();
    await open(user, /^1\. Options Trading Basics/);
    expect(screen.getByRole("button", { name: /Previous/ })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /Next/ }));
    expect(screen.getByTestId("lesson-title")).toHaveTextContent("The Four Trading Positions");
    await user.click(screen.getByRole("button", { name: /Previous/ }));
    expect(screen.getByTestId("lesson-title")).toHaveTextContent("Options Trading Basics");
    await open(user, /^10\. Practical/);
    expect(screen.getByRole("button", { name: /Next/ })).toBeDisabled();
  });
});

describe("search and glossary", () => {
  it("finds lessons and terms as you type, in either language", async () => {
    const { user } = page();
    await user.type(screen.getByRole("searchbox", { name: "Search lessons and terms" }), "theta");
    const res = within(screen.getByTestId("search-results"));
    expect(res.getByRole("button", { name: /6\. Option Greeks/ })).toBeInTheDocument();
    expect(res.getByText("Theta")).toBeInTheDocument();
    await user.click(res.getByRole("button", { name: /6\. Option Greeks/ }));
    expect(screen.getByTestId("lesson-title")).toHaveTextContent("Option Greeks");
    expect(screen.getByRole("searchbox", { name: "Search lessons and terms" })).toHaveValue("");
    await toMl(user);
    await user.type(screen.getByRole("searchbox", { name: "പാഠങ്ങളും പദങ്ങളും തിരയുക" }), "ഡെൽറ്റ");
    expect(within(screen.getByTestId("search-results")).getByRole("button", { name: /6\. ഓപ്ഷൻ ഗ്രീക്സ്/ })).toBeInTheDocument();
  });

  it("says when nothing matches and clears with the X", async () => {
    const { user } = page();
    await user.type(screen.getByRole("searchbox", { name: "Search lessons and terms" }), "zzzz");
    expect(screen.getByText(/Nothing found/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear search" }));
    expect(screen.getByTestId("home")).toBeInTheDocument();
  });

  it("filters the glossary and shows definitions", async () => {
    const { user } = page();
    await user.click(nav().getByRole("button", { name: /^Glossary/ }));
    expect(screen.getByTestId("glossary-count")).toHaveTextContent(`${GLOSSARY.length} terms`);
    await user.type(screen.getByRole("searchbox", { name: "Filter terms" }), "open interest");
    const gl = within(screen.getByTestId("glossary"));
    expect(gl.getByText("Open interest (OI)")).toBeInTheDocument();
    expect(gl.getByText(/still open at a strike/)).toBeInTheDocument();
    expect(screen.getByTestId("glossary-count")).not.toHaveTextContent(`${GLOSSARY.length} terms`);
  });
});

describe("responsive layout", () => {
  it("lays out as a sidebar on large screens and a scrolling strip on small ones", () => {
    page();
    expect(screen.getByTestId("learning-centre").querySelector(".lg\\:grid-cols-\\[250px_minmax\\(0\\,1fr\\)\\]")).not.toBeNull();
    expect(screen.getByRole("navigation", { name: "Lessons" }).className).toMatch(/overflow-x-auto/);
    expect(screen.getByRole("navigation", { name: "Lessons" }).className).toMatch(/lg:flex-col/);
  });

  it("wide tables scroll inside their own box instead of the page", async () => {
    const { user } = page();
    await open(user, /^5\. Option Chain/);
    expect(screen.getByTestId("chain-table").parentElement?.className).toMatch(/overflow-x-auto/);
  });
});

describe("Latest Options & Market News", () => {
  const news = async (user: ReturnType<typeof page>["user"]) => { await user.click(nav().getByRole("button", { name: /Latest options/ })); return within(await screen.findByTestId("learn-news")); };

  it("lists real articles with headline, summary, date and time, source and the original link", async () => {
    const { user } = page();
    const n = await news(user);
    const cards = await n.findAllByTestId("learn-article");
    expect(cards).toHaveLength(makePmFeed().articles.length);
    const first = within(cards.find((c) => c.textContent?.includes("Wall Street rallies"))!);
    expect(first.getByRole("link", { name: "Wall Street rallies as Fed signals rate cut" })).toHaveAttribute("href", "https://example.com/a");
    expect(first.getByText(/Source: Reuters/)).toBeInTheDocument();
    expect(first.getByText("18 Nov 2026, 22:10 IST", { exact: false })).toBeInTheDocument();
    expect(first.getByTestId("learn-summary")).toHaveTextContent(/US stocks closed higher/);
    const link = first.getByRole("link", { name: /Read the original article/ });
    expect(link).toHaveAttribute("href", "https://example.com/a");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(screen.getByTestId("learn-news-updated")).toHaveTextContent(/19 Nov 2026, 08:44 IST/);
  });

  it("never invents a summary", async () => {
    const { user } = page();
    const n = await news(user);
    const card = within((await n.findAllByTestId("learn-article")).find((c) => c.textContent?.includes("Crude oil slumps"))!);
    expect(card.queryByTestId("learn-summary")).not.toBeInTheDocument();
    expect(card.getByText(/gives no summary/)).toBeInTheDocument();
  });

  it("filters by topic and shows the counts", async () => {
    const { user } = page();
    const n = await news(user);
    await n.findAllByTestId("learn-article");
    await user.click(n.getByRole("button", { name: /FII \/ DII \(1\)/ }));
    const cards = n.getAllByTestId("learn-article");
    expect(cards).toHaveLength(1);
    expect(cards[0]).toHaveTextContent("FIIs sell");
    await user.click(n.getByRole("button", { name: /SEBI \(0\)/ }));
    expect(n.getByText("No articles match this topic right now.")).toBeInTheDocument();
  });

  it("refreshes from the server on demand", async () => {
    const { user, api } = page();
    const n = await news(user);
    await n.findAllByTestId("learn-article");
    expect(api.callsTo("GET", "/api/premarket/news")[0].query.get("refresh")).toBeNull();
    await user.click(n.getByRole("button", { name: "Refresh news" }));
    await waitFor(() => expect(api.callsTo("GET", "/api/premarket/news").some((c) => c.query.get("refresh") === "1")).toBe(true));
  });

  it("shows a loading state, then an error with a retry", async () => {
    let calls = 0;
    const api = mockApi().on("GET", "/api/premarket/news", () => (++calls === 1 ? fail("Feed service is down", 502, "RuntimeError") : makePmFeed()));
    const { user } = page(api);
    await user.click(nav().getByRole("button", { name: /Latest options/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Feed service is down");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect((await screen.findAllByTestId("learn-article")).length).toBeGreaterThan(0);
  });

  it("shows a loading message while the first answer is on its way", async () => {
    const api = mockApi().on("GET", "/api/premarket/news", () => new Promise(() => {}));
    const { user } = page(api);
    await user.click(nav().getByRole("button", { name: /Latest options/ }));
    expect(await screen.findByText("Fetching the latest news…")).toBeInTheDocument();
  });

  it("says live news is not connected instead of showing anything made up", async () => {
    const api = mockApi().on("GET", "/api/premarket/news", () => makePmFeed({ status: "unavailable", articles: [], fetched_at: null }));
    const { user } = page(api);
    await user.click(nav().getByRole("button", { name: /Latest options/ }));
    expect(await screen.findByText(/Live news is not connected right now/)).toBeInTheDocument();
    expect(screen.queryByTestId("learn-article")).not.toBeInTheDocument();
  });

  it("labels news from an earlier fetch as such", async () => {
    const api = mockApi().on("GET", "/api/premarket/news", () => makePmFeed({ status: "stale", fetched_at: "2026-11-19T07:00:00" }));
    const { user } = page(api);
    await user.click(nav().getByRole("button", { name: /Latest options/ }));
    expect(await screen.findByText(/could not be refreshed.*07:00 IST/s)).toBeInTheDocument();
  });

  it("shows Malayalam summaries (from the article's tags) when Malayalam is selected, and says the rest is not translated", async () => {
    const { user } = page();
    await toMl(user);
    await user.click(nav().getByRole("button", { name: /വാർത്തകൾ/ }));
    const n = within(await screen.findByTestId("learn-news"));
    const cards = await n.findAllByTestId("learn-article");
    const first = within(cards.find((c) => c.textContent?.includes("Wall Street rallies"))!);
    expect(first.getByTestId("learn-ml-summary")).toHaveTextContent("വിഷയം: യുഎസ് വിപണി");
    expect(first.getByTestId("learn-ml-summary")).toHaveTextContent("NIFTY-യിൽ സാധ്യതയുള്ള സ്വാധീനം");
    expect(first.getByText(/ഉറവിടം: Reuters/)).toBeInTheDocument();
    expect(first.getByRole("link", { name: /ഒറിജിനൽ ലേഖനം വായിക്കുക/ })).toHaveAttribute("href", "https://example.com/a");
    expect(n.getByText(/പരിഭാഷാ സേവനം ബന്ധിപ്പിക്കാത്തതിനാൽ/)).toBeInTheDocument();
    expect(n.getByRole("button", { name: /വാർത്തകൾ പുതുക്കുക/ })).toBeInTheDocument();
  });

  it("builds the Malayalam summary from the tags only", () => {
    const s = mlSummary(makePmArticle({ topic: "Crude Oil", sentiment: "negative", nifty_impact: "bearish", impact_level: "Low" }));
    expect(s).toBe("വിഷയം: ക്രൂഡ് ഓയിൽ. വാർത്തയുടെ സ്വഭാവം: നെഗറ്റീവ്. NIFTY-യിൽ സാധ്യതയുള്ള സ്വാധീനം: താഴ്ചയ്ക്ക് അനുകൂലം. സ്വാധീന തോത്: കുറവ്.");
  });
});
