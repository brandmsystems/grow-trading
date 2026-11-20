import { History } from "lucide-react";
import type { PmHistory } from "../../types/api";
import { dmy, inr, pct, pnlClass } from "../../utils/format";
import { Card, Pill, Stat, type Tone } from "../common/Card";

const oc = (o: string | null): Tone => (o === "CORRECT" ? "good" : o === "INCORRECT" ? "bad" : "neutral");

/** Stored days: the pre-market score against what NIFTY did and what paper trading made that day. */
export function HistoryPanel({ h }: { h: PmHistory }) {
  const a = h.accuracy;
  return (
    <Card title="History: pre-market bias versus what happened" icon={<History size={16} className="text-blue-600" />}>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Days stored" value={a.days} sub={`${a.settled} settled`} />
        <Stat label="Directional calls" value={a.calls} sub={`${a.correct} correct`} />
        <Stat label="Hit rate" value={a.hit_pct != null ? pct(a.hit_pct) : "—"} />
        <div className="col-span-2 text-xs text-slate-500 sm:col-span-1" data-testid="pm-accuracy-note">{a.note}</div>
      </div>
      {h.effectiveness.length > 0 && (
        <div className="mt-3" data-testid="effectiveness">
          <div className="mb-1 text-xs font-semibold text-slate-600 dark:text-slate-300">Paper trades by whether the pre-market bias agreed</div>
          <table className="w-full text-xs"><tbody>{h.effectiveness.map((g) => (
            <tr key={g.group} className="border-t border-slate-100 dark:border-slate-800"><td className="py-1">{g.group}</td><td className="num text-right">{g.trades} trades</td>
              <td className="num text-right">{g.win_pct != null ? pct(g.win_pct, 0) : "—"} won</td><td className={`num text-right font-medium ${pnlClass(g.net)}`}>{inr(g.net, true, 0)}</td></tr>))}</tbody></table>
        </div>
      )}
      {h.days.length === 0 ? <p className="mt-3 text-sm text-slate-500">No stored days yet. A report is stored every trading morning from 08:30 IST while the server runs.</p> : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-xs" data-testid="pm-history">
            <thead><tr className="text-left text-slate-500"><th className="py-1">Day</th><th>Score</th><th>Bias</th><th>Lean</th><th className="text-right">NIFTY day</th><th>Result</th><th className="text-right">Paper trades</th><th className="text-right">Paper net</th></tr></thead>
            <tbody>{h.days.map((d) => (
              <tr key={d.day} className="border-t border-slate-100 dark:border-slate-800">
                <td className="py-1">{dmy(d.day)}</td><td className="num">{d.total > 0 ? `+${d.total}` : d.total}</td><td>{d.bias}</td><td>{d.preference}</td>
                <td className="num text-right">{d.actual ? `${d.actual.change_pct > 0 ? "+" : ""}${d.actual.change_pct}% ${d.actual.direction}` : "pending"}</td>
                <td>{d.outcome ? <Pill tone={oc(d.outcome)}>{d.outcome}</Pill> : "—"}</td>
                <td className="num text-right">{d.paper_trades}</td><td className={`num text-right ${pnlClass(d.paper_net)}`}>{d.paper_trades ? inr(d.paper_net, true, 0) : "—"}</td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
