import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useApi, waitForJob } from "../../hooks/useApi";
import { describe as describeAlert, isEntry, isExit, useAlerts } from "../../hooks/useAlerts";
import { mockApi, ok } from "../../test/mockApi";
import { makeAlert, makeJob } from "../../test/fixtures";
import type { Alert } from "../../types/api";

describe("useApi", () => {
  it("starts loading, then exposes data", async () => {
    const { result } = renderHook(() => useApi(() => Promise.resolve({ n: 1 }), []));
    expect(result.current.loading).toBe(true);
    expect(result.current.data).toBeNull();
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toEqual({ n: 1 });
    expect(result.current.error).toBeNull();
  });

  it("exposes the error message and no data when the call fails", async () => {
    const { result } = renderHook(() => useApi(() => Promise.reject(new Error("boom")), []));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe("boom");
    expect(result.current.data).toBeNull();
  });

  it("reload() fetches again and clears an earlier error", async () => {
    let n = 0;
    const fn = vi.fn(async () => { n += 1; if (n === 1) throw new Error("first fails"); return n; });
    const { result } = renderHook(() => useApi(fn, []));
    await waitFor(() => expect(result.current.error).toBe("first fails"));
    await act(async () => { await result.current.reload(); });
    expect(result.current.data).toBe(2);
    expect(result.current.error).toBeNull();
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("re-runs when its dependencies change", async () => {
    const fn = vi.fn(async (k: string) => k);
    const { result, rerender } = renderHook(({ k }) => useApi(() => fn(k), [k]), { initialProps: { k: "a" } });
    await waitFor(() => expect(result.current.data).toBe("a"));
    rerender({ k: "b" });
    await waitFor(() => expect(result.current.data).toBe("b"));
  });

  it("ignores a slow, superseded response (no stale data after a newer call)", async () => {
    const resolvers: Record<string, (v: string) => void> = {};
    const fn = (k: string) => new Promise<string>((res) => { resolvers[k] = res; });
    const { result, rerender } = renderHook(({ k }) => useApi(() => fn(k), [k]), { initialProps: { k: "old" } });
    rerender({ k: "new" });
    await act(async () => { resolvers.new("new-data"); });
    await waitFor(() => expect(result.current.data).toBe("new-data"));
    await act(async () => { resolvers.old("old-data"); });
    expect(result.current.data).toBe("new-data");
    expect(result.current.loading).toBe(false);
  });
});

describe("waitForJob", () => {
  it("polls until the job is done, reporting progress each time", async () => {
    const states = [makeJob({ state: "queued", progress: 0 }), makeJob({ state: "running", progress: 0.5 }), makeJob({ state: "done", progress: 1, result: { hash: "h" } })];
    const api = mockApi();
    api.on("GET", /^\/api\/jobs\//, () => states.shift());
    const seen: number[] = [];
    const job = await waitForJob("job 1", (j) => seen.push(j.progress), 1);
    expect(job.state).toBe("done");
    expect(seen).toEqual([0, 0.5, 1]);
    expect(api.callsTo("GET", /^\/api\/jobs\//)[0].path).toBe("/api/jobs/job%201");   // id is URL-encoded
  });

  it("resolves with the failed job (it does not throw) so callers can show job.error", async () => {
    const api = mockApi();
    api.on("GET", /^\/api\/jobs\//, () => makeJob({ state: "error", error: "no data" }));
    const job = await waitForJob("j", undefined, 1);
    expect(job).toMatchObject({ state: "error", error: "no data" });
  });

  it("rejects when the job endpoint itself fails", async () => {
    const api = mockApi();
    api.on("GET", /^\/api\/jobs\//, () => ({ __wire: true, status: 404, body: { ok: false, error: "unknown job" } }));
    await expect(waitForJob("missing", undefined, 1)).rejects.toThrow("unknown job");
    expect(ok()).toBeDefined();
  });
});

describe("alert helpers", () => {
  it("tells entries from exits", () => {
    for (const a of ["BUY CE", "BUY PE", "SELL CE", "SELL PE"]) expect(isEntry({ action: a })).toBe(true);
    for (const a of ["SELL", "BUY BACK"]) expect(isExit({ action: a })).toBe(true);
    expect(isEntry({ action: "SELL" })).toBe(false);
    expect(isExit({ action: "BUY CE" })).toBe(false);
    expect(isEntry({ action: "HOLD" }) || isExit({ action: "HOLD" })).toBe(false);
  });

  it("describes an entry with the contract and premium", () => {
    expect(describeAlert(makeAlert(1, { strike: 25000.4, opt_type: "CE", entry_price: 120.5, status: "signal" }))).toBe("NIFTY 25000 CE · premium ₹120.50 · signal");
  });

  it("describes an exit with the reason and a signed net", () => {
    const win = makeAlert(1, { action: "SELL", exit_price: 135, reason: "target", net: 2100 });
    expect(describeAlert(win)).toBe("NIFTY 25000 CE · exit ₹135.00 · target hit · net +₹2100.00");
    const loss = makeAlert(2, { action: "SELL", exit_price: 90, reason: "stop", net: -450.5 });
    expect(describeAlert(loss)).toContain("net −₹450.50");
    expect(describeAlert(makeAlert(3, { action: "SELL", reason: "something_new" }))).toContain("something_new");
  });

  it("falls back to the reason for no-trade alerts", () => {
    expect(describeAlert({ ...makeAlert(1), action: "HOLD", strike: undefined, reason: "Outside entry window" })).toBe("Outside entry window");
    expect(describeAlert({ ...makeAlert(1), action: "HOLD", strike: undefined, reason: undefined })).toBe("No trade");
  });
});

/**
 * Replaces AudioContext and Notification so sound and browser alerts can be counted.
 * useAlerts keeps one AudioContext for the page's life, so the stub class (and its counter) is shared by all tests.
 */
const beeps = { oscillators: 0 };
class FakeAudio {
  state = "running"; currentTime = 0; destination = {};
  resume() { return Promise.resolve(); }
  createOscillator() { beeps.oscillators += 1; return { frequency: { value: 0 }, connect: (n: unknown) => n, start() {}, stop() {} }; }
  createGain() { return { gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect: (n: unknown) => n }; }
}
function stubNotifications(permission: "granted" | "denied") {
  beeps.oscillators = 0;
  const shown: { title: string; body?: string; tag?: string }[] = [];
  class N { static permission = permission; constructor(title: string, o?: { body?: string; tag?: string }) { shown.push({ title, ...o }); } }
  vi.stubGlobal("AudioContext", FakeAudio);
  vi.stubGlobal("Notification", N);
  return { beeps, shown };
}

describe("live-mode alerts without their fill details (privacy)", () => {
  it("reads cleanly when price, quantity and P&L are not sent", () => {
    const entry = makeAlert(1, { mode: "live", action: "BUY CE", premium: undefined, entry_price: undefined, status: "awaiting your confirmation" });
    const exit = makeAlert(2, { mode: "live", action: "SELL", reason: "target", exit_price: undefined, net: undefined });
    for (const a of [entry, exit]) {
      const text = describeAlert(a);
      expect(text).not.toMatch(/undefined|NaN|null|₹/);
      expect(text.length).toBeGreaterThan(0);
    }
    expect(describeAlert(entry)).toContain("awaiting your confirmation");
    expect(describeAlert(exit)).toContain("target hit");
  });
});

describe("useAlerts", () => {
  const props = (alerts: Alert[] | undefined, sound = true) => ({ alerts, sound });

  it("never notifies for alerts that were already there when the page opened", () => {
    const { shown, beeps } = stubNotifications("granted");
    const { result } = renderHook(({ alerts, sound }) => useAlerts(alerts, sound), { initialProps: props([makeAlert(7), makeAlert(6)]) });
    expect(result.current).toBeNull();
    expect(shown).toHaveLength(0);
    expect(beeps.oscillators).toBe(0);
  });

  it("notifies once for a new alert: sound, browser notification, and a fresh marker", () => {
    const { shown, beeps } = stubNotifications("granted");
    const { result, rerender } = renderHook(({ alerts, sound }) => useAlerts(alerts, sound), { initialProps: props([makeAlert(7)]) });
    const next = [makeAlert(8, { action: "BUY PE", opt_type: "PE", direction: "Bearish", signal_ts: "2026-11-18T10:20:00" }), makeAlert(7)];
    rerender(props(next));
    expect(result.current?.id).toBe(8);
    expect(beeps.oscillators).toBe(2);                              // the two-note entry tone
    expect(shown).toEqual([{ title: "BUY PE · 10:20", body: expect.stringContaining("NIFTY 25000 PE"), tag: "8" }]);

    rerender(props([...next]));                                      // same alerts again: nothing more
    rerender(props([...next]));
    expect(shown).toHaveLength(1);
    expect(beeps.oscillators).toBe(2);
  });

  it("reports only the newest of several alerts that arrive together, but marks them all as seen", () => {
    const { shown } = stubNotifications("granted");
    const { result, rerender } = renderHook(({ alerts, sound }) => useAlerts(alerts, sound), { initialProps: props([makeAlert(1)]) });
    rerender(props([makeAlert(4), makeAlert(3), makeAlert(2), makeAlert(1)]));
    expect(result.current?.id).toBe(4);
    expect(shown).toHaveLength(1);
    rerender(props([makeAlert(4), makeAlert(3), makeAlert(2), makeAlert(1)]));
    expect(shown).toHaveLength(1);
  });

  it("stays silent (no sound, no browser alert) when sound is off, but still flags the alert", () => {
    const { shown, beeps } = stubNotifications("granted");
    const { result, rerender } = renderHook(({ alerts, sound }) => useAlerts(alerts, sound), { initialProps: props([makeAlert(1)], false) });
    rerender(props([makeAlert(2), makeAlert(1)], false));
    expect(result.current?.id).toBe(2);
    expect(shown).toHaveLength(0);
    expect(beeps.oscillators).toBe(0);
  });

  it("does not show a browser notification when permission was denied", () => {
    const { shown, beeps } = stubNotifications("denied");
    const { rerender } = renderHook(({ alerts, sound }) => useAlerts(alerts, sound), { initialProps: props([makeAlert(1)]) });
    rerender(props([makeAlert(2), makeAlert(1)]));
    expect(shown).toHaveLength(0);
    expect(beeps.oscillators).toBeGreaterThan(0);
  });

  it("uses a different tone for exits and puts the alert in the tab title while the tab is hidden", () => {
    const { beeps } = stubNotifications("denied");
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    try {
      const { rerender } = renderHook(({ alerts, sound }) => useAlerts(alerts, sound), { initialProps: props([makeAlert(1)]) });
      rerender(props([makeAlert(2, { action: "SELL", exit_price: 130 }), makeAlert(1)]));
      expect(beeps.oscillators).toBe(2);
      expect(document.title).toBe("● SELL · Grow Trading");
      Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
      act(() => { document.dispatchEvent(new Event("visibilitychange")); });
      expect(document.title).toBe("Grow Trading");
    } finally {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    }
  });

  it("does nothing until alerts are loaded", () => {
    const { shown } = stubNotifications("granted");
    const { result, rerender } = renderHook(({ alerts, sound }) => useAlerts(alerts, sound), { initialProps: props(undefined) });
    rerender(props([makeAlert(9)]));            // first real list = baseline, not a new alert
    expect(result.current).toBeNull();
    expect(shown).toHaveLength(0);
  });
});
