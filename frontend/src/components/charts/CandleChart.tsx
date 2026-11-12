import { useEffect, useRef } from "react";
import {
  createChart, CrosshairMode, LineStyle, type IChartApi, type IPriceLine, type ISeriesApi, type SeriesMarker, type Time, type UTCTimestamp,
} from "lightweight-charts";
import type { Bar, Cross } from "../../types/api";
import { chartTime } from "../../utils/format";

export interface ChartMarker { ts: string; position: "aboveBar" | "belowBar" | "inBar"; color: string; shape: "arrowUp" | "arrowDown" | "circle" | "square"; text: string }
export interface PriceLevel { price: number; color: string; title: string }

interface Props {
  bars: Bar[];
  forming?: Bar | null;
  crosses?: Cross[];
  markers?: ChartMarker[];
  levels?: PriceLevel[];
  showEma?: boolean;
  showVwap?: boolean;      // basis-adjusted futures VWAP (bars[].vwap)
  showVolume?: boolean;    // futures volume histogram (bars[].v)
  panels?: boolean;        // RSI and MACD panels under the chart, time-synced
  dark: boolean;
  height?: number;
}

export const CHART_COLORS = (dark: boolean) => ({
  text: dark ? "#94a3b8" : "#475569", grid: dark ? "#1e293b" : "#eef2f7", border: dark ? "#334155" : "#cbd5e1",
  up: "#16a34a", down: "#dc2626", fast: "#3b82f6", slow: "#f97316",
});

export function baseOptions(dark: boolean) {
  const k = CHART_COLORS(dark);
  return {
    autoSize: true,
    layout: { background: { color: "transparent" }, textColor: k.text, fontFamily: "Inter, system-ui, sans-serif" },
    grid: { vertLines: { color: k.grid }, horzLines: { color: k.grid } },
    crosshair: { mode: CrosshairMode.Normal },
    timeScale: { timeVisible: true, secondsVisible: false, borderColor: k.border },
    rightPriceScale: { borderColor: k.border },
    handleScroll: true, handleScale: true,
  };
}

/** Candles + optional EMA 9/21 lines, crossover/trade markers and price levels. Zoom, pan and crosshair built in. */
export function CandleChart({ bars, forming, crosses = [], markers = [], levels = [], showEma = true, showVwap = false,
  showVolume = false, panels = false, dark, height = 380 }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const rsiBox = useRef<HTMLDivElement>(null);
  const macdBox = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const s = useRef<{ c: ISeriesApi<"Candlestick">; f: ISeriesApi<"Line">; sl: ISeriesApi<"Line">; vw: ISeriesApi<"Line">; vol: ISeriesApi<"Histogram"> } | null>(null);
  const sub = useRef<{ rsi?: ISeriesApi<"Line">; macd?: ISeriesApi<"Line">; sig?: ISeriesApi<"Line">; hist?: ISeriesApi<"Histogram">; charts: IChartApi[] }>({ charts: [] });
  const lines = useRef<IPriceLine[]>([]);
  const fitted = useRef("");

  useEffect(() => {
    if (!box.current) return;
    const k = CHART_COLORS(dark);
    const ch = createChart(box.current, baseOptions(dark));
    const c = ch.addCandlestickSeries({ upColor: k.up, downColor: k.down, borderUpColor: k.up, borderDownColor: k.down, wickUpColor: k.up, wickDownColor: k.down });
    const f = ch.addLineSeries({ color: k.fast, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title: "EMA 9" });
    const sl = ch.addLineSeries({ color: k.slow, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title: "EMA 21" });
    const vw = ch.addLineSeries({ color: "#a855f7", lineWidth: 1, lineStyle: LineStyle.Dotted, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title: "VWAP" });
    const vol = ch.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    ch.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    chart.current = ch;
    s.current = { c, f, sl, vw, vol };
    fitted.current = "";
    // RSI and MACD panels share the main chart's visible range.
    const subCharts: IChartApi[] = [];
    if (panels && rsiBox.current && macdBox.current) {
      const opts = { ...baseOptions(dark), timeScale: { ...baseOptions(dark).timeScale, visible: false }, handleScroll: false, handleScale: false };
      const rc = createChart(rsiBox.current, opts);
      const rsi = rc.addLineSeries({ color: "#0ea5e9", lineWidth: 2, priceLineVisible: false, title: "RSI 14" });
      rsi.createPriceLine({ price: 70, color: "#dc2626", lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: "" });
      rsi.createPriceLine({ price: 50, color: "#64748b", lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: "" });
      rsi.createPriceLine({ price: 30, color: "#16a34a", lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: "" });
      const mc = createChart(macdBox.current, opts);
      const hist = mc.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
      const macd = mc.addLineSeries({ color: "#3b82f6", lineWidth: 1, priceLineVisible: false, title: "MACD" });
      const sig = mc.addLineSeries({ color: "#f97316", lineWidth: 1, priceLineVisible: false, title: "Signal" });
      subCharts.push(rc, mc);
      sub.current = { rsi, macd, sig, hist, charts: subCharts };
      ch.timeScale().subscribeVisibleLogicalRangeChange((r) => { if (r) subCharts.forEach((x) => x.timeScale().setVisibleLogicalRange(r)); });
    } else {
      sub.current = { charts: [] };
    }
    return () => { subCharts.forEach((x) => x.remove()); ch.remove(); chart.current = null; s.current = null; lines.current = []; sub.current = { charts: [] }; };
  }, [dark, panels]);

  useEffect(() => {
    const sr = s.current;
    if (!sr) return;
    const all = forming ? [...bars, forming] : bars;
    sr.c.setData(all.map((b) => ({ time: chartTime(b.t) as UTCTimestamp, open: b.o, high: b.h, low: b.l, close: b.c })));
    const ema = showEma && bars.length && bars[0].e9 != null;
    sr.f.setData(ema ? bars.map((b) => ({ time: chartTime(b.t) as UTCTimestamp, value: b.e9! })) : []);
    sr.sl.setData(ema ? bars.map((b) => ({ time: chartTime(b.t) as UTCTimestamp, value: b.e21! })) : []);
    const T = (b: Bar) => chartTime(b.t) as UTCTimestamp;
    sr.vw.setData(showVwap ? bars.filter((b) => b.vwap != null).map((b) => ({ time: T(b), value: b.vwap! })) : []);
    sr.vol.setData(showVolume ? bars.filter((b) => b.v != null).map((b) => ({ time: T(b), value: b.v!, color: b.c >= b.o ? "rgba(22,163,74,0.35)" : "rgba(220,38,38,0.35)" })) : []);
    const sb = sub.current;
    if (sb.rsi) {
      sb.rsi.setData(bars.filter((b) => b.rsi != null).map((b) => ({ time: T(b), value: b.rsi! })));
      sb.macd!.setData(bars.filter((b) => b.macd != null).map((b) => ({ time: T(b), value: b.macd! })));
      sb.sig!.setData(bars.filter((b) => b.macd_signal != null).map((b) => ({ time: T(b), value: b.macd_signal! })));
      sb.hist!.setData(bars.filter((b) => b.macd_hist != null).map((b) => ({ time: T(b), value: b.macd_hist!, color: b.macd_hist! >= 0 ? "rgba(22,163,74,0.6)" : "rgba(220,38,38,0.6)" })));
      const r = chart.current?.timeScale().getVisibleLogicalRange();
      if (r) sb.charts.forEach((x) => x.timeScale().setVisibleLogicalRange(r));
    }

    // A cross is reported at its bar's close: mark the bar that produced it.
    const starts = all.map((b) => chartTime(b.t));
    const barFor = (iso: string, before = false) => {
      const ts = chartTime(iso);
      let pick: number | undefined;
      for (const st of starts) if (before ? st < ts : st <= ts) pick = st;
      return pick;
    };
    const m: SeriesMarker<Time>[] = [];
    for (const x of crosses) {
      const t = barFor(x.ts, true);
      if (t != null) m.push({ time: t as UTCTimestamp, position: x.direction > 0 ? "belowBar" : "aboveBar", color: x.direction > 0 ? "#16a34a" : "#dc2626",
        shape: x.direction > 0 ? "arrowUp" : "arrowDown", text: x.direction > 0 ? "9/21 ↑" : "9/21 ↓" });
    }
    for (const x of markers) {
      const t = barFor(x.ts);
      if (t != null) m.push({ time: t as UTCTimestamp, position: x.position, color: x.color, shape: x.shape, text: x.text });
    }
    m.sort((a, b) => (a.time as number) - (b.time as number));
    sr.c.setMarkers(m);

    lines.current.forEach((l) => sr.c.removePriceLine(l));
    lines.current = levels.map((l) => sr.c.createPriceLine({ price: l.price, color: l.color, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: l.title }));

    const key = `${bars[0]?.t ?? ""}|${bars.length > 0 ? bars[bars.length - 1].t.slice(0, 10) : ""}`;
    if (bars.length && fitted.current !== key) { chart.current?.timeScale().fitContent(); fitted.current = key; }
  }, [bars, forming, crosses, markers, levels, showEma, showVwap, showVolume, panels]);

  return (
    <div>
      <div ref={box} style={{ height }} className="w-full touch-pan-y" aria-label="NIFTY candlestick chart" />
      {panels && (
        <>
          <div className="mt-1 text-[11px] text-slate-500">RSI 14 (30 / 50 / 70)</div>
          <div ref={rsiBox} style={{ height: 90 }} className="w-full" aria-label="RSI panel" />
          <div className="mt-1 text-[11px] text-slate-500">MACD 12/26/9 · histogram, <span className="text-blue-500">MACD</span>, <span className="text-orange-500">signal</span></div>
          <div ref={macdBox} style={{ height: 100 }} className="w-full" aria-label="MACD panel" />
        </>
      )}
    </div>
  );
}
