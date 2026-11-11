import { useEffect, useRef } from "react";
import {
  createChart, CrosshairMode, type IChartApi, type ISeriesApi, type SeriesMarker, type Time, type UTCTimestamp,
} from "lightweight-charts";
import type { Bar } from "../../types/api";
import { chartTime } from "../../utils/format";

interface Props {
  bars: Bar[];
  forming?: Bar | null;
  crosses?: { ts: string; direction: number }[];
  dark: boolean;
  height?: number;
}

const COLORS = (dark: boolean) => ({
  text: dark ? "#94a3b8" : "#475569",
  grid: dark ? "#1e293b" : "#e2e8f0",
  up: "#16a34a", down: "#dc2626", fast: "#3b82f6", slow: "#f97316",
});

/** NIFTY candles with EMA fast/slow lines and crossover markers (TradingView Lightweight Charts 4). */
export function CandleChart({ bars, forming, crosses = [], dark, height = 360 }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<{ c: ISeriesApi<"Candlestick">; f: ISeriesApi<"Line">; s: ISeriesApi<"Line"> } | null>(null);
  const fitted = useRef<string>("");

  useEffect(() => {
    if (!box.current) return;
    const k = COLORS(dark);
    const ch = createChart(box.current, {
      autoSize: true,
      layout: { background: { color: "transparent" }, textColor: k.text, fontFamily: "Inter, system-ui, sans-serif" },
      grid: { vertLines: { color: k.grid }, horzLines: { color: k.grid } },
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: k.grid },
      rightPriceScale: { borderColor: k.grid },
    });
    const c = ch.addCandlestickSeries({ upColor: k.up, downColor: k.down, borderUpColor: k.up, borderDownColor: k.down, wickUpColor: k.up, wickDownColor: k.down });
    const f = ch.addLineSeries({ color: k.fast, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    const s = ch.addLineSeries({ color: k.slow, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    chart.current = ch;
    series.current = { c, f, s };
    fitted.current = "";
    return () => { ch.remove(); chart.current = null; series.current = null; };
  }, [dark]);

  useEffect(() => {
    const sr = series.current;
    if (!sr) return;
    const all = forming ? [...bars, forming] : bars;
    sr.c.setData(all.map((b) => ({ time: chartTime(b.t) as UTCTimestamp, open: b.o, high: b.h, low: b.l, close: b.c })));
    sr.f.setData(bars.map((b) => ({ time: chartTime(b.t) as UTCTimestamp, value: b.e9 })));
    sr.s.setData(bars.map((b) => ({ time: chartTime(b.t) as UTCTimestamp, value: b.e21 })));
    // A cross is reported at its bar's close; mark the bar that produced it.
    const starts = bars.map((b) => chartTime(b.t));
    const markers: SeriesMarker<Time>[] = crosses.flatMap((x) => {
      const ts = chartTime(x.ts);
      const bar = [...starts].reverse().find((s) => s < ts);
      return bar ? [{
        time: bar as UTCTimestamp,
        position: x.direction > 0 ? "belowBar" : "aboveBar",
        color: x.direction > 0 ? "#16a34a" : "#dc2626",
        shape: x.direction > 0 ? "arrowUp" : "arrowDown",
        text: x.direction > 0 ? "Bull cross" : "Bear cross",
      } as SeriesMarker<Time>] : [];
    });
    sr.c.setMarkers(markers);
    const day = bars[0]?.t.slice(0, 10) ?? "";
    if (day && fitted.current !== day) { chart.current?.timeScale().fitContent(); fitted.current = day; }
  }, [bars, forming, crosses]);

  return <div ref={box} style={{ height }} className="w-full" aria-label="NIFTY candlestick chart with EMA 9 and EMA 21" />;
}
