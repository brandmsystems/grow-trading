import { Target } from "lucide-react";
import type { PmReport } from "../../types/api";
import { num } from "../../utils/format";
import { Card, Pill, Stat } from "../common/Card";
import { totalTone } from "./ScoreMeter";

/** The conclusion: direction, lean (CE / PE / HOLD), levels, risks. A lean, never an order. */
export function Recommendation({ r }: { r: PmReport }) {
  const c = r.conclusion, lv = c.levels;
  const tone = totalTone(r);
  const prefTone = c.preference === "BUY CE" ? "good" : c.preference === "BUY PE" ? "bad" : "neutral";
  return (
    <Card title="Final conclusion" icon={<Target size={16} className="text-blue-600" />} accent={tone === "good" ? "gain" : tone === "bad" ? "loss" : "neutral"}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className={`text-2xl font-bold ${tone === "good" ? "text-gain" : tone === "bad" ? "text-loss" : ""}`} data-testid="pm-bias">{c.direction}</div>
          <div className="text-sm text-slate-600 dark:text-slate-300">Expect {c.opening}.</div>
        </div>
        <div className="text-right">
          <Pill tone={prefTone}>{c.preference}</Pill>
          <div className="mt-1 text-[11px] uppercase tracking-wide text-slate-500">preference, not an order</div>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Factor agreement" value={`${c.confidence}%`} tip={c.confidence_note} />
        <Stat label="Breakout above" value={lv.breakout != null ? num(lv.breakout, 1) : "—"} sub="previous-day high" />
        <Stat label="Breakdown below" value={lv.breakdown != null ? num(lv.breakdown, 1) : "—"} sub="previous-day low" />
        <Stat label="Pivot" value={lv.pivot != null ? num(lv.pivot, 1) : "—"} sub={lv.previous_close != null ? `prev close ${num(lv.previous_close, 1)}` : undefined} />
      </div>
      <p className="mt-2 text-xs text-slate-500" data-testid="confidence-note">{c.confidence_note}</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {(["resistance", "support"] as const).map((k) => (
          <div key={k}>
            <div className="mb-1 text-xs font-semibold capitalize text-slate-600 dark:text-slate-300">{k}</div>
            {(lv[k] ?? []).length
              ? <ul className="space-y-0.5 text-xs">{(lv[k] ?? []).map((x) => <li key={x.name} className="flex justify-between"><span>{x.name}</span><span className="num font-medium">{num(x.price, 1)}</span></li>)}</ul>
              : <span className="text-xs text-slate-500">unavailable</span>}
          </div>
        ))}
      </div>
      {c.risks.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-xs font-semibold text-slate-600 dark:text-slate-300">Risks and upcoming events</div>
          <ul className="list-disc space-y-0.5 pl-4 text-xs text-slate-600 dark:text-slate-300" data-testid="risks">{c.risks.map((x) => <li key={x}>{x}</li>)}</ul>
        </div>
      )}
      <p className="mt-3 rounded-md bg-slate-100 px-2 py-1.5 text-xs dark:bg-slate-800">{c.action}</p>
    </Card>
  );
}
