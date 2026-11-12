import { useCallback, useEffect, useRef, useState } from "react";
import { io, type Socket } from "socket.io-client";
import { getDashboard, type DashboardQuery } from "../services/api";
import type { Dashboard } from "../types/api";

export type Connection = "connecting" | "online" | "offline";
/** How the data is arriving: pushed over the WebSocket, or fetched by REST polling (the fallback). */
export type Transport = "socket" | "polling";

interface PushEvent { seq: number; room: string; server_time: string; data: Dashboard | null; error: string | null }

const CHECK_MS = 2000;   // how often the fallback checks whether the socket is still healthy (no API call)

/**
 * Live dashboard data for the whole app (used once, by LiveProvider).
 *
 * * Primary: Socket.IO push (`/socket.io`). The server sends `dashboard` events when the content
 *   changes and `heartbeat` events otherwise. Events carry a per-room sequence number; anything
 *   not newer than the last one seen is dropped, so duplicates and late events never overwrite data.
 * * Fallback: the existing REST poll of /api/live/dashboard. It runs only while the socket is
 *   disconnected, unsubscribed or stale (no event for the server's heartbeat threshold), so a healthy
 *   socket means no repeated API calls. Polling is faster while the market is open and backs off
 *   (up to 30 s) while the backend is unreachable.
 * * Socket.IO reconnects automatically; on reconnect the hook subscribes again.
 */
export function useDashboard(q: DashboardQuery) {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [transport, setTransport] = useState<Transport>("polling");
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const failures = useRef(0);
  const timer = useRef<number | undefined>(undefined);
  const key = JSON.stringify(q);
  const qRef = useRef(q);
  qRef.current = q;

  const sock = useRef<Socket | null>(null);
  const room = useRef<string | null>(null);
  const lastSeq = useRef(0);
  const lastEvent = useRef(0);
  const staleMs = useRef(15000);
  const subscribed = useRef(false);

  const socketHealthy = () => !!sock.current?.connected && subscribed.current && Date.now() - lastEvent.current < staleMs.current;

  const apply = useCallback((d: Dashboard) => {
    setData(d); setError(null); setConnection("online"); setUpdatedAt(new Date());
    failures.current = 0;
  }, []);

  // REST poll: only does a request when the socket isn't delivering.
  const load = useCallback(async (force = false) => {
    window.clearTimeout(timer.current);
    let next = CHECK_MS;
    if (!force && socketHealthy()) {
      timer.current = window.setTimeout(load, next);
      return;
    }
    setTransport("polling");
    try {
      const d = await getDashboard(qRef.current);
      apply(d);
      next = d.feed?.market?.state === "open" || d.state !== "stopped" ? 2000 : 10000;
    } catch (e) {
      failures.current += 1;
      setError((e as Error).message);
      setConnection("offline");
      next = Math.min(30000, 2000 * 2 ** failures.current);
    }
    timer.current = window.setTimeout(load, next);
  }, [apply]); // eslint-disable-line react-hooks/exhaustive-deps

  // Socket: one connection for the provider's lifetime; cleaned up on unmount.
  useEffect(() => {
    const s = io({ path: "/socket.io", transports: ["websocket"], reconnection: true,
      reconnectionDelay: 1000, reconnectionDelayMax: 10000, timeout: 10000 });
    sock.current = s;
    const subscribe = () => {
      subscribed.current = false; room.current = null; lastSeq.current = 0;
      s.emit("subscribe", qRef.current);
    };
    s.on("connect", subscribe);
    s.on("hello", (h: { heartbeat_stale_sec?: number }) => { if (h?.heartbeat_stale_sec) staleMs.current = h.heartbeat_stale_sec * 1000; });
    const accept = (ev: PushEvent) => {
      if (room.current !== ev.room) { room.current = ev.room; lastSeq.current = 0; }
      if (ev.seq <= lastSeq.current) return false;      // duplicate or out of order
      lastSeq.current = ev.seq;
      lastEvent.current = Date.now();
      subscribed.current = true;
      return true;
    };
    s.on("dashboard", (ev: PushEvent) => {
      if (!accept(ev) || !ev.data) return;
      apply(ev.data);
      setTransport("socket");
    });
    s.on("heartbeat", (ev: PushEvent) => {
      if (!accept(ev)) return;
      setTransport("socket");
      setConnection("online");
      if (ev.error) setError(ev.error);
    });
    s.on("subscribe_error", (e: { error: string }) => { subscribed.current = false; setError(e.error); });
    s.on("disconnect", () => { subscribed.current = false; setTransport("polling"); void load(true); });
    return () => {
      s.removeAllListeners();
      s.disconnect();
      sock.current = null;
    };
  }, [apply, load]);

  // New settings: resubscribe (socket) and refresh once (covers a socket that isn't up yet).
  useEffect(() => {
    if (sock.current?.connected) {
      subscribed.current = false; room.current = null; lastSeq.current = 0;
      sock.current.emit("subscribe", qRef.current);
    }
    void load(!sock.current?.connected);
    return () => window.clearTimeout(timer.current);
  }, [key, load]);

  return { data, error, connection, transport, updatedAt, refresh: () => load(true), setData };
}
