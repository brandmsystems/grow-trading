import { useEffect, useRef } from "react";
import { createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { baseOptions, CHART_COLORS } from "./CandleChart";
import { chartTime } from "../../utils/format";
import type { RangeDay } from "../../types/api";

export type RangeView = "candles" | "range";

interface Props {
  days: RangeDay[];
  view: RangeView;
  dark: boolean;
  height?: number;
  /** Called with the day under the crosshair, or null when it leaves the chart. */
  onHover?: (day: RangeDay | null) => void;
}

const T = (d: RangeDay) => chartTime(d.date) as UTCTimestamp;
const AVG = [["avg10", "#3b82f6", "10-day average"], ["avg20", "#f97316", "20-day average"], ["avg50", "#a855f7", "50-day average"]] as const;
export const AVG_LEGEND = AVG.map(([key, color, label]) => ({ key, color, label }));

/**
 * Daily candles, or daily range bars (high minus low, in points) with the 10/20/50-day average range.
 * Green = the day closed above its open, red = below. Days with missing minutes or still in progress are drawn
 * lighter. Zoom (wheel / pinch) and pan (drag) are built in.
 */
export function RangeChart({ days, view, dark, height = 420, onHover }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<{ c?: ISeriesApi<"Candlestick">; h?: ISeriesApi<"Histogram">; avg: ISeriesApi<"Line">[] }>({ avg: [] });
  const byTime = useRef(new Map<number, RangeDay>());
  const hover = useRef(onHover);
  hover.current = onHover;
  const fitted = useRef("");

  useEffect(() => {
    if (!box.current) return;
    const k = CHART_COLORS(dark);
    const ch = createChart(box.current, { ...baseOptions(dark), timeScale: { ...baseOptions(dark).timeScale, timeVisible: false } });
    if (view === "candles") {
      series.current = { avg: [], c: ch.addCandlestickSeries({ upColor: k.up, downColor: k.down, borderUpColor: k.up, borderDownColor: k.down, wickUpColor: k.up, wickDownColor: k.down }) };
    } else {
      const h = ch.addHistogramSeries({ priceFormat: { type: "price", precision: 0, minMove: 1 }, priceLineVisible: false, lastValueVisible: false });
      const avg = AVG.map(([, color]) => ch.addLineSeries({ color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }));   // named in the legend under the chart, not on the axis
      series.current = { h, avg };
    }
    ch.subscribeCrosshairMove((p) => hover.current?.(p.time == null ? null : byTime.current.get(p.time as number) ?? null));
    chart.current = ch;
    fitted.current = "";
    return () => { ch.remove(); chart.current = null; series.current = { avg: [] }; };
  }, [dark, view]);

  useEffect(() => {
    const s = series.current;
    byTime.current = new Map(days.map((d) => [T(d), d]));
    const shade = (d: RangeDay, col: string, faint: string) => (d.status === "complete" ? col : faint);
    const up = (d: RangeDay) => d.close >= d.open;
    if (s.c) {
      s.c.setData(days.map((d) => {
        const col = up(d) ? CHART_COLORS(dark).up : CHART_COLORS(dark).down;
        const faint = up(d) ? "rgba(22,163,74,0.4)" : "rgba(220,38,38,0.4)";
        return { time: T(d), open: d.open, high: d.high, low: d.low, close: d.close,
          color: shade(d, col, faint), borderColor: shade(d, col, faint), wickColor: shade(d, col, faint) };
      }));
    }
    if (s.h) {
      s.h.setData(days.map((d) => ({ time: T(d), value: d.range,
        color: shade(d, up(d) ? CHART_COLORS(dark).up : CHART_COLORS(dark).down, up(d) ? "rgba(22,163,74,0.4)" : "rgba(220,38,38,0.4)") })));
      AVG.forEach(([key], i) => s.avg[i]?.setData(days.filter((d) => d[key] != null).map((d) => ({ time: T(d), value: d[key] as number }))));
    }
    const key = `${view}|${days[0]?.date ?? ""}|${days[days.length - 1]?.date ?? ""}`;
    if (days.length && fitted.current !== key) { chart.current?.timeScale().fitContent(); fitted.current = key; }
  }, [days, view, dark]);

  return <div ref={box} style={{ height }} className="w-full touch-pan-y" role="img"
    aria-label={view === "candles" ? "NIFTY daily candlestick chart" : "NIFTY daily range bar chart"} />;
}
