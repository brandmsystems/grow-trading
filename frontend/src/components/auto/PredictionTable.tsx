import { Target } from "lucide-react";
import type { BiasPrediction } from "../../types/api";
import { hm, num, pct } from "../../utils/format";
import { Card, Pill } from "../common/Card";
import { Empty } from "../common/States";
import { arrow, biasTone, dirTone, outcomeTone } from "./BiasPanel";

/** Each closed candle's prediction next to what the next candle actually did. */
export function PredictionTable({ rows, day }: { rows: BiasPrediction[]; day: string }) {
  const done = rows.filter((r) => r.outcome);
  const right = done.filter((r) => r.outcome === "CORRECT").length;
  const wrong = done.filter((r) => r.outcome === "INCORRECT").length;
  return (
    <Card title="Predictions vs actual" icon={<Target size={16} className="text-orange-600" />}
      right={<span>{day} · {right} correct, {wrong} incorrect{right + wrong ? ` (${pct(100 * right / (right + wrong), 0)})` : ""}, {done.length - right - wrong} neutral</span>}>
      {rows.length === 0 ? <Empty title="No predictions yet">One is recorded for every completed 5-minute candle once the engine runs.</Empty> : (
        <div className="scroll-thin max-h-96 overflow-auto">
          <table className="w-full min-w-[640px] text-xs">
            <thead className="sticky top-0 bg-white text-left text-slate-500 dark:bg-slate-900">
              <tr><th className="py-1.5">Candle</th><th className="text-right">NIFTY</th><th>Bias</th><th className="text-right">Conf.</th>
                <th>Predicted</th><th className="text-right">Next close</th><th>Actual</th><th>Result</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.bar_close} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="py-1.5">{hm(r.bar_close)}</td>
                  <td className="num text-right">{num(r.nifty_close)}</td>
                  <td><Pill tone={biasTone(r.bias)}>{r.bias}</Pill></td>
                  <td className="num text-right">{num(r.confidence, 0)}%</td>
                  <td><Pill tone={dirTone(r.predicted)}>{arrow(r.predicted)}</Pill></td>
                  <td className="num text-right">{r.next_close != null ? num(r.next_close) : "—"}</td>
                  <td>{r.actual ? <Pill tone={dirTone(r.actual === "FLAT" ? "NEUTRAL" : r.actual)}>{r.actual === "FLAT" ? "FLAT" : arrow(r.actual)}</Pill> : <span className="text-slate-400">pending</span>}</td>
                  <td>{r.outcome ? <Pill tone={outcomeTone(r.outcome)}>{r.outcome}</Pill> : <span className="text-slate-400">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-2 text-[11px] text-slate-500">Each prediction is for the very next analysis candle. NEUTRAL: no direction was predicted, or that candle moved less than 0.1 × ATR. Accuracy counts CORRECT and INCORRECT only.</p>
    </Card>
  );
}
