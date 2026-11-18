// One analyzer configuration in full: KPIs, yearly/monthly/regime tables, checks, equity curve and trades.
import { useEffect, useState } from "react";
import { Gauge, ListChecks, X } from "lucide-react";
import { useApi } from "../../hooks/useApi";
import { getScalpConfig } from "../../services/api";
import { Card, Pill, Stat } from "../../components/common/Card";
import { Button, Segmented } from "../../components/common/Controls";
import { ErrorNote, Loading } from "../../components/common/States";
import { BarsChart, LineChart } from "../../components/charts/SeriesChart";
import { dmy, hm, inr, inrShort, num, pct, pnlClass } from "../../utils/format";
import type { ScalpStats, ScalpTrade } from "../../types/api";
import { REASON, CHECK, pf, label } from "./shared";

function KPIs({ m }: { m: ScalpStats }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
      <Stat label="Net P&L" value={inr(m.net_pnl, true, 0)} className={pnlClass(m.net_pnl)} sub="after all costs" />
      <Stat label="Gross P&L" value={inr(m.gross_pnl, true, 0)} className={pnlClass(m.gross_pnl)} sub="before costs" />
      <Stat label="Brokerage" value={inr(m.brokerage ?? 0, false, 0)} className="text-orange-600" />
      <Stat label="Taxes & fees" value={inr(m.taxes ?? 0, false, 0)} className="text-orange-600" sub={`slippage ${inr(m.slippage ?? 0, false, 0)}`} tip="STT, exchange, SEBI, stamp duty and GST." />
      <Stat label="Trades" value={m.trades} sub={<><span className="text-gain">{m.wins ?? 0} won</span> · <span className="text-loss">{m.losses ?? 0} lost</span></>} />
      <Stat label="Win rate" value={pct(m.win_rate)} />
      <Stat label="Profit factor" value={pf(m.profit_factor)} />
      <Stat label="Max drawdown" value={inr(-m.max_drawdown, false, 0)} className="text-loss" />
      <Stat label="Avg holding" value={m.avg_hold_min != null ? `${num(m.avg_hold_min, 1)} min` : "—"} />
      <Stat label="Risk / reward" value={m.risk_reward ? `1 : ${num(m.risk_reward)}` : "—"} tip="Average win ÷ average loss (net)." />
      <Stat label="Avg win / loss" value={<span className="text-sm">{inr(m.avg_win ?? 0, false, 0)} / {inr(m.avg_loss ?? 0, false, 0)}</span>} />
      <Stat label="Exits" value={<span className="text-[11px] font-normal">{Object.entries(m.exits ?? {}).map(([k, v]) => `${REASON[k] ?? k} ${v}`).join(" · ") || "—"}</span>} />
    </div>
  );
}

function GroupTable({ title, rows }: { title: string; rows: Record<string, { net: number; gross: number; trades: number; win_rate: number }> }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[420px] text-xs">
        <thead><tr className="text-left uppercase text-slate-500"><th className="py-1.5">{title}</th><th className="text-right">Trades</th><th className="text-right">Win rate</th><th className="text-right">Gross</th><th className="text-right">Net</th></tr></thead>
        <tbody>
          {Object.entries(rows).map(([k, v]) => (
            <tr key={k} className="border-t border-slate-100 dark:border-slate-800">
              <td className="py-1">{k}</td><td className="num text-right">{v.trades}</td><td className="num text-right">{pct(v.win_rate)}</td>
              <td className={`num text-right ${pnlClass(v.gross)}`}>{inrShort(v.gross)}</td><td className={`num text-right font-semibold ${pnlClass(v.net)}`}>{inrShort(v.net)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TradeDetail({ t, onClose }: { t: ScalpTrade; onClose: () => void }) {
  return (
    <div className="mt-3 rounded-xl border border-slate-200 p-3 text-sm dark:border-slate-800">
      <div className="flex items-center justify-between gap-2">
        <div className="font-semibold">{t.symbol} · {t.direction} · {dmy(t.day)}</div>
        <Button onClick={onClose}><X size={14} /></Button>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Signal (bar close)" value={hm(t.signal_ts)} sub={`NIFTY ${num(t.spot)} · ${t.regime}`} />
        <Stat label="BUY" value={`₹${num(t.entry)} → fill ₹${num(t.entry_fill)}`} sub={hm(t.entry_ts)} />
        <Stat label="SELL" value={`₹${num(t.exit)} → fill ₹${num(t.exit_fill)}`} sub={`${hm(t.exit_ts)} · ${REASON[t.reason] ?? t.reason}`} />
        <Stat label="Held" value={`${num(t.hold_min, 1)} min`} />
        <Stat label="Contract" value={`${num(t.strike, 0)} ${t.opt_type}`} sub={`expiry ${dmy(t.expiry)}`} />
        <Stat label="Quantity" value={`${t.qty}`} sub={`lot size ${t.lot_size}`} />
        <Stat label="Gross" value={inr(t.gross, true)} className={pnlClass(t.gross)} />
        <Stat label="Slippage" value={inr(t.slippage)} className="text-orange-600" />
        <Stat label="Brokerage" value={inr(t.brokerage)} className="text-orange-600" />
        <Stat label="Taxes & fees" value={inr(t.taxes)} className="text-orange-600" />
        <Stat label="Net" value={inr(t.net, true)} className={pnlClass(t.net)} />
      </div>
    </div>
  );
}

function BacktestTrades({ trades }: { trades: ScalpTrade[] }) {
  const [filter, setFilter] = useState<"all" | "win" | "loss">("all");
  const [page, setPage] = useState(0);
  const [sel, setSel] = useState<ScalpTrade | null>(null);
  const rows = trades.filter((t) => filter === "all" || (filter === "win" ? t.net > 0 : t.net <= 0)).slice().reverse();
  const per = 50, pages = Math.max(1, Math.ceil(rows.length / per));
  useEffect(() => { setPage(0); setSel(null); }, [filter, trades]);
  return (
    <>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Segmented value={filter} onChange={setFilter} options={[{ value: "all", label: `All ${trades.length}` }, { value: "win", label: `Winning ${trades.filter((t) => t.net > 0).length}` }, { value: "loss", label: `Losing ${trades.filter((t) => t.net <= 0).length}` }]} />
        <span className="text-xs text-slate-500">newest first · click a trade for every detail</span>
      </div>
      <div className="scroll-thin max-h-[28rem] overflow-auto">
        <table className="w-full min-w-[900px] text-xs">
          <thead className="sticky top-0 bg-white text-left text-slate-500 dark:bg-slate-900">
            <tr><th className="py-1.5">Day</th><th>Signal</th><th>Contract</th><th className="text-right">Qty</th><th className="text-right">BUY</th><th className="text-right">SELL</th><th>Exit</th><th className="text-right">Held</th><th className="text-right">Gross</th><th className="text-right">Costs</th><th className="text-right">Net</th></tr>
          </thead>
          <tbody>
            {rows.slice(page * per, page * per + per).map((t) => (
              <tr key={t.entry_ts + t.symbol} onClick={() => setSel(t)} className={`cursor-pointer border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/60 ${sel === t ? "bg-blue-50 dark:bg-blue-950/40" : ""}`}>
                <td className="py-1">{dmy(t.day)}</td><td>{hm(t.signal_ts)} <Pill tone={t.opt_type === "CE" ? "good" : "bad"}>{t.opt_type}</Pill></td>
                <td>{num(t.strike, 0)} · {dmy(t.expiry).slice(0, 6)}</td><td className="num text-right">{t.qty}</td>
                <td className="num text-right">{hm(t.entry_ts)} ₹{num(t.entry_fill)}</td><td className="num text-right">{hm(t.exit_ts)} ₹{num(t.exit_fill)}</td>
                <td>{REASON[t.reason] ?? t.reason}</td><td className="num text-right">{num(t.hold_min, 0)}m</td>
                <td className={`num text-right ${pnlClass(t.gross)}`}>{inr(t.gross, true, 0)}</td><td className="num text-right text-orange-600">{inr(t.friction, false, 0)}</td>
                <td className={`num text-right font-semibold ${pnlClass(t.net)}`}>{inr(t.net, true, 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="mt-2 flex items-center gap-2 text-xs">
          <Button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}>Newer</Button>
          <span>Page {page + 1} / {pages}</span>
          <Button onClick={() => setPage((p) => Math.min(pages - 1, p + 1))} disabled={page >= pages - 1}>Older</Button>
        </div>
      )}
      {sel && <TradeDetail t={sel} onClose={() => setSel(null)} />}
    </>
  );
}

export function ConfigDetail({ k, dark }: { k: string; dark: boolean }) {
  const d = useApi(() => getScalpConfig(k), [k]);
  const c = d.data;
  if (d.error) return <ErrorNote>{d.error}</ErrorNote>;
  if (!c) return <Loading />;
  const monthly = Object.entries(c.monthly ?? {}).map(([m, v]) => ({ time: `${m}-01`, value: v.net }));
  return (
    <div className="space-y-4">
      <Card title={label(c)} icon={<Gauge size={16} className="text-violet-600" />} accent="strat"
        right={<Pill tone={c.verdict.consistent ? "good" : "bad"}>{c.verdict.consistent ? "Consistently profitable" : "Not consistently profitable"}</Pill>}>
        <KPIs m={c} />
        <div className="mt-3 flex flex-wrap gap-1.5">
          {Object.entries(c.verdict.checks).map(([n, ok]) => <Pill key={n} tone={ok ? "good" : "bad"}>{ok ? "✓" : "✗"} {CHECK[n] ?? n}</Pill>)}
          <Pill tone="neutral">years positive {c.verdict.years_positive}</Pill>
        </div>
        {Object.keys(c.skipped).length > 0 && (
          <p className="mt-2 text-xs text-slate-500">Signals not traded: {Object.entries(c.skipped).map(([r, n]) => `${r} ${n}`).join(" · ")}</p>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="CE versus PE">
          <div className="grid grid-cols-2 gap-4">
            {(["ce", "pe"] as const).map((s) => (
              <div key={s} className="space-y-2">
                <Pill tone={s === "ce" ? "good" : "bad"}>{s.toUpperCase()} · {s === "ce" ? "bullish" : "bearish"} signals</Pill>
                <Stat label="Net" value={inr(c[s].net_pnl, true, 0)} className={pnlClass(c[s].net_pnl)} sub={`gross ${inr(c[s].gross_pnl, true, 0)}`} />
                <Stat label="Trades · win rate" value={`${c[s].trades} · ${pct(c[s].win_rate)}`} />
                <Stat label="Profit factor · max DD" value={`${pf(c[s].profit_factor)} · ${inrShort(-c[s].max_drawdown, false)}`} />
              </div>
            ))}
          </div>
        </Card>
        <Card title="In-sample vs out-of-sample" right="split by trading days, 60 / 40">
          <div className="grid grid-cols-2 gap-4">
            {([["In-sample (first 60%)", c.in_sample], ["Out-of-sample (last 40%)", c.out_of_sample]] as const).map(([t, v]) => (
              <div key={t} className="space-y-2">
                <div className="text-xs font-semibold">{t}</div>
                {v ? <>
                  <Stat label="Net" value={inr(v.net_pnl, true, 0)} className={pnlClass(v.net_pnl)} />
                  <Stat label="Trades · PF" value={`${v.trades} · ${pf(v.profit_factor)}`} />
                  <Stat label="Max drawdown" value={inr(-v.max_drawdown, false, 0)} className="text-loss" />
                </> : <span className="text-xs text-slate-500">no trades</span>}
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card title="Equity (net, 1 lot per trade)">
        <LineChart series={[{ name: "Net", color: "#7c3aed", data: (c.equity ?? []).map(([t, v]) => ({ time: t, value: v })) }]} dark={dark} height={260} />
      </Card>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Yearly performance"><GroupTable title="Year" rows={c.yearly} /></Card>
        <Card title="By market condition" right="daily regime of NIFTY"><GroupTable title="Regime" rows={c.regimes ?? {}} /></Card>
      </div>
      <Card title="Monthly net P&L"><BarsChart data={monthly} dark={dark} height={220} /></Card>

      {c.risk && (
        <Card title="Sized by risk % of ₹1,00,000" right="lots so the loss at the stop fits the risk">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-xs">
              <thead><tr className="text-left uppercase text-slate-500"><th className="py-1.5">Risk / trade</th><th className="text-right">Trades</th><th className="text-right">Avg lots</th><th className="text-right">Gross</th><th className="text-right">Brokerage</th><th className="text-right">Taxes</th><th className="text-right">Net</th><th className="text-right">Max DD</th><th className="text-right">PF</th><th className="text-right">Too small</th></tr></thead>
              <tbody>
                {Object.entries(c.risk).map(([r, v]) => (
                  <tr key={r} className="border-t border-slate-100 dark:border-slate-800">
                    <td className="py-1">{r}%</td><td className="num text-right">{v.trades}</td><td className="num text-right">{num(v.avg_lots)}</td>
                    <td className={`num text-right ${pnlClass(v.gross_pnl)}`}>{inrShort(v.gross_pnl)}</td><td className="num text-right">{inrShort(v.brokerage, false)}</td><td className="num text-right">{inrShort(v.taxes, false)}</td>
                    <td className={`num text-right font-semibold ${pnlClass(v.net_pnl)}`}>{inrShort(v.net_pnl)}</td><td className="num text-right text-loss">{inrShort(-v.max_drawdown, false)} ({pct(v.max_drawdown_pct)})</td>
                    <td className="num text-right">{pf(v.profit_factor)}</td><td className="num text-right">{v.too_small}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      <Card title="Backtest trades (BUY and SELL)" icon={<ListChecks size={16} className="text-blue-600" />}><BacktestTrades trades={c.trade_list} /></Card>
    </div>
  );
}
