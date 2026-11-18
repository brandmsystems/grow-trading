import { Bell, Moon, Sun, TrendingUp, Volume2, VolumeX } from "lucide-react";
import { useLive } from "../../context/LiveContext";
import { useSettings } from "../../context/SettingsContext";
import { Dot, Pill } from "../common/Card";
import { num } from "../../utils/format";

const STATE_LABEL: Record<string, string> = { stopped: "Engine off", waiting: "Waiting for market", running: "Running", halted: "Halted", error: "ERROR" };

/** Header: market status, Groww connection, engine state, notifications, sound and theme. */
export function Topbar({ title, onBell }: { title: string; onBell: () => void }) {
  const { settings, update } = useSettings();
  const { data, connection, transport, updatedAt, unread } = useLive();
  const mk = data?.feed?.market ?? data?.market;
  const q = data?.feed?.quote;
  const sig = data?.feed?.signal;
  const st = data?.state ?? "stopped";
  const mode = data?.config?.trade_mode;
  const groww = connection !== "online" ? (connection === "offline" ? "bad" : "neutral")
    : data?.feed?.error ? "bad" : q?.state === "delayed" ? "warn" : "good";
  const growwText = connection === "offline" ? "Backend offline" : connection === "connecting" ? "Connecting"
    : data?.feed?.error ? "Groww error" : q?.state === "delayed" ? "Groww delayed" : "Groww connected";
  return (
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-950/85">
      <div className="flex h-14 items-center gap-3 px-3 sm:px-5">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-green-500 to-blue-600 text-white md:hidden"><TrendingUp size={17} /></span>
        <h1 className="hidden truncate text-base font-semibold sm:block sm:text-lg">{title}</h1>
        {/* Phone: NIFTY price always visible near the top. */}
        {q?.price != null && (
          <span className="num ml-1 text-sm font-semibold sm:hidden">
            {num(q.price, 0)} <span className={(q.change ?? 0) >= 0 ? "text-gain" : "text-loss"}>{num(q.change_pct, 1)}%</span>
          </span>
        )}
        {sig && (
          <span className="sm:hidden"><Pill tone={sig.action === "BUY CE" ? "good" : sig.action === "BUY PE" ? "bad" : "neutral"} title="Latest strategy signal">{sig.action}</Pill></span>
        )}
        <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
          <span className="hidden items-center gap-1.5 text-xs sm:flex" title={updatedAt ? `Last update ${updatedAt.toLocaleTimeString()}${data?.feed?.error ? ` · ${data.feed.error}` : ""}` : undefined}>
            <Dot tone={groww} pulse={groww === "good" && mk?.state === "open"} />{growwText}
          </span>
          {connection === "online" && (
            <span className="hidden sm:inline-flex" title={transport === "socket" ? "Updates are pushed over a WebSocket" : "WebSocket unavailable: the app is polling the server instead"}>
              <Pill tone={transport === "socket" ? "good" : "warn"}>{transport === "socket" ? "Live push" : "Polling"}</Pill>
            </span>
          )}
          {mk && <span className="hidden md:inline-flex"><Pill tone={mk.state === "open" ? "good" : mk.state === "preopen" ? "warn" : "neutral"}>{mk.label}</Pill></span>}
          <span className="hidden lg:inline-flex"><Pill tone={st === "running" ? "good" : st === "error" ? "bad" : st === "halted" ? "warn" : "neutral"}>
            {STATE_LABEL[st] ?? st}{st !== "stopped" && mode ? ` · ${mode.toUpperCase()}` : ""}
          </Pill></span>
          <span className="sm:hidden"><Dot tone={groww} /></span>
          {/* Phone: the desktop "Live push / Polling" pill is hidden, so say so when the WebSocket is down. */}
          {connection === "online" && transport === "polling" && (
            <span className="sm:hidden" title="WebSocket unavailable: the app is polling the server instead"><Pill tone="warn">Polling</Pill></span>
          )}
          <button className="relative rounded-lg p-2 hover:bg-slate-100 dark:hover:bg-slate-800" onClick={onBell} aria-label={`Notifications${unread ? `, ${unread} new` : ""}`}>
            <Bell size={18} />
            {unread > 0 && <span className="absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">{unread > 9 ? "9+" : unread}</span>}
          </button>
          <button className="hidden rounded-lg p-2 hover:bg-slate-100 sm:inline-flex dark:hover:bg-slate-800" title={settings.sound ? "Alert sound on" : "Alert sound off"}
            aria-label="Toggle alert sound"
            onClick={() => {
              update({ sound: !settings.sound });
              if (!settings.sound && "Notification" in window && Notification.permission === "default") void Notification.requestPermission();
            }}>{settings.sound ? <Volume2 size={18} /> : <VolumeX size={18} />}</button>
          <button className="hidden rounded-lg p-2 hover:bg-slate-100 sm:inline-flex dark:hover:bg-slate-800" aria-label="Toggle theme"
            onClick={() => update({ theme: settings.theme === "dark" ? "light" : "dark" })}>
            {settings.theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </button>
        </div>
      </div>
    </header>
  );
}
