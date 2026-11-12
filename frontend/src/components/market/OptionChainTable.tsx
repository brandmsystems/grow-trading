import { useCallback, useEffect, useRef, useState } from "react";
import { RefreshCw, Table2 } from "lucide-react";
import type { ChainSide, OptionChain } from "../../types/api";
import { getOptionChain } from "../../services/api";
import { dmy, hms, num, pct } from "../../utils/format";
import { Card, Stat } from "../common/Card";
import { Button, selectInline } from "../common/Controls";
import { ErrorNote, Limitation, Loading } from "../common/States";

const big = (v: number | null | undefined) =>
  v == null ? "—" : Math.abs(v) >= 1e7 ? `${num(v / 1e7, 2)} Cr` : Math.abs(v) >= 1e5 ? `${num(v / 1e5, 2)} L` : num(v, 0);
const sgn = (v: number | null | undefined, f: (x: number) => string) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${f(Math.abs(v))}`);
const tone = (v: number | null | undefined) => (v == null || v === 0 ? "" : v > 0 ? "text-gain" : "text-loss");

/** One side's cells, ordered outward from the strike column (mirrored for CE). */
function cells(s: ChainSide | null, itm: boolean, mirror: boolean) {
  const bg = itm ? "bg-amber-50/70 dark:bg-amber-950/20" : "";
  const list = [
    <td key="ltp" className={`num px-1.5 text-right font-semibold ${bg}`}>{s?.ltp != null ? num(s.ltp) : "—"}</td>,
    <td key="chg" className={`num px-1.5 text-right ${tone(s?.change)} ${bg}`}>{s?.change != null ? <>{sgn(s.change, (x) => num(x))}<span className="block text-[10px] opacity-80">{sgn(s.change_pct, (x) => pct(x))}</span></> : "—"}</td>,
    <td key="iv" className={`num px-1.5 text-right ${bg}`}>{s?.iv != null ? num(s.iv, 1) : "—"}</td>,
    <td key="d" className={`num px-1.5 text-right ${bg}`}>{s?.delta != null ? num(s.delta, 2) : "—"}</td>,
    <td key="vol" className={`num px-1.5 text-right ${bg}`}>{big(s?.volume)}</td>,
    <td key="oic" className={`num px-1.5 text-right ${tone(s?.oi_change)} ${bg}`}>{s?.oi_change != null ? <>{sgn(s.oi_change, big)}<span className="block text-[10px] opacity-80">{sgn(s.oi_change_pct, (x) => pct(x))}</span></> : "—"}</td>,
    <td key="oi" className={`num px-1.5 text-right ${bg}`}>{big(s?.oi)}</td>,
  ];
  return mirror ? list.reverse() : list;
}
const HEAD = ["LTP ₹", "Chg", "IV", "Δ", "Volume", "OI chg", "OI"];

/**
 * Live NIFTY option chain from Groww: CE and PE side by side around ATM. Premiums are the
 * option contracts' own prices; the NIFTY spot is shown separately above the table.
 */
export function OptionChainTable() {
  const [expiry, setExpiry] = useState<string | undefined>();
  const [width, setWidth] = useState(10);
  const [data, setData] = useState<OptionChain | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);
  const box = useRef<HTMLDivElement>(null);
  const centred = useRef("");

  const load = useCallback(async () => {
    const n = ++seq.current;
    setBusy(true);
    try {
      const d = await getOptionChain(expiry, width);
      if (n === seq.current) { setData(d); setErr(null); }
    } catch (e) { if (n === seq.current) setErr((e as Error).message); }
    finally { if (n === seq.current) setBusy(false); }
  }, [expiry, width]);

  useEffect(() => { void load(); }, [load]);
  // Refresh every 15 s while the market is open (Groww chain is cached 10 s server-side, quotes 60 s).
  useEffect(() => {
    if (data?.market !== "open") return;
    const t = setInterval(() => { void load(); }, 15000);
    return () => clearInterval(t);
  }, [data?.market, load]);

  // On narrow screens, open the table centred on the strike column (once per expiry/width).
  useEffect(() => {
    const el = box.current, key = `${data?.expiry}|${data?.width}`;
    if (!el || !data || centred.current === key) return;
    centred.current = key;
    el.scrollLeft = (el.scrollWidth - el.clientWidth) / 2;
  }, [data]);

  const spot = data?.spot.price ?? data?.underlying_ltp ?? null;
  return (
    <Card title="Option chain" icon={<Table2 size={16} className="text-violet-600" />}
      right={
        <div className="flex flex-wrap items-center gap-2">
          <select aria-label="Expiry" className={selectInline} value={data?.expiry ?? expiry ?? ""} onChange={(e) => setExpiry(e.target.value)}>
            {(data?.expiries ?? []).map((e) => <option key={e} value={e}>{dmy(e)}</option>)}
          </select>
          <select aria-label="Strikes" className={selectInline} value={width} onChange={(e) => setWidth(Number(e.target.value))}>
            {[5, 10, 15, 20].map((w) => <option key={w} value={w}>ATM ±{w}</option>)}
          </select>
          <Button onClick={() => void load()} disabled={busy}><RefreshCw size={14} className={busy ? "animate-spin" : ""} /></Button>
        </div>
      }>
      {err && <ErrorNote>{err}</ErrorNote>}
      {!data ? (!err && <Loading text="Loading the option chain from Groww…" />) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Stat label="NIFTY spot (index)" value={num(spot)} sub={data.spot.change != null ? `${sgn(data.spot.change, (x) => num(x))} (${sgn(data.spot.change_pct, (x) => pct(x, 2))})` : undefined}
              className={tone(data.spot.change)} />
            <Stat label="ATM strike" value={num(data.atm, 0)} sub="nearest to spot" />
            <Stat label="Expiry" value={dmy(data.expiry)} sub={`${data.days_to_expiry} day${data.days_to_expiry === 1 ? "" : "s"} · lot ${data.lot_size ?? "—"}`} />
            <Stat label="Call OI (shown)" value={big(data.totals.ce_oi)} sub={`volume ${big(data.totals.ce_volume)}`} />
            <Stat label="Put OI (shown)" value={big(data.totals.pe_oi)} sub={`volume ${big(data.totals.pe_volume)}`} />
            <Stat label="Put/call OI ratio" value={data.totals.pcr != null ? num(data.totals.pcr, 2) : "—"} sub="calculated, shown strikes"
              tip="Put OI ÷ call OI over the strikes in the table. Calculated here from Groww's OI, not published by NSE." />
          </div>
          <div ref={box} className="scroll-thin mt-3 max-h-[640px] overflow-auto rounded-xl border border-slate-200 dark:border-slate-800">
            <table className="w-full min-w-[980px] text-xs">
              <thead className="sticky top-0 z-10 bg-white dark:bg-slate-900">
                <tr className="text-center text-[11px] font-semibold">
                  <th colSpan={7} className="bg-green-50 py-1 text-green-700 dark:bg-green-950/30 dark:text-green-300">CALLS (CE)</th>
                  <th className="bg-slate-100 dark:bg-slate-800">Strike</th>
                  <th colSpan={7} className="bg-red-50 py-1 text-red-700 dark:bg-red-950/30 dark:text-red-300">PUTS (PE)</th>
                </tr>
                <tr className="text-right text-slate-500">
                  {[...HEAD].reverse().map((h) => <th key={`c${h}`} className="px-1.5 py-1 font-medium">{h}</th>)}
                  <th className="bg-slate-100 px-2 text-center font-medium dark:bg-slate-800">₹</th>
                  {HEAD.map((h) => <th key={`p${h}`} className="px-1.5 py-1 font-medium">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.strike} className={`border-t border-slate-100 dark:border-slate-800 ${r.atm ? "outline outline-2 -outline-offset-2 outline-violet-500" : ""}`}>
                    {cells(r.ce, spot != null && r.strike < spot, true)}
                    <td className={`num bg-slate-100 px-2 text-center font-bold dark:bg-slate-800 ${r.atm ? "text-violet-700 dark:text-violet-300" : ""}`}>
                      {num(r.strike, 0)}{r.atm && <span className="block text-[9px] font-semibold uppercase">ATM</span>}
                    </td>
                    {cells(r.pe, spot != null && r.strike > spot, false)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-slate-500">
            Shaded cells are in the money. Chain as of {hms(data.chain_as_of)}{data.chain_error ? ` (last refresh failed: ${data.chain_error})` : ""};
            change and OI change as of {hms(data.quotes_as_of)}{data.quotes_error ? ` (failed: ${data.quotes_error})` : ""}.
          </p>
          <Limitation>
            All values are from Groww. LTP, volume, OI, IV and Greeks come from Groww's option chain for every strike. Premium change and
            OI change come from each contract's own quote, fetched only for ATM ±{data.quote_width} to stay within Groww's rate limits; other
            strikes show "—" rather than an estimate. OI change is the quote's OI minus its previous-day OI. Groww has no history of IV or Greeks.
          </Limitation>
        </>
      )}
    </Card>
  );
}
