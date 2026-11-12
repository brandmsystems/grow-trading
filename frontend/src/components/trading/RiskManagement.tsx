import { useEffect, useMemo, useState } from "react";
import { Gauge, RotateCcw, ShieldAlert } from "lucide-react";
import type { Dashboard, PaperAccount, RiskCalc } from "../../types/api";
import { getPaperAccount, resetPaperAccount, riskCalc } from "../../services/api";
import { inr, num, pnlClass } from "../../utils/format";
import { Card, Pill, Stat } from "../common/Card";
import { Button, Field, inputCls, Segmented } from "../common/Controls";
import { ErrorNote, Limitation } from "../common/States";

export const PRESETS: { key: string; label: string; pct: number }[] = [
  { key: "conservative", label: "Conservative", pct: 0.5 }, { key: "low", label: "Low", pct: 1 },
  { key: "moderate", label: "Moderate", pct: 1.5 }, { key: "high", label: "High", pct: 2 },
];

/** Shared poll of the virtual account and daily risk figures (every 10 s). */
export function usePaperAccount(dep?: unknown) {
  const [acct, setAcct] = useState<PaperAccount | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => getPaperAccount().then((a) => { if (alive) { setAcct(a); setErr(null); } }).catch((e) => alive && setErr((e as Error).message));
    load();
    const t = window.setInterval(load, 10000);
    return () => { alive = false; window.clearInterval(t); };
  }, [dep]);
  return { acct, err, reload: () => getPaperAccount().then(setAcct) };
}

/** Rows of the risk calculation, used by the calculator and by each trade's detail view. */
export function RiskRows({ r }: { r: RiskCalc }) {
  const rows: [string, string, string?][] = [
    ["1. Available capital", inr(r.capital, false, 0)],
    ["2. Risk per trade", `${num(r.risk_pct, 2)}%`],
    ["3. Maximum risk amount", inr(r.risk_amount ?? 0), "capital × risk % ÷ 100"],
    ["4. Entry premium", r.entry != null ? `₹${num(r.entry)}` : "—"],
    ["5. Stop-loss premium", r.stop != null ? `₹${num(r.stop)}` : "—", r.stop_method || (r.stop_distance != null ? `${num(r.stop_distance)} below entry` : undefined)],
    ["6. Risk per lot", r.risk_per_lot != null ? inr(r.risk_per_lot) : "—", r.risk_per_lot != null ? `(entry − stop) × ${r.lot_size} + slippage ${inr(r.slippage_per_lot ?? 0)} + charges ${inr(r.charges_per_lot ?? 0)}` : undefined],
    ["7. Recommended lots", String(r.lots), r.lots_by_risk != null ? `by risk ${r.lots_by_risk}${r.lots_by_cash != null ? ` · by cash ${r.lots_by_cash}` : ""}${r.max_lots ? ` · max ${r.max_lots}` : ""}${r.limited_by ? ` → limited by ${r.limited_by.replace("_", " ")}` : ""}` : undefined],
    ["8. Total quantity", `${r.qty}`, r.lot_size ? `${r.lots} × lot ${r.lot_size}` : undefined],
    ["9. Required investment", r.investment != null ? inr(r.investment) : "—", r.balance_after != null ? `balance after entry ${inr(r.balance_after, false, 0)}` : r.margin_note],
    ["10. Estimated charges", r.charges != null ? inr(r.charges) : "—", r.slippage != null ? `+ slippage allowance ${inr(r.slippage)}` : undefined],
    ["11. Maximum possible loss", r.max_loss != null ? inr(-r.max_loss) : "—", r.risk_reward ? `risk/reward 1 : ${num(r.risk_reward, 2)}` : undefined],
  ];
  return (
    <div className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
      {rows.map(([k, v, sub]) => (
        <div key={k} className="flex items-start justify-between gap-3 py-1.5">
          <div><div className="text-slate-600 dark:text-slate-300">{k}</div>{sub && <div className="text-[11px] text-slate-500">{sub}</div>}</div>
          <div className={`num shrink-0 font-semibold ${k.startsWith("11") ? "text-loss" : k.startsWith("7") ? "text-blue-600 dark:text-blue-400" : ""}`}>{v}</div>
        </div>
      ))}
    </div>
  );
}

export function Decision({ r }: { r: RiskCalc }) {
  return r.decision === "TRADE"
    ? <Pill tone="good">TRADE · {r.lots} lot(s)</Pill>
    : <Pill tone="bad">NO TRADE</Pill>;
}

/** Risk calculator: same backend function and costs the paper engine uses before every trade. */
export function RiskCalculator({ data, acct }: { data: Dashboard; acct: PaperAccount | null }) {
  const rec = data.feed?.signal?.rec;
  const [f, setF] = useState({ capital: "", risk: "1", preset: "low", entry: "", stopMode: "pct" as "pct" | "price", stop: "30", lot: "", maxLots: "10" });
  const [r, setR] = useState<RiskCalc | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const set = (p: Partial<typeof f>) => setF((x) => ({ ...x, ...p }));
  // Fill blanks from the account and the current recommendation (premium and lot size are real Groww values).
  const capital = f.capital || (acct ? String(acct.available) : "");
  const entry = f.entry || (rec?.premium != null ? String(rec.premium) : "");
  const lot = f.lot || (rec?.lot_size != null ? String(rec.lot_size) : "");
  const body = useMemo(() => ({
    capital: Number(capital) || null, risk_pct: Number(f.risk) || null, entry: Number(entry) || null, lot_size: Number(lot) || null,
    max_lots: Number(f.maxLots) || null, ...(f.stopMode === "pct" ? { stop_pct: Number(f.stop) || null } : { stop: Number(f.stop) || null }),
  }), [capital, f.risk, entry, lot, f.maxLots, f.stopMode, f.stop]);

  useEffect(() => {
    if (!body.capital || !body.risk_pct) { setR(null); return; }
    const t = window.setTimeout(() => {
      riskCalc(body).then((x) => { setR(x); setErr(null); }).catch((e) => { setR(null); setErr((e as Error).message); });
    }, 200);
    return () => window.clearTimeout(t);
  }, [body]);

  return (
    <Card accent="risk" title="Risk Management" icon={<ShieldAlert size={16} className="text-orange-600" />} right={r && <Decision r={r} />}>
      <div className="space-y-3">
        <Segmented value={f.preset} onChange={(v) => { const p = PRESETS.find((x) => x.key === v); set({ preset: v, risk: p ? String(p.pct) : f.risk }); }}
          options={[...PRESETS.map((p) => ({ value: p.key, label: `${p.pct}%` })), { value: "custom", label: "Custom" }]} />
        <p className="-mt-1 text-xs text-slate-500">Preset: <b>{PRESETS.find((p) => p.key === f.preset)?.label ?? "Custom"}</b> · Conservative 0.5%, Low 1%, Moderate 1.5%, High 2%</p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Virtual capital ₹"><input type="number" min={0} step={10000} className={inputCls} value={capital} onChange={(e) => set({ capital: e.target.value })} /></Field>
          <Field label="Risk %"><input type="number" min={0.05} max={100} step={0.05} className={inputCls} value={f.risk} onChange={(e) => set({ risk: e.target.value, preset: "custom" })} /></Field>
          <Field label="Entry premium ₹"><input type="number" min={0} step={0.05} className={inputCls} placeholder="option LTP" value={entry} onChange={(e) => set({ entry: e.target.value })} /></Field>
          <Field label={<span className="flex items-center gap-2">Stop-loss
            <select className="rounded border border-slate-300 bg-transparent text-xs dark:border-slate-700" value={f.stopMode} onChange={(e) => set({ stopMode: e.target.value as "pct" | "price", stop: e.target.value === "pct" ? "30" : "" })}>
              <option value="pct">% below</option><option value="price">price ₹</option></select></span>}>
            <input type="number" min={0} step={f.stopMode === "pct" ? 1 : 0.05} className={inputCls} value={f.stop} onChange={(e) => set({ stop: e.target.value })} /></Field>
          <Field label="Lot size"><input type="number" min={1} className={inputCls} placeholder="contract lot" value={lot} onChange={(e) => set({ lot: e.target.value })} /></Field>
          <Field label="Max lots"><input type="number" min={1} className={inputCls} value={f.maxLots} onChange={(e) => set({ maxLots: e.target.value })} /></Field>
        </div>
        {err && <ErrorNote>{err}</ErrorNote>}
        {r && (
          <>
            {r.decision !== "TRADE" && <p className="rounded-lg bg-red-50 p-2 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-400"><b>NO TRADE.</b> {r.reason}</p>}
            <RiskRows r={r} />
          </>
        )}
        {!r && !err && <p className="text-sm text-slate-500">Enter capital and risk % to see the calculation.</p>}
        <Limitation>Risk amount = capital × risk % ÷ 100. Risk per lot includes estimated slippage and charges. Presets are settings, not safe risk levels.
          The paper engine runs this same calculation on the live premium before every trade and stores it with the trade.</Limitation>
      </div>
    </Card>
  );
}

/** Daily risk monitor + virtual account (balance, reset). */
export function DailyRisk({ acct, err, reload }: { acct: PaperAccount | null; err: string | null; reload: () => void }) {
  const [cap, setCap] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  if (err && !acct) return <Card title="Daily Risk"><ErrorNote>{err}</ErrorNote></Card>;
  if (!acct) return null;
  const used = acct.risk_used_pct ?? 0;
  async function reset() {
    const v = Number(cap);
    if (!v || v <= 0) { setMsg("Enter the new virtual capital."); return; }
    if (window.prompt(`Start a new virtual account with ₹${v.toLocaleString("en-IN")}? Past trades are kept. Type RESET to confirm.`) !== "RESET") return;
    setBusy(true); setMsg(null);
    try { await resetPaperAccount(v); setCap(""); reload(); } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
  }
  return (
    <Card title="Daily Risk" icon={<Gauge size={16} className="text-violet-600" />}
      right={acct.limit_reached ? <Pill tone="bad">Limit reached</Pill> : <Pill tone={used >= 75 ? "warn" : "good"}>{num(used, 0)}% used</Pill>}>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Stat label="Starting daily capital" value={inr(acct.day_start_capital, false, 0)} />
        <Stat label="Today's P&L" value={inr(acct.pnl_today, true)} className={pnlClass(acct.pnl_today)} sub={acct.mtm != null ? `incl. open ${inr(acct.mtm, true)}` : "realised"} />
        <Stat label="Daily loss limit" value={acct.daily_limit != null ? inr(acct.daily_limit, false, 0) : "off"} sub={`${acct.settings.daily_risk_pct}% or ₹${num(acct.settings.max_daily_loss, 0)}, the smaller`} />
        <Stat label="Remaining risk budget" value={acct.remaining_risk != null ? inr(acct.remaining_risk, false, 0) : "—"} />
        <Stat label="Consecutive losses" value={acct.consecutive_losses} className={acct.consecutive_losses >= 3 ? "text-loss" : ""} />
        <Stat label="Max drawdown" value={inr(-acct.max_drawdown, false, 0)} sub={acct.max_drawdown_pct != null ? `${num(acct.max_drawdown_pct)}% of capital` : undefined} className="text-loss" />
        <Stat label="Open-position risk" value={inr(acct.open_risk, false, 0)} />
        <Stat label="Risk used today" value={acct.risk_used_pct != null ? `${num(acct.risk_used_pct, 1)}%` : "—"} />
        <Stat label="Next trade risk" value={inr(acct.risk_amount, false, 0)} sub={`${acct.settings.risk_pct}% of available`} />
      </div>
      <div className="mt-2 h-2 rounded bg-slate-100 dark:bg-slate-800">
        <div className={`h-2 rounded ${used >= 100 ? "bg-red-500" : used >= 75 ? "bg-orange-400" : "bg-green-500"}`} style={{ width: `${Math.min(100, used)}%` }} />
      </div>
      <div className="mt-3 rounded-lg border border-slate-200 p-3 text-sm dark:border-slate-800">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span>Virtual account #{acct.account_id}: balance <b className="num">{inr(acct.balance)}</b>, available <b className="num">{inr(acct.available)}</b></span>
          <span className="text-xs text-slate-500">started with {inr(acct.starting_capital, false, 0)} · {acct.trades_total} closed trade(s)</span>
        </div>
        <div className="mt-2 flex gap-2">
          <input type="number" min={1000} step={10000} placeholder="New capital ₹" className={`${inputCls} max-w-40`} value={cap} onChange={(e) => setCap(e.target.value)} />
          <Button onClick={reset} disabled={busy || !!acct.engine_running}><RotateCcw size={14} /> Reset account</Button>
        </div>
        {acct.engine_running && <p className="mt-1 text-xs text-slate-500">Stop the paper engine to reset the account.</p>}
        {msg && <p className="mt-1 text-xs text-red-600">{msg}</p>}
      </div>
      <p className="mt-2 text-xs text-slate-500">When the daily loss limit is reached, new paper entries stop and any open position is squared off. Trading resumes at the next session.</p>
    </Card>
  );
}
