import { NavLink } from "react-router-dom";
import { ChevronsLeft, ChevronsRight, TrendingUp } from "lucide-react";
import { NAV } from "./nav";
import { useSettings } from "../../context/SettingsContext";
import { useLive } from "../../context/LiveContext";
import { Dot } from "../common/Card";
import { num } from "../../utils/format";

/** Desktop/tablet sidebar. Full width on large screens (collapsible), icon rail on tablets. */
export function Sidebar() {
  const { settings, update } = useSettings();
  const { data } = useLive();
  const collapsed = settings.sidebarCollapsed;
  const q = data?.feed?.quote;
  const sig = data?.feed?.signal;
  return (
    <aside className={`sticky top-0 hidden h-screen shrink-0 flex-col border-r border-slate-200 bg-white transition-[width] duration-200 md:flex dark:border-slate-800 dark:bg-slate-900 ${collapsed ? "w-[68px]" : "w-[68px] lg:w-60"}`}>
      <div className="flex h-14 items-center gap-2 px-4">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-green-500 to-blue-600 text-white"><TrendingUp size={17} /></span>
        <span className={`truncate font-bold tracking-tight ${collapsed ? "hidden" : "hidden lg:inline"}`}>Grow Trading</span>
      </div>

      {!collapsed && q?.price != null && (
        <div className="mx-3 mb-2 hidden rounded-xl bg-blue-50 px-3 py-2 lg:block dark:bg-blue-950/40">
          <div className="flex items-center justify-between text-[11px] font-medium text-blue-700 dark:text-blue-300">
            NIFTY 50 <Dot tone={q.state === "live" ? "good" : q.state === "delayed" ? "warn" : "neutral"} pulse={q.state === "live"} />
          </div>
          <div className="num text-lg font-bold">{num(q.price)}</div>
          <div className={`num text-xs ${(q.change ?? 0) >= 0 ? "text-gain" : "text-loss"}`}>
            {(q.change ?? 0) >= 0 ? "+" : "−"}{num(Math.abs(q.change ?? 0))} ({num(q.change_pct)}%)
          </div>
          {sig && <div className="mt-1 text-[11px] text-slate-600 dark:text-slate-300">Signal: <b className={sig.action === "BUY CE" ? "text-gain" : sig.action === "BUY PE" ? "text-loss" : ""}>{sig.action}</b></div>}
        </div>
      )}

      <nav className="scroll-thin flex-1 space-y-0.5 overflow-y-auto px-2" aria-label="Main">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} end={to === "/"} title={label}
            className={({ isActive }) => `flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors ${
              isActive ? "bg-blue-600 text-white shadow-sm" : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"}`}>
            <Icon size={18} className="shrink-0" />
            <span className={`truncate ${collapsed ? "hidden" : "hidden lg:inline"}`}>{label}</span>
          </NavLink>
        ))}
      </nav>

      <button onClick={() => update({ sidebarCollapsed: !collapsed })}
        className="m-2 hidden items-center gap-2 rounded-xl px-3 py-2 text-xs text-slate-500 hover:bg-slate-100 lg:flex dark:hover:bg-slate-800"
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
        {collapsed ? <ChevronsRight size={16} /> : <><ChevronsLeft size={16} /> Collapse</>}
      </button>
    </aside>
  );
}
