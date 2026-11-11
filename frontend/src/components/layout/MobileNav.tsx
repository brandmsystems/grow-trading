import { useEffect } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { Menu, X } from "lucide-react";
import { NAV } from "./nav";

/** Phone navigation: a bottom bar with the main pages plus a drawer with everything. */
export function MobileNav({ open, setOpen }: { open: boolean; setOpen: (v: boolean) => void }) {
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname, setOpen]);
  return (
    <>
      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-slate-200 bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden dark:border-slate-800 dark:bg-slate-900/95" aria-label="Main">
        {NAV.filter((n) => n.mobile).map(({ to, short, icon: Icon }) => (
          <NavLink key={to} to={to} end={to === "/"}
            className={({ isActive }) => `flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] font-medium ${isActive ? "text-blue-600 dark:text-blue-400" : "text-slate-500"}`}>
            <Icon size={20} />{short}
          </NavLink>
        ))}
        <button onClick={() => setOpen(true)} className="flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] font-medium text-slate-500" aria-label="All pages">
          <Menu size={20} />More
        </button>
      </nav>

      {open && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="absolute inset-0 bg-slate-950/50" onClick={() => setOpen(false)} />
          <div className="fade-in absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-white p-3 shadow-xl dark:bg-slate-900">
            <div className="mb-2 flex items-center justify-between px-2">
              <span className="font-bold">Grow Trading</span>
              <button onClick={() => setOpen(false)} className="rounded-lg p-2 hover:bg-slate-100 dark:hover:bg-slate-800" aria-label="Close menu"><X size={18} /></button>
            </div>
            {NAV.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} end={to === "/"}
                className={({ isActive }) => `flex min-h-11 items-center gap-3 rounded-xl px-3 text-sm font-medium ${isActive ? "bg-blue-600 text-white" : "hover:bg-slate-100 dark:hover:bg-slate-800"}`}>
                <Icon size={18} />{label}
              </NavLink>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
