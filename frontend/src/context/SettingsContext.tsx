import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import type { EngineConfig } from "../types/api";

/** Per-browser preferences. Trading state itself lives on the server, never here. */
export interface Settings {
  theme: "dark" | "light";
  sound: boolean;
  timeframe: number;          // chart / signal timeframe
  capital: number | null;     // for position sizing; empty = use Groww's available margin
  riskPct: number;            // % of capital risked per trade
  engine: EngineConfig;       // last used engine settings
  sidebarCollapsed: boolean;  // desktop sidebar shows icons only
}

export const DEFAULT_ENGINE: EngineConfig = {
  trade_mode: "paper", exec_mode: "ATM_BUY", timeframe: 5, entry_start: "09:30", cutoff: "14:30",
  lots: 1, roll_on_expiry_day: true, max_daily_loss: 5000, max_trades_per_day: 6,
  signal_mode: "cross", strategy: "ema_9_21", min_score: 50, order_confirmation: "manual",
  risk_pct: 1, daily_risk_pct: 3, max_open_positions: 1, max_lots: 10, min_balance: 0, stop_mode: "atr", stop_atr: 1, stop_pct: 30,
};
const DEFAULTS: Settings = { theme: "dark", sound: true, timeframe: 5, capital: null, riskPct: 1, engine: DEFAULT_ENGINE, sidebarCollapsed: false };
const KEY = "gt-settings";

function load(): Settings {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const s = JSON.parse(raw);
      // Manual confirmation is always the starting point: never restore "auto" silently.
      return { ...DEFAULTS, ...s, engine: { ...DEFAULT_ENGINE, ...s.engine, order_confirmation: "manual" } };
    }
  } catch { /* private mode or bad JSON: use defaults */ }
  return DEFAULTS;
}

const Ctx = createContext<{ settings: Settings; update: (p: Partial<Settings>) => void } | null>(null);

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<Settings>(load);
  useEffect(() => {
    try { localStorage.setItem(KEY, JSON.stringify(settings)); } catch { /* ignore */ }
    try { localStorage.setItem("gt-theme", settings.theme); } catch { /* ignore */ }
    document.documentElement.classList.toggle("dark", settings.theme === "dark");
  }, [settings]);
  const update = useCallback((p: Partial<Settings>) => setSettings((s) => ({ ...s, ...p })), []);
  return <Ctx.Provider value={{ settings, update }}>{children}</Ctx.Provider>;
}

export function useSettings() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSettings must be used inside SettingsProvider");
  return v;
}
