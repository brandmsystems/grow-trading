import type { Alert } from "../../types/api";
import { describe, isEntry, isExit } from "../../hooks/useAlerts";
import { Card, Pill } from "../common/Card";

export function Notifications({ alerts, freshId }: { alerts: Alert[]; freshId?: number }) {
  const today = new Date().toISOString().slice(0, 10);
  return (
    <Card title="Notifications" right={alerts.length ? `last ${alerts.length}` : undefined}>
      <ol className="max-h-80 divide-y divide-slate-200 overflow-y-auto dark:divide-slate-800">
        {alerts.length === 0 && <li className="px-4 py-6 text-center text-sm text-slate-500">No notifications yet.</li>}
        {alerts.map((a) => {
          const tone = isExit(a) ? "info" : isEntry(a) ? (a.direction === "Bullish" || a.action.endsWith("CE") && a.action.startsWith("BUY") ? "good" : "bad") : "neutral";
          return (
            <li key={a.id} className={`grid grid-cols-[3rem_6.5rem_1fr] items-center gap-2 px-4 py-2 text-sm ${a.id === freshId ? "bg-blue-50 dark:bg-blue-950/40" : ""}`}>
              <span className="num text-xs text-slate-500">{a.day !== today ? a.day.slice(5) : (a.signal_ts ?? a.ts).slice(11, 16)}</span>
              <Pill tone={tone} className="justify-center">{a.action}</Pill>
              <span className="truncate text-slate-600 dark:text-slate-300" title={describe(a)}>
                {describe(a)} <span className="text-xs text-slate-400">· {a.mode === "signal" ? "strategy" : a.mode}</span>
              </span>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
