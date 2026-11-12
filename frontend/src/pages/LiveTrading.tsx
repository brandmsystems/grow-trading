import { useMemo } from "react";
import { CandlestickChart } from "lucide-react";
import { useLive } from "../context/LiveContext";
import { useSettings } from "../context/SettingsContext";
import { PremiumCard, SpotCard } from "../components/market/MarketCards";
import { RecommendationCard } from "../components/trading/RecommendationCard";
import { OrderCalculator } from "../components/trading/OrderCalculator";
import { EnginePanel } from "../components/trading/EnginePanel";
import { DailyRisk, RiskCalculator, usePaperAccount } from "../components/trading/RiskManagement";
import { PaperTrades } from "../components/trading/PaperTrades";
import { CandleChart, type ChartMarker, type PriceLevel } from "../components/charts/CandleChart";
import { AlertList } from "../components/layout/NotificationPanel";
import { Card } from "../components/common/Card";
import { Segmented } from "../components/common/Controls";
import { Loading, Warning } from "../components/common/States";
import { hm, num } from "../utils/format";

export default function LiveTrading() {
  const { data, trades, fresh } = useLive();
  const { settings, update } = useSettings();
  const running = data && data.state !== "stopped";
  const paper = (running ? data?.config?.trade_mode : settings.engine.trade_mode) === "paper";
  const tradeKey = `${trades.length}|${trades.filter((t) => t.status === "CLOSED").length}`;
  const account = usePaperAccount(tradeKey);

  // Engine entries/exits from today's trades, drawn on the chart.
  const markers = useMemo<ChartMarker[]>(() => trades.flatMap((t) => {
    const bull = t.direction === "Bullish";
    const out: ChartMarker[] = [];
    if (t.entry_ts) out.push({ ts: t.entry_ts, position: bull ? "belowBar" : "aboveBar", color: "#7c3aed", shape: "circle", text: `Entry ${t.opt_type}` });
    if (t.exit_ts) out.push({ ts: t.exit_ts, position: bull ? "aboveBar" : "belowBar", color: "#64748b", shape: "square", text: "Exit" });
    return out;
  }), [trades]);
  const levels = useMemo<PriceLevel[]>(() => {
    const rec = data?.feed?.signal?.rec;
    const p = data?.position;
    const out: PriceLevel[] = [];
    const stop = p?.stop_ref ?? (rec?.verified ? rec.nifty_stop : undefined);
    const target = p?.target_ref ?? (rec?.verified ? rec.nifty_target : undefined);
    if (stop != null) out.push({ price: stop, color: "#dc2626", title: "Stop" });
    if (target != null) out.push({ price: target, color: "#16a34a", title: "Target" });
    return out;
  }, [data?.feed?.signal?.rec, data?.position]);

  if (!data) return <Loading text="Connecting to the live feed…" className="h-[60vh]" />;
  const bars = data.feed?.chart?.bars ?? [];
  const tf = data.feed?.timeframe ?? settings.timeframe;

  return (
    <div className="space-y-4">
      {data.feed?.error && <Warning>Groww feed: {data.feed.error}</Warning>}
      {data.feed?.warnings?.map((w) => <Warning key={w}>{w}</Warning>)}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <SpotCard data={data} />
          <Card title={`NIFTY 50 · ${tf}-minute candles`} icon={<CandlestickChart size={16} className="text-blue-600" />}
            right={
              <div className="flex items-center gap-3">
                <span className="hidden text-xs sm:inline"><span className="text-blue-500">━ EMA 9</span> <span className="ml-1 text-orange-500">━ EMA 21</span></span>
                <Segmented value={tf} disabled={!!running} onChange={(v) => update({ timeframe: v })}
                  options={[5, 15, 30].map((t) => ({ value: t, label: `${t}m` }))} />
              </div>
            }>
            {bars.length ? (
              <CandleChart bars={bars} forming={data.feed.chart.forming} crosses={data.feed.crosses} markers={markers} levels={levels}
                dark={settings.theme === "dark"} height={430} />
            ) : (
              <div className="grid h-[430px] place-items-center text-sm text-slate-500">{data.feed?.bars_error ?? "No candles for today yet."}</div>
            )}
            <p className="mt-2 text-xs text-slate-500">
              Scroll or pinch to zoom, drag to pan. Arrows mark EMA crossovers; circles and squares mark engine entries and exits.
              {data.feed?.ema && <> Last closed bar {hm(data.feed.ema.bar_close)}: close {num(data.feed.ema.close)}.</>}
              {running && " Timeframe follows the running engine."}
            </p>
          </Card>
          <PremiumCard data={data} />
        </div>
        <div className="space-y-4">
          <RecommendationCard data={data} flash={!!fresh} />
          {paper ? <RiskCalculator data={data} acct={account.acct} /> : <OrderCalculator data={data} />}
          <EnginePanel />
        </div>
      </div>

      {paper && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          <DailyRisk acct={account.acct} err={account.err} reload={() => void account.reload()} />
          <div className="xl:col-span-2"><PaperTrades refreshKey={tradeKey} /></div>
        </div>
      )}

      <Card title="Notifications">
        <AlertList alerts={data.alerts ?? []} freshId={fresh?.id} limit={12} />
      </Card>
    </div>
  );
}
