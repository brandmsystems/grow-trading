/** Records what the app draws with lightweight-charts, so tests can assert on data, markers and levels. */
import { vi } from "vitest";

export interface FakeSeries {
  kind: "candlestick" | "line" | "histogram";
  options: Record<string, unknown>;
  data: { time: number | string; [k: string]: unknown }[];
  markers: { time: number; position: string; shape: string; text: string; color: string }[];
  /** Lines currently on the chart (removed ones are taken out). */
  priceLines: { price: number; title: string; color: string }[];
  removedLines: number;
}
export interface FakeChart {
  options: Record<string, unknown>;
  series: FakeSeries[];
  removed: boolean;
  fitted: number;
}

export const charts: FakeChart[] = [];
export const resetCharts = () => { charts.length = 0; };
export const liveCharts = () => charts.filter((c) => !c.removed);
export const seriesOf = (c: FakeChart, kind: FakeSeries["kind"]) => c.series.filter((s) => s.kind === kind);

function makeSeries(chart: FakeChart, kind: FakeSeries["kind"], options: Record<string, unknown> = {}) {
  const s: FakeSeries = { kind, options, data: [], markers: [], priceLines: [], removedLines: 0 };
  chart.series.push(s);
  return {
    setData: vi.fn((d: FakeSeries["data"]) => { s.data = d; }),
    setMarkers: vi.fn((m: FakeSeries["markers"]) => { s.markers = m; }),
    createPriceLine: vi.fn((l: { price: number; title: string; color: string }) => { s.priceLines.push(l); return l; }),
    removePriceLine: vi.fn((l: unknown) => { const i = s.priceLines.indexOf(l as FakeSeries["priceLines"][number]); if (i >= 0) s.priceLines.splice(i, 1); s.removedLines += 1; }),
    __series: s,
  };
}

export function fakeCreateChart(_el: unknown, options: Record<string, unknown> = {}) {
  const chart: FakeChart = { options, series: [], removed: false, fitted: 0 };
  charts.push(chart);
  return {
    addCandlestickSeries: (o?: Record<string, unknown>) => makeSeries(chart, "candlestick", o),
    addLineSeries: (o?: Record<string, unknown>) => makeSeries(chart, "line", o),
    addHistogramSeries: (o?: Record<string, unknown>) => makeSeries(chart, "histogram", o),
    removeSeries: vi.fn(),
    priceScale: () => ({ applyOptions: vi.fn() }),
    timeScale: () => ({
      fitContent: vi.fn(() => { chart.fitted += 1; }),
      subscribeVisibleLogicalRangeChange: vi.fn(),
      setVisibleLogicalRange: vi.fn(),
      getVisibleLogicalRange: vi.fn(() => null),
    }),
    remove: vi.fn(() => { chart.removed = true; }),
  };
}
