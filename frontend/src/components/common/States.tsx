import type { ReactNode } from "react";
import { AlertTriangle, Inbox, Loader2, PlugZap, Info } from "lucide-react";

export function Loading({ text = "Loading…", className = "h-40" }: { text?: string; className?: string }) {
  return (
    <div className={`grid place-items-center text-sm text-slate-500 ${className}`}>
      <span className="flex items-center gap-2"><Loader2 size={16} className="animate-spin" />{text}</span>
    </div>
  );
}

export function Empty({ title, children, className = "" }: { title: string; children?: ReactNode; className?: string }) {
  return (
    <div className={`flex flex-col items-center gap-2 rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center dark:border-slate-700 ${className}`}>
      <Inbox className="text-slate-400" />
      <div className="font-medium">{title}</div>
      {children && <div className="max-w-md text-sm text-slate-500 dark:text-slate-400">{children}</div>}
    </div>
  );
}

export function ErrorNote({ children, offline = false }: { children: ReactNode; offline?: boolean }) {
  return (
    <div role="alert" className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-400">
      {offline ? <PlugZap size={16} className="mt-0.5 shrink-0" /> : <AlertTriangle size={16} className="mt-0.5 shrink-0" />}
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export function Warning({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-xl border border-orange-200 bg-orange-50 px-3 py-2 text-sm text-orange-800 dark:border-orange-900 dark:bg-orange-950/40 dark:text-orange-300">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" /><div className="min-w-0">{children}</div>
    </div>
  );
}

/** Says plainly that the backend doesn't provide something, instead of showing made-up data. */
export function Limitation({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-xl bg-slate-100 px-3 py-2 text-xs text-slate-600 dark:bg-slate-800/70 dark:text-slate-400">
      <Info size={14} className="mt-0.5 shrink-0" /><div className="min-w-0">{children}</div>
    </div>
  );
}

export function Progress({ value, text }: { value: number; text?: string }) {
  return (
    <div className="space-y-1">
      <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
        <div className="h-full rounded-full bg-blue-500 transition-all" style={{ width: `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%` }} />
      </div>
      {text && <div className="truncate text-xs text-slate-500">{text}</div>}
    </div>
  );
}
