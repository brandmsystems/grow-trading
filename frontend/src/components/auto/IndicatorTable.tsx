import { Layers } from "lucide-react";
import type { BiasIndicatorRow } from "../../types/api";
import { num } from "../../utils/format";
import { Card, Pill } from "../common/Card";
import { voteTone } from "./BiasPanel";

const WORD = { bullish: "Bullish", bearish: "Bearish", neutral: "Neutral", unavailable: "n/a" } as const;

/** Every strategy's vote on the 5m and 15m candle (+1 fully bullish, -1 fully bearish). */
export function IndicatorTable({ rows, title = "Strategy confirmations", tf = [5, 15] }: { rows: BiasIndicatorRow[]; title?: string; tf?: [number, number] }) {
  return (
    <Card title={title} icon={<Layers size={16} className="text-violet-600" />} right="vote -1 … +1 · weight in brackets">
      <div className="scroll-thin overflow-x-auto">
        <table className="w-full min-w-[420px] text-xs">
          <thead className="text-left text-slate-500">
            <tr><th className="py-1.5">Strategy</th><th className="text-right">{tf[0]}m vote</th><th className="pl-2">{tf[0]}m</th><th className="text-right">{tf[1]}m vote</th><th className="pl-2">{tf[1]}m</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className="border-t border-slate-100 dark:border-slate-800">
                <td className="py-1.5">{r.label} <span className="text-slate-400">({r.weight})</span></td>
                <td className="num text-right">{r.v5 != null ? num(r.v5, 2) : "—"}</td>
                <td className="pl-2"><Pill tone={voteTone(r.status5)}>{WORD[r.status5]}</Pill></td>
                <td className="num text-right">{r.v15 != null ? num(r.v15, 2) : "—"}</td>
                <td className="pl-2"><Pill tone={voteTone(r.status15)}>{WORD[r.status15]}</Pill></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-slate-500">VWAP and volume come from NIFTY futures (the index has no volume) and abstain when futures candles are missing. RSI divergence abstains unless a divergence formed in the last six candles.</p>
    </Card>
  );
}
