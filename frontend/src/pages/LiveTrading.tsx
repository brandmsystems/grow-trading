import { useMemo, useState } from "react";
import { CandlestickChart } from "lucide-react";
import { useLive } from "../context/LiveContext";
import { useSettings } from "../context/SettingsContext";
import { PremiumCard, SpotCard } from "../components/market/MarketCards";
import { PatternsCard, TradingPlanCard } from "../components/market/TradingPlan";
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

const ACTION_MARK: Record<string, Pick<ChartMarker, "color" | "shape" | "position">> = {
  "BUY CE": { color: "#16a34a", shape: "arrowUp", position: "belowBar" },
  "BUY PE": { color: "#dc2626", shape: "arrowDown", position: "aboveBar" },
  EXIT: { color: "#64748b", shape: "square", position: "aboveBar" },
  HOLD: { color: "#94a3b8", shape: "circle", position: "aboveBar" },
};

export default function LiveTrading() {
  const { data, trades, fresh } = useLive();
  const { settings, update } = useSettings();
  const [show, setShow] = useState({ vwap: true, volume: true, panels: false, levels: true });
  const running = data && data.state !== "stopped";
  const paper = (running ? data?.config?.trade_mode : settings.engine.trade_mode) === "paper";
  const tradeKey = `${trades.length}|${trades.filter((t) => t.status === "CLOSED").length}`;
  const account = usePaperAccount(tradeKey);

  // Strategy calls (BUY CE / BUY PE / EXIT / HOLD) and the engine's own fills, drawn on the chart.
  const markers = useMemo<ChartMarker[]>(() => {
    const calls = (data?.feed?.markers ?? []).map((m) => ({ ts: m.ts, text: m.action, ...ACTION_MARK[m.action] }));
    const fills = trades.flatMap((t) => {
      const out: ChartMarker[] = [];
      if (t.entry_ts) out.push({ ts: t.entry_ts, position: t.direction === "Bullish" ? "belowBar" : "aboveBar", color: "#7c3aed", shape: "circle", text: `Entry ${t.opt_type}` });
      if (t.exit_ts) out.push({ ts: t.exit_ts, position: "aboveBar", color: "#64748b", shape: "square", text: `Exit${t.exit_reason === "stop_loss" ? " (stop)" : ""}` });
      return out;
    });
    return [...calls, ...fills];
  }, [data?.feed?.markers, trades]);
  const levels = useMemo<PriceLevel[]>(() => {
    const rec = data?.feed?.signal?.rec;
    const p = data?.position;
    const out: PriceLevel[] = [];
    const stop = p?.nifty_stop ?? p?.stop_ref ?? (rec?.verified ? rec.nifty_stop : undefined);
    const target = p?.nifty_target ?? p?.target_ref ?? (rec?.verified ? rec.nifty_target : undefined);
    const sig = data?.feed?.signal;
    if (sig && sig.action !== "HOLD" && sig.nifty) out.push({ price: sig.nifty, color: "#7c3aed", title: "Entry ref" });
    if (stop != null) out.push({ price: stop, color: "#dc2626", title: p?.stop_premium != null ? `Stop ₹${num(p.stop_premium)}` : "Stop" });
    if (target != null) out.push({ price: target, color: "#16a34a", title: p?.target_premium != null ? `Target ₹${num(p.target_premium)}` : "Target" });
    if (show.levels) {
      for (const l of data?.feed?.plan?.levels ?? []) {
        if (["Pivot R1", "Pivot S1", "Opening range high", "Opening range low", "Previous day high", "Previous day low"].includes(l.name))
          out.push({ price: l.price, color: l.kind === "resistance" ? "#f97316" : "#0ea5e9", title: l.name.replace("Opening range", "OR").replace("Previous day", "PD") });
      }
    }
    return out;
  }, [data?.feed?.signal, data?.position, data?.feed?.plan, show.levels]);

  if (!data) return <Loading text="Connecting to the live feed…" className="h-[60vh]" />;
  const bars = data.feed?.chart?.bars ?? [];
  const tf = data.feed?.timeframe ?? settings.timeframe;
  const toggle = (k: keyof typeof show) => setShow((s) => ({ ...s, [k]: !s[k] }));

  return (
    <div className="space-y-4">
      {data.feed?.error && <Warning>Groww feed: {data.feed.error}</Warning>}
      {data.feed?.warnings?.map((w) => <Warning key={w}>{w}</Warning>)}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <SpotCard data={data} />
          <TradingPlanCard plan={data.feed?.plan} />
          <div className="xl:hidden"><RecommendationCard data={data} flash={!!fresh} /></div>
          <Card title={`NIFTY 50 · ${tf}-minute candles`} icon={<CandlestickChart size={16} className="text-blue-600" />}
            right={
              <Segmented value={tf} disabled={!!running} onChange={(v) => update({ timeframe: v })}
                options={[1, 5, 15, 30].map((t) => ({ value: t, label: `${t}m` }))} />
            }>
            <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
              <span><span className="text-blue-500">━ EMA 9</span> <span className="ml-1 text-orange-500">━ EMA 21</span></span>
              {(["vwap", "volume", "levels", "panels"] as const).map((k) => (
                <label key={k} className="flex items-center gap-1"><input type="checkbox" checked={show[k]} onChange={() => toggle(k)} />
                  {k === "vwap" ? "VWAP" : k === "volume" ? "Volume" : k === "levels" ? "Support / resistance" : "RSI & MACD"}</label>
              ))}
            </div>
            {bars.length ? (
              <CandleChart bars={bars} forming={data.feed.chart.forming} crosses={data.feed.crosses} markers={markers} levels={levels}
                showVwap={show.vwap} showVolume={show.volume} panels={show.panels} dark={settings.theme === "dark"} height={430} />
            ) : (
              <div className="grid h-[430px] place-items-center text-sm text-slate-500">{data.feed?.bars_error ?? "No candles for today yet."}</div>
            )}
            <p className="mt-2 text-xs text-slate-500">
              Closed candles only, plus the forming one with no indicators. Arrows marked 9/21 are crossovers; BUY CE / BUY PE / EXIT / HOLD are the strategy's calls
              (HOLD = a crossover outside the entry window). VWAP and volume come from NIFTY futures (the index has no volume); VWAP is shifted by the futures–spot basis.
              {data.feed?.ema && <> Last closed bar {hm(data.feed.ema.bar_close)}: close {num(data.feed.ema.close)}.</>}
              {running ? " Timeframe follows the running engine." : tf === 1 ? " 1-minute is for the chart and signals; the engine trades 5, 15 or 30 minutes." : ""}
            </p>
          </Card>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <PremiumCard data={data} />
            <PatternsCard items={data.feed?.patterns} />
          </div>
        </div>
        <div className="space-y-4">
          <div className="hidden xl:block"><RecommendationCard data={data} flash={!!fresh} /></div>
          <EnginePanel />
          {paper ? <RiskCalculator data={data} acct={account.acct} /> : <OrderCalculator data={data} />}
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
