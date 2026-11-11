import { useEffect, useRef, useState } from "react";
import type { Alert } from "../types/api";

export const isEntry = (a: Pick<Alert, "action">) => /^(BUY|SELL) (CE|PE)$/.test(a.action);
export const isExit = (a: Pick<Alert, "action">) => a.action === "SELL" || a.action === "BUY BACK";

const REASON: Record<string, string> = {
  opposite_cross: "opposite crossover", square_off: "15:00 square-off", target: "target hit", stop: "stop hit",
  daily_loss_limit: "daily loss limit", manual_square_off: "squared off manually", manual_stop: "engine stopped",
};

export function describe(a: Alert): string {
  const contract = a.strike != null ? `NIFTY ${Math.round(a.strike)} ${a.opt_type ?? ""}`.trim() : "";
  if (isEntry(a)) {
    const px = a.entry_price ?? a.entry ?? a.premium;
    return [contract, px != null ? `premium ₹${px.toFixed(2)}` : "", a.status ?? ""].filter(Boolean).join(" · ");
  }
  if (isExit(a)) return [contract, a.exit_price != null ? `exit ₹${a.exit_price.toFixed(2)}` : "", a.reason ? REASON[a.reason] ?? a.reason : "",
    a.net != null ? `net ${a.net >= 0 ? "+" : "−"}₹${Math.abs(a.net).toFixed(2)}` : ""].filter(Boolean).join(" · ");
  return a.reason ?? "No trade";
}

let audio: AudioContext | null = null;
export function beep(kind: "entry" | "exit" | "info" | "warn") {
  try {
    audio = audio ?? new AudioContext();
    if (audio.state === "suspended") void audio.resume();
    const notes = kind === "entry" ? [660, 880] : kind === "exit" ? [880, 660] : kind === "warn" ? [440, 330] : [520];
    notes.forEach((f, i) => {
      const o = audio!.createOscillator();
      const g = audio!.createGain();
      const t = audio!.currentTime + i * 0.18;
      o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.25, t + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.16);
      o.connect(g).connect(audio!.destination);
      o.start(t);
      o.stop(t + 0.17);
    });
  } catch { /* audio not available */ }
}

/**
 * Notifies once per new alert id (never for alerts that existed when the page opened):
 * sound, browser notification and a flash. The server stores each signal once, so a signal
 * can't alert twice even across reloads.
 */
export function useAlerts(alerts: Alert[] | undefined, sound: boolean) {
  const lastId = useRef<number | null>(null);
  const [fresh, setFresh] = useState<Alert | null>(null);

  useEffect(() => {
    if (!alerts) return;
    const newest = alerts[0]?.id ?? 0;
    if (lastId.current === null) { lastId.current = newest; return; }
    const added = alerts.filter((a) => a.id > (lastId.current ?? 0)).reverse();
    if (!added.length) return;
    lastId.current = newest;
    const a = added[added.length - 1];
    setFresh(a);
    if (sound) beep(isEntry(a) ? "entry" : isExit(a) ? "exit" : "info");
    if (sound && "Notification" in window && Notification.permission === "granted") {
      try { new Notification(`${a.action} · ${(a.signal_ts ?? a.ts).slice(11, 16)}`, { body: describe(a), tag: String(a.id) }); } catch { /* ignore */ }
    }
    if (document.hidden) document.title = `● ${a.action} · Grow Trading`;
  }, [alerts, sound]);

  useEffect(() => {
    const onVis = () => { if (!document.hidden) document.title = "Grow Trading"; };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  return fresh;
}
