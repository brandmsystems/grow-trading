import type { ReactNode } from "react";
import { Info } from "lucide-react";

/** Accent colours of the colour system (see index.css). */
export type Accent = "spot" | "gain" | "loss" | "strat" | "risk" | "neutral";
const ACCENT_BAR: Record<Accent, string> = {
  spot: "before:bg-blue-500", gain: "before:bg-green-500", loss: "before:bg-red-500",
  strat: "before:bg-violet-500", risk: "before:bg-orange-500", neutral: "before:bg-slate-400",
};

export function Card({ title, icon, right, accent, children, className = "", bodyClass = "" }: {
  title?: ReactNode; icon?: ReactNode; right?: ReactNode; accent?: Accent; children: ReactNode; className?: string; bodyClass?: string;
}) {
  const bar = accent ? `relative overflow-hidden before:absolute before:inset-x-0 before:top-0 before:h-1 ${ACCENT_BAR[accent]}` : "";
  return (
    <section className={`fade-in min-w-0 rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900 ${bar} ${className}`}>
      {(title || right) && (
        <div className="flex items-center justify-between gap-2 px-4 pt-4 pb-2">
          <h2 className="flex min-w-0 items-center gap-2 text-sm font-semibold text-slate-700 dark:text-slate-200">{icon}{title}</h2>
          {right && <div className="shrink-0 text-xs text-slate-500 dark:text-slate-400">{right}</div>}
        </div>
      )}
      <div className={bodyClass || (title || right ? "px-4 pb-4" : "p-4 pt-5")}>{children}</div>
    </section>
  );
}

/** Small labelled value used inside cards. */
export function Stat({ label, value, sub, tip, className = "" }: {
  label: string; value: ReactNode; sub?: ReactNode; tip?: string; className?: string;
}) {
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {label}{tip && <InfoTip text={tip} />}
      </div>
      <div className={`num truncate text-base font-semibold ${className}`}>{value}</div>
      {sub && <div className="truncate text-xs text-slate-500 dark:text-slate-400">{sub}</div>}
    </div>
  );
}

/** Hover / focus explanation. */
export function InfoTip({ text }: { text: string }) {
  return (
    <span className="group relative inline-flex" tabIndex={0} aria-label={text}>
      <Info size={12} className="text-slate-400" />
      <span role="tooltip" className="pointer-events-none absolute bottom-full left-1/2 z-30 mb-1 hidden w-56 -translate-x-1/2 rounded-lg bg-slate-900 px-2.5 py-1.5 text-[11px] font-normal normal-case tracking-normal text-white shadow-lg group-hover:block group-focus:block dark:bg-slate-700">
        {text}
      </span>
    </span>
  );
}

const TONES = {
  neutral: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  good: "bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-400",
  bad: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-400",
  warn: "bg-orange-100 text-orange-700 dark:bg-orange-950 dark:text-orange-400",
  info: "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-400",
  strat: "bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300",
} as const;
export type Tone = keyof typeof TONES;

export function Pill({ tone = "neutral", children, className = "", title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  return <span title={title} className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold ${TONES[tone]} ${className}`}>{children}</span>;
}

export function Dot({ tone, pulse = false }: { tone: Tone; pulse?: boolean }) {
  const c = { neutral: "bg-slate-400", good: "bg-green-500", bad: "bg-red-500", warn: "bg-orange-500", info: "bg-blue-500", strat: "bg-violet-500" }[tone];
  return (
    <span className="relative inline-flex h-2 w-2">
      {pulse && <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${c}`} />}
      <span className={`relative inline-flex h-2 w-2 rounded-full ${c}`} />
    </span>
  );
}

/** Big headline number for overview cards. */
export function BigValue({ value, sub, className = "" }: { value: ReactNode; sub?: ReactNode; className?: string }) {
  return (
    <div>
      <div className={`num text-2xl font-bold tracking-tight sm:text-3xl ${className}`}>{value}</div>
      {sub && <div className="mt-0.5 text-sm">{sub}</div>}
    </div>
  );
}
