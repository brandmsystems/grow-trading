import { useState } from "react";
import { BellRing, KeyRound, Palette, RefreshCw, User, Wallet } from "lucide-react";
import { useApi } from "../hooks/useApi";
import { useSettings } from "../context/SettingsContext";
import { getCredentialStatus, getFunds, getProfile, relogin } from "../services/api";
import { Card, Pill, Stat } from "../components/common/Card";
import { Button, Field, inputCls, PageHeader, Segmented } from "../components/common/Controls";
import { ErrorNote, Loading } from "../components/common/States";
import { inr } from "../utils/format";

const label = (k: string) => k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export default function Account() {
  const { settings, update } = useSettings();
  const keys = useApi(getCredentialStatus, []);
  const profile = useApi(getProfile, []);
  const funds = useApi(getFunds, []);
  const [busy, setBusy] = useState(false);
  const [perm, setPerm] = useState(typeof Notification !== "undefined" ? Notification.permission : "unsupported");
  const f = (funds.data ?? {}) as Record<string, unknown>;
  const fno = (f.fno_margin_details ?? {}) as Record<string, unknown>;
  const n = (v: unknown) => (typeof v === "number" ? v : null);

  return (
    <div className="space-y-4">
      <PageHeader title="Account & Settings" actions={
        <Button onClick={async () => { setBusy(true); try { await relogin(); } catch { /* shown below */ } finally { setBusy(false); void profile.reload(); void funds.reload(); void keys.reload(); } }} disabled={busy}>
          <RefreshCw size={14} className={busy ? "animate-spin" : ""} /> Re-login to Groww
        </Button>} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card title="Groww connection" icon={<KeyRound size={16} className="text-blue-600" />}>
          {keys.loading ? <Loading className="h-16" /> : (
            <div className="space-y-2 text-sm">
              <Pill tone={keys.data?.keys ? "good" : "bad"}>{keys.data?.keys ? "Credentials configured" : "Credentials missing"}</Pill>
              <p className="text-slate-500">{keys.data?.message ?? keys.error}</p>
              <p className="text-xs text-slate-500">Credentials are read from <code>.env</code> (GROWW_API_KEY + GROWW_TOTP_SECRET) or <code>keys.txt</code>. They're never shown in the browser.</p>
            </div>
          )}
        </Card>
        <Card title="Funds" icon={<Wallet size={16} className="text-green-600" />} className="lg:col-span-2">
          {funds.loading ? <Loading className="h-16" /> : funds.error ? <ErrorNote>{funds.error}</ErrorNote> : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat label="Cash" value={inr(n(f.clear_cash))} className="text-lg" />
              <Stat label="Margin used" value={inr(n(f.net_margin_used))} className="text-lg" />
              <Stat label="F&O option buying" value={inr(n(fno.option_buy_balance_available))} className="text-lg text-gain" tip="What the order calculator uses when you leave capital empty." />
              <Stat label="Collateral available" value={inr(n(f.collateral_available))} className="text-lg" />
            </div>
          )}
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card title="Profile" icon={<User size={16} className="text-slate-500" />}>
          {profile.loading ? <Loading className="h-16" /> : profile.error ? <ErrorNote>{profile.error}</ErrorNote> : (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
              {Object.entries(profile.data ?? {}).map(([k, v]) => (
                <div key={k} className="contents"><dt className="text-slate-500">{label(k)}</dt>
                  <dd className="num truncate text-right">{Array.isArray(v) ? v.join(", ") : typeof v === "boolean" ? (v ? "Yes" : "No") : String(v ?? "—")}</dd></div>
              ))}
            </dl>
          )}
        </Card>
        <Card title="Appearance & alerts" icon={<Palette size={16} className="text-violet-600" />}>
          <div className="space-y-3 text-sm">
            <Field label="Theme"><Segmented value={settings.theme} onChange={(v) => update({ theme: v })} options={[{ value: "dark", label: "Dark" }, { value: "light", label: "Light" }]} /></Field>
            <label className="flex items-center gap-2"><input type="checkbox" checked={settings.sound} onChange={(e) => update({ sound: e.target.checked })} /> Sound and browser alerts for new signals</label>
            <div className="flex flex-wrap items-center gap-2">
              <BellRing size={15} className="text-slate-500" /> Browser notifications: <Pill tone={perm === "granted" ? "good" : perm === "denied" ? "bad" : "neutral"}>{perm}</Pill>
              {perm === "default" && <Button onClick={async () => setPerm(await Notification.requestPermission())}>Allow</Button>}
            </div>
          </div>
        </Card>
        <Card title="Order calculator defaults" icon={<Wallet size={16} className="text-orange-600" />}>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Capital ₹"><input type="number" min={0} className={inputCls} placeholder="Groww margin" value={settings.capital ?? ""}
              onChange={(e) => update({ capital: e.target.value ? Number(e.target.value) : null })} /></Field>
            <Field label="Risk per trade %"><input type="number" min={0.1} max={100} step={0.5} className={inputCls} value={settings.riskPct}
              onChange={(e) => update({ riskPct: Number(e.target.value) || 1 })} /></Field>
          </div>
          <p className="mt-2 text-xs text-slate-500">Saved in this browser only.</p>
        </Card>
      </div>
    </div>
  );
}
