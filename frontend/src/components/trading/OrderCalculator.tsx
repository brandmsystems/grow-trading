import { Calculator } from "lucide-react";
import type { Dashboard } from "../../types/api";
import { useSettings } from "../../context/SettingsContext";
import { inr, num } from "../../utils/format";
import { Card, Stat } from "../common/Card";
import { Field, inputCls } from "../common/Controls";
import { Limitation } from "../common/States";

/** Shows the backend's position sizing (options/sizing.py) for the recommended contract. */
export function OrderCalculator({ data }: { data: Dashboard }) {
  const { settings, update } = useSettings();
  const rec = data.feed?.signal?.rec;
  const sz = rec?.sizing;
  const ch = sz?.charges_detail;
  return (
    <Card accent="risk" title="Order Calculator" icon={<Calculator size={16} className="text-orange-600" />}>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Available capital ₹">
          <input type="number" min={0} step={10000} placeholder="Use Groww margin" className={inputCls}
            value={settings.capital ?? ""} onChange={(e) => update({ capital: e.target.value ? Number(e.target.value) : null })} />
        </Field>
        <Field label="Risk per trade %">
          <input type="number" min={0.1} max={100} step={0.5} className={inputCls}
            value={settings.riskPct} onChange={(e) => update({ riskPct: Number(e.target.value) || 1 })} />
        </Field>
      </div>

      {!rec || data.feed?.signal?.action === "HOLD" ? (
        <p className="mt-3 text-sm text-slate-500">Sizing appears when the strategy recommends BUY CE or BUY PE.</p>
      ) : !sz ? (
        <p className="mt-3 text-sm text-orange-600">{rec.sizing_error ?? rec.error ?? "Sizing unavailable."}</p>
      ) : (
        <>
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Stat label="Capital used" value={inr(sz.available != null ? Math.min(sz.capital, sz.available) : sz.capital, false, 0)}
              sub={sz.available != null ? `Groww margin ${inr(sz.available, false, 0)}` : "your entry"} tip="The smaller of your capital and Groww's available option-buying margin." />
            <Stat label="Recommended lots" value={sz.lots} className="text-blue-600 dark:text-blue-400" sub={`limited by ${sz.limited_by}`}
              tip={`By risk: ${sz.lots_by_risk} lot(s). By cash: ${sz.lots_by_cash} lot(s). The smaller wins.`} />
            <Stat label="Lot size × lots" value={`${sz.lot_size} × ${sz.lots}`} sub={`${sz.qty} quantity`} />
            <Stat label="Investment" value={inr(sz.investment ?? 0)} tip="Premium × quantity (the cash an option buy needs)." />
            <Stat label="Brokerage & taxes" value={inr(sz.charges_stop ?? 0)} className="text-orange-600" tip="Estimated round-trip charges: brokerage, STT, exchange, SEBI, stamp duty and GST." />
            <Stat label="Max stop-loss risk" value={inr(-(sz.max_risk ?? 0))} className="text-loss" sub={`budget ${inr(sz.risk_budget, false, 0)}`} tip="Loss if the stop is hit, including charges." />
            <Stat label="Est. target profit" value={inr(sz.target_profit ?? 0, true)} className="text-gain" tip="Profit if the target is hit, after charges." />
            <Stat label="Risk per lot" value={inr(sz.risk_per_lot)} />
            <Stat label="Cost per lot" value={inr(sz.cost_per_lot)} />
          </div>
          {sz.note && <p className="mt-2 text-xs text-orange-600">{sz.note}</p>}
          {ch && (
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
              {(["brokerage", "stt", "exchange", "sebi", "stamp", "gst"] as const).map((k) => <span key={k}>{k.toUpperCase()} {num(ch[k] ?? 0)}</span>)}
              <span>(charges at target)</span>
            </div>
          )}
        </>
      )}
      <div className="mt-3"><Limitation>Figures come from the backend's sizing and charges model. Groww's real margin can differ.</Limitation></div>
    </Card>
  );
}
