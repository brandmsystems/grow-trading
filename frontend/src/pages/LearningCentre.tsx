import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ArrowLeft, ArrowRight, BookOpen, BookText, Check, CheckCircle2, Circle, Compass, GraduationCap, Newspaper, Play, Search, X } from "lucide-react";
import { Card, Pill } from "../components/common/Card";
import { Button, inputCls, PageHeader, Segmented } from "../components/common/Controls";
import { Empty, Progress, Warning } from "../components/common/States";
import { Diagram } from "../components/learn/Diagrams";
import { EXAMPLES } from "../components/learn/examples";
import { GLOSSARY, termLabel } from "../components/learn/glossary";
import { LearnNews } from "../components/learn/LearnNews";
import { LESSONS, LEVELS, ROADMAP_ORDER, lessonById, type Lang, type Lesson } from "../components/learn/lessons";
import { tt, UI, useLearn } from "../components/learn/ui";

type Section = "home" | "glossary" | "roadmap" | "news" | string;
const TRACKED = ROADMAP_ORDER;

/** Everything a lesson says, in both languages, lower-cased: so English terms are found while reading Malayalam. */
const lessonText = (x: Lesson) => [x.title, x.intro, x.key, ...x.points.flatMap((p) => [p.term, p.text])].flatMap((v) => [v.en, v.ml]).join(" ").toLowerCase();
const termText = (g: (typeof GLOSSARY)[number]) => `${g.term} ${g.ml ?? ""} ${g.def.en} ${g.def.ml}`.toLowerCase();
const matches = (hay: string, q: string) => q.toLowerCase().split(/\s+/).filter(Boolean).every((w) => hay.includes(w));

function Key({ lang, children }: { lang: Lang; children: ReactNode }) {
  return (
    <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm dark:border-blue-900 dark:bg-blue-950/30" data-testid="key-idea">
      <div className="mb-0.5 text-[11px] font-bold uppercase tracking-wide text-blue-700 dark:text-blue-300">{tt(UI.keyIdea, lang)}</div>
      <div className="font-medium text-slate-800 dark:text-slate-100">{children}</div>
    </div>
  );
}

function LevelPill({ level, lang }: { level: string; lang: Lang }) {
  return <Pill tone={level === "beginner" ? "good" : level === "intermediate" ? "info" : "warn"}>{tt(UI.levelLabel[level], lang)}</Pill>;
}

// ------------------------------------------------------------------ lesson
function Examples({ lang }: { lang: Lang }) {
  return (
    <div className="space-y-3" data-testid="examples">
      {EXAMPLES.map((e, i) => (
        <details key={e.id} open={i === 0} className="group rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900" data-testid={`example-${e.id}`}>
          <summary className="cursor-pointer list-none px-4 py-3 text-sm font-semibold marker:hidden">{tt(e.title, lang)}</summary>
          <div className="space-y-3 px-4 pb-4">
            <p className="text-sm text-slate-700 dark:text-slate-200">{tt(e.setup, lang)}</p>
            <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-800">
              <table className="w-full min-w-[320px] text-sm"><tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {e.rows.map((r, j) => (
                  <tr key={j}><td className="px-3 py-2">{tt(r.label, lang)}</td>
                    <td className={`num px-3 py-2 text-right font-semibold ${r.tone === "good" ? "text-green-600" : r.tone === "bad" ? "text-red-600" : ""}`} data-testid="example-value">{r.value}</td></tr>
                ))}
              </tbody></table>
            </div>
            <p className="text-xs text-slate-500">{tt(e.note, lang)}</p>
            <Pill tone="warn">{tt(UI.illustrative, lang)}</Pill>
          </div>
        </details>
      ))}
    </div>
  );
}

function LessonView({ lesson, lang, done, onToggle, onGo }: { lesson: Lesson; lang: Lang; done: boolean; onToggle: () => void; onGo: (id: Section) => void }) {
  const order = ROADMAP_ORDER.indexOf(lesson.id);
  const prev = order > 0 ? ROADMAP_ORDER[order - 1] : null, next = order >= 0 && order < ROADMAP_ORDER.length - 1 ? ROADMAP_ORDER[order + 1] : null;
  return (
    <div className="space-y-4" data-testid="lesson">
      <Card bodyClass="space-y-3 p-5">
        <div className="flex flex-wrap items-center gap-2"><LevelPill level={lesson.level} lang={lang} /><span className="text-xs text-slate-500">~{lesson.minutes} {tt(UI.minutes, lang)}</span>{done && <Pill tone="good">{tt(UI.done, lang)}</Pill>}</div>
        <h2 className="text-xl font-bold tracking-tight" data-testid="lesson-title">{tt(lesson.title, lang)}</h2>
        <p className="text-sm text-slate-600 dark:text-slate-300">{tt(lesson.intro, lang)}</p>
        <Key lang={lang}>{tt(lesson.key, lang)}</Key>
      </Card>

      {lesson.diagrams.map((k, i) => <Diagram key={k} k={k} lang={lang} n={i + 1} />)}

      {lesson.examples && <Examples lang={lang} />}

      {lesson.points.length > 0 && (
        <div className="space-y-2">
          {lesson.points.map((pt, i) => (
            <details key={pt.term.en} open={i < 2} className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900" data-testid="point">
              <summary className="cursor-pointer px-4 py-3 text-sm font-semibold">{tt(pt.term, lang)}</summary>
              <p className="px-4 pb-3 text-sm leading-relaxed text-slate-700 dark:text-slate-200">{tt(pt.text, lang)}</p>
            </details>
          ))}
        </div>
      )}

      {lesson.warning && <div data-testid="risk-warning"><Warning><b>{tt(UI.risk, lang)}: </b>{tt(lesson.warning, lang)}</Warning></div>}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button onClick={() => prev && onGo(prev)} disabled={!prev}><ArrowLeft size={16} />{tt(UI.prev, lang)}</Button>
        <Button variant={done ? "secondary" : "success"} onClick={onToggle}><Check size={16} />{tt(done ? UI.markUndo : UI.markDone, lang)}</Button>
        <Button onClick={() => next && onGo(next)} disabled={!next}>{tt(UI.next, lang)}<ArrowRight size={16} /></Button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ glossary, roadmap, search
function Glossary({ lang, query }: { lang: Lang; query: string }) {
  const [q, setQ] = useState(query);
  useEffect(() => setQ(query), [query]);
  const rows = useMemo(() => GLOSSARY.filter((g) => matches(termText(g), q)).sort((a, b) => a.term.localeCompare(b.term)), [q]);
  return (
    <Card title={<span>{tt(UI.glossary, lang)}</span>} icon={<BookText size={16} className="text-blue-600" />} right={<span data-testid="glossary-count">{rows.length} {tt(UI.terms, lang)}</span>}>
      <div className="space-y-3">
        <input type="search" aria-label={tt(UI.glossarySearch, lang)} placeholder={tt(UI.glossarySearch, lang)} value={q} onChange={(e) => setQ(e.target.value)} className={inputCls} />
        {rows.length === 0 ? <Empty title={tt(UI.noResults, lang)} /> : (
          <dl className="divide-y divide-slate-100 dark:divide-slate-800" data-testid="glossary">
            {rows.map((g) => (
              <div key={g.term} className="py-2.5"><dt className="text-sm font-semibold">{termLabel(g, lang)}</dt><dd className="mt-0.5 text-sm text-slate-600 dark:text-slate-300">{tt(g.def, lang)}</dd></div>
            ))}
          </dl>
        )}
      </div>
    </Card>
  );
}

function Roadmap({ lang, done, onGo, onReset }: { lang: Lang; done: string[]; onGo: (id: Section) => void; onReset: () => void }) {
  return (
    <div className="space-y-4" data-testid="roadmap">
      <p className="text-sm text-slate-600 dark:text-slate-300">{tt(UI.roadmapIntro, lang)}</p>
      {LEVELS.map((lv) => {
        const ids = ROADMAP_ORDER.filter((id) => lessonById(id)?.level === lv.key);
        const n = ids.filter((id) => done.includes(id)).length;
        return (
          <Card key={lv.key} title={<span>{tt(lv.title, lang)}</span>} right={<span>{n} / {ids.length}</span>} accent={lv.key === "beginner" ? "gain" : lv.key === "intermediate" ? "spot" : "risk"}>
            <div className="space-y-3">
              <p className="text-sm text-slate-600 dark:text-slate-300">{tt(lv.text, lang)}</p>
              <Progress value={ids.length ? n / ids.length : 0} />
              <ul className="space-y-1.5">
                {ids.map((id) => {
                  const ls = lessonById(id)!, ok = done.includes(id);
                  return (
                    <li key={id}>
                      <button type="button" onClick={() => onGo(id)} className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-slate-100 dark:hover:bg-slate-800">
                        {ok ? <CheckCircle2 size={16} className="shrink-0 text-green-600" /> : <Circle size={16} className="shrink-0 text-slate-400" />}
                        <span className="min-w-0 flex-1">{tt(ls.title, lang)}</span>
                        <span className="shrink-0 text-xs text-slate-500">{ok ? tt(UI.done, lang) : tt(UI.todo, lang)}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          </Card>
        );
      })}
      <div><Button variant="ghost" onClick={onReset}>{tt(UI.resetProgress, lang)}</Button></div>
    </div>
  );
}

function SearchResults({ q, lang, onGo, onGlossary }: { q: string; lang: Lang; onGo: (id: Section) => void; onGlossary: () => void }) {
  const ls = LESSONS.filter((x) => matches(lessonText(x), q));
  const gs = GLOSSARY.filter((g) => matches(termText(g), q));
  return (
    <Card title={<span>{tt(UI.searchResults, lang)}: “{q}”</span>} icon={<Search size={16} className="text-blue-600" />} right={<span data-testid="search-count">{ls.length + gs.length}</span>}>
      {ls.length + gs.length === 0 ? <Empty title={tt(UI.noResults, lang)} /> : (
        <div className="space-y-4" data-testid="search-results">
          {ls.length > 0 && (
            <div><h3 className="mb-1 text-xs font-bold uppercase tracking-wide text-slate-500">{tt(UI.lessonsHead, lang)}</h3>
              <ul className="space-y-1">{ls.map((x) => (
                <li key={x.id}><button type="button" onClick={() => onGo(x.id)} className="w-full rounded-lg px-2 py-1.5 text-left text-sm font-medium text-blue-700 hover:bg-slate-100 dark:text-blue-400 dark:hover:bg-slate-800">{tt(x.title, lang)}</button></li>
              ))}</ul></div>
          )}
          {gs.length > 0 && (
            <div><h3 className="mb-1 flex items-center justify-between text-xs font-bold uppercase tracking-wide text-slate-500">{tt(UI.glossary, lang)}
              <button type="button" onClick={onGlossary} className="font-medium normal-case text-blue-700 hover:underline dark:text-blue-400">{tt(UI.open, lang)}</button></h3>
              <dl className="divide-y divide-slate-100 dark:divide-slate-800">{gs.slice(0, 12).map((g) => (
                <div key={g.term} className="py-2"><dt className="text-sm font-semibold">{termLabel(g, lang)}</dt><dd className="text-sm text-slate-600 dark:text-slate-300">{tt(g.def, lang)}</dd></div>
              ))}</dl></div>
          )}
        </div>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ home
function Home({ lang, done, last, onGo }: { lang: Lang; done: string[]; last: string | null; onGo: (id: Section) => void }) {
  const n = TRACKED.filter((id) => done.includes(id)).length;
  const nextId = (last && !done.includes(last) && TRACKED.includes(last) ? last : TRACKED.find((id) => !done.includes(id))) ?? null;
  const finished = n === TRACKED.length;
  const started = n > 0 || last !== null;
  return (
    <div className="space-y-4" data-testid="home">
      <Card accent="spot" bodyClass="space-y-3 p-5">
        <div className="flex items-center gap-2 text-lg font-bold"><GraduationCap size={20} className="text-blue-600" />{tt(started ? UI.cont : UI.start, lang)}</div>
        <p className="text-sm text-slate-600 dark:text-slate-300">{finished ? tt(UI.allDone, lang) : !started ? tt(UI.welcome, lang) : tt(lessonById(nextId!)!.title, lang)}</p>
        <Progress value={n / TRACKED.length} text={`${tt(UI.progress, lang)}: ${n} / ${TRACKED.length} ${tt(UI.lessonsDone, lang)}`} />
        {nextId && <Button variant="primary" onClick={() => onGo(nextId)}><Play size={16} />{tt(started ? UI.cont : UI.start, lang)}</Button>}
      </Card>
      <div className="grid gap-3 md:grid-cols-3">
        {LEVELS.map((lv) => {
          const ids = ROADMAP_ORDER.filter((id) => lessonById(id)?.level === lv.key);
          return (
            <Card key={lv.key} title={<span>{tt(lv.title, lang)}</span>} accent={lv.key === "beginner" ? "gain" : lv.key === "intermediate" ? "spot" : "risk"}>
              <p className="mb-2 text-sm text-slate-600 dark:text-slate-300">{tt(lv.text, lang)}</p>
              <ul className="space-y-1">{ids.map((id) => (
                <li key={id}><button type="button" onClick={() => onGo(id)} className="flex w-full items-center gap-2 rounded-lg px-2 py-1 text-left text-sm hover:bg-slate-100 dark:hover:bg-slate-800">
                  {done.includes(id) ? <CheckCircle2 size={14} className="shrink-0 text-green-600" /> : <Circle size={14} className="shrink-0 text-slate-400" />}<span className="min-w-0">{tt(lessonById(id)!.title, lang)}</span></button></li>
              ))}</ul>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ page
export default function LearningCentre() {
  const { lang, done, last, setLang, toggle, setLast, reset } = useLearn();
  const [section, setSection] = useState<Section>("home");
  const [q, setQ] = useState("");
  const go = (id: Section) => { setSection(id); setQ(""); if (lessonById(id)) setLast(id); window.scrollTo?.({ top: 0 }); };
  const lesson = lessonById(section);
  const n = TRACKED.filter((id) => done.includes(id)).length;

  const NavBtn = ({ id, icon, label, check }: { id: Section; icon?: ReactNode; label: string; check?: boolean }) => (
    <button type="button" onClick={() => go(id)} aria-current={section === id && !q ? "page" : undefined}
      className={`flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-left text-sm font-medium transition-colors lg:w-full ${section === id && !q ? "bg-blue-600 text-white" : "text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"}`}>
      {check !== undefined ? (check ? <CheckCircle2 size={15} className="shrink-0 text-green-500" /> : <Circle size={15} className="shrink-0 opacity-50" />) : icon}
      <span className="whitespace-nowrap lg:whitespace-normal">{label}</span>
    </button>
  );

  return (
    <div data-testid="learning-centre" lang={lang === "ml" ? "ml" : "en"}>
      <PageHeader title={tt(UI.title, lang)} subtitle={tt(UI.subtitle, lang)}
        actions={<div className="flex items-center gap-2" role="group" aria-label={tt(UI.language, lang)}>
          <span className="text-xs font-medium text-slate-500">{tt(UI.language, lang)}</span>
          <Segmented<Lang> value={lang} onChange={setLang} options={[{ value: "en", label: "English" }, { value: "ml", label: "മലയാളം" }]} />
        </div>} />
      <div className="mb-4" data-testid="disclaimer"><Warning>{tt(UI.disclaimer, lang)}</Warning></div>

      <div className="grid gap-4 lg:grid-cols-[250px_minmax(0,1fr)]">
        <aside className="min-w-0 space-y-3 lg:sticky lg:top-4 lg:self-start">
          <div className="relative">
            <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <input type="search" aria-label={tt(UI.search, lang)} placeholder={tt(UI.search, lang)} value={q} onChange={(e) => setQ(e.target.value)} className={`${inputCls} pl-8 pr-8`} />
            {q && <button type="button" aria-label={tt(UI.clear, lang)} onClick={() => setQ("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700"><X size={14} /></button>}
          </div>
          <div className="hidden lg:block"><Progress value={n / TRACKED.length} text={`${n} / ${TRACKED.length} ${tt(UI.lessonsDone, lang)}`} /></div>
          <nav aria-label={tt(UI.lessonsHead, lang)} className="flex gap-1 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible lg:pb-0">
            <NavBtn id="home" icon={<Compass size={15} className="shrink-0" />} label={tt(UI.home, lang)} />
            {LESSONS.map((x) => <NavBtn key={x.id} id={x.id} label={tt(x.title, lang)} check={done.includes(x.id)} />)}
            <NavBtn id="glossary" icon={<BookText size={15} className="shrink-0" />} label={tt(UI.glossary, lang)} />
            <NavBtn id="roadmap" icon={<BookOpen size={15} className="shrink-0" />} label={tt(UI.roadmap, lang)} />
            <NavBtn id="news" icon={<Newspaper size={15} className="shrink-0" />} label={tt(UI.news, lang)} />
          </nav>
        </aside>

        <main className="min-w-0">
          {q.trim() ? <SearchResults q={q} lang={lang} onGo={go} onGlossary={() => go("glossary")} />
            : section === "home" ? <Home lang={lang} done={done} last={last} onGo={go} />
            : lesson ? <LessonView key={lesson.id} lesson={lesson} lang={lang} done={done.includes(lesson.id)} onToggle={() => toggle(lesson.id)} onGo={go} />
            : section === "glossary" ? <Glossary lang={lang} query="" />
            : section === "roadmap" ? <Roadmap lang={lang} done={done} onGo={go} onReset={reset} />
            : <LearnNews lang={lang} />}
        </main>
      </div>
    </div>
  );
}
