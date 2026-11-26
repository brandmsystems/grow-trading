/** Illustrative NIFTY examples for the Learning Centre. Every number is made up for teaching and is not a live price or a
 *  recommendation. The profit and loss figures are calculated here (not typed in), so the lessons and the page always agree. */
import { l, type L } from "./lessons";

export const LOT = 75;
export type Side = "buy" | "sell";
export type Kind = "CE" | "PE";
export interface Position { side: Side; kind: Kind; strike: number; premium: number }

/** Value of one unit of the option at expiry. */
export const intrinsic = (kind: Kind, strike: number, spot: number) => Math.max(kind === "CE" ? spot - strike : strike - spot, 0);

/** Profit (+) or loss (-) in rupees for one lot held to expiry, before brokerage, taxes and charges. */
export function expiryPnl(pos: Position, spot: number, lot = LOT): number {
  const gain = intrinsic(pos.kind, pos.strike, spot) - pos.premium;
  return Math.round((pos.side === "buy" ? gain : -gain) * lot) + 0;      // + 0 turns -0 into 0
}

/** Profit (+) or loss (-) in rupees for one lot when the option is bought or sold at `entry` and closed at `exit`. */
export const tradePnl = (side: Side, entry: number, exit: number, lot = LOT) => Math.round((side === "buy" ? exit - entry : entry - exit) * lot) + 0;

export const breakeven = (pos: Position) => (pos.kind === "CE" ? pos.strike + pos.premium : pos.strike - pos.premium);

export const POSITIONS: Record<"buyCE" | "buyPE" | "sellCE" | "sellPE", Position> = {
  buyCE: { side: "buy", kind: "CE", strike: 24000, premium: 120 },
  buyPE: { side: "buy", kind: "PE", strike: 24000, premium: 110 },
  sellCE: { side: "sell", kind: "CE", strike: 24200, premium: 60 },
  sellPE: { side: "sell", kind: "PE", strike: 23800, premium: 55 },
};

/** Risk and reward of the stop-loss / target example, and the position-size example. */
export const PLAN = { entry: 120, stop: 84, target: 192, capital: 300000, riskPct: 1 };
export const planRisk = () => (PLAN.entry - PLAN.stop) * LOT;
export const planReward = () => (PLAN.target - PLAN.entry) * LOT;
export const planRatio = () => planReward() / planRisk();
export const breakEvenWinRate = () => 1 / (1 + planRatio());
export const planLots = () => Math.floor((PLAN.capital * PLAN.riskPct / 100) / planRisk());

/** IV crush example: premium before and after, NIFTY unchanged. */
export const CRUSH = { before: 150, after: 110 };

export const inr = (n: number) => `${n < 0 ? "-" : n > 0 ? "+" : ""}₹${Math.abs(n).toLocaleString("en-IN")}`;
export const rs = (n: number) => `₹${n.toLocaleString("en-IN")}`;

export interface ExampleRow { label: L; value: string; tone?: "good" | "bad" }
export interface Example { id: string; title: L; setup: L; rows: ExampleRow[]; note: L }

const sc = (pos: Position, spot: number): ExampleRow => {
  const v = expiryPnl(pos, spot);
  return { label: l(`NIFTY ends at ${spot.toLocaleString("en-IN")}`, `NIFTY ${spot.toLocaleString("en-IN")}-ൽ അവസാനിച്ചാൽ`), value: inr(v), tone: v > 0 ? "good" : v < 0 ? "bad" : undefined };
};
const B = POSITIONS;
const ce = B.buyCE, pe = B.buyPE, sce = B.sellCE;

export const EXAMPLES: Example[] = [
  {
    id: "buyce-trade",
    title: l("Example 1: Buy CE, exit early with a stop loss and a target", "ഉദാഹരണം 1: Buy CE, സ്റ്റോപ് ലോസും ടാർഗറ്റും ഉപയോഗിച്ച് നേരത്തെ പുറത്തുകടക്കൽ"),
    setup: l(`NIFTY is near 24,000. You buy 1 lot (${LOT}) of the 24,000 CE at ${PLAN.entry}. Your plan: stop loss ${PLAN.stop}, target ${PLAN.target}.`,
      `NIFTY 24,000 അടുത്ത്. നിങ്ങൾ 24,000 CE-യുടെ 1 ലോട്ട് (${LOT}) ${PLAN.entry}-ന് വാങ്ങുന്നു. പ്ലാൻ: സ്റ്റോപ് ലോസ് ${PLAN.stop}, ടാർഗറ്റ് ${PLAN.target}.`),
    rows: [
      { label: l("Entry cost", "പ്രവേശന ചെലവ്"), value: rs(PLAN.entry * LOT) },
      { label: l(`Target hit: exit at ${PLAN.target}`, `ടാർഗറ്റ് എത്തി: ${PLAN.target}-ൽ പുറത്തുകടക്കുന്നു`), value: inr(tradePnl("buy", PLAN.entry, PLAN.target)), tone: "good" },
      { label: l(`Stop loss hit: exit at ${PLAN.stop}`, `സ്റ്റോപ് ലോസ് എത്തി: ${PLAN.stop}-ൽ പുറത്തുകടക്കുന്നു`), value: inr(tradePnl("buy", PLAN.entry, PLAN.stop)), tone: "bad" },
      { label: l("Risk : reward", "റിസ്ക് : റിവാർഡ്"), value: `1 : ${planRatio()}` },
    ],
    note: l("Profit or loss = (exit - entry) x 75, before brokerage, taxes and charges. The loss is fixed by the stop loss; without a stop it could be the whole 9,000.",
      "ലാഭം/നഷ്ടം = (പുറത്തുകടക്കുന്ന വില - പ്രവേശന വില) x 75, ബ്രോക്കറേജ്, നികുതി, ചാർജുകൾക്ക് മുമ്പ്. സ്റ്റോപ് ലോസ് നഷ്ടം നിശ്ചയിക്കുന്നു; സ്റ്റോപ് ഇല്ലെങ്കിൽ 9,000 മുഴുവനും നഷ്ടപ്പെടാം."),
  },
  {
    id: "buyce-expiry",
    title: l("Example 2: Buy CE held to expiry", "ഉദാഹരണം 2: Buy CE എക്സ്പയറിവരെ കൈവശം വച്ചാൽ"),
    setup: l(`Buy 1 lot of the 24,000 CE at ${ce.premium} (cost ${rs(ce.premium * LOT)}). Breakeven is ${breakeven(ce).toLocaleString("en-IN")}.`,
      `24,000 CE-യുടെ 1 ലോട്ട് ${ce.premium}-ന് വാങ്ങുന്നു (ചെലവ് ${rs(ce.premium * LOT)}). ബ്രേക്ക്ഈവൻ ${breakeven(ce).toLocaleString("en-IN")}.`),
    rows: [sc(ce, 23900), sc(ce, 24000), sc(ce, 24120), sc(ce, 24300)],
    note: l("Below the strike the CE is worth nothing, so the loss stops at the premium paid. Between 24,000 and 24,120 the CE has value but not enough to cover the premium.",
      "സ്ട്രൈക്കിന് താഴെ CE-ക്ക് മൂല്യമില്ല, അതിനാൽ നഷ്ടം നൽകിയ പ്രീമിയത്തിൽ അവസാനിക്കുന്നു. 24,000-നും 24,120-നും ഇടയിൽ CE-ക്ക് മൂല്യമുണ്ട്, പക്ഷേ പ്രീമിയം തിരിച്ചുപിടിക്കാൻ പര്യാപ്തമല്ല."),
  },
  {
    id: "buype-expiry",
    title: l("Example 3: Buy PE held to expiry", "ഉദാഹരണം 3: Buy PE എക്സ്പയറിവരെ കൈവശം വച്ചാൽ"),
    setup: l(`Buy 1 lot of the 24,000 PE at ${pe.premium} (cost ${rs(pe.premium * LOT)}). Breakeven is ${breakeven(pe).toLocaleString("en-IN")}.`,
      `24,000 PE-യുടെ 1 ലോട്ട് ${pe.premium}-ന് വാങ്ങുന്നു (ചെലവ് ${rs(pe.premium * LOT)}). ബ്രേക്ക്ഈവൻ ${breakeven(pe).toLocaleString("en-IN")}.`),
    rows: [sc(pe, 24100), sc(pe, 24000), sc(pe, 23890), sc(pe, 23700)],
    note: l("A PE gains as NIFTY falls below the strike. Above the strike it expires worthless and you lose only the premium.",
      "NIFTY സ്ട്രൈക്കിന് താഴെ പോകുമ്പോൾ PE-ക്ക് നേട്ടം. സ്ട്രൈക്കിന് മുകളിൽ അത് വിലയില്ലാതാകും, പ്രീമിയം മാത്രം നഷ്ടപ്പെടും."),
  },
  {
    id: "sellce-expiry",
    title: l("Example 4: Sell CE (writing) held to expiry", "ഉദാഹരണം 4: Sell CE (റൈറ്റിംഗ്) എക്സ്പയറിവരെ"),
    setup: l(`Sell 1 lot of the 24,200 CE at ${sce.premium} and receive ${rs(sce.premium * LOT)} up front. Breakeven is ${breakeven(sce).toLocaleString("en-IN")}. Margin is blocked by the broker.`,
      `24,200 CE-യുടെ 1 ലോട്ട് ${sce.premium}-ന് വിൽക്കുകയും മുൻകൂറായി ${rs(sce.premium * LOT)} സ്വീകരിക്കുകയും ചെയ്യുന്നു. ബ്രേക്ക്ഈവൻ ${breakeven(sce).toLocaleString("en-IN")}. ബ്രോക്കർ മാർജിൻ തടഞ്ഞുവയ്ക്കുന്നു.`),
    rows: [sc(sce, 24100), sc(sce, 24200), sc(sce, 24260), sc(sce, 24400), sc(sce, 24600)],
    note: l("The gain is capped at the premium received. The loss grows point by point as NIFTY rises, with no upper limit.",
      "ലാഭം ലഭിച്ച പ്രീമിയത്തിൽ പരിമിതമാണ്. NIFTY ഉയരുന്തോറും നഷ്ടം പോയിന്റ് പോയിന്റായി കൂടുന്നു, മുകളിൽ പരിധിയില്ല."),
  },
  {
    id: "iv-crush",
    title: l("Example 5: IV crush after an event", "ഉദാഹരണം 5: സംഭവത്തിന് ശേഷമുള്ള IV ക്രഷ്"),
    setup: l(`Before an event you buy the 24,000 CE at ${CRUSH.before}. The event passes and NIFTY has not moved, but IV has fallen and the CE now trades at ${CRUSH.after}.`,
      `ഒരു സംഭവത്തിന് മുമ്പ് 24,000 CE ${CRUSH.before}-ന് വാങ്ങുന്നു. സംഭവം കഴിഞ്ഞു, NIFTY ചലിച്ചിട്ടില്ല, പക്ഷേ IV കുറഞ്ഞു; CE ഇപ്പോൾ ${CRUSH.after}-ൽ.`),
    rows: [{ label: l("Loss on 1 lot", "1 ലോട്ടിലെ നഷ്ടം"), value: inr(tradePnl("buy", CRUSH.before, CRUSH.after)), tone: "bad" }],
    note: l("The direction was not wrong, NIFTY simply did not move. The premium had included the uncertainty, and that part disappeared. All numbers are illustrative.",
      "ദിശ തെറ്റിയില്ല, NIFTY ചലിച്ചില്ല എന്നേയുള്ളൂ. പ്രീമിയത്തിൽ അനിശ്ചിതത്വം ഉൾപ്പെട്ടിരുന്നു, ആ ഭാഗം ഇല്ലാതായി. എല്ലാ സംഖ്യകളും ഉദാഹരണത്തിനുള്ളതാണ്."),
  },
  {
    id: "sizing",
    title: l("Example 6: Position sizing with a 1% rule", "ഉദാഹരണം 6: 1% നിയമം ഉപയോഗിച്ചുള്ള പൊസിഷൻ സൈസിംഗ്"),
    setup: l(`Capital ${rs(PLAN.capital)}. You risk ${PLAN.riskPct}% per trade, which is ${rs(PLAN.capital * PLAN.riskPct / 100)}. One lot of Example 1 risks ${rs(planRisk())}.`,
      `മൂലധനം ${rs(PLAN.capital)}. ഒരു ട്രേഡിൽ ${PLAN.riskPct}% അപകടത്തിലാക്കുന്നു, അത് ${rs(PLAN.capital * PLAN.riskPct / 100)}. ഉദാഹരണം 1-ലെ ഒരു ലോട്ടിന്റെ റിസ്ക് ${rs(planRisk())}.`),
    rows: [
      { label: l("Lots allowed (rounded down)", "അനുവദിക്കുന്ന ലോട്ടുകൾ (താഴേക്ക് റൗണ്ട്)"), value: String(planLots()) },
      { label: l("Money at risk with that size", "ആ വലിപ്പത്തിൽ അപകടത്തിലുള്ള പണം"), value: rs(planLots() * planRisk()) },
      { label: l("Win rate needed to break even at 1 : 2", "1 : 2-ൽ ബ്രേക്ക്ഈവനാകാൻ വേണ്ട വിജയ നിരക്ക്"), value: `${Math.round(breakEvenWinRate() * 100)}%` },
    ],
    note: l("If one lot risked more than the allowed amount, the answer would be 0 lots: skip the trade or choose a tighter stop.",
      "ഒരു ലോട്ടിന്റെ റിസ്ക് അനുവദിച്ച തുകയേക്കാൾ കൂടുതലാണെങ്കിൽ ഉത്തരം 0 ലോട്ട് ആയിരിക്കും: ട്രേഡ് ഒഴിവാക്കുക അല്ലെങ്കിൽ ചെറിയ സ്റ്റോപ് തിരഞ്ഞെടുക്കുക."),
  },
];

/** Sample option chain (illustrative). OI, change and volume are in lakh contracts. */
export interface ChainRow { strike: number; ce: { oi: number; chg: number; vol: number; ltp: number }; pe: { oi: number; chg: number; vol: number; ltp: number } }
export const CHAIN_SPOT = 24000;
export const CHAIN: ChainRow[] = [
  { strike: 23800, ce: { oi: 8.2, chg: 1.1, vol: 3.1, ltp: 235 }, pe: { oi: 26.4, chg: 7.9, vol: 8.4, ltp: 38 } },
  { strike: 23900, ce: { oi: 12.4, chg: -0.6, vol: 6.2, ltp: 165 }, pe: { oi: 19.7, chg: 3.2, vol: 9.9, ltp: 62 } },
  { strike: 24000, ce: { oi: 21.5, chg: 4.3, vol: 14.8, ltp: 105 }, pe: { oi: 24.1, chg: 2.0, vol: 15.2, ltp: 100 } },
  { strike: 24100, ce: { oi: 18.9, chg: 6.2, vol: 11.0, ltp: 60 }, pe: { oi: 9.3, chg: -0.8, vol: 5.6, ltp: 150 } },
  { strike: 24200, ce: { oi: 30.2, chg: 9.8, vol: 12.7, ltp: 32 }, pe: { oi: 5.1, chg: -0.5, vol: 3.3, ltp: 220 } },
];
export const chainTotals = () => {
  const ce = CHAIN.reduce((a, r) => a + r.ce.oi, 0), pe = CHAIN.reduce((a, r) => a + r.pe.oi, 0);
  return { ce: Math.round(ce * 10) / 10, pe: Math.round(pe * 10) / 10, pcr: Math.round((pe / ce) * 100) / 100 };
};
