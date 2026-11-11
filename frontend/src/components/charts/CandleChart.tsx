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
export function CandleChart({ bars, forming, crosses = [], markers = [], levels = [], showEma = true, dark, height = 380 }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const s = useRef<{ c: ISeriesApi<"Candlestick">; f: ISeriesApi<"Line">; sl: ISeriesApi<"Line"> } | null>(null);
  const lines = useRef<IPriceLine[]>([]);
  const fitted = useRef("");

  useEffect(() => {
    if (!box.current) return;
    const k = CHART_COLORS(dark);
    const ch = createChart(box.current, baseOptions(dark));
    const c = ch.addCandlestickSeries({ upColor: k.up, downColor: k.down, borderUpColor: k.up, borderDownColor: k.down, wickUpColor: k.up, wickDownColor: k.down });
    const f = ch.addLineSeries({ color: k.fast, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title: "EMA 9" });
    const sl = ch.addLineSeries({ color: k.slow, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title: "EMA 21" });
    chart.current = ch;
    s.current = { c, f, sl };
    fitted.current = "";
    return () => { ch.remove(); chart.current = null; s.current = null; lines.current = []; };
  }, [dark]);

  useEffect(() => {
    const sr = s.current;
    if (!sr) return;
    const all = forming ? [...bars, forming] : bars;
    sr.c.setData(all.map((b) => ({ time: chartTime(b.t) as UTCTimestamp, open: b.o, high: b.h, low: b.l, close: b.c })));
    const ema = showEma && bars.length && bars[0].e9 != null;
    sr.f.setData(ema ? bars.map((b) => ({ time: chartTime(b.t) as UTCTimestamp, value: b.e9! })) : []);
    sr.sl.setData(ema ? bars.map((b) => ({ time: chartTime(b.t) as UTCTimestamp, value: b.e21! })) : []);

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
        shape: x.direction > 0 ? "arrowUp" : "arrowDown", text: x.direction > 0 ? "Buy CE" : "Buy PE" });
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
  }, [bars, forming, crosses, markers, levels, showEma]);

  return <div ref={box} style={{ height }} className="w-full touch-pan-y" aria-label="NIFTY candlestick chart" />;
}
