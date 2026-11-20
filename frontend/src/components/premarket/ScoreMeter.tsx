import type { PmReport } from "../../types/api";

/** -5 .. +5 scale with a marker at the total; the band names follow the five-point rule. */
export function ScoreMeter({ total, available }: { total: number; available: number }) {
  const cells = Array.from({ length: 11 }, (_, i) => i - 5);
  const tone = (v: number) => (v > 0 ? "bg-green-500" : v < 0 ? "bg-red-500" : "bg-slate-400");
  return (
    <div>
      <div className="flex gap-1" role="meter" aria-label="Pre-market directional score" aria-valuemin={-5} aria-valuemax={5} aria-valuenow={total}>
        {cells.map((v) => (
          <div key={v} className="flex-1 text-center">
            <div className={`h-6 rounded ${v === total ? tone(v) + " ring-2 ring-offset-2 ring-slate-900 dark:ring-white dark:ring-offset-slate-900" : "bg-slate-200 dark:bg-slate-800"}`} />
            <div className={`num mt-1 text-[10px] ${v === total ? "font-bold" : "text-slate-500"}`}>{v > 0 ? `+${v}` : v}</div>
          </div>
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-slate-500"><span>Strong bearish</span><span>Neutral</span><span>Strong bullish</span></div>
      <div className="mt-2 text-xs text-slate-500">{available} of 5 factors had data; a factor with no data earns no point.</div>
    </div>
  );
}

export const totalTone = (r: Pick<PmReport, "total">) => (r.total.total >= 2 ? "good" : r.total.total <= -2 ? "bad" : "neutral");
