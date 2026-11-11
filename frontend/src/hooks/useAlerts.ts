import { useEffect, useRef, useState } from "react";
import type { Alert } from "../types/api";

const isEntry = (a: Alert) => /^(BUY|SELL) (CE|PE)$/.test(a.action);
const isExit = (a: Alert) => a.action === "SELL" || a.action === "BUY BACK";

export function describe(a: Alert): string {
  const contract = a.strike != null ? `NIFTY ${Math.round(a.strike)} ${a.opt_type ?? ""}`.trim() : "";
  if (isEntry(a)) {
    const px = a.entry_price ?? a.entry ?? a.premium;
    return [contract, px != null ? `@ ₹${px.toFixed(2)}` : "", a.status ?? ""].filter(Boolean).join(" · ");
  }
  if (isExit(a)) return [contract, a.exit_price != null ? `exit @ ₹${a.exit_price.toFixed(2)}` : "", a.reason ?? ""].filter(Boolean).join(" · ");
  return a.reason ?? "No trade";
}

let audio: AudioContext | null = null;
function beep(a: Alert) {
  try {
    audio = audio ?? new AudioContext();
    if (audio.state === "suspended") void audio.resume();
    const notes = isEntry(a) ? [660, 880] : isExit(a) ? [880, 660] : [520];
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
    if (sound) beep(a);
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

export { isEntry, isExit };
