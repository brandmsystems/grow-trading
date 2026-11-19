import { useState } from "react";
import { BarChart3 } from "lucide-react";
import { getBiasAccuracy, getBiasHistoryAccuracy } from "../../services/api";
import { useApi } from "../../hooks/useApi";
import type { BiasAccuracyRow } from "../../types/api";
import { Card } from "../common/Card";
import { Segmented } from "../common/Controls";
import { Empty, ErrorNote, Limitation, Loading } from "../common/States";

const cell = (r?: BiasAccuracyRow) => {
  if (!r || r.accuracy == null) return <span className="text-slate-400">—</span>;
  const tone = r.accuracy >= 53 ? "text-gain" : r.accuracy <= 47 ? "text-loss" : "";
  return <span className={`num ${tone}`}>{r.accuracy.toFixed(1)}% <span className="text-slate-400">n={r.n.toLocaleString("en-IN")}</span></span>;
};

/** Next-candle accuracy of the combined bias and of each strategy on the 5m and 15m vote. */
export function AccuracyPanel({ mode, tf = 5, confirm = 15 }: { mode: string; tf?: number; confirm?: number }) {
  const [src, setSrc] = useState<"stored" | "history">("stored");
  const res = useApi(() => (src === "stored" ? getBiasAccuracy(mode) : getBiasHistoryAccuracy(undefined, undefined, tf, confirm)), [src, mode, tf, confirm]);
  const rows = res.data?.rows ?? [];
  const [t1, t2] = res.data?.timeframes ?? [tf, confirm];
  const by = (k: string, label: string) => rows.find((r) => r.key === k && r.timeframe === label);
  const keys = [...new Set(rows.filter((r) => r.key !== "combined").map((r) => r.key))];
  const combined = rows.find((r) => r.key === "combined");
  return (
    <Card title="Prediction accuracy by strategy and timeframe" icon={<BarChart3 size={16} className="text-blue-600" />}
      right={<Segmented value={src} onChange={setSrc} options={[{ value: "stored", label: "This app's predictions" }, { value: "history", label: "Last 60 days (stored candles)" }]} />}>
      {res.loading && <Loading />}
      {res.error && <ErrorNote>{res.error}</ErrorNote>}
      {res.data && res.data.candles === 0 && <Empty title="Nothing to score yet">{src === "stored" ? "Predictions appear here once the next candle after each one has closed." : "No stored candles for that period."}</Empty>}
      {res.data && res.data.candles > 0 && (
        <>
          <p className="mb-2 text-sm">Combined bias: <b data-testid="combined-accuracy">{combined?.accuracy != null ? `${combined.accuracy.toFixed(1)}%` : "—"}</b> right on {combined?.n.toLocaleString("en-IN") ?? 0} calls
            ({res.data.candles.toLocaleString("en-IN")} candles scored{res.data.from ? `, ${res.data.from} to ${res.data.to}` : ""}).</p>
          <div className="scroll-thin overflow-x-auto">
            <table className="w-full min-w-[420px] text-xs">
              <thead className="text-left text-slate-500"><tr><th className="py-1.5">Strategy</th><th>{t1}m vote</th><th>{t2}m vote</th></tr></thead>
              <tbody>
                {keys.map((k) => (
                  <tr key={k} className="border-t border-slate-100 dark:border-slate-800">
                    <td className="py-1.5">{by(k, `${t1}m`)?.label}</td><td>{cell(by(k, `${t1}m`))}</td><td>{cell(by(k, `${t2}m`))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <div className="mt-3"><Limitation>
        Accuracy is the share of CORRECT among CORRECT + INCORRECT calls for the very next 5-minute candle; 50% is a coin flip, and a few tenths of a point above it is not a tradable edge after brokerage, taxes and slippage.
        A prediction is judged only on the candle after it; the analysis uses closed candles only.
      </Limitation></div>
    </Card>
  );
}
