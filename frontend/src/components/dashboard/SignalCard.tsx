import { AlertTriangle } from "lucide-react";
import type { Dashboard } from "../../types/api";
import { dmy, hm, inr, num } from "../../utils/format";
import { useSettings } from "../../context/SettingsContext";
import { Card, Pill, Stat } from "../common/Card";

/** The strategy's current call, the verified option to trade, its levels and the position size. */
export function SignalCard({ data, flash }: { data: Dashboard; flash: boolean }) {
  const { settings, update } = useSettings();
  const sig = data.feed?.signal;
  const rec = sig?.rec;
  const sz = rec?.sizing;
  const tone = sig?.action === "BUY CE" ? "good" : sig?.action === "BUY PE" ? "bad" : "neutral";
  return (
    <Card title="Recommendation" right={sig?.since ? `signal ${hm(sig.since)}` : undefined} className={flash ? "flash" : ""}>
      <div className="space-y-4 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <Pill tone={tone} className="px-4 py-1.5 text-xl">{sig?.action ?? "HOLD"}</Pill>
          {sig?.nifty != null && <span className="num text-sm text-slate-500">NIFTY {num(sig.nifty)} at signal</span>}
        </div>
        <p className="text-sm text-slate-600 dark:text-slate-300">{sig?.reason ?? data.feed?.error ?? "Waiting for data…"}</p>

        {rec && sig?.action !== "HOLD" && (
          rec.verified ? (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <Stat label="Option" value={`${num(rec.strike, 0)} ${rec.opt_type}`} sub={rec.strike_rule} />
                <Stat label="Expiry" value={dmy(rec.expiry)} sub={rec.symbol} />
                <Stat label="Live premium" value={`₹${num(rec.premium)}`} sub={rec.quote_as_of ? `as of ${rec.quote_as_of.slice(11, 19)}` : undefined} />
                <Stat label="Entry" value={`₹${num(rec.entry)}`} sub={rec.entry_basis} />
                <Stat label="Stop loss" value={`₹${num(rec.stop)}`} className="text-loss" sub={`NIFTY ${num(rec.nifty_stop)}`} />
                <Stat label="Target" value={`₹${num(rec.target)}`} className="text-gain" sub={`NIFTY ${num(rec.nifty_target)}`} />
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <div className="mb-2 flex flex-wrap items-end gap-3 text-xs">
                  <label className="flex flex-col gap-1">Capital ₹
                    <input type="number" min={0} step={10000} placeholder="Groww margin"
                      className="w-32 rounded-md border border-slate-300 bg-transparent px-2 py-1 dark:border-slate-700"
                      value={settings.capital ?? ""} onChange={(e) => update({ capital: e.target.value ? Number(e.target.value) : null })} />
                  </label>
                  <label className="flex flex-col gap-1">Risk per trade %
                    <input type="number" min={0.1} max={100} step={0.5}
                      className="w-20 rounded-md border border-slate-300 bg-transparent px-2 py-1 dark:border-slate-700"
                      value={settings.riskPct} onChange={(e) => update({ riskPct: Number(e.target.value) || 1 })} />
                  </label>
                </div>
                {sz ? (
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <Stat label="Lots" value={sz.lots} sub={`${sz.qty} qty · lot ${sz.lot_size}`} />
                    <Stat label="Investment" value={inr(sz.investment ?? 0)} sub={`limited by ${sz.limited_by}`} />
                    <Stat label="Max risk" value={inr(sz.max_risk ?? sz.risk_per_lot)} className="text-loss" sub={`budget ${inr(sz.risk_budget, false, 0)}`} />
                    <Stat label="At target" value={inr(sz.target_profit ?? 0, true)} className="text-gain" sub="after charges" />
                    {sz.note && <p className="col-span-full text-xs text-amber-600">{sz.note}</p>}
                  </div>
                ) : (
                  <p className="text-xs text-amber-600">{rec.sizing_error ?? "Sizing unavailable."}</p>
                )}
              </div>
            </>
          ) : (
            <p className="flex items-start gap-2 text-sm text-amber-600"><AlertTriangle size={16} className="mt-0.5 shrink-0" />{rec.error ?? "The option couldn't be verified, so nothing is recommended."}</p>
          )
        )}
        {data.feed?.warnings?.map((w) => <p key={w} className="text-xs text-amber-600">{w}</p>)}
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Stop and target are estimates (1 × and 2 × ATR on NIFTY, converted with the option's delta). The strategy itself exits on the opposite crossover or at 15:00.
          Signals are not a guaranteed result.
        </p>
      </div>
    </Card>
  );
}
