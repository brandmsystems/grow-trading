import { useState } from "react";
import { BellRing, KeyRound, Palette, RefreshCw, ShieldCheck, Wallet } from "lucide-react";
import { useApi } from "../hooks/useApi";
import { useSettings } from "../context/SettingsContext";
import { getCredentialStatus, relogin } from "../services/api";
import { Card, Pill } from "../components/common/Card";
import { Button, Field, inputCls, PageHeader, PercentInput, Segmented } from "../components/common/Controls";
import { Loading } from "../components/common/States";

export default function Account() {
  const { settings, update } = useSettings();
  const keys = useApi(getCredentialStatus, []);
  const [busy, setBusy] = useState(false);
  const [perm, setPerm] = useState(typeof Notification !== "undefined" ? Notification.permission : "unsupported");

  return (
    <div className="space-y-4">
      <PageHeader title="Account & Settings" actions={
        <Button onClick={async () => { setBusy(true); try { await relogin(); } catch { /* shown below */ } finally { setBusy(false); void keys.reload(); } }} disabled={busy}>
          <RefreshCw size={14} className={busy ? "animate-spin" : ""} /> Re-login to Groww
        </Button>} />

      <div className="grid grid-cols-1 gap-4">
        <Card title="Groww connection" icon={<KeyRound size={16} className="text-blue-600" />}>
          {keys.loading ? <Loading className="h-16" /> : (
            <div className="space-y-2 text-sm">
              <Pill tone={keys.data?.keys ? "good" : "bad"}>{keys.data?.keys ? "Credentials configured" : "Credentials missing"}</Pill>
              <p className="text-slate-500">{keys.data?.message ?? keys.error}</p>
              <p className="text-xs text-slate-500">Credentials are read from <code>.env</code> (GROWW_API_KEY + GROWW_TOTP_SECRET) or <code>keys.txt</code>. They're never shown in the browser.</p>
              <p className="flex items-start gap-1.5 text-xs text-slate-500"><ShieldCheck size={14} className="mt-0.5 shrink-0 text-green-600" />
                This app does not show your Groww balance, funds, profile, positions, orders or real trades. It uses Groww only for market prices and, if you start Live mode, to place the orders you confirm.</p>
            </div>
          )}
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
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
            <Field label="Capital ₹"><input type="number" min={0} className={inputCls} placeholder="Paper account capital" value={settings.capital ?? ""}
              onChange={(e) => update({ capital: e.target.value ? Number(e.target.value) : null })} /></Field>
            <Field label="Risk per trade %"><PercentInput value={settings.riskPct} onCommit={(v) => update({ riskPct: v })} /></Field>
          </div>
          <p className="mt-2 text-xs text-slate-500">Saved in this browser only.</p>
        </Card>
      </div>
    </div>
  );
}
