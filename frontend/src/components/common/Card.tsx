import type { ReactNode } from "react";

export function Card({ title, right, children, className = "" }: {
  title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900 ${className}`}>
      {(title || right) && (
        <div className="flex items-center justify-between gap-2 border-b border-slate-200 px-4 py-2.5 dark:border-slate-800">
          <h2 className="text-sm font-semibold">{title}</h2>
          {right && <div className="text-xs text-slate-500 dark:text-slate-400">{right}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

/** Small labelled value used inside cards. */
export function Stat({ label, value, sub, className = "" }: {
  label: string; value: ReactNode; sub?: ReactNode; className?: string;
}) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</div>
      <div className={`num truncate text-base font-semibold ${className}`}>{value}</div>
      {sub && <div className="truncate text-xs text-slate-500 dark:text-slate-400">{sub}</div>}
    </div>
  );
}

const TONES = {
  neutral: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  good: "bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-400",
  bad: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-400",
  warn: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-400",
  info: "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-400",
} as const;
export type Tone = keyof typeof TONES;

export function Pill({ tone = "neutral", children, className = "" }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${TONES[tone]} ${className}`}>{children}</span>;
}

export function Dot({ tone }: { tone: Tone }) {
  const c = { neutral: "bg-slate-400", good: "bg-green-500", bad: "bg-red-500", warn: "bg-amber-500", info: "bg-blue-500" }[tone];
  return <span className={`inline-block h-2 w-2 rounded-full ${c}`} />;
}
