import {
  Activity, BarChart3, Bot, CandlestickChart, Database, FlaskConical, LayoutDashboard, Layers, Settings, Sunrise, Timer, Zap,
  type LucideIcon,
} from "lucide-react";

export interface NavItem { to: string; label: string; short: string; icon: LucideIcon; mobile?: boolean }

/** One list drives the sidebar, the mobile bottom bar and the mobile drawer. */
export const NAV: NavItem[] = [
  { to: "/", label: "Overview", short: "Overview", icon: LayoutDashboard, mobile: true },
  { to: "/live", label: "Live Trading", short: "Live", icon: Activity, mobile: true },
  { to: "/auto", label: "Automated Paper Trading", short: "Auto", icon: Bot },
  { to: "/premarket", label: "Pre-Market Analysis", short: "Pre-market", icon: Sunrise },
  { to: "/signals", label: "Trading Signals", short: "Signals", icon: Zap, mobile: true },
  { to: "/options", label: "Options Analysis", short: "Options", icon: Layers },
  { to: "/backtest", label: "Backtesting", short: "Backtest", icon: FlaskConical, mobile: true },
  { to: "/compare", label: "Strategy Comparison", short: "Compare", icon: BarChart3 },
  { to: "/scalping", label: "5-Minute Scalping", short: "Scalping", icon: Timer },
  { to: "/data", label: "Market Data", short: "Data", icon: Database },
  { to: "/history", label: "Historical Charts", short: "Charts", icon: CandlestickChart },
  { to: "/account", label: "Account & Settings", short: "Account", icon: Settings },
];
