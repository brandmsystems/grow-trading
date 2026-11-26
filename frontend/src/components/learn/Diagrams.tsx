import { useId } from "react";
import { Card } from "../common/Card";
import { DIAGRAM_META, type DiagramKey, type Lang } from "./lessons";
import { CHAIN, CHAIN_SPOT, PLAN, breakEvenWinRate, chainTotals, planReward, planRisk, rs } from "./examples";
import { UI, tt } from "./ui";

const GREEN = "#16a34a", RED = "#dc2626", BLUE = "#3b82f6", ORANGE = "#f97316";
const TXT = "fill-slate-600 dark:fill-slate-300";
const AXIS = "stroke-slate-300 dark:stroke-slate-600";
const D = (k: string, lang: Lang) => tt(UI.d[k], lang);

/** Builds an SVG path from a function sampled between two x values. */
function curve(f: (x: number) => number, x0: number, x1: number, n: number, px: (x: number) => number, py: (y: number) => number) {
  return Array.from({ length: n + 1 }, (_, i) => { const x = x0 + ((x1 - x0) * i) / n; return `${i ? "L" : "M"}${px(x).toFixed(1)},${py(f(x)).toFixed(1)}`; }).join(" ");
}

function Svg({ vb, label, children }: { vb: string; label: string; children: React.ReactNode }) {
  return <svg viewBox={vb} role="img" aria-label={label} className="mx-auto h-auto w-full max-w-xl">{children}</svg>;
}

// ------------------------------------------------------------------ CE and PE
function CePe({ lang }: { lang: Lang }) {
  const box = (x: number, title: string, sub: string, note: string, col: string, up: boolean) => (
    <g>
      <rect x={x} y={10} width={145} height={110} rx={10} fill={col} fillOpacity={0.1} stroke={col} />
      <text x={x + 72} y={34} textAnchor="middle" className={TXT} fontSize={13} fontWeight={700}>{title}</text>
      <text x={x + 72} y={52} textAnchor="middle" className={TXT} fontSize={10}>{sub}</text>
      <path d={up ? `M${x + 72},100 L${x + 72},66 M${x + 62},76 L${x + 72},64 L${x + 82},76` : `M${x + 72},66 L${x + 72},100 M${x + 62},90 L${x + 72},102 L${x + 82},90`}
        stroke={col} strokeWidth={3} fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <text x={x + 72} y={116} textAnchor="middle" className={TXT} fontSize={9}>{note}</text>
    </g>
  );
  return (
    <Svg vb="0 0 330 130" label={tt(DIAGRAM_META.cepe.title, lang)}>
      {box(10, "CE · Call", D("right_buy", lang), D("market_up", lang), GREEN, true)}
      {box(175, "PE · Put", D("right_sell", lang), D("market_down", lang), RED, false)}
    </Svg>
  );
}

// ------------------------------------------------------------------ four payoff panels
const PAYOFF = {
  buyCE: { pts: [[20, 85], [100, 85], [165, 20]], be: 120, name: "Buy CE", buyer: true },
  buyPE: { pts: [[35, 20], [100, 85], [180, 85]], be: 80, name: "Buy PE", buyer: true },
  sellCE: { pts: [[20, 45], [100, 45], [165, 110]], be: 120, name: "Sell CE", buyer: false },
  sellPE: { pts: [[35, 110], [100, 45], [180, 45]], be: 80, name: "Sell PE", buyer: false },
} as const;

function Payoff({ k, lang }: { k: keyof typeof PAYOFF; lang: Lang }) {
  const id = useId().replace(/:/g, "");
  const { pts, be, name, buyer } = PAYOFF[k];
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x},${y}`).join(" ");
  const area = `${line} L${pts[pts.length - 1][0]},65 L${pts[0][0]},65 Z`;
  return (
    <figure className="rounded-xl border border-slate-200 p-2 dark:border-slate-800" data-testid={`payoff-${k}`}>
      <svg viewBox="0 0 200 130" role="img" aria-label={`${name}: ${tt(buyer ? UI.d.buyers : UI.d.sellers, lang)}`} className="h-auto w-full">
        <defs>
          <clipPath id={`${id}u`}><rect x={0} y={0} width={200} height={65} /></clipPath>
          <clipPath id={`${id}d`}><rect x={0} y={65} width={200} height={65} /></clipPath>
        </defs>
        <path d={area} fill={GREEN} fillOpacity={0.3} clipPath={`url(#${id}u)`} />
        <path d={area} fill={RED} fillOpacity={0.3} clipPath={`url(#${id}d)`} />
        <line x1={0} y1={65} x2={200} y2={65} className={AXIS} strokeDasharray="3 3" />
        <line x1={100} y1={8} x2={100} y2={122} className={AXIS} strokeDasharray="2 3" />
        <line x1={be} y1={58} x2={be} y2={72} stroke={BLUE} strokeWidth={2} />
        <path d={line} fill="none" stroke={BLUE} strokeWidth={2.5} strokeLinejoin="round" />
        <text x={be} y={be < 100 ? 82 : 55} textAnchor="middle" className={TXT} fontSize={9} fontWeight={700}>BE</text>
        <text x={102} y={126} className={TXT} fontSize={9}>K</text>
        <text x={4} y={11} fill={GREEN} fontSize={9}>{D("profit", lang)}</text>
        <text x={4} y={126} fill={RED} fontSize={9}>{D("loss", lang)}</text>
      </svg>
      <figcaption className="mt-1 text-xs"><span className="font-semibold">{name}</span> <span className="text-slate-500 dark:text-slate-400">· {tt(buyer ? UI.d.buyers : UI.d.sellers, lang)}</span></figcaption>
    </figure>
  );
}
const Positions = ({ lang }: { lang: Lang }) => (
  <div className="grid gap-3 sm:grid-cols-2">{(Object.keys(PAYOFF) as (keyof typeof PAYOFF)[]).map((k) => <Payoff key={k} k={k} lang={lang} />)}</div>
);

// ------------------------------------------------------------------ ATM / ITM / OTM
function Moneyness({ lang }: { lang: Lang }) {
  const strikes = [23800, 23900, 24000, 24100, 24200];
  const kind = (call: boolean, i: number) => (i === 2 ? "atm" : call ? (i < 2 ? "itm" : "otm") : (i > 2 ? "itm" : "otm"));
  const fill = { itm: GREEN, atm: BLUE, otm: "#94a3b8" } as const;
  const row = (call: boolean, y: number) => strikes.map((s, i) => {
    const k = kind(call, i);
    return (
      <g key={`${call}${s}`} data-testid={`${call ? "ce" : "pe"}-${s}`}>
        <rect x={12 + i * 64} y={y} width={58} height={40} rx={6} fill={fill[k]} fillOpacity={k === "otm" ? 0.2 : 0.22} stroke={fill[k]} />
        <text x={41 + i * 64} y={y + 17} textAnchor="middle" className={TXT} fontSize={10}>{s.toLocaleString("en-IN")}</text>
        <text x={41 + i * 64} y={y + 32} textAnchor="middle" fill={fill[k]} fontSize={11} fontWeight={700}>{D(k, lang)}</text>
      </g>
    );
  });
  return (
    <Svg vb="0 0 340 170" label={tt(DIAGRAM_META.moneyness.title, lang)}>
      <text x={170} y={14} textAnchor="middle" className={TXT} fontSize={11} fontWeight={700}>{D("now", lang)}</text>
      <path d="M164,20 L170,28 L176,20 Z" fill={BLUE} />
      <text x={12} y={44} className={TXT} fontSize={10} fontWeight={700}>{D("calls", lang)}</text>
      {row(true, 48)}
      <text x={12} y={110} className={TXT} fontSize={10} fontWeight={700}>{D("puts", lang)}</text>
      {row(false, 114)}
    </Svg>
  );
}

// ------------------------------------------------------------------ premium = intrinsic + time value
function Premium({ lang }: { lang: Lang }) {
  const px = (s: number) => 30 + ((s - 23700) / 600) * 280, py = (p: number) => 150 - (p / 400) * 135;
  const intr = (s: number) => Math.max(s - 24000, 0), prem = (s: number) => intr(s) + 95 * Math.exp(-(((s - 24000) / 160) ** 2));
  const up = curve(prem, 23700, 24300, 60, px, py), low = curve(intr, 23700, 24300, 60, px, py);
  const back = Array.from({ length: 61 }, (_, i) => { const s = 24300 - (600 * i) / 60; return `L${px(s).toFixed(1)},${py(intr(s)).toFixed(1)}`; }).join(" ");
  return (
    <Svg vb="0 0 330 185" label={tt(DIAGRAM_META.premium.title, lang)}>
      <line x1={30} y1={150} x2={310} y2={150} className={AXIS} /><line x1={30} y1={10} x2={30} y2={150} className={AXIS} />
      <path d={`${up} ${back} Z`} fill={ORANGE} fillOpacity={0.3} />
      <path d={low} fill="none" stroke={BLUE} strokeWidth={2} strokeDasharray="5 3" />
      <path d={up} fill="none" stroke={GREEN} strokeWidth={2.5} />
      <line x1={px(24000)} y1={150} x2={px(24000)} y2={156} className={AXIS} />
      <text x={px(24000)} y={168} textAnchor="middle" className={TXT} fontSize={10}>{D("strike", lang)} 24,000</text>
      <text x={170} y={182} textAnchor="middle" className={TXT} fontSize={9}>{D("nifty", lang)}</text>
      <text x={px(24000) - 8} y={py(75)} textAnchor="end" fill={ORANGE} fontSize={10} fontWeight={700}>{D("timev", lang)}</text>
      <text x={px(24200)} y={py(255)} textAnchor="end" fill={BLUE} fontSize={10} fontWeight={700}>{D("intrinsic", lang)}</text>
      <text x={px(24300) - 4} y={py(398) + 4} textAnchor="end" fill={GREEN} fontSize={10} fontWeight={700}>{D("premium", lang)}</text>
    </Svg>
  );
}

// ------------------------------------------------------------------ time decay
function Decay({ lang }: { lang: Lang }) {
  const px = (d: number) => 30 + ((30 - d) / 30) * 280, py = (p: number) => 150 - (p / 200) * 130;
  const f = (d: number) => 200 * Math.sqrt(Math.max(d, 0) / 30);
  return (
    <Svg vb="0 0 330 185" label={tt(DIAGRAM_META.decay.title, lang)}>
      <line x1={30} y1={150} x2={310} y2={150} className={AXIS} /><line x1={30} y1={10} x2={30} y2={150} className={AXIS} />
      <path d={`${curve(f, 30, 0, 60, px, py)} L${px(0)},150 L${px(30)},150 Z`} fill={ORANGE} fillOpacity={0.15} />
      <path d={curve(f, 30, 0, 60, px, py)} fill="none" stroke={ORANGE} strokeWidth={2.5} />
      {[30, 15, 7, 0].map((d) => <g key={d}><line x1={px(d)} y1={150} x2={px(d)} y2={155} className={AXIS} /><text x={px(d)} y={166} textAnchor="middle" className={TXT} fontSize={9}>{d}</text></g>)}
      <text x={170} y={181} textAnchor="middle" className={TXT} fontSize={9}>{D("days", lang)}</text>
      <text x={60} y={py(185) - 4} className={TXT} fontSize={10}>{D("slow", lang)}</text>
      <text x={px(0) - 6} y={py(80)} textAnchor="end" fill={RED} fontSize={10} fontWeight={700}>{D("fast", lang)}</text>
      <text x={36} y={20} className={TXT} fontSize={9}>{D("premium", lang)}</text>
    </Svg>
  );
}

// ------------------------------------------------------------------ IV crush
function Volatility({ lang }: { lang: Lang }) {
  const iv = [14, 14.5, 15, 16.5, 18.5, 21, 24, 13, 12.8, 12.5, 12.5];
  const px = (i: number) => 30 + (i / 10) * 280, py = (v: number) => 140 - ((v - 10) / 16) * 120;
  const path = iv.map((v, i) => `${i ? "L" : "M"}${px(i)},${py(v)}`).join(" ");
  return (
    <Svg vb="0 0 330 180" label={tt(DIAGRAM_META.volatility.title, lang)}>
      <line x1={30} y1={140} x2={310} y2={140} className={AXIS} /><line x1={30} y1={10} x2={30} y2={140} className={AXIS} />
      <line x1={px(6.5)} y1={14} x2={px(6.5)} y2={140} stroke={RED} strokeDasharray="4 3" />
      <path d={path} fill="none" stroke={BLUE} strokeWidth={2.5} strokeLinejoin="round" />
      <path d={`M${px(6)},${py(24)} L${px(7)},${py(13)}`} stroke={RED} strokeWidth={3} />
      <text x={px(6.5) - 5} y={22} textAnchor="end" className={TXT} fontSize={10} fontWeight={700}>{D("event", lang)}</text>
      <text x={px(7) + 6} y={py(18)} fill={RED} fontSize={10} fontWeight={700}>{D("crush", lang)}</text>
      <text x={36} y={20} className={TXT} fontSize={9}>{D("iv", lang)}</text>
      <text x={170} y={166} textAnchor="middle" className={TXT} fontSize={9}>t →</text>
    </Svg>
  );
}

// ------------------------------------------------------------------ option chain (HTML table)
function Chain({ lang }: { lang: Lang }) {
  const tot = chainTotals();
  const head = "px-2 py-1.5 text-right text-[11px] font-semibold uppercase tracking-wide text-slate-500";
  const shade = (itm: boolean, atm: boolean) => (atm ? "bg-blue-50 dark:bg-blue-950/40" : itm ? "bg-green-50 dark:bg-green-950/20" : "");
  const sg = (n: number) => (n > 0 ? `+${n}` : String(n));
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-800">
        <table className="w-full min-w-[640px] text-sm" data-testid="chain-table">
          <thead className="bg-slate-50 dark:bg-slate-800/60">
            <tr>
              <th colSpan={4} className="px-2 py-1.5 text-center text-xs font-bold text-green-700 dark:text-green-400">{D("calls", lang)}</th>
              <th className="px-2 py-1.5 text-center text-xs font-bold">{D("strike", lang)}</th>
              <th colSpan={4} className="px-2 py-1.5 text-center text-xs font-bold text-red-700 dark:text-red-400">{D("puts", lang)}</th>
            </tr>
            <tr>{["chg", "oi", "vol", "ltp"].map((k) => <th key={`c${k}`} className={head}>{D(k, lang)}</th>)}<th className={`${head} text-center`}>{" "}</th>
              {["ltp", "vol", "oi", "chg"].map((k) => <th key={`p${k}`} className={head}>{D(k, lang)}</th>)}</tr>
          </thead>
          <tbody className="num divide-y divide-slate-100 dark:divide-slate-800">
            {CHAIN.map((r) => {
              const atm = r.strike === CHAIN_SPOT;
              return (
                <tr key={r.strike} data-testid={`chain-${r.strike}`}>
                  {[sg(r.ce.chg), r.ce.oi, r.ce.vol, r.ce.ltp].map((v, i) => <td key={i} className={`px-2 py-1.5 text-right ${shade(r.strike < CHAIN_SPOT, atm)} ${i === 0 && r.ce.chg < 0 ? "text-red-600" : ""}`}>{v}</td>)}
                  <td className={`px-2 py-1.5 text-center font-bold ${atm ? "bg-blue-100 dark:bg-blue-900/50" : "bg-slate-50 dark:bg-slate-800/40"}`}>{r.strike.toLocaleString("en-IN")}{atm && <span className="ml-1 text-[10px] text-blue-700 dark:text-blue-300">{D("atm", lang)}</span>}</td>
                  {[r.pe.ltp, r.pe.vol, r.pe.oi, sg(r.pe.chg)].map((v, i) => <td key={i} className={`px-2 py-1.5 text-right ${shade(r.strike > CHAIN_SPOT, atm)} ${i === 3 && r.pe.chg < 0 ? "text-red-600" : ""}`}>{v}</td>)}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-slate-600 dark:text-slate-300" data-testid="chain-pcr">
        {D("totals", lang)}: CE {tot.ce} · PE {tot.pe} → <b>{D("pcr", lang)} = {tot.pe} / {tot.ce} = {tot.pcr.toFixed(2)}</b>
      </p>
    </div>
  );
}

// ------------------------------------------------------------------ Greeks
function GreekPanel({ title, text, children, testid }: { title: string; text: string; children: React.ReactNode; testid: string }) {
  return (
    <figure className="rounded-xl border border-slate-200 p-2 dark:border-slate-800" data-testid={testid}>
      <svg viewBox="0 0 170 100" role="img" aria-label={`${title}: ${text}`} className="h-auto w-full">
        <line x1={10} y1={88} x2={162} y2={88} className={AXIS} /><line x1={10} y1={8} x2={10} y2={88} className={AXIS} />
        {children}
      </svg>
      <figcaption className="mt-1 text-xs"><span className="font-semibold">{title}</span> <span className="text-slate-500 dark:text-slate-400">· {text}</span></figcaption>
    </figure>
  );
}
function Greeks({ lang }: { lang: Lang }) {
  const x = (s: number) => 10 + ((s - 23600) / 800) * 150;
  const delta = (s: number) => 1 / (1 + Math.exp(-(s - 24000) / 110)), gamma = (s: number) => Math.exp(-(((s - 24000) / 120) ** 2));
  const dy = (v: number) => 88 - v * 76;
  const tx = (d: number) => 10 + ((30 - d) / 30) * 150, ty = (p: number) => 88 - (p / 200) * 76;
  const vx = (v: number) => 10 + ((v - 10) / 20) * 150, vy = (p: number) => 88 - ((p - 40) / 100) * 76;
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <GreekPanel testid="greek-delta" title={D("delta", lang)} text={D("deltaT", lang)}>
        <path d={curve(delta, 23600, 24400, 50, x, dy)} fill="none" stroke={BLUE} strokeWidth={2.5} />
        <circle cx={x(24000)} cy={dy(0.5)} r={3.5} fill={BLUE} /><text x={x(24000) + 6} y={dy(0.5) + 12} className={TXT} fontSize={8}>ATM 0.5</text>
      </GreekPanel>
      <GreekPanel testid="greek-gamma" title={D("gamma", lang)} text={D("gammaT", lang)}>
        <path d={curve(gamma, 23600, 24400, 50, x, (v) => 88 - v * 70)} fill="none" stroke={ORANGE} strokeWidth={2.5} />
        <text x={x(24000)} y={12} textAnchor="middle" className={TXT} fontSize={8}>ATM</text>
      </GreekPanel>
      <GreekPanel testid="greek-theta" title={D("theta", lang)} text={D("thetaT", lang)}>
        <path d={curve((d) => 200 * Math.sqrt(Math.max(d, 0) / 30), 30, 0, 50, tx, ty)} fill="none" stroke={RED} strokeWidth={2.5} />
        <text x={14} y={96} className={TXT} fontSize={8}>30 → 0</text>
      </GreekPanel>
      <GreekPanel testid="greek-vega" title={D("vega", lang)} text={D("vegaT", lang)}>
        <path d={curve((v) => 40 + 100 * Math.sqrt((v - 10) / 20), 10, 30, 40, vx, vy)} fill="none" stroke={GREEN} strokeWidth={2.5} />
        <text x={14} y={96} className={TXT} fontSize={8}>IV →</text>
      </GreekPanel>
    </div>
  );
}

// ------------------------------------------------------------------ support / resistance
function Structure({ lang }: { lang: Lang }) {
  const pts = [[10, 100], [38, 62], [66, 112], [96, 119], [126, 78], [158, 61], [188, 102], [218, 119], [246, 72], [262, 58], [284, 40], [310, 24]];
  const path = pts.map(([x, y], i) => `${i ? "L" : "M"}${x},${y}`).join(" ");
  return (
    <Svg vb="0 0 330 165" label={tt(DIAGRAM_META.structure.title, lang)}>
      <line x1={10} y1={60} x2={320} y2={60} stroke={RED} strokeDasharray="5 3" strokeWidth={1.5} />
      <line x1={10} y1={119} x2={320} y2={119} stroke={GREEN} strokeDasharray="5 3" strokeWidth={1.5} />
      <path d={path} fill="none" stroke={BLUE} strokeWidth={2.5} strokeLinejoin="round" />
      <text x={12} y={54} fill={RED} fontSize={10} fontWeight={700}>{D("resistance", lang)} 24,200</text>
      <text x={12} y={134} fill={GREEN} fontSize={10} fontWeight={700}>{D("support", lang)} 23,900</text>
      <circle cx={262} cy={58} r={5} fill="none" stroke={ORANGE} strokeWidth={2} />
      <text x={250} y={96} textAnchor="middle" fill={ORANGE} fontSize={10} fontWeight={700}>{D("breakout", lang)}</text>
      <path d="M250,100 L260,66" stroke={ORANGE} strokeWidth={1.5} />
    </Svg>
  );
}

// ------------------------------------------------------------------ risk against reward
function Risk({ lang }: { lang: Lang }) {
  const risk = planRisk(), reward = planReward(), k = 200 / reward;
  return (
    <Svg vb="0 0 330 130" label={tt(DIAGRAM_META.risk.title, lang)}>
      <text x={10} y={24} className={TXT} fontSize={11} fontWeight={700}>{D("risk", lang)}</text>
      <rect x={10} y={30} width={risk * k} height={22} rx={4} fill={RED} fillOpacity={0.75} />
      <text x={16 + risk * k} y={46} className={TXT} fontSize={11}>{rs(risk)}</text>
      <text x={10} y={76} className={TXT} fontSize={11} fontWeight={700}>{D("reward", lang)}</text>
      <rect x={10} y={82} width={reward * k} height={22} rx={4} fill={GREEN} fillOpacity={0.75} />
      <text x={16 + reward * k} y={98} className={TXT} fontSize={11}>{rs(reward)}</text>
      <text x={320} y={20} textAnchor="end" className={TXT} fontSize={11} fontWeight={700}>1 : {reward / risk}</text>
      <text x={320} y={124} textAnchor="end" className={TXT} fontSize={10}>{D("winrate", lang)}: {Math.round(breakEvenWinRate() * 100)}%</text>
      <text x={10} y={124} className={TXT} fontSize={9}>{PLAN.entry} → {PLAN.stop} / {PLAN.target}</text>
    </Svg>
  );
}

const BODY: Record<DiagramKey, (p: { lang: Lang }) => React.ReactElement> = {
  cepe: CePe, positions: Positions, moneyness: Moneyness, premium: Premium, decay: Decay, volatility: Volatility, chain: Chain, greeks: Greeks, structure: Structure, risk: Risk,
};

/** A diagram with its title and a plain-language explanation, in the chosen language. */
export function Diagram({ k, lang, n }: { k: DiagramKey; lang: Lang; n: number }) {
  const Body = BODY[k];
  const m = DIAGRAM_META[k];
  return (
    <Card title={<span>{tt(UI.figure, lang)} {n}: {tt(m.title, lang)}</span>} className="print:break-inside-avoid" bodyClass="space-y-3 px-4 pb-4">
      <div data-testid={`diagram-${k}`}><Body lang={lang} /></div>
      <p className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700 dark:bg-slate-800/60 dark:text-slate-200" data-testid={`caption-${k}`}>{tt(m.caption, lang)}</p>
      <p className="text-[11px] text-slate-500">{tt(UI.illustrative, lang)}</p>
    </Card>
  );
}
