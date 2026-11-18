// Labels and helpers shared by the Scalping page and its components.
import { num } from "../../utils/format";
import type { ScalpConfig } from "../../types/api";

export const REASON: Record<string, string> = {
  time_exit: "5-min time exit", stop_loss: "stop-loss", target: "target", square_off: "15:00 square-off",
  daily_loss_limit: "daily loss limit", manual_stop: "you stopped", manual_square_off: "you squared off",
};
export const CHECK: Record<string, string> = {
  net_positive: "Net positive after costs", enough_trades: "Enough trades", profit_factor_1_1: "Profit factor ≥ 1.1",
  most_years_positive: "≥ 75% of years positive", out_of_sample_positive: "Positive out of sample",
};
export const pf = (v: number | null | undefined) => (v == null ? "∞" : num(v));
export const label = (c: ScalpConfig) => `${c.strategy_label} · ${c.contract_label} · ${c.exit_label}`;

export type SortKey = "rank" | "net_pnl" | "oos_net" | "profit_factor" | "max_drawdown" | "win_rate" | "trades";
