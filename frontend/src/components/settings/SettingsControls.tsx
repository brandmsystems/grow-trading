import { useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { TsConfig, TsIssue, TsParam, TsValue } from "../../types/api";
import { Pill } from "../common/Card";
import { inputCls } from "../common/Controls";

/** An accessible ON/OFF switch. */
export function Toggle({ on, onChange, label, disabled }: { on: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} onClick={() => onChange(!on)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${on ? "bg-green-600" : "bg-slate-300 dark:bg-slate-700"}`}>
      <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ${on ? "translate-x-5" : "translate-x-0.5"}`} />
      <span className="sr-only">{on ? "ON" : "OFF"}</span>
    </button>
  );
}

const stepFor = (p: TsParam) => (p.type === "int" ? 1 : p.max <= 1 ? 0.05 : p.max <= 10 ? 0.1 : p.max <= 100 ? 0.5 : 1);

/** One editable parameter, drawn from the server's schema (label, type, bounds). `error` is the problem the server reported for it. */
export function ParamField({ p, value, onChange, id, error }: { p: TsParam; value: TsValue | undefined; onChange: (v: TsValue) => void; id: string; error?: string }) {
  const [draft, setDraft] = useState<string | null>(null);
  const label = p.label;
  let control: ReactNode;
  if (p.type === "bool") {
    control = <input id={id} type="checkbox" className="h-4 w-4" aria-label={label} checked={value === true} onChange={(e) => onChange(e.target.checked)} />;
  } else if (p.type === "choice") {
    control = (
      <select id={id} className={inputCls} aria-label={label} value={String(value ?? p.default)}
        onChange={(e) => onChange(typeof p.choices?.[0] === "number" ? Number(e.target.value) : e.target.value)}>
        {(p.choices ?? []).map((c) => <option key={String(c)} value={String(c)}>{String(c)}</option>)}
      </select>
    );
  } else if (p.type === "time") {
    control = <input id={id} type="time" className={inputCls} aria-label={label} value={String(value ?? p.default)} onChange={(e) => onChange(e.target.value)} />;
  } else {
    control = (
      <input id={id} type="number" className={inputCls} aria-label={label} step={stepFor(p)} min={p.min} max={p.max} value={draft ?? String(value ?? p.default)}
        aria-invalid={!!error}
        onChange={(e) => { setDraft(e.target.value); const v = e.target.valueAsNumber; if (Number.isFinite(v)) onChange(v); }} onBlur={() => setDraft(null)} />
    );
  }
  return (
    <div className={`flex min-w-0 flex-col gap-1 text-xs font-medium text-slate-600 dark:text-slate-400 ${p.type === "bool" ? "justify-end" : ""}`}>
      {p.type === "bool" ? <label className="flex items-center gap-2" htmlFor={id}>{control}<span>{label}</span></label> : <><label htmlFor={id}>{label}</label>{control}</>}
      {error && <span role="alert" className="text-[11px] font-normal text-red-600">{error}</span>}
    </div>
  );
}

/** Errors the server listed for this path or anything below it, by exact path. */
export const issueAt = (issues: TsIssue[], path: string) => issues.find((i) => i.path === path)?.message;

/** A switchable item (a strategy or an indicator) with its note, status and an expandable parameter list. */
export function ItemCard({ id, title, badge, note, on, onToggle, blocked, params, values, onParam, issues, basePath, tag }: {
  id: string; title: string; badge?: ReactNode; note?: string; on: boolean; onToggle: (v: boolean) => void; blocked?: string[];
  params: TsParam[]; values: Record<string, TsValue>; onParam: (key: string, v: TsValue) => void; issues: TsIssue[]; basePath: string; tag?: string;
}) {
  const hasErr = issues.some((i) => i.path.startsWith(basePath));
  const [open, setOpen] = useState(false);
  const show = open || hasErr;
  return (
    <div data-testid={`item-${id}`} className={`rounded-xl border p-3 ${on ? "border-green-300 bg-green-50/40 dark:border-green-900 dark:bg-green-950/20" : "border-slate-200 dark:border-slate-800"}`}>
      <div className="flex items-start gap-3">
        <Toggle on={on} onChange={onToggle} label={`${title} ${on ? "ON" : "OFF"}`} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold">{title}</span>
            {tag && <Pill tone="neutral">{tag}</Pill>}
            {badge}
            {on && blocked && blocked.length > 0 && <Pill tone="warn" title={blocked.join("; ")}>blocked</Pill>}
          </div>
          {note && <p className="mt-0.5 text-xs text-slate-500">{note}</p>}
          {on && blocked && blocked.length > 0 && <p className="mt-1 text-xs text-orange-700 dark:text-orange-400" data-testid={`blocked-${id}`}>Cannot trade: {blocked.join("; ")}.</p>}
        </div>
      </div>
      {params.length > 0 && (
        <div className="mt-2">
          <button type="button" className="flex items-center gap-1 text-xs font-medium text-blue-700 hover:underline dark:text-blue-400" aria-expanded={show}
            onClick={() => setOpen(!open)}>
            {show ? <ChevronDown size={14} /> : <ChevronRight size={14} />}Parameters ({params.map((p) => String(values[p.key] ?? p.default)).join(" · ")})
          </button>
          {show && (
            <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-3">
              {params.map((p) => <ParamField key={p.key} p={p} id={`${id}-${p.key}`} value={values[p.key]} onChange={(v) => onParam(p.key, v)} error={issueAt(issues, `${basePath}.params.${p.key}`)} />)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Immutable `set` at a dotted path. */
export function setIn<T>(obj: T, path: string[], value: unknown): T {
  if (path.length === 0) return value as T;
  const [head, ...rest] = path;
  const cur = obj as Record<string, unknown>;
  return { ...cur, [head]: setIn(cur[head], rest, value) } as T;
}

export const cfgEqual = (a: TsConfig | null, b: TsConfig | null) => JSON.stringify(a) === JSON.stringify(b);
