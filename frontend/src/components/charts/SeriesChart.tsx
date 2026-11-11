import { useEffect, useRef } from "react";
import { createChart, type IChartApi, type Time } from "lightweight-charts";
import { baseOptions } from "./CandleChart";
import { inrShort } from "../../utils/format";

export interface Series { name: string; color: string; data: { time: string; value: number }[] }

const rupees = { priceFormatter: (v: number) => inrShort(v, false).replace("₹-", "−₹") };

/** One or more line series (equity curves). Times are "YYYY-MM-DD" business days. */
export function LineChart({ series, dark, height = 280 }: { series: Series[]; dark: boolean; height?: number }) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  useEffect(() => {
    if (!box.current) return;
    const ch = createChart(box.current, { ...baseOptions(dark), timeScale: { ...baseOptions(dark).timeScale, timeVisible: false }, localization: rupees });
    chart.current = ch;
    return () => { ch.remove(); chart.current = null; };
  }, [dark]);
  useEffect(() => {
    const ch = chart.current;
    if (!ch) return;
    const made = series.map((s) => {
      const l = ch.addLineSeries({ color: s.color, lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title: s.name });
      l.setData(s.data.map((d) => ({ time: d.time as Time, value: d.value })));
      return l;
    });
    ch.timeScale().fitContent();
    return () => { made.forEach((l) => { try { ch.removeSeries(l); } catch { /* chart already removed */ } }); };
  }, [series, dark]);
  return <div ref={box} style={{ height }} className="w-full" />;
}

/** Green/red bars, e.g. monthly P&L. */
export function BarsChart({ data, dark, height = 240 }: { data: { time: string; value: number }[]; dark: boolean; height?: number }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!box.current) return;
    const ch = createChart(box.current, { ...baseOptions(dark), timeScale: { ...baseOptions(dark).timeScale, timeVisible: false }, localization: rupees });
    const h = ch.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
    h.setData(data.map((d) => ({ time: d.time as Time, value: d.value, color: d.value >= 0 ? "#16a34a" : "#dc2626" })));
    ch.timeScale().fitContent();
    return () => ch.remove();
  }, [data, dark]);
  return <div ref={box} style={{ height }} className="w-full" />;
}
