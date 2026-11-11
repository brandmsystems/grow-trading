import { useCallback, useEffect, useRef, useState } from "react";
import { getDashboard, type DashboardQuery } from "../services/api";
import type { Dashboard } from "../types/api";

export type Connection = "connecting" | "online" | "offline";

/**
 * Polls /api/live/dashboard. Faster while the market is open, slower when it's closed,
 * and backs off (up to 30 s) while the backend is unreachable, then recovers automatically.
 */
export function useDashboard(q: DashboardQuery) {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const failures = useRef(0);
  const timer = useRef<number | undefined>(undefined);
  const key = JSON.stringify(q);
  const qRef = useRef(q);
  qRef.current = q;

  const load = useCallback(async () => {
    window.clearTimeout(timer.current);
    let next = 3000;
    try {
      const d = await getDashboard(qRef.current);
      setData(d);
      setError(null);
      setConnection("online");
      setUpdatedAt(new Date());
      failures.current = 0;
      next = d.feed?.market?.state === "open" || d.state !== "stopped" ? 2000 : 10000;
    } catch (e) {
      failures.current += 1;
      setError((e as Error).message);
      setConnection("offline");
      next = Math.min(30000, 2000 * 2 ** failures.current);
    }
    timer.current = window.setTimeout(load, next);
  }, []);

  useEffect(() => {
    load();
    return () => window.clearTimeout(timer.current);
  }, [key, load]);

  return { data, error, connection, updatedAt, refresh: load, setData };
}
