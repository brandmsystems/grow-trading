import { X } from "lucide-react";
import { useLive } from "../../context/LiveContext";
import { describe, isEntry, isExit } from "../../hooks/useAlerts";
import { Pill, type Tone } from "../common/Card";
import { todayIST } from "../../utils/format";
import type { Alert } from "../../types/api";

export function alertTone(a: Alert): Tone {
  if (isExit(a)) return "info";
  if (isEntry(a)) return a.action === "BUY CE" || a.direction === "Bullish" ? "good" : "bad";
  return "neutral";
}

/** Alert history list, reused by the notification panel and the Live Trading page. */
export function AlertList({ alerts, freshId, limit }: { alerts: Alert[]; freshId?: number; limit?: number }) {
  const today = todayIST();
  const list = limit ? alerts.slice(0, limit) : alerts;
  if (!list.length) return <p className="px-1 py-6 text-center text-sm text-slate-500">No signal notifications yet. They appear when the strategy produces a signal.</p>;
  return (
    <ol className="divide-y divide-slate-100 dark:divide-slate-800">
      {list.map((a) => (
        <li key={a.id} className={`flex items-start gap-3 py-2.5 ${a.id === freshId ? "rounded-lg bg-violet-50 px-2 dark:bg-violet-950/30" : ""}`}>
          <Pill tone={alertTone(a)} className="mt-0.5 w-20 justify-center">{a.action}</Pill>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm" title={describe(a)}>{describe(a)}</div>
            <div className="text-xs text-slate-500">
              {a.day !== today ? `${a.day} · ` : ""}{(a.signal_ts ?? a.ts).slice(11, 16)} · {a.mode === "signal" ? "strategy" : a.mode}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}

/** Slide-over panel opened from the bell: signal alerts plus connection/engine events. */
export function NotificationPanel({ onClose }: { onClose: () => void }) {
  const { data, events, fresh } = useLive();
  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="Notifications">
      <div className="absolute inset-0 bg-slate-950/40" onClick={onClose} />
      <div className="fade-in absolute inset-y-0 right-0 flex w-full max-w-md flex-col bg-white shadow-2xl dark:bg-slate-900">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
          <h2 className="font-semibold">Notifications</h2>
          <button onClick={onClose} className="rounded-lg p-2 hover:bg-slate-100 dark:hover:bg-slate-800" aria-label="Close notifications"><X size={18} /></button>
        </div>
        <div className="scroll-thin flex-1 space-y-4 overflow-y-auto px-4 py-3">
          {events.length > 0 && (
            <section>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Connection & engine</h3>
              <ol className="space-y-1.5">
                {events.map((e) => (
                  <li key={e.id} className="flex items-start gap-2 text-sm">
                    <Pill tone={e.tone === "good" ? "good" : e.tone === "bad" ? "bad" : "warn"}>{e.kind}</Pill>
                    <span className="min-w-0 flex-1">{e.text}<span className="block text-xs text-slate-500">{new Date(e.ts).toLocaleTimeString()}</span></span>
                  </li>
                ))}
              </ol>
            </section>
          )}
          <section>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Signals & trades</h3>
            <AlertList alerts={data?.alerts ?? []} freshId={fresh?.id} />
          </section>
          <p className="text-xs text-slate-500">Each signal is stored once on the server, so it never notifies twice. Sound and browser alerts follow the bell setting in the header.</p>
        </div>
      </div>
    </div>
  );
}
