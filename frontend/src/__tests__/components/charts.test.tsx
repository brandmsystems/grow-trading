import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CandleChart, type ChartMarker, type PriceLevel } from "../../components/charts/CandleChart";
import { BarsChart, LineChart } from "../../components/charts/SeriesChart";
import { charts, liveCharts, seriesOf, type FakeChart } from "../../test/fakeCharts";
import { at, makeBars } from "../../test/fixtures";
import { chartTime } from "../../utils/format";
import type { Bar, Cross } from "../../types/api";

const byTitle = (c: FakeChart, title: string) => c.series.find((s) => s.options.title === title)!;
const candles = (c: FakeChart) => seriesOf(c, "candlestick")[0];

describe("CandleChart", () => {
  const bars = makeBars(6);

  it("draws the bars as candles with real OHLC values at their start time", () => {
    render(<CandleChart bars={bars} dark />);
    const c = liveCharts()[0];
    expect(candles(c).data).toHaveLength(6);
    expect(candles(c).data[0]).toEqual({ time: chartTime(bars[0].t), open: bars[0].o, high: bars[0].h, low: bars[0].l, close: bars[0].c });
    expect(candles(c).data[5]).toMatchObject({ time: chartTime(bars[5].t), close: bars[5].c });
  });

  it("appends the forming bar to the candles only (it has no indicators)", () => {
    const forming: Bar = { t: at("09:45"), o: 25000, h: 25010, l: 24995, c: 25005 };
    render(<CandleChart bars={bars} forming={forming} dark />);
    const c = liveCharts()[0];
    expect(candles(c).data).toHaveLength(7);
    expect(candles(c).data[6]).toMatchObject({ time: chartTime(forming.t), close: 25005 });
    expect(byTitle(c, "EMA 9").data).toHaveLength(6);
  });

  it("plots EMA 9 and EMA 21 from the bars, and nothing when EMAs are switched off or missing", () => {
    const { rerender } = render(<CandleChart bars={bars} dark />);
    const c = liveCharts()[0];
    expect(byTitle(c, "EMA 9").data.map((d) => d.value)).toEqual(bars.map((b) => b.e9));
    expect(byTitle(c, "EMA 21").data.map((d) => d.value)).toEqual(bars.map((b) => b.e21));
    rerender(<CandleChart bars={bars} showEma={false} dark />);
    expect(byTitle(liveCharts()[0], "EMA 9").data).toEqual([]);
    rerender(<CandleChart bars={bars.map(({ e9: _a, e21: _b, ...rest }) => rest)} dark />);
    expect(byTitle(liveCharts()[0], "EMA 21").data).toEqual([]);
  });

  it("shows VWAP and volume only when asked, and colours volume by candle direction", () => {
    const mixed = makeBars(2).map((b, i) => (i === 1 ? { ...b, o: b.c + 5 } : b));      // second candle closes down
    const { rerender } = render(<CandleChart bars={mixed} dark />);
    expect(byTitle(liveCharts()[0], "VWAP").data).toEqual([]);
    expect(seriesOf(liveCharts()[0], "histogram")[0].data).toEqual([]);
    rerender(<CandleChart bars={mixed} showVwap showVolume dark />);
    const c = liveCharts()[0];
    expect(byTitle(c, "VWAP").data.map((d) => d.value)).toEqual(mixed.map((b) => b.vwap));
    const vol = seriesOf(c, "histogram")[0].data;
    expect(vol.map((d) => d.value)).toEqual(mixed.map((b) => b.v));
    expect(vol[0].color).toContain("22,163,74");          // up: green
    expect(vol[1].color).toContain("220,38,38");          // down: red
  });

  it("marks each crossover on the bar that produced it, with the direction arrow", () => {
    const crosses: Cross[] = [{ ts: at("09:40"), direction: 1, close: 25000 }, { ts: at("09:25"), direction: -1, close: 24990 }];
    render(<CandleChart bars={bars} crosses={crosses} dark />);
    const m = candles(liveCharts()[0]).markers;
    expect(m.map((x) => x.text)).toEqual(["9/21 ↓", "9/21 ↑"]);                // sorted by time, not input order
    expect(m[1]).toMatchObject({ position: "belowBar", shape: "arrowUp", color: "#16a34a", time: chartTime(at("09:35")) });   // the bar before the 09:40 close
    expect(m[0]).toMatchObject({ position: "aboveBar", shape: "arrowDown", color: "#dc2626", time: chartTime(at("09:20")) });
  });

  it("places trade markers on the bar containing their time", () => {
    const markers: ChartMarker[] = [{ ts: at("09:32"), position: "belowBar", color: "#7c3aed", shape: "circle", text: "Entry CE" }];
    render(<CandleChart bars={bars} markers={markers} dark />);
    expect(candles(liveCharts()[0]).markers).toEqual([{ time: chartTime(at("09:30")), position: "belowBar", color: "#7c3aed", shape: "circle", text: "Entry CE" }]);
  });

  it("ignores markers that happened before the first bar", () => {
    render(<CandleChart bars={bars} markers={[{ ts: at("08:00"), position: "aboveBar", color: "#000", shape: "square", text: "early" }]} dark />);
    expect(candles(liveCharts()[0]).markers).toEqual([]);
  });

  it("draws price levels and replaces them when they change", () => {
    const l1: PriceLevel[] = [{ price: 24950, color: "#dc2626", title: "Stop" }, { price: 25100, color: "#16a34a", title: "Target" }];
    const { rerender } = render(<CandleChart bars={bars} levels={l1} dark />);
    const s = candles(liveCharts()[0]);
    expect(s.priceLines.map((l) => [l.title, l.price])).toEqual([["Stop", 24950], ["Target", 25100]]);
    rerender(<CandleChart bars={bars} levels={[{ price: 25200, color: "#000", title: "New" }]} dark />);
    expect(s.removedLines).toBe(2);
    expect(s.priceLines.at(-1)).toMatchObject({ title: "New", price: 25200 });
  });

  it("adds time-synced RSI and MACD panels only when asked", () => {
    const { rerender } = render(<CandleChart bars={bars.map((b, i) => ({ ...b, rsi: 50 + i, macd: i, macd_signal: i / 2, macd_hist: i - 2 }))} dark />);
    expect(liveCharts()).toHaveLength(1);
    rerender(<CandleChart bars={bars.map((b, i) => ({ ...b, rsi: 50 + i, macd: i, macd_signal: i / 2, macd_hist: i - 2 }))} panels dark />);
    expect(liveCharts()).toHaveLength(3);                          // main + RSI + MACD
    const [, rsi, macd] = liveCharts();
    expect(byTitle(rsi, "RSI 14").data.map((d) => d.value)).toEqual([50, 51, 52, 53, 54, 55]);
    expect(rsi.series[0].priceLines.map((l) => l.price)).toEqual([70, 50, 30]);
    expect(byTitle(macd, "MACD").data).toHaveLength(6);
    const hist = seriesOf(macd, "histogram")[0].data;
    expect(hist[0].color).toContain("220,38,38");                  // negative histogram: red
    expect(hist[5].color).toContain("22,163,74");                  // positive: green
  });

  it("removes its charts when unmounted and rebuilds them when the theme changes", () => {
    const { rerender, unmount } = render(<CandleChart bars={bars} dark />);
    expect(charts).toHaveLength(1);
    rerender(<CandleChart bars={bars} dark={false} />);
    expect(charts).toHaveLength(2);
    expect(charts[0].removed).toBe(true);
    expect(charts[1].removed).toBe(false);
    unmount();
    expect(liveCharts()).toHaveLength(0);
  });

  it("fits the view once per day/range, not on every refresh (so the user's zoom survives live updates)", () => {
    const { rerender } = render(<CandleChart bars={bars} dark />);
    const c = liveCharts()[0];
    expect(c.fitted).toBe(1);
    rerender(<CandleChart bars={[...bars]} forming={{ t: at("09:45"), o: 1, h: 2, l: 0, c: 1 }} dark />);
    expect(c.fitted).toBe(1);
    rerender(<CandleChart bars={makeBars(3, 9 * 60 + 15).map((b) => ({ ...b, t: b.t.replace("2026-11-18", "2026-11-19") }))} dark />);
    expect(c.fitted).toBe(2);
  });

  it("is labelled for assistive technology", () => {
    const { getByLabelText } = render(<CandleChart bars={bars} panels dark />);
    expect(getByLabelText("NIFTY candlestick chart")).toBeInTheDocument();
    expect(getByLabelText("RSI panel")).toBeInTheDocument();
    expect(getByLabelText("MACD panel")).toBeInTheDocument();
  });
});

describe("LineChart and BarsChart", () => {
  it("LineChart draws one titled, coloured line per series", () => {
    render(<LineChart dark series={[
      { name: "ATM buy", color: "#2563eb", data: [{ time: "2026-10-05", value: 100 }, { time: "2026-10-06", value: 250 }] },
      { name: "ATM sell", color: "#ea580c", data: [{ time: "2026-10-05", value: -50 }] },
    ]} />);
    const c = liveCharts()[0];
    expect(c.series.map((s) => [s.options.title, s.options.color])).toEqual([["ATM buy", "#2563eb"], ["ATM sell", "#ea580c"]]);
    expect(c.series[0].data).toEqual([{ time: "2026-10-05", value: 100 }, { time: "2026-10-06", value: 250 }]);
    expect(c.fitted).toBe(1);
  });

  it("LineChart formats the price axis in rupees", () => {
    render(<LineChart dark series={[]} />);
    const fmt = (liveCharts()[0].options.localization as { priceFormatter: (v: number) => string }).priceFormatter;
    expect(fmt(180326)).toBe("₹1.80L");
    expect(fmt(-2500)).toBe("−₹2,500");
  });

  it("BarsChart colours gains green and losses red", () => {
    render(<BarsChart dark data={[{ time: "2026-10-01", value: 500 }, { time: "2026-11-01", value: -300 }]} />);
    const h = seriesOf(liveCharts()[0], "histogram")[0].data;
    expect(h.map((d) => [d.value, d.color])).toEqual([[500, "#16a34a"], [-300, "#dc2626"]]);
  });
});
