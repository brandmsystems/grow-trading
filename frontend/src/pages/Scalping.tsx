import { useEffect, useMemo, useState } from "react";
import { Award, RefreshCw } from "lucide-react";
import { useSettings } from "../context/SettingsContext";
import { useApi, waitForJob } from "../hooks/useApi";
import { getScalping, runScalping } from "../services/api";
import { Card, Stat } from "../components/common/Card";
import { Button, PageHeader, Segmented, selectInline } from "../components/common/Controls";
import { Empty, ErrorNote, Limitation, Loading, Progress } from "../components/common/States";
import { dmy, inrShort, pct, pnlClass } from "../utils/format";
import type { Job, ScalpConfig } from "../types/api";
import { ConfigDetail } from "../components/scalping/ConfigDetail";
import { PaperPanel } from "../components/scalping/PaperPanel";
import { pf, label, type SortKey } from "../components/scalping/shared";

export default function Scalping() {
  const { settings } = useSettings();
  const dark = settings.theme === "dark";
  const res = useApi(getScalping, []);
  const [job, setJob] = useState<Job | null>(null);
  const [contract, setContract] = useState<"all" | "ATM_BUY" | "ITM5_BUY">("all");
  const [exitKind, setExitKind] = useState<"all" | "time" | "sl_target">("all");
  const [sort, setSort] = useState<SortKey>("rank");
  const [picked, setPicked] = useState<string | null>(null);
  const run = res.data?.data;

  useEffect(() => {
    const j = res.data?.job;
    if (j && typeof j === "object" && !job) waitForJob(j.id, setJob, 3000).then(() => { setJob(null); void res.reload(); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [res.data?.job]);

  async function start() {
    if (!window.confirm("Re-run the full five-year scalping analysis? It reads every stored option candle and takes several minutes.")) return;
    try {
      const r = await runScalping();
      const j = await waitForJob(String(r.job), setJob, 3000);
      setJob(null);
      if (j.state === "error") throw new Error(j.error ?? "Run failed");
      await res.reload();
    } catch (e) { setJob(null); alert((e as Error).message); }
  }

  const configs = run?.configs ?? [];
  const rank = useMemo(() => Object.fromEntries((run?.ranking ?? []).map((k, i) => [k, i + 1])), [run]);
  const rows = useMemo(() => configs
    .filter((c) => (contract === "all" || c.contract === contract) && (exitKind === "all" || c.exit_kind === exitKind))
    .sort((a, b) => {
      if (sort === "rank") return (rank[a.key] ?? 9999) - (rank[b.key] ?? 9999);
      if (sort === "max_drawdown") return a.max_drawdown - b.max_drawdown;
      return ((b[sort] as number) ?? -Infinity) - ((a[sort] as number) ?? -Infinity);
    }), [configs, contract, exitKind, sort, rank]);
  const featured = run?.best ?? run?.top_in_sample ?? configs[0]?.key ?? null;
  const selected = picked ?? featured;
  const best = configs.find((c) => c.key === run?.best);
  const top = configs.find((c) => c.key === run?.top_in_sample);
  const netPositive = configs.filter((c) => c.net_pnl > 0).length;
  const grossPositive = configs.filter((c) => c.gross_pnl > 0).length;
  const bestExisting = [...(run?.existing ?? [])].sort((a, b) => b.net_pnl - a.net_pnl).slice(0, 8);
  const strategies = [...new Map(configs.map((c) => [c.strategy, c.strategy_label])).entries()];
  const sumBy = (f: (c: ScalpConfig) => boolean, side: "ce" | "pe") => configs.filter(f).reduce((s, c) => s + c[side].net_pnl, 0);

  return (
    <div className="space-y-4">
      <PageHeader title="5-Minute Scalping" subtitle={run ? `${configs.length} configurations · ${dmy(run.start_date)} → ${dmy(run.end_date)} · completed 5-min NIFTY bars, real option premiums, all costs` : "EMA strategies on completed 5-minute bars, 5-minute holds, ATM and ITM 5 options"}
        actions={<Button onClick={start} disabled={!!job}><RefreshCw size={14} className={job ? "animate-spin" : ""} /> Run analysis</Button>} />
      {job && <Card><Progress value={job.progress} text={job.message} /></Card>}
      {res.error && <ErrorNote>{res.error}</ErrorNote>}
      {res.loading && !run ? <Loading /> : !run ? (
        <Empty title="No scalping analysis yet">Run the analysis. It uses the stored NIFTY and option 1-minute history (Data page).</Empty>
      ) : (
        <>
          <Card title="Verdict" icon={<Award size={16} className="text-blue-600" />} accent={run.consistent.length ? "gain" : "loss"}>
            <div className="space-y-2 text-sm">
              {run.consistent.length ? (
                <p><b className="text-gain">{run.consistent.length}</b> configuration(s) passed every consistency check after costs.</p>
              ) : (
                <p className="font-semibold text-loss">No configuration has shown consistent profitability after all costs. {netPositive} of {configs.length} are net positive; {grossPositive} were positive before costs.</p>
              )}
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <Stat label="Best-performing (selection rule)" value={best ? label(best) : "None qualifies"} className={best ? "text-gain" : "text-loss"}
                  sub={best ? `net ${inrShort(best.net_pnl)} · out-of-sample ${inrShort(best.oos_net)}` : "no in-sample leader stayed positive out of sample"} />
                <Stat label="Top in-sample (before the test)" value={top ? <span className="text-sm">{label(top)}</span> : "—"}
                  sub={top ? `in-sample ${inrShort(top.in_sample?.net_pnl)} → out-of-sample ${inrShort(top.oos_net)}` : undefined} />
                <Stat label="Walk-forward total (year by year)" value={inrShort(run.walk_forward.total_oos)} className={pnlClass(run.walk_forward.total_oos)}
                  sub={`${run.walk_forward.rows.filter((r) => r.pick).length} of ${run.walk_forward.rows.length} years had a qualifying pick`} />
              </div>
              <p className="text-xs text-slate-500">{run.selection_rule}</p>
            </div>
          </Card>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card title="CE versus PE (net, all configurations)">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[360px] text-xs">
                  <thead><tr className="text-left uppercase text-slate-500"><th className="py-1.5">Strategy</th><th className="text-right">CE net</th><th className="text-right">PE net</th></tr></thead>
                  <tbody>
                    {strategies.map(([s, l]) => {
                      const ce = sumBy((c) => c.strategy === s, "ce"), pe = sumBy((c) => c.strategy === s, "pe");
                      return <tr key={s} className="border-t border-slate-100 dark:border-slate-800"><td className="py-1">{l}</td><td className={`num text-right ${pnlClass(ce)}`}>{inrShort(ce)}</td><td className={`num text-right ${pnlClass(pe)}`}>{inrShort(pe)}</td></tr>;
                    })}
                  </tbody>
                </table>
              </div>
              <p className="mt-1 text-[11px] text-slate-500">Summed over every contract and exit rule of the strategy, 1 lot per trade.</p>
            </Card>
            <Card title="Walk-forward (choose on earlier years, test on the next)">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[420px] text-xs">
                  <thead><tr className="text-left uppercase text-slate-500"><th className="py-1.5">Year</th><th>Trained on</th><th>Pick</th><th className="text-right">That year</th></tr></thead>
                  <tbody>
                    {run.walk_forward.rows.map((r) => (
                      <tr key={r.year} className="border-t border-slate-100 dark:border-slate-800">
                        <td className="py-1">{r.year}</td><td>{r.trained_on}</td><td className="max-w-56 truncate">{r.pick_label ?? <span className="text-slate-500">none qualified: no trading</span>}</td>
                        <td className={`num text-right ${pnlClass(r.oos_net)}`}>{r.pick ? inrShort(r.oos_net) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>

          <Card title="All configurations" right="click a row for its full report">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <Segmented value={contract} onChange={setContract} options={[{ value: "all", label: "All" }, { value: "ATM_BUY", label: "ATM" }, { value: "ITM5_BUY", label: "ITM 5" }]} />
              <Segmented value={exitKind} onChange={setExitKind} options={[{ value: "all", label: "All exits" }, { value: "time", label: "Fixed 5-min" }, { value: "sl_target", label: "SL / target" }]} />
              <select aria-label="Sort" className={selectInline} value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
                <option value="rank">Sort: in-sample rank</option><option value="net_pnl">Net P&L</option><option value="oos_net">Out-of-sample net</option>
                <option value="profit_factor">Profit factor</option><option value="max_drawdown">Smallest drawdown</option><option value="win_rate">Win rate</option><option value="trades">Trades</option>
              </select>
            </div>
            <div className="scroll-thin max-h-[30rem] overflow-auto">
              <table className="w-full min-w-[980px] text-xs">
                <thead className="sticky top-0 bg-white text-left text-slate-500 dark:bg-slate-900">
                  <tr><th className="py-1.5">#</th><th>Strategy</th><th>Contract</th><th>Exit</th><th className="text-right">Trades</th><th className="text-right">Win</th><th className="text-right">Gross</th><th className="text-right">Brokerage</th><th className="text-right">Taxes</th><th className="text-right">Net</th><th className="text-right">PF</th><th className="text-right">Max DD</th><th className="text-right">Out-of-sample</th><th className="text-right">Years +</th></tr>
                </thead>
                <tbody>
                  {rows.map((c) => (
                    <tr key={c.key} onClick={() => setPicked(c.key)} className={`cursor-pointer border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/60 ${selected === c.key ? "bg-blue-50 dark:bg-blue-950/40" : ""}`}>
                      <td className="py-1">{rank[c.key] ?? "—"}</td><td>{c.strategy_label}</td><td>{c.contract === "ATM_BUY" ? "ATM" : "ITM 5"}</td><td>{c.exit_kind === "time" ? "5-min" : `SL ${c.stop}% / TP ${c.target}%`}</td>
                      <td className="num text-right">{c.trades}</td><td className="num text-right">{pct(c.win_rate, 0)}</td>
                      <td className={`num text-right ${pnlClass(c.gross_pnl)}`}>{inrShort(c.gross_pnl)}</td><td className="num text-right">{inrShort(c.brokerage ?? 0, false)}</td><td className="num text-right">{inrShort(c.taxes ?? 0, false)}</td>
                      <td className={`num text-right font-semibold ${pnlClass(c.net_pnl)}`}>{inrShort(c.net_pnl)}</td><td className="num text-right">{pf(c.profit_factor)}</td>
                      <td className="num text-right text-loss">{inrShort(-c.max_drawdown, false)}</td><td className={`num text-right ${pnlClass(c.oos_net)}`}>{inrShort(c.oos_net)}</td><td className="num text-right">{c.verdict.years_positive}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {selected && <ConfigDetail k={selected} dark={dark} />}

          <Card title="Against the existing strategies" right="Compare page results, 1 lot, same costs, held until the opposite cross">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-xs">
                <thead><tr className="text-left uppercase text-slate-500"><th className="py-1.5">Strategy</th><th>TF</th><th>Contract</th><th className="text-right">Trades</th><th className="text-right">Win</th><th className="text-right">Net</th><th className="text-right">PF</th><th className="text-right">Max DD</th><th className="text-right">Years +</th></tr></thead>
                <tbody>
                  {top && <tr className="bg-violet-50 dark:bg-violet-950/30"><td className="py-1 font-semibold">Scalp: {top.strategy_label} ({top.exit_label})</td><td>5m</td><td>{top.contract === "ATM_BUY" ? "ATM" : "ITM 5"}</td><td className="num text-right">{top.trades}</td><td className="num text-right">{pct(top.win_rate, 0)}</td><td className={`num text-right font-semibold ${pnlClass(top.net_pnl)}`}>{inrShort(top.net_pnl)}</td><td className="num text-right">{pf(top.profit_factor)}</td><td className="num text-right text-loss">{inrShort(-top.max_drawdown, false)}</td><td className="num text-right">{top.verdict.years_positive}</td></tr>}
                  {bestExisting.map((e) => (
                    <tr key={`${e.strategy}${e.timeframe}${e.contract}`} className="border-t border-slate-100 dark:border-slate-800">
                      <td className="py-1">{e.label}</td><td>{e.timeframe}m</td><td>{e.contract === "ATM_BUY" ? "ATM" : "ITM 5"}</td><td className="num text-right">{e.trades}</td><td className="num text-right">{pct(e.win_rate, 0)}</td>
                      <td className={`num text-right font-semibold ${pnlClass(e.net_pnl)}`}>{inrShort(e.net_pnl)}</td><td className="num text-right">{pf(e.profit_factor)}</td><td className="num text-right text-loss">{inrShort(-e.max_drawdown, false)}</td><td className="num text-right">{e.years_positive}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-1 text-[11px] text-slate-500">The 8 best existing strategy × timeframe × contract results by net P&L ({run.existing.length} in total).</p>
          </Card>

          {selected && <PaperPanel configs={configs} selected={selected} consistent={run.consistent} />}
          <Limitation>Results are historical simulations with real option premiums, NSE lot sizes, slippage, brokerage and taxes. They do not promise future profits. Picking the best of {configs.length} configurations after the fact overstates what you would have earned; the out-of-sample and walk-forward figures are the honest tests.</Limitation>
        </>
      )}
    </div>
  );
}
