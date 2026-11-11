import { Bell, BellOff, Moon, Sun, TrendingUp } from "lucide-react";
import type { Connection } from "../../hooks/useDashboard";
import type { Dashboard } from "../../types/api";
import { useSettings } from "../../context/SettingsContext";
import { Dot, Pill } from "../common/Card";

// Pages not yet ported to React are still served by Flask (same origin in production).
const LEGACY = import.meta.env.DEV ? "http://127.0.0.1:5000" : "";
const NAV = [["Backtest", "/"], ["Compare", "/compare"], ["Signals", "/signals"], ["Data", "/data"], ["History", "/history"], ["Account", "/account"]];
const STATE_LABEL: Record<string, string> = { stopped: "Engine off", waiting: "Waiting for market", running: "Running", halted: "Halted", error: "ERROR" };

export function Header({ data, connection, updatedAt }: { data: Dashboard | null; connection: Connection; updatedAt: Date | null }) {
  const { settings, update } = useSettings();
  const mk = data?.feed?.market ?? data?.market;
  const st = data?.state ?? "stopped";
  const mode = data?.config?.trade_mode;
  const quoteState = data?.feed?.quote?.state;
  return (
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5">
        <a href="/app/" className="flex items-center gap-2 font-semibold">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-green-600 text-white"><TrendingUp size={16} /></span>
          Grow Trading
        </a>
        <nav className="flex flex-wrap gap-1 text-sm">
          <span className="rounded-md bg-slate-100 px-2.5 py-1 font-medium dark:bg-slate-800">Live</span>
          {NAV.map(([label, href]) => (
            <a key={href} href={LEGACY + href} className="rounded-md px-2.5 py-1 text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800">{label}</a>
          ))}
        </nav>
        <div className="ml-auto flex flex-wrap items-center gap-2 text-xs">
          <span className="flex items-center gap-1.5" title={updatedAt ? `Last update ${updatedAt.toLocaleTimeString()}` : undefined}>
            <Dot tone={connection === "online" ? (quoteState === "delayed" ? "warn" : "good") : connection === "offline" ? "bad" : "neutral"} />
            {connection === "online" ? (quoteState === "delayed" ? "Groww data delayed" : "Connected") : connection === "offline" ? "Disconnected, retrying" : "Connecting"}
          </span>
          {mk && <Pill tone={mk.state === "open" ? "good" : mk.state === "preopen" ? "warn" : "neutral"}>Market: {mk.label}</Pill>}
          <Pill tone={st === "running" ? "good" : st === "error" ? "bad" : st === "halted" ? "warn" : "neutral"}>
            {STATE_LABEL[st] ?? st}{st !== "stopped" && mode ? ` · ${mode.toUpperCase()}` : ""}
          </Pill>
          <button
            className="rounded-md p-1.5 hover:bg-slate-100 dark:hover:bg-slate-800" title={settings.sound ? "Alerts sound on" : "Alerts sound off"}
            aria-label="Toggle alert sound"
            onClick={() => {
              update({ sound: !settings.sound });
              if (!settings.sound && "Notification" in window && Notification.permission === "default") void Notification.requestPermission();
            }}
          >{settings.sound ? <Bell size={16} /> : <BellOff size={16} />}</button>
          <button className="rounded-md p-1.5 hover:bg-slate-100 dark:hover:bg-slate-800" aria-label="Toggle theme"
            onClick={() => update({ theme: settings.theme === "dark" ? "light" : "dark" })}>
            {settings.theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          </button>
        </div>
      </div>
    </header>
  );
}
