import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { useLive } from "../context/LiveContext";
import { useSettings } from "../context/SettingsContext";
import { PerformanceCard, PremiumCard, SpotCard, StrategyCard } from "../components/market/MarketCards";
import { RecommendationCard } from "../components/trading/RecommendationCard";
import { CandleChart } from "../components/charts/CandleChart";
import { AlertList } from "../components/layout/NotificationPanel";
import { Card } from "../components/common/Card";
import { Loading, Warning } from "../components/common/States";

export default function Overview() {
  const { data, trades, fresh } = useLive();
  const { settings } = useSettings();
  if (!data) return <Loading text="Connecting to Grow Trading…" className="h-[60vh]" />;
  const bars = data.feed?.chart?.bars ?? [];
  return (
    <div className="space-y-4">
      {data.feed?.error && <Warning>Groww feed: {data.feed.error}</Warning>}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <SpotCard data={data} />
        <PremiumCard data={data} />
        <StrategyCard data={data} />
        <PerformanceCard data={data} trades={trades} />
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card title={`NIFTY · ${data.feed?.timeframe ?? settings.timeframe}-minute`} className="xl:col-span-2"
          right={<Link to="/live" className="flex items-center gap-1 font-semibold text-blue-600 hover:underline">Open terminal <ArrowRight size={14} /></Link>}>
          {bars.length ? <CandleChart bars={bars} forming={data.feed.chart.forming} crosses={data.feed.crosses} dark={settings.theme === "dark"} height={300} />
            : <div className="grid h-[300px] place-items-center text-sm text-slate-500">{data.feed?.bars_error ?? "No candles for today yet."}</div>}
        </Card>
        <RecommendationCard data={data} flash={!!fresh} />
      </div>
      <Card title="Recent notifications" right={<Link to="/signals" className="font-semibold text-blue-600 hover:underline">All signals</Link>}>
        <AlertList alerts={data.alerts ?? []} freshId={fresh?.id} limit={6} />
      </Card>
    </div>
  );
}
