/** Labels of the Learning Centre page itself, English and Malayalam, plus the language / progress state (remembered in the browser). */
import { useCallback, useEffect, useState } from "react";
import { l, type Lang, type L } from "./lessons";

export const UI = {
  title: l("Options Trading Learning Centre", "ഓപ്ഷൻ ട്രേഡിംഗ് ലേണിംഗ് സെന്റർ"),
  subtitle: l("Learn options from zero, in simple steps, with pictures and NIFTY examples.", "ഓപ്ഷൻസ് പൂജ്യത്തിൽ നിന്ന് പഠിക്കുക: ലളിതമായ ഘട്ടങ്ങൾ, ചിത്രങ്ങൾ, NIFTY ഉദാഹരണങ്ങൾ."),
  language: l("Language", "ഭാഷ"),
  disclaimer: l("For education only. Not investment advice. All prices and examples are illustrative, not live prices or recommendations. Options can lose the whole premium, and selling them can lose far more.",
    "വിദ്യാഭ്യാസത്തിന് മാത്രം. നിക്ഷേപ ഉപദേശമല്ല. എല്ലാ വിലകളും ഉദാഹരണങ്ങളും ഉദാഹരണത്തിനുള്ളതാണ്, ലൈവ് വിലകളോ ശുപാർശകളോ അല്ല. ഓപ്ഷനിൽ മുഴുവൻ പ്രീമിയവും നഷ്ടപ്പെടാം; വിൽക്കുമ്പോൾ അതിലും വളരെ കൂടുതൽ."),
  start: l("Start learning", "പഠനം ആരംഭിക്കുക"),
  cont: l("Continue learning", "പഠനം തുടരുക"),
  allDone: l("You have finished every lesson. Revisit any lesson, or read the latest news.", "നിങ്ങൾ എല്ലാ പാഠങ്ങളും പൂർത്തിയാക്കി. ഏത് പാഠവും വീണ്ടും വായിക്കാം, അല്ലെങ്കിൽ പുതിയ വാർത്തകൾ വായിക്കാം."),
  welcome: l("New to options? Start with lesson 1. Each lesson takes about 10 minutes.", "ഓപ്ഷൻസിൽ പുതിയതാണോ? പാഠം 1-ൽ നിന്ന് തുടങ്ങുക. ഓരോ പാഠത്തിനും ഏകദേശം 10 മിനിറ്റ്."),
  progress: l("Your progress", "നിങ്ങളുടെ പുരോഗതി"),
  lessonsDone: l("lessons completed", "പാഠങ്ങൾ പൂർത്തിയായി"),
  search: l("Search lessons and terms", "പാഠങ്ങളും പദങ്ങളും തിരയുക"),
  searchResults: l("Search results", "തിരയൽ ഫലങ്ങൾ"),
  noResults: l("Nothing found. Try a shorter word, for example delta, expiry or premium.", "ഒന്നും കണ്ടില്ല. ചെറിയ വാക്ക് പരീക്ഷിക്കുക, ഉദാഹരണത്തിന് delta, expiry, premium."),
  clear: l("Clear search", "തിരയൽ മായ്ക്കുക"),
  home: l("Start here", "ഇവിടെ തുടങ്ങുക"),
  lessonsHead: l("Lessons", "പാഠങ്ങൾ"),
  toolsHead: l("Tools", "ഉപകരണങ്ങൾ"),
  glossary: l("Glossary", "പദാവലി"),
  roadmap: l("Learning roadmap", "പഠന റോഡ്മാപ്പ്"),
  news: l("Latest options & market news", "ഏറ്റവും പുതിയ ഓപ്ഷൻസ്, വിപണി വാർത്തകൾ"),
  keyIdea: l("Key idea", "പ്രധാന ആശയം"),
  risk: l("Risk warning", "റിസ്ക് മുന്നറിയിപ്പ്"),
  minutes: l("min", "മിനിറ്റ്"),
  markDone: l("Mark as complete", "പൂർത്തിയായതായി അടയാളപ്പെടുത്തുക"),
  markUndo: l("Completed. Click to undo", "പൂർത്തിയായി. തിരുത്താൻ ക്ലിക്ക് ചെയ്യുക"),
  prev: l("Previous", "മുമ്പത്തേത്"),
  next: l("Next", "അടുത്തത്"),
  open: l("Open", "തുറക്കുക"),
  done: l("Done", "പൂർത്തിയായി"),
  todo: l("To do", "ബാക്കി"),
  figure: l("Figure", "ചിത്രം"),
  illustrative: l("Illustrative values, not live prices.", "ഉദാഹരണ മൂല്യങ്ങൾ, ലൈവ് വിലകളല്ല."),
  examplesHead: l("Worked examples", "ഉദാഹരണ കണക്കുകൾ"),
  glossarySearch: l("Filter terms", "പദങ്ങൾ ഫിൽട്ടർ ചെയ്യുക"),
  terms: l("terms", "പദങ്ങൾ"),
  resetProgress: l("Reset progress", "പുരോഗതി റീസെറ്റ് ചെയ്യുക"),
  roadmapIntro: l("Follow the three levels in order. Tick each lesson off as you finish it.", "മൂന്ന് തലങ്ങളും ക്രമത്തിൽ പിന്തുടരുക. ഓരോ പാഠവും പൂർത്തിയാക്കുമ്പോൾ അടയാളപ്പെടുത്തുക."),
  // news
  newsIntro: l("Real articles from publisher feeds, with the original link. Nothing here is written or invented by this page.", "പ്രസാധകരുടെ ഫീഡുകളിൽ നിന്നുള്ള യഥാർത്ഥ ലേഖനങ്ങൾ, ഒറിജിനൽ ലിങ്കോടെ. ഈ പേജ് ഇവിടെ ഒന്നും എഴുതുകയോ കെട്ടിച്ചമയ്ക്കുകയോ ചെയ്യുന്നില്ല."),
  refresh: l("Refresh news", "വാർത്തകൾ പുതുക്കുക"),
  loadingNews: l("Fetching the latest news…", "പുതിയ വാർത്തകൾ എടുക്കുന്നു…"),
  newsError: l("Could not load the news.", "വാർത്തകൾ ലോഡ് ചെയ്യാൻ കഴിഞ്ഞില്ല."),
  retry: l("Try again", "വീണ്ടും ശ്രമിക്കുക"),
  notConnected: l("Live news is not connected right now. No news source answered, so nothing is shown instead of made-up headlines. Try Refresh later.",
    "ലൈവ് വാർത്ത ഇപ്പോൾ ബന്ധിപ്പിച്ചിട്ടില്ല. ഒരു വാർത്താ സ്രോതസ്സും മറുപടി നൽകിയില്ല; കെട്ടിച്ചമച്ച തലക്കെട്ടുകൾക്ക് പകരം ഒന്നും കാണിക്കുന്നില്ല. പിന്നീട് പുതുക്കി നോക്കുക."),
  stale: l("The news could not be refreshed. These are the articles from the last successful fetch at", "വാർത്തകൾ പുതുക്കാൻ കഴിഞ്ഞില്ല. അവസാനം വിജയകരമായി എടുത്ത ലേഖനങ്ങളാണിവ, സമയം"),
  emptyNews: l("No articles match this topic right now.", "ഈ വിഷയത്തിൽ ഇപ്പോൾ ലേഖനങ്ങളൊന്നുമില്ല."),
  updated: l("Last updated", "അവസാനം പുതുക്കിയത്"),
  readMore: l("Read the original article", "ഒറിജിനൽ ലേഖനം വായിക്കുക"),
  source: l("Source", "ഉറവിടം"),
  published: l("Published", "പ്രസിദ്ധീകരിച്ചത്"),
  showMore: l("Show more", "കൂടുതൽ കാണിക്കുക"),
  mlNote: l("Malayalam summary is built from the article's tags. The headline and the publisher's own summary stay in English because no translation service is connected.",
    "മലയാള സംഗ്രഹം ലേഖനത്തിന്റെ ടാഗുകളിൽ നിന്ന് ഉണ്ടാക്കിയതാണ്. പരിഭാഷാ സേവനം ബന്ധിപ്പിക്കാത്തതിനാൽ തലക്കെട്ടും പ്രസാധകന്റെ സ്വന്തം സംഗ്രഹവും ഇംഗ്ലീഷിൽ തുടരുന്നു."),
  publisherSummary: l("Publisher's summary", "പ്രസാധകന്റെ സംഗ്രഹം"),
  noSummary: l("This publisher gives no summary. Open the original article.", "ഈ പ്രസാധകൻ സംഗ്രഹം നൽകുന്നില്ല. ഒറിജിനൽ ലേഖനം തുറക്കുക."),
  topics: {
    all: l("All", "എല്ലാം"), nifty: l("NIFTY", "NIFTY"), options: l("Options", "ഓപ്ഷൻസ്"), nse: l("NSE", "NSE"), sebi: l("SEBI", "SEBI"),
    vix: l("India VIX / volatility", "ഇന്ത്യ VIX / വോളാറ്റിലിറ്റി"), fii: l("FII / DII", "FII / DII"), global: l("Global markets", "ആഗോള വിപണികൾ"),
  } as Record<string, L>,
  levelLabel: { beginner: l("Beginner", "തുടക്കക്കാർ"), intermediate: l("Intermediate", "ഇടത്തരം"), advanced: l("Advanced", "ഉയർന്ന തലം") } as Record<string, L>,
  // diagram labels
  d: {
    profit: l("Profit", "ലാഭം"), loss: l("Loss", "നഷ്ടം"), strike: l("Strike", "സ്ട്രൈക്ക്"), nifty: l("NIFTY at expiry", "എക്സ്പയറിയിൽ NIFTY"),
    right_buy: l("Right to BUY", "വാങ്ങാനുള്ള അവകാശം"), right_sell: l("Right to SELL", "വിൽക്കാനുള്ള അവകാശം"), market_up: l("Gains when NIFTY rises", "NIFTY ഉയരുമ്പോൾ നേട്ടം"),
    market_down: l("Gains when NIFTY falls", "NIFTY താഴുമ്പോൾ നേട്ടം"), intrinsic: l("Intrinsic value", "ഇൻട്രിൻസിക് വാല്യൂ"), timev: l("Time value", "ടൈം വാല്യൂ"), premium: l("Premium", "പ്രീമിയം"),
    days: l("Days to expiry", "എക്സ്പയറിക്ക് ബാക്കി ദിവസം"), slow: l("Slow at first", "ആദ്യം പതുക്കെ"), fast: l("Fast near expiry", "എക്സ്പയറിക്ക് അടുത്ത് വേഗത്തിൽ"),
    event: l("Event", "സംഭവം"), crush: l("IV crush", "IV ക്രഷ്"), iv: l("IV %", "IV %"), support: l("Support", "സപ്പോർട്ട്"), resistance: l("Resistance", "റെസിസ്റ്റൻസ്"),
    breakout: l("Breakout", "ബ്രേക്ക്ഔട്ട്"), risk: l("Risk", "റിസ്ക്"), reward: l("Reward", "റിവാർഡ്"), winrate: l("Break-even win rate", "ബ്രേക്ക്ഈവൻ വിജയ നിരക്ക്"),
    calls: l("CALLS (CE)", "കോളുകൾ (CE)"), puts: l("PUTS (PE)", "പുട്ടുകൾ (PE)"), atm: l("ATM", "ATM"), itm: l("ITM", "ITM"), otm: l("OTM", "OTM"), spot: l("NIFTY", "NIFTY"),
    oi: l("OI", "OI"), chg: l("OI chg", "OI മാറ്റം"), vol: l("Volume", "വോളിയം"), ltp: l("LTP", "LTP"), pcr: l("PCR", "PCR"), totals: l("Total OI (lakh)", "മൊത്തം OI (ലക്ഷം)"),
    buyers: l("Loss limited to the premium. Gain can be large.", "നഷ്ടം പ്രീമിയത്തിൽ ഒതുങ്ങും. ലാഭം വലുതാകാം."), sellers: l("Gain limited to the premium. Loss can be large.", "ലാഭം പ്രീമിയത്തിൽ ഒതുങ്ങും. നഷ്ടം വലുതാകാം."),
    delta: l("Delta", "ഡെൽറ്റ"), gamma: l("Gamma", "ഗാമ"), theta: l("Theta", "തീറ്റ"), vega: l("Vega", "വേഗ"),
    deltaT: l("How much the premium moves per point of NIFTY (0 to 1 for a CE).", "NIFTY ഒരു പോയിന്റ് ചലിക്കുമ്പോൾ പ്രീമിയം ചലിക്കുന്നത് (CE-ക്ക് 0 മുതൽ 1 വരെ)."),
    gammaT: l("How fast delta changes. Highest at the money.", "ഡെൽറ്റ മാറുന്ന വേഗത. ATM-ൽ ഏറ്റവും കൂടുതൽ."),
    thetaT: l("Premium lost to time every day. Faster near expiry.", "ദിവസവും സമയം മൂലം നഷ്ടപ്പെടുന്ന പ്രീമിയം. എക്സ്പയറിക്ക് അടുത്ത് വേഗത്തിൽ."),
    vegaT: l("Premium rises when IV rises.", "IV കൂടുമ്പോൾ പ്രീമിയം കൂടുന്നു."),
    now: l("NIFTY 24,000", "NIFTY 24,000"),
  } as Record<string, L>,
};

export const tt = (x: L, lang: Lang) => x[lang];

// ------------------------------------------------------------------ remembered state
const KEY = "learn.v1";
export interface Saved { lang: Lang; done: string[]; last: string | null }
const EMPTY: Saved = { lang: "en", done: [], last: null };

function load(): Saved {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return EMPTY;
    const v = JSON.parse(raw) as Partial<Saved>;
    return { lang: v.lang === "ml" ? "ml" : "en", done: Array.isArray(v.done) ? v.done.filter((x) => typeof x === "string") : [], last: typeof v.last === "string" ? v.last : null };
  } catch { return EMPTY; }
}

/** Language, completed lessons and the last lesson opened. Kept in localStorage; the page works without it. */
export function useLearn() {
  const [s, setS] = useState<Saved>(load);
  useEffect(() => { try { window.localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* private mode */ } }, [s]);
  const setLang = useCallback((lang: Lang) => setS((p) => ({ ...p, lang })), []);
  const toggle = useCallback((id: string) => setS((p) => ({ ...p, done: p.done.includes(id) ? p.done.filter((x) => x !== id) : [...p.done, id] })), []);
  const setLast = useCallback((id: string) => setS((p) => (p.last === id ? p : { ...p, last: id })), []);
  const reset = useCallback(() => setS((p) => ({ ...p, done: [], last: null })), []);
  return { lang: s.lang, done: s.done, last: s.last, setLang, toggle, setLast, reset };
}
