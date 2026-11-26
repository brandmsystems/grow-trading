import {
  Activity, BarChart3, Bot, CalendarRange, CandlestickChart, Database, GraduationCap, Ruler, FlaskConical, LayoutDashboard, Layers, Settings, SlidersHorizontal, Sunrise, Timer, Zap,
  type LucideIcon,
} from "lucide-react";

export interface NavItem { to: string; label: string; short: string; icon: LucideIcon; mobile?: boolean }

/** One list drives the sidebar, the mobile bottom bar and the mobile drawer. */
export const NAV: NavItem[] = [
  { to: "/", label: "Overview", short: "Overview", icon: LayoutDashboard, mobile: true },
  { to: "/live", label: "Live Trading", short: "Live", icon: Activity, mobile: true },
  { to: "/auto", label: "Automated Paper Trading", short: "Auto", icon: Bot },
  { to: "/position", label: "Position Trading", short: "Position", icon: CalendarRange },
  { to: "/premarket", label: "Pre-Market Analysis", short: "Pre-market", icon: Sunrise },
  { to: "/signals", label: "Trading Signals", short: "Signals", icon: Zap, mobile: true },
  { to: "/options", label: "Options Analysis", short: "Options", icon: Layers },
  { to: "/backtest", label: "Backtesting", short: "Backtest", icon: FlaskConical, mobile: true },
  { to: "/compare", label: "Strategy Comparison", short: "Compare", icon: BarChart3 },
  { to: "/scalping", label: "5-Minute Scalping", short: "Scalping", icon: Timer },
  { to: "/data", label: "Market Data", short: "Data", icon: Database },
  { to: "/history", label: "Historical Charts", short: "Charts", icon: CandlestickChart },
  { to: "/range", label: "Daily Range", short: "Range", icon: Ruler },
  { to: "/learn", label: "Options Trading Learning Centre", short: "Learn", icon: GraduationCap },
  { to: "/trading-settings", label: "Trading Settings", short: "Rules", icon: SlidersHorizontal },
  { to: "/account", label: "Account & Settings", short: "Account", icon: Settings },
];
