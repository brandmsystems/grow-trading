import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useDashboard, type Connection } from "../hooks/useDashboard";
import { beep, useAlerts } from "../hooks/useAlerts";
import { getLiveTrades } from "../services/api";
import { useSettings } from "./SettingsContext";
import { todayIST } from "../utils/format";
import type { Alert, Dashboard, LiveTrade } from "../types/api";

/** Status events raised by the app itself from real state changes (never sample data). */
export interface StatusEvent { id: string; ts: string; kind: "connection" | "engine"; tone: "good" | "bad" | "warn"; text: string }

interface LiveValue {
  data: Dashboard | null;
  error: string | null;
  connection: Connection;
  updatedAt: Date | null;
  refresh: () => void;
  trades: LiveTrade[];
  fresh: Alert | null;
  events: StatusEvent[];
  unread: number;
  markRead: () => void;
}

const Ctx = createContext<LiveValue | null>(null);
const SEEN_KEY = "gt-alerts-seen";

/**
 * One shared live poll for the whole app: the header, Overview, Live Trading and Options
 * pages read the same /api/live/dashboard response, so navigating never duplicates calls.
 */
export function LiveProvider({ children }: { children: ReactNode }) {
  const { settings } = useSettings();
  const eng = settings.engine;
  const { data, error, connection, updatedAt, refresh } = useDashboard({
    tf: settings.timeframe, mode: eng.trade_mode, exec_mode: eng.exec_mode, capital: settings.capital, risk_pct: settings.riskPct,
  });
  const fresh = useAlerts(data?.alerts, settings.sound);

  // Today's engine trades: refetched only when the engine's counters change.
  const [trades, setTrades] = useState<LiveTrade[]>([]);
  // The engine's own session (also after it stops): its mode and its day, e.g. a replay's day.
  const mode = data?.config?.trade_mode ?? eng.trade_mode;
  const day = data?.day ?? todayIST();
  const tradesKey = `${mode}|${day}|${data?.trades_today}|${data?.realised_today}|${data?.position ? 1 : 0}`;
  useEffect(() => {
    if (!data) return;
    getLiveTrades(mode, day).then(setTrades).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tradesKey]);

  // Connection and engine-state changes become notifications.
  const [events, setEvents] = useState<StatusEvent[]>([]);
  const prevConn = useRef<Connection>("connecting");
  const prevState = useRef<string | null>(null);
  const push = (e: Omit<StatusEvent, "id" | "ts">) => {
    setEvents((list) => [{ ...e, id: `${Date.now()}-${Math.random()}`, ts: new Date().toISOString() }, ...list].slice(0, 30));
    if (settings.sound && e.tone !== "good") beep("warn");
  };
  useEffect(() => {
    if (prevConn.current === "online" && connection === "offline") push({ kind: "connection", tone: "bad", text: `Lost connection to the backend: ${error ?? ""}` });
    if (prevConn.current === "offline" && connection === "online") push({ kind: "connection", tone: "good", text: "Connection restored" });
    prevConn.current = connection;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connection]);
  useEffect(() => {
    const st = data?.state ?? null;
    if (st && prevState.current && st !== prevState.current) {
      const tone = st === "error" ? "bad" : st === "halted" ? "warn" : "good";
      push({ kind: "engine", tone, text: `Engine ${prevState.current} → ${st}${data?.halt_reason ? `: ${data.halt_reason}` : ""}` });
    }
    prevState.current = st;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.state]);

  // Unread badge: alerts newer than the last one you opened the panel on, plus new status events.
  const [seen, setSeen] = useState<number>(() => { try { return Number(localStorage.getItem(SEEN_KEY)) || 0; } catch { return 0; } });
  const [seenEvents, setSeenEvents] = useState(0);
  const alerts = data?.alerts ?? [];
  const unread = alerts.filter((a) => a.id > seen).length + Math.max(0, events.length - seenEvents);
  const markRead = () => {
    const top = alerts[0]?.id ?? seen;
    setSeen(top);
    setSeenEvents(events.length);
    try { localStorage.setItem(SEEN_KEY, String(top)); } catch { /* ignore */ }
  };

  return (
    <Ctx.Provider value={{ data, error, connection, updatedAt, refresh, trades, fresh, events, unread, markRead }}>
      {children}
    </Ctx.Provider>
  );
}

export function useLive() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useLive must be used inside LiveProvider");
  return v;
}
