import { useState, type ReactNode } from "react";

const base = "min-w-0 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 dark:border-slate-700 dark:bg-slate-900";
export const inputCls = `w-full ${base}`;
/** Same look, natural width (for filter selects in a row). */
export const selectInline = `w-auto ${base}`;

export function Field({ label, children, className = "" }: { label: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={`flex min-w-0 flex-col gap-1 text-xs font-medium text-slate-600 dark:text-slate-400 ${className}`}>
      {label}{children}
    </label>
  );
}

/** Segmented buttons for small option sets (timeframe, mode...). */
export function Segmented<T extends string | number>({ value, options, onChange, disabled, size = "sm" }: {
  value: T; options: { value: T; label: ReactNode; tone?: "danger" }[]; onChange: (v: T) => void; disabled?: boolean; size?: "sm" | "md";
}) {
  return (
    <div role="radiogroup" className="inline-flex overflow-hidden rounded-lg border border-slate-300 dark:border-slate-700">
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button key={String(o.value)} type="button" role="radio" aria-checked={on} disabled={disabled}
            onClick={() => onChange(o.value)}
            className={`${size === "md" ? "px-4 py-2" : "px-3 py-1.5"} text-sm font-medium transition-colors disabled:opacity-50 ${
              on ? (o.tone === "danger" ? "bg-red-600 text-white" : "bg-blue-600 text-white")
                 : "bg-white text-slate-600 hover:bg-slate-100 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"}`}>
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function Button({ children, onClick, variant = "secondary", disabled, type = "button", className = "", title }: {
  children: ReactNode; onClick?: () => void; variant?: "primary" | "secondary" | "danger" | "success" | "ghost";
  disabled?: boolean; type?: "button" | "submit"; className?: string; title?: string;
}) {
  const v = {
    primary: "bg-blue-600 text-white hover:bg-blue-700",
    success: "bg-green-600 text-white hover:bg-green-700",
    danger: "border border-red-500 text-red-600 hover:bg-red-50 dark:hover:bg-red-950/40",
    secondary: "border border-slate-300 bg-white hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:hover:bg-slate-800",
    ghost: "hover:bg-slate-100 dark:hover:bg-slate-800",
  }[variant];
  return (
    <button type={type} title={title} onClick={onClick} disabled={disabled}
      className={`inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg px-3.5 py-1.5 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${v} ${className}`}>
      {children}
    </button>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-bold tracking-tight sm:text-2xl">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/**
 * A percentage box that can be typed into key by key ("0", then "0.5"). It keeps what is being typed
 * locally and only passes a valid value (above 0, up to `max`) to `onCommit`; leaving the box shows the saved value again.
 */
export function PercentInput({ value, onCommit, max = 100, step = 0.5, min = 0.1, className = inputCls, ...rest }: {
  value: number; onCommit: (v: number) => void; max?: number; step?: number; min?: number; className?: string; "aria-label"?: string;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <input type="number" min={min} max={max} step={step} className={className} value={draft ?? value} {...rest}
      onChange={(e) => {
        setDraft(e.target.value);
        const v = Number(e.target.value);
        if (e.target.value !== "" && Number.isFinite(v) && v > 0 && v <= max) onCommit(v);
      }}
      onBlur={() => setDraft(null)} />
  );
}
