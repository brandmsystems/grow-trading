import { useState } from "react";
import { addPremarketInput } from "../../services/api";
import type { PmReport } from "../../types/api";
import { Card } from "../common/Card";
import { Button, Field, inputCls } from "../common/Controls";
import { ErrorNote } from "../common/States";

const yesterday = () => new Date(Date.now() - 86400000 + 5.5 * 3600000).toISOString().slice(0, 10);

/** FII/DII figures cannot be read by any script (NSE blocks them), so they are typed in from the NSE report. */
export function ManualInputs({ onSaved }: { onSaved: (r: PmReport) => void }) {
  const [day, setDay] = useState(yesterday());
  const [f, setF] = useState({ fii_net_cash: "", dii_net_cash: "", fii_index_fut_long: "", fii_index_fut_short: "" });
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const toNum = (s: string) => (s.trim() === "" ? null : Number(s));
  const run = async (fn: () => Promise<{ report: PmReport }>) => {
    setBusy(true); setErr(null);
    try { onSaved((await fn()).report); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const field = (k: keyof typeof f, label: string) => (
    <Field label={label}><input className={inputCls} inputMode="decimal" aria-label={label} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></Field>
  );
  return (
    <Card title="Enter data no script can read" right={<span>saved with the day's report; the score is recalculated at once</span>}>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        <Field label="FII/DII for day"><input type="date" className={inputCls} aria-label="FII/DII for day" value={day} onChange={(e) => setDay(e.target.value)} /></Field>
        {field("fii_net_cash", "FII net cash (₹ cr)")}{field("dii_net_cash", "DII net cash (₹ cr)")}
        {field("fii_index_fut_long", "FII index fut long")}{field("fii_index_fut_short", "FII index fut short")}
      </div>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <Button disabled={busy} onClick={() => void run(() => addPremarketInput({
          kind: "fii_dii", day, source: "entered by hand (NSE FII/DII report)", fii_net_cash: toNum(f.fii_net_cash), dii_net_cash: toNum(f.dii_net_cash),
          fii_index_fut_long: toNum(f.fii_index_fut_long), fii_index_fut_short: toNum(f.fii_index_fut_short) }))}>Save FII/DII figures</Button>
        <Field label="Scheduled event today" className="min-w-[220px] flex-1">
          <input className={inputCls} aria-label="Scheduled event today" value={title} placeholder="e.g. RBI policy decision 10:00" onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Button disabled={busy || !title.trim()} onClick={() => void run(() => addPremarketInput({ kind: "event", title }))}>Add event</Button>
      </div>
      {err && <div className="mt-2"><ErrorNote>{err}</ErrorNote></div>}
    </Card>
  );
}
