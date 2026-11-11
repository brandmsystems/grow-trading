import { useEffect } from "react";
import { Loader2, WifiOff } from "lucide-react";
import { useDashboard } from "../hooks/useDashboard";
import { useAlerts } from "../hooks/useAlerts";
import { useSettings } from "../context/SettingsContext";
import { Header } from "../components/dashboard/Header";
import { MarketSummary } from "../components/dashboard/MarketSummary";
import { SignalCard } from "../components/dashboard/SignalCard";
import { Notifications } from "../components/dashboard/Notifications";
import { CandleChart } from "../components/charts/CandleChart";
import { EnginePanel } from "../components/trading/EnginePanel";
import { Card } from "../components/common/Card";

export default function LiveDashboard() {
  const { settings, update } = useSettings();
  const eng = settings.engine;
  const { data, error, connection, updatedAt, refresh } = useDashboard({
    tf: settings.timeframe, mode: eng.trade_mode, exec_mode: eng.exec_mode,
    capital: settings.capital, risk_pct: settings.riskPct,
  });
  const fresh = useAlerts(data?.alerts, settings.sound);
  // While the engine runs, the chart and signal follow the engine's timeframe.
  const engineTf = data && data.state !== "stopped" ? data.config?.timeframe : undefined;
  useEffect(() => {
    if (engineTf && engineTf !== settings.timeframe) update({ timeframe: engineTf });
  }, [engineTf, settings.timeframe, update]);

  return (
    <div className="min-h-screen">
      <Header data={data} connection={connection} updatedAt={updatedAt} />
      <main className="mx-auto max-w-7xl space-y-3 px-4 py-4">
        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-400">
            <WifiOff size={16} /> {error} {data ? "(showing the last data received)" : ""}
          </div>
        )}
        {data?.feed?.error && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">
            Groww feed: {data.feed.error}
          </div>
        )}
        {!data ? (
          <div className="grid h-64 place-items-center text-slate-500">
            {connection === "offline" ? "Can't reach the backend. Start it with python start.py." : <Loader2 className="animate-spin" />}
          </div>
        ) : (
          <>
            <MarketSummary data={data} />
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
              <Card title={`NIFTY · ${data.feed?.timeframe ?? settings.timeframe}-minute`} className="lg:col-span-2"
                right={<span><span className="text-ema-fast">━ EMA 9</span> <span className="ml-2 text-ema-slow">━ EMA 21</span></span>}>
                <div className="p-2">
                  {data.feed?.chart?.bars?.length ? (
                    <CandleChart bars={data.feed.chart.bars} forming={data.feed.chart.forming} crosses={data.feed.crosses}
                      dark={settings.theme === "dark"} />
                  ) : (
                    <div className="grid h-[360px] place-items-center text-sm text-slate-500">{data.feed?.bars_error ?? "No candles for today yet."}</div>
                  )}
                </div>
              </Card>
              <SignalCard data={data} flash={!!fresh} />
            </div>
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
              <div className="lg:col-span-2"><Notifications alerts={data.alerts ?? []} freshId={fresh?.id} /></div>
              <EnginePanel data={data} onChange={refresh} />
            </div>
          </>
        )}
      </main>
    </div>
  );
}
