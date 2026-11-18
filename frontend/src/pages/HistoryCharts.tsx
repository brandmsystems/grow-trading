import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ChevronLeft, ChevronRight, CandlestickChart } from "lucide-react";
import { useSettings } from "../context/SettingsContext";
import { useApi } from "../hooks/useApi";
import { getCandles, getDataOverview } from "../services/api";
import { Card, Stat } from "../components/common/Card";
import { Button, Field, inputCls, PageHeader, Segmented } from "../components/common/Controls";
import { Empty, ErrorNote, Limitation, Loading } from "../components/common/States";
import { CandleChart } from "../components/charts/CandleChart";
import { dmy, num } from "../utils/format";
import type { Bar } from "../types/api";

const shift = (d: string, n: number) => { const x = new Date(d + "T00:00:00Z"); x.setUTCDate(x.getUTCDate() + n); return x.toISOString().slice(0, 10); };
const span = (a: string, b: string) => Math.round((Date.parse(b) - Date.parse(a)) / 864e5) + 1;

/** EMA for display on the loaded range only (adjust=False, same formula as the backend). */
function withEma(bars: { t: string; o: number; h: number; l: number; c: number }[]): Bar[] {
  const k9 = 2 / 10, k21 = 2 / 22;
  let e9 = 0, e21 = 0;
  return bars.map((b, i) => {
    e9 = i ? b.c * k9 + e9 * (1 - k9) : b.c;
    e21 = i ? b.c * k21 + e21 * (1 - k21) : b.c;
    return { ...b, e9: Math.round(e9 * 100) / 100, e21: Math.round(e21 * 100) / 100 };
  });
}

export default function HistoryCharts() {
  const { settings } = useSettings();
  const [q, setQ] = useSearchParams();
  const ov = useApi(getDataOverview, []);
  const last = ov.data?.coverage.summary.last?.slice(0, 10) ?? null;
  const [to, setTo] = useState(q.get("to") ?? "");
  const [from, setFrom] = useState(q.get("from") ?? "");
  const [tf, setTf] = useState(Number(q.get("tf") ?? 5));
  const [ema, setEma] = useState(true);
  useEffect(() => { if (last && !to) { setTo(last); setFrom(shift(last, -6)); } }, [last, to]);
  const candles = useApi(() => (from && to ? getCandles(from, to, tf) : Promise.resolve({ bars: [] })), [from, to, tf]);
  // Keep the address in step with the chart. Skip it when it already matches: setQ changes identity with
  // every URL change, so an unconditional update re-navigates (and can cancel a click on another page's link).
  useEffect(() => {
    if (!from || !to) return;
    if (q.get("from") === from && q.get("to") === to && q.get("tf") === String(tf)) return;
    setQ({ from, to, tf: String(tf) }, { replace: true });
  }, [from, to, tf, q, setQ]);
  const bars = useMemo(() => withEma(candles.data?.bars ?? []), [candles.data]);
  const move = (dir: number) => { const n = span(from, to); setFrom(shift(from, dir * n)); setTo(shift(to, dir * n)); };
  const lastBar = bars[bars.length - 1];

  if (ov.loading && !ov.data) return <Loading />;
  if (ov.data && !last) return <Empty title="No stored NIFTY data">Download history on the Market Data page first.</Empty>;

  return (
    <div className="space-y-4">
      <PageHeader title="Historical Charts" subtitle="Stored candles from the database. Nothing is fetched live here." />
      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Instrument" className="w-44"><select className={inputCls} disabled><option>NIFTY 50 (spot)</option></select></Field>
          <Field label="From" className="w-40"><input type="date" className={inputCls} value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
          <Field label="To" className="w-40"><input type="date" className={inputCls} value={to} onChange={(e) => setTo(e.target.value)} /></Field>
          <Field label="Timeframe"><Segmented value={tf} onChange={setTf} options={[1, 5, 15, 30].map((t) => ({ value: t, label: `${t}m` }))} /></Field>
          <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" checked={ema} onChange={(e) => setEma(e.target.checked)} /> EMA 9 / 21</label>
          <div className="ml-auto flex gap-2">
            <Button onClick={() => move(-1)} title="Earlier"><ChevronLeft size={16} /> Earlier</Button>
            <Button onClick={() => move(1)} title="Later">Later <ChevronRight size={16} /></Button>
            <Button onClick={() => { if (last) { setTo(last); setFrom(shift(last, -6)); } }}>Latest</Button>
          </div>
        </div>
      </Card>
      <Card title={`NIFTY 50 · ${tf}-minute · ${dmy(from)} → ${dmy(to)}`} icon={<CandlestickChart size={16} className="text-blue-600" />}
        right={lastBar ? `O ${num(lastBar.o)} H ${num(lastBar.h)} L ${num(lastBar.l)} C ${num(lastBar.c)}` : undefined}>
        {candles.error ? <ErrorNote>{candles.error}</ErrorNote> : candles.loading && !bars.length ? <Loading className="h-[480px]" />
          : !bars.length ? <Empty title="No candles in this range">It may be a holiday or not downloaded yet.</Empty>
          : <CandleChart bars={bars} showEma={ema} dark={settings.theme === "dark"} height={480} />}
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Bars" value={bars.length} />
          <Stat label="Range high" value={bars.length ? num(Math.max(...bars.map((b) => b.h))) : "—"} />
          <Stat label="Range low" value={bars.length ? num(Math.min(...bars.map((b) => b.l))) : "—"} />
          <Stat label="Last close" value={num(lastBar?.c)} />
        </div>
      </Card>
      <Limitation>Only NIFTY spot is available here: the candles endpoint serves NIFTY only. The EMAs are calculated in the browser on the loaded range (same formula as the strategy), so the first bars differ slightly from the strategy's EMAs, which carry over from earlier days.</Limitation>
    </div>
  );
}
