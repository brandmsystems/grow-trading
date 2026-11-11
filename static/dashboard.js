/* 9/21 EMA backtester dashboard */
(() => {
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const inr = (v, sign = false) => v == null || isNaN(v) ? "—" :
  (sign && v > 0 ? "+" : v < 0 ? "−" : "") + "₹" + Math.abs(v).toLocaleString("en-IN", {minimumFractionDigits: 2, maximumFractionDigits: 2});
const pnlCls = v => v > 0 ? "pos" : v < 0 ? "neg" : "";
const num = (v, d = 2) => v == null || isNaN(v) ? "—" : Number(v).toLocaleString("en-IN", {minimumFractionDigits: d, maximumFractionDigits: d});
const hhmm = iso => iso ? iso.slice(11, 16) : "—";
const dmy = iso => { const d = new Date(iso.slice(0, 10) + "T00:00:00Z"); return d.toLocaleDateString("en-IN", {day: "2-digit", month: "short", year: "2-digit", timeZone: "UTC"}); };
const toTime = iso => Math.floor(Date.parse(iso + "Z") / 1000);   // IST wall clock shown as-is
const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
};

const S = {
  meta: null, params: null, result: null, hash: null,
  filters: {mode: "ATM_BUY", outcome: "all", ordinal: "all", exit: "all"},
  list: [], selId: null, chartCache: new Map(), busy: false,
};
const MODE_SHORT = {ITM5_BUY: "ITM 5 buy", ATM_BUY: "ATM buy", ATM_SELL: "ATM sell"};
const MODE_SLOT = {ITM5_BUY: "--s1", ATM_BUY: "--s2", ATM_SELL: "--s3"};

// ------------------------------------------------------------------ API
async function api(url, opts = {}) {
  if (opts.body && typeof opts.body !== "string") {
    opts.body = JSON.stringify(opts.body);
    opts.headers = {"Content-Type": "application/json"};
  }
  let r;
  try { r = await fetch(url, opts); } catch (e) { throw new Error("Server unreachable. Is app.py running?"); }
  const j = await r.json().catch(() => ({ok: false, error: `HTTP ${r.status}`}));
  if (!j.ok) throw Object.assign(new Error(j.error || "Request failed"), {kind: j.kind, status: r.status});
  return j;
}

function banner(msg, kind = "error") {
  const b = $("#banner");
  if (!msg) { b.style.display = "none"; return; }
  b.className = "banner" + (kind === "info" ? " info" : "");
  b.textContent = msg; b.style.display = "block";
}
function progress(frac, msg) {
  const p = $("#progress");
  if (frac == null) { p.hidden = true; return; }
  p.hidden = false; $("#pfill").style.width = Math.round(frac * 100) + "%"; $("#pmsg").textContent = msg || "";
}
function setBusy(b) {
  S.busy = b;
  ["#runBtn", "#downloadBtn", "#emptyRun", "#emptyDownload"].forEach(s => $(s).disabled = b);
}

async function pollJob(jid) {
  for (;;) {
    const {data: j} = await api(`/api/jobs/${jid}`);
    progress(j.progress, j.message);
    if (j.state === "done") return j.result;
    if (j.state === "error") throw new Error(j.error);
    await new Promise(r => setTimeout(r, 500));
  }
}

// ------------------------------------------------------------------ params / settings
function readSettings() {
  const p = S.params;
  p.dataset = $("#p_dataset").value;
  p.start_date = $("#p_start_date").value;
  p.end_date = $("#p_end_date").value;
  p.roll_on_expiry_day = $("#p_roll_on_expiry_day").checked;
  p.lot_size = +$("#p_lot_size").value; p.lots = +$("#p_lots").value; p.capital = +$("#p_capital").value;
  $$("[id^=c_]").forEach(el => {
    const scale = +(el.dataset.scale || 1);
    p.costs[el.id.slice(2)] = +el.value / scale;
  });
  store.set("bt_params", p);
}
function writeSettings() {
  const p = S.params;
  $("#p_dataset").value = p.dataset;
  $("#p_start_date").value = p.start_date; $("#p_end_date").value = p.end_date;
  $("#p_roll_on_expiry_day").checked = !!p.roll_on_expiry_day;
  $("#p_lot_size").value = p.lot_size; $("#p_lots").value = p.lots; $("#p_capital").value = p.capital;
  $$("[id^=c_]").forEach(el => {
    const scale = +(el.dataset.scale || 1);
    el.value = +(p.costs[el.id.slice(2)] * scale).toPrecision(6);
  });
  updateDatasetInfo();
}
function updateDatasetInfo() {
  const ds = S.params.dataset, info = S.meta.datasets[ds] || {};
  const badge = $("#datasetBadge");
  badge.className = "badge " + ds;
  badge.textContent = ds === "synthetic" ? "SYNTHETIC DEMO DATA" : "Groww market data";
  let t = info.error ? `Database error: ${info.error}` :
    info.rows ? `${info.days} sessions stored (${info.first.slice(0, 10)} → ${info.last.slice(0, 10)}).` : "No data stored yet.";
  if (ds === "groww" && !S.meta.keys) t += " keys.txt is incomplete: add the TOTP secret to download real data.";
  if (ds === "synthetic") t += " Generated random-walk prices for trying the app. Not market data; results mean nothing.";
  $("#datasetInfo").textContent = t;
}

function buildFilters() {
  const seg = (el, items, cur, on) => {
    el.innerHTML = items.map(([v, l]) => `<button type="button" data-v="${v}" aria-pressed="${String(v) === String(cur)}">${l}</button>`).join("");
    el.onclick = e => { const b = e.target.closest("button"); if (!b) return; $$("button", el).forEach(x => x.setAttribute("aria-pressed", x === b)); on(b.dataset.v); };
  };
  seg($("#f_tf"), S.meta.timeframes.map(t => [t, t + "m"]), S.params.timeframe, v => { S.params.timeframe = +v; store.set("bt_params", S.params); runBacktest(); });
  seg($("#f_mode"), Object.keys(S.meta.modes).map(m => [m, MODE_SHORT[m]]), S.filters.mode, v => { S.filters.mode = v; S.selId = null; render(); });
  $("#f_start").innerHTML = S.meta.starts.map(s => `<option>${s}</option>`).join("");
  $("#f_cutoff").innerHTML = S.meta.cutoffs.map(s => `<option>${s}</option>`).join("");
  $("#f_start").value = S.params.entry_start; $("#f_cutoff").value = S.params.cutoff;
  $("#f_start").onchange = e => { S.params.entry_start = e.target.value; store.set("bt_params", S.params); runBacktest(); };
  $("#f_cutoff").onchange = e => { S.params.cutoff = e.target.value; store.set("bt_params", S.params); runBacktest(); };
  $("#p_end_date").onchange = e => store.set("bt_end_auto", e.target.value >= S.meta.defaults.end_date);
  for (const k of ["outcome", "ordinal", "exit"]) {
    $(`#f_${k}`).value = S.filters[k];
    $(`#f_${k}`).onchange = e => { S.filters[k] = e.target.value; S.selId = null; render(); };
  }
}

// ------------------------------------------------------------------ run flow
async function runBacktest(force = false) {
  if (S.busy) return;
  banner(null); setBusy(true);
  try {
    progress(0.01, "Starting backtest");
    const r = await api("/api/bt/run", {method: "POST", body: {...S.params, force}});
    const h = r.hash || (await pollJob(r.job)).hash;
    await loadResult(h);
  } catch (e) {
    if (/No spot data/.test(e.message)) showEmpty("No data for this range", e.message + " Use Download data, then run.");
    else banner(e.message);
  } finally { progress(null); setBusy(false); }
}

async function downloadData() {
  if (S.busy) return;
  readSettings(); banner(null); setBusy(true);
  try {
    progress(0.01, "Starting download");
    const {job} = await api("/api/bt/data", {method: "POST", body: S.params});
    await pollJob(job);
    S.meta = (await api("/api/bt/meta")).data; updateDatasetInfo();
    S.chartCache.clear();
    setBusy(false);
    await runBacktest(true);
  } catch (e) {
    banner(e.kind === "keys" || /keys\.txt|TOTP/.test(e.message)
      ? e.message + " Open keys.txt and add TOTP_SECRET, or switch to the synthetic dataset in Settings."
      : /forbidden/i.test(e.message)
        ? "Groww refused market data (403). Your API plan doesn't include it yet. Switch to the synthetic dataset in Settings, or enable market data on Groww."
        : "Download failed: " + e.message);
  } finally { progress(null); setBusy(false); }
}

async function loadResult(h) {
  const {data} = await api(`/api/bt/result/${h}`);
  S.result = data; S.hash = h; S.chartCache.clear();
  if (!S.selId || !findTrade(S.selId)) S.selId = null;
  $("#empty").hidden = true; $("#content").hidden = false;
  render();
}

function showEmpty(title, msg) {
  $("#content").hidden = true; $("#empty").hidden = false;
  $("#emptyTitle").textContent = title; $("#emptyMsg").textContent = msg;
}

// ------------------------------------------------------------------ metrics (mirror of metrics.py)
function metrics(trades, capital) {
  const n = trades.length, nets = trades.map(t => t.net);
  const wins = nets.filter(x => x > 0), losses = nets.filter(x => x <= 0);
  const sw = wins.reduce((a, b) => a + b, 0), sl = -losses.reduce((a, b) => a + b, 0);
  let eq = capital, peak = capital, dd = 0, ddp = 0; const curve = [];
  for (const t of trades) { eq += t.net; peak = Math.max(peak, eq); const d = peak - eq; dd = Math.max(dd, d); if (peak > 0) ddp = Math.max(ddp, d / peak * 100); curve.push([t.exit_ts, eq]); }
  const aw = wins.length ? sw / wins.length : 0, al = losses.length ? sl / losses.length : 0;
  return {
    trades: n, wins: wins.length, win_rate: n ? wins.length / n * 100 : 0,
    net: nets.reduce((a, b) => a + b, 0), gross: trades.reduce((a, t) => a + t.gross, 0),
    friction: trades.reduce((a, t) => a + t.friction, 0),
    pf: sl > 0 ? sw / sl : (wins.length ? Infinity : null), payoff: al > 0 ? aw / al : null,
    exp: n ? nets.reduce((a, b) => a + b, 0) / n : 0, dd, ddp, curve,
  };
}
const pfText = v => v == null ? "—" : v === Infinity ? "∞" : num(v);

function passes(t, ignoreOutcome = false) {
  const f = S.filters;
  if (!ignoreOutcome && f.outcome !== "all" && t.outcome !== f.outcome) return false;
  if (f.ordinal !== "all" && (f.ordinal === "4" ? t.ordinal < 4 : t.ordinal !== +f.ordinal)) return false;
  if (f.exit === "whipsaw" ? !t.whipsaw : f.exit !== "all" && t.exit_reason !== f.exit) return false;
  return true;
}
function findTrade(id) {
  if (!S.result) return null;
  const m = id.slice(0, id.lastIndexOf("-"));
  return (S.result.trades[m] || []).find(t => t.id === id) || null;
}

// ------------------------------------------------------------------ rendering
function kpi(l, v, cls = "", sub = "") {
  return `<div class="kpi"><div class="l">${l}</div><div class="v num ${cls}">${v}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;
}

function render() {
  const r = S.result; if (!r) return;
  const cap = r.params.capital;
  S.list = (r.trades[S.filters.mode] || []).filter(t => passes(t));
  if (!S.selId || !S.list.some(t => t.id === S.selId)) S.selId = S.list[0]?.id || null;
  const m = metrics(S.list, cap);
  const sel = S.selId ? findTrade(S.selId) : null;

  $("#kpis").innerHTML =
    kpi("Total trades", m.trades, "", `${m.wins} won · ${m.trades - m.wins} lost`) +
    kpi("Win rate", m.trades ? num(m.win_rate, 1) + "%" : "—") +
    kpi("Net PnL", inr(m.net, true), pnlCls(m.net)) +
    kpi("Gross PnL", inr(m.gross, true), pnlCls(m.gross)) +
    kpi("Profit factor", pfText(m.pf)) +
    kpi("Selected trade", sel ? inr(sel.net, true) : "—", sel ? pnlCls(sel.net) : "", sel ? `${dmy(sel.day)} · ${hhmm(sel.entry_ts)}` : "");
  $("#kpis2").innerHTML =
    kpi("Friction", inr(-m.friction)) + kpi("Payoff ratio", m.payoff == null ? "—" : num(m.payoff)) +
    kpi("Expectancy / trade", inr(m.exp, true), pnlCls(m.exp)) +
    kpi("Max drawdown", inr(-m.dd)) + kpi("Max drawdown %", m.trades ? num(m.ddp) + "%" : "—");

  const p = r.params;
  $("#runInfo").textContent = `${p.start_date} → ${p.end_date} · ${p.timeframe}m · entry ${p.entry_start}–${p.cutoff} · ${r.signals} signals · ${r.trade_days} sessions${r.partial_asof ? ` · today up to ${hhmm(r.partial_asof)}` : ""}`;
  renderCompare();
  renderList();
  renderNoTrade();
  $("#spotTf").textContent = `· ${p.timeframe}-minute`;
  if (sel) selectTrade(sel.id, false); else renderEmptyDetail();
}

function renderCompare() {
  const r = S.result, cap = r.params.capital;
  const rows = Object.keys(r.trades).map(mode => [mode, metrics(r.trades[mode].filter(t => passes(t, true)), cap)]);
  $("#compareTable").innerHTML = `<thead><tr><th>Mode</th><th>Trades</th><th>Win %</th><th>Gross</th><th>Friction</th><th>Net</th><th>PF</th><th>Payoff</th><th>Expect.</th><th>Max DD</th></tr></thead><tbody>` +
    rows.map(([mode, m]) => `<tr data-mode="${mode}" class="${mode === S.filters.mode ? "sel" : ""}">
      <td><span class="sw" style="background:var(${MODE_SLOT[mode]})"></span> ${esc(r.summary[mode].label)}</td>
      <td class="num">${m.trades}</td><td class="num">${m.trades ? num(m.win_rate, 1) : "—"}</td>
      <td class="num ${pnlCls(m.gross)}">${inr(m.gross, true)}</td><td class="num">${inr(-m.friction)}</td>
      <td class="num ${pnlCls(m.net)}"><b>${inr(m.net, true)}</b></td><td class="num">${pfText(m.pf)}</td>
      <td class="num">${m.payoff == null ? "—" : num(m.payoff)}</td><td class="num ${pnlCls(m.exp)}">${inr(m.exp, true)}</td>
      <td class="num">${inr(-m.dd)} <span class="muted">${num(m.ddp, 1)}%</span></td></tr>`).join("") + "</tbody>";
  $$("#compareTable tbody tr").forEach(tr => tr.onclick = () => {
    S.filters.mode = tr.dataset.mode; S.selId = null;
    $$("#f_mode button").forEach(b => b.setAttribute("aria-pressed", b.dataset.v === tr.dataset.mode));
    render();
  });
  Charts.equity(rows, cap);
}

function renderList() {
  $("#listCount").textContent = `· ${S.list.length}`;
  const el = $("#tradeList");
  if (!S.list.length) {
    el.innerHTML = `<div class="chart-msg" style="position:static;padding:40px 16px">No trades match these filters.</div>`;
    return;
  }
  el.innerHTML = S.list.map(t => `<div class="trow ${t.id === S.selId ? "sel" : ""}" data-id="${t.id}" role="option" aria-selected="${t.id === S.selId}">
      <span class="dir ${t.direction}">${t.direction === "Bullish" ? "▲ Bull" : "▼ Bear"}</span>
      <span class="when num">${dmy(t.day)} ${hhmm(t.entry_ts)}→${hhmm(t.exit_ts)}</span>
      <span class="pnl num ${pnlCls(t.net)}">${inr(t.net, true)}</span>
      <span class="sub"><span>${t.side} ${t.strike} ${t.opt_type}</span><span>#${t.ordinal}</span><span>${t.exit_reason === "square_off" ? "15:00" : t.exit_reason === "open" ? "open" : "cross"}</span>${t.whipsaw ? '<span class="tag">WHIPSAW</span>' : ""}</span>
    </div>`).join("");
  el.onclick = e => { const row = e.target.closest(".trow"); if (row) selectTrade(row.dataset.id); };
}

function renderNoTrade() {
  const r = S.result;
  $("#ntCount").textContent = `· ${r.no_trade_days.length} days, ${r.skipped.length} skipped`;
  $("#noTradeList").innerHTML = "<h3>No-trade days</h3>" + (r.no_trade_days.map(d => `<div><span class="num">${d.day}</span><span class="muted">${esc(d.reason)}</span></div>`).join("") || '<p class="muted">None</p>');
  $("#skippedList").innerHTML = "<h3>Skipped trades</h3>" + (r.skipped.map(s => `<div><span class="num">${s.day} ${hhmm(s.entry_ts)}</span><span>${MODE_SHORT[s.mode]}</span><span class="muted">${esc(s.reason)}</span></div>`).join("") || '<p class="muted">None</p>');
}

function renderEmptyDetail() {
  $("#metaBar").innerHTML = `<div class="m"><div class="mv muted">Select a trade to audit it.</div></div>`;
  $("#costCard").innerHTML = ""; $("#optSym").textContent = "";
  Charts.clear("No trade selected");
}

function selectTrade(id, scroll = true) {
  const t = findTrade(id); if (!t) return;
  S.selId = id;
  $$("#tradeList .trow").forEach(r => { const on = r.dataset.id === id; r.classList.toggle("sel", on); r.setAttribute("aria-selected", on); if (on && scroll) r.scrollIntoView({block: "nearest"}); });
  const selK = $("#kpis .kpi:last-child");
  if (selK) selK.outerHTML = kpi("Selected trade", inr(t.net, true), pnlCls(t.net), `${dmy(t.day)} · ${hhmm(t.entry_ts)}`);
  const M = (l, v, cls = "") => `<div class="m"><div class="ml">${l}</div><div class="mv num ${cls}">${v}</div></div>`;
  $("#metaBar").innerHTML =
    M("Symbol", esc(t.symbol.replace(/^SYNTH:/, "SYNTH "))) +
    M("Direction", `${t.direction} · ${t.side}`, t.direction === "Bullish" ? "pos" : "neg") +
    M("NIFTY entry → exit", `${num(t.spot_entry)} → ${num(t.spot_exit)}`) +
    M("Option entry → exit", `${num(t.opt_entry)} → ${num(t.opt_exit)}`) +
    M("Fills (after slippage)", `${num(t.entry_fill)} → ${num(t.exit_fill)}`) +
    M("Expiry / DTE", `${t.expiry} · ${t.dte}d`) +
    M("Exit reason", (t.exit_reason === "square_off" ? "15:00 square-off" : t.exit_reason === "open" ? "Still open, valued at latest price" : "Opposite cross") + ` · ${t.bars_held} bars`) +
    M("Cross #", t.ordinal + (t.whipsaw ? ' <span class="tag">WHIPSAW</span>' : "")) +
    M("Net PnL", inr(t.net, true), pnlCls(t.net));
  const c = t.charges, C = (l, v, cls = "") => `<div class="c ${cls}"><div class="cl">${l}</div><div class="cv num">${v}</div></div>`;
  $("#costCard").innerHTML = `<div class="card-head"><h2>Cost breakdown</h2><span class="muted">${t.qty} qty · ${t.side === "BUY" ? "buy → sell" : "sell → buy back"}</span></div><div class="costs">` +
    C("Gross PnL", `<span class="${pnlCls(t.gross)}">${inr(t.gross, true)}</span>`) + C("Slippage", inr(-t.slippage)) +
    C("Brokerage", inr(-c.brokerage)) + C("STT", inr(-c.stt)) + C("Exchange txn", inr(-c.exchange)) +
    C("SEBI fee", inr(-c.sebi)) + C("Stamp duty", inr(-c.stamp)) + C("GST", inr(-c.gst)) +
    C("Total friction", inr(-t.friction), "total") + C("Net PnL", `<span class="${pnlCls(t.net)}">${inr(t.net, true)}</span>`, "total") + "</div>";
  $("#optSym").textContent = "· " + t.symbol.replace(/^SYNTH:/, "SYNTH ");
  loadChart(t);
  prefetchAround(id);
}

async function chartData(t) {
  const key = S.hash + "|" + t.id;
  if (!S.chartCache.has(key)) {
    const p = api(`/api/bt/chart/${S.hash}/${encodeURIComponent(t.id)}`).then(r => r.data);
    S.chartCache.set(key, p);
    p.catch(() => S.chartCache.delete(key));
  }
  return S.chartCache.get(key);
}
function prefetchAround(id) {
  const i = S.list.findIndex(t => t.id === id);
  for (const j of [i + 1, i - 1, i + 2]) if (S.list[j]) chartData(S.list[j]).catch(() => {});
  if (S.chartCache.size > 300) [...S.chartCache.keys()].slice(0, 100).forEach(k => S.chartCache.delete(k));
}
async function loadChart(t) {
  Charts.loading();
  try {
    const d = await chartData(t);
    if (S.selId !== t.id) return;   // user moved on
    Charts.trade(t, d, S.result.params.timeframe);
  } catch (e) {
    if (S.selId === t.id) Charts.clear("Chart failed to load: " + e.message);
  }
}

// ------------------------------------------------------------------ charts
const Charts = (() => {
  const LW = window.LightweightCharts;
  let spot, opt, eq, sCandles, sE9, sE21, oCandles, eqLines = {}, priceLines = [];
  const msg = (el, text) => {
    let m = $(".chart-msg", el);
    if (!text) { m?.remove(); return; }
    if (!m) { m = document.createElement("div"); m.className = "chart-msg"; el.appendChild(m); }
    m.innerHTML = text;
  };
  const base = () => ({
    layout: {background: {type: "solid", color: css("--surface")}, textColor: css("--text-2"), fontFamily: "Inter, system-ui, sans-serif", fontSize: 11},
    grid: {vertLines: {color: css("--grid")}, horzLines: {color: css("--grid")}},
    rightPriceScale: {borderColor: css("--border")},
    timeScale: {borderColor: css("--border"), timeVisible: true, secondsVisible: false},
    crosshair: {mode: LW ? LW.CrosshairMode.Normal : 0},
    autoSize: true,
  });
  const candleOpts = () => ({upColor: css("--gain"), downColor: css("--loss"), borderVisible: false, wickUpColor: css("--gain"), wickDownColor: css("--loss")});

  function init() {
    if (!LW) { ["#spotChart", "#optChart", "#equityChart"].forEach(s => msg($(s), "Chart library failed to load (offline?).")); return false; }
    spot = LW.createChart($("#spotChart"), base());
    sCandles = spot.addCandlestickSeries(candleOpts());
    sE9 = spot.addLineSeries({color: css("--s1"), lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false});
    sE21 = spot.addLineSeries({color: css("--s2"), lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false});
    opt = LW.createChart($("#optChart"), base());
    oCandles = opt.addCandlestickSeries(candleOpts());
    eq = LW.createChart($("#equityChart"), {...base(), timeScale: {...base().timeScale, timeVisible: false},
      localization: {priceFormatter: v => "₹" + (Math.abs(v) >= 1e5 ? (v / 1e5).toFixed(2) + "L" : Math.round(v).toLocaleString("en-IN"))}});
    for (const m of ["ITM5_BUY", "ATM_BUY", "ATM_SELL"])
      eqLines[m] = eq.addLineSeries({color: css(MODE_SLOT[m]), lineWidth: 2, priceLineVisible: false, lastValueVisible: false});
    eq.subscribeCrosshairMove(p => eqLegend(p));
    return true;
  }
  let ok = null;
  const ready = () => (ok ??= init());

  let eqLast = {};
  function eqLegend(p) {
    const vals = {};
    for (const m in eqLines) {
      const d = p?.seriesData?.get(eqLines[m]);
      vals[m] = d ? d.value : eqLast[m];
    }
    $("#eqLegend").innerHTML = "Equity · " + Object.keys(eqLines).map(m =>
      `<span class="sw" style="background:var(${MODE_SLOT[m]})"></span>${MODE_SHORT[m]} <span class="num">${vals[m] == null ? "—" : inr(vals[m])}</span>`).join(" ");
  }

  function equity(rows, cap) {
    if (!ready()) return;
    eqLast = {};
    for (const [mode, m] of rows) {
      const pts = []; let lastT = 0;
      for (const [ts, v] of m.curve) { let t = toTime(ts); if (t <= lastT) t = lastT + 60; pts.push({time: t, value: v}); lastT = t; }
      eqLines[mode].setData(pts);
      eqLast[mode] = pts.length ? pts[pts.length - 1].value : cap;
    }
    eq.timeScale().fitContent();
    eqLegend(null);
    msg($("#equityChart"), rows.every(([, m]) => !m.trades) ? "No trades" : null);
  }

  function loading() {
    if (!ready()) return;
    msg($("#spotChart"), '<div class="skel" style="width:90%;height:80%"></div>');
    msg($("#optChart"), '<div class="skel" style="width:90%;height:70%"></div>');
  }
  function clear(text) {
    if (!ready()) return;
    sCandles.setData([]); sE9.setData([]); sE21.setData([]); oCandles.setData([]);
    msg($("#spotChart"), esc(text)); msg($("#optChart"), esc(text));
  }

  function trade(t, d, tf) {
    if (!ready()) return;
    const bull = t.direction === "Bullish";
    const bars = d.spot;
    if (!bars.length) { clear("No spot candles for this day"); return; }
    sCandles.setData(bars.map(b => ({time: toTime(b.t), open: b.o, high: b.h, low: b.l, close: b.c})));
    sE9.setData(bars.map(b => ({time: toTime(b.t), value: b.e9})));
    sE21.setData(bars.map(b => ({time: toTime(b.t), value: b.e21})));
    const barAt = iso => { const ts = toTime(iso); let best = bars[0]; for (const b of bars) if (toTime(b.t) <= ts) best = b; return toTime(best.t); };
    const sig = bars.find(b => b.c_ts === t.entry_ts);
    const mk = [];
    if (sig) mk.push({time: toTime(sig.t), position: bull ? "belowBar" : "aboveBar", color: css("--accent"), shape: "circle", text: "Cross"});
    mk.push({time: barAt(t.entry_ts), position: bull ? "belowBar" : "aboveBar", color: bull ? css("--gain") : css("--loss"), shape: bull ? "arrowUp" : "arrowDown", text: `Entry ${hhmm(t.entry_ts)}`});
    mk.push({time: barAt(t.exit_ts), position: bull ? "aboveBar" : "belowBar", color: css("--text-2"), shape: "square", text: `Exit ${hhmm(t.exit_ts)}`});
    mk.sort((a, b) => a.time - b.time);
    sCandles.setMarkers(mk);
    spot.timeScale().fitContent();
    msg($("#spotChart"), null);

    priceLines.forEach(pl => oCandles.removePriceLine(pl)); priceLines = [];
    if (!d.option.length) { oCandles.setData([]); oCandles.setMarkers([]); msg($("#optChart"), "No option candles stored for this day"); return; }
    oCandles.setData(d.option.map(b => ({time: toTime(b.t), open: b.o, high: b.h, low: b.l, close: b.c})));
    const buy = t.side === "BUY";
    oCandles.setMarkers([
      {time: toTime(t.fill_entry_ts), position: buy ? "belowBar" : "aboveBar", color: buy ? css("--gain") : css("--loss"), shape: buy ? "arrowUp" : "arrowDown", text: `${buy ? "Buy" : "Sell"} ${num(t.opt_entry)}`},
      {time: toTime(t.fill_exit_ts), position: buy ? "aboveBar" : "belowBar", color: css("--text-2"), shape: "square", text: `${buy ? "Sell" : "Cover"} ${num(t.opt_exit)}`},
    ].sort((a, b) => a.time - b.time));
    priceLines.push(oCandles.createPriceLine({price: t.opt_entry, color: css("--accent"), lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "entry"}));
    priceLines.push(oCandles.createPriceLine({price: t.opt_exit, color: css("--muted"), lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "exit"}));
    opt.timeScale().fitContent();
    msg($("#optChart"), null);
  }

  function retheme() {
    if (!ok) return;
    for (const c of [spot, opt, eq]) c.applyOptions(base());
    sCandles.applyOptions(candleOpts()); oCandles.applyOptions(candleOpts());
    sE9.applyOptions({color: css("--s1")}); sE21.applyOptions({color: css("--s2")});
    for (const m in eqLines) eqLines[m].applyOptions({color: css(MODE_SLOT[m])});
  }
  return {equity, trade, clear, loading, retheme};
})();

// ------------------------------------------------------------------ wiring
function openDrawer(open) {
  $("#drawer").classList.toggle("open", open); $("#scrim").classList.toggle("open", open);
  $("#drawer").setAttribute("aria-hidden", !open);
}

function wire() {
  $("#settingsBtn").onclick = () => openDrawer(true);
  $("#drawerClose").onclick = $("#scrim").onclick = () => { readSettings(); openDrawer(false); };
  $("#p_dataset").onchange = () => { S.params.dataset = $("#p_dataset").value; updateDatasetInfo(); };
  $("#runBtn").onclick = () => { readSettings(); openDrawer(false); updateDatasetInfo(); runBacktest(); };
  $("#downloadBtn").onclick = () => { openDrawer(false); downloadData(); };
  $("#emptyRun").onclick = () => runBacktest();
  $("#emptyDownload").onclick = () => downloadData();
  $("#themeBtn").onclick = () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("theme", JSON.stringify(root.dataset.theme).replace(/"/g, "")); } catch (e) {}
    Charts.retheme();
  };
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => Charts.retheme());
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") { openDrawer(false); return; }
    if (!["ArrowDown", "ArrowUp"].includes(e.key) || e.target.closest("input,select,textarea,.drawer") || !S.list.length) return;
    e.preventDefault();
    const i = S.list.findIndex(t => t.id === S.selId);
    const j = Math.min(S.list.length - 1, Math.max(0, i + (e.key === "ArrowDown" ? 1 : -1)));
    if (j !== i) selectTrade(S.list[j].id);
  });
}

async function boot() {
  wire();
  try {
    S.meta = (await api("/api/bt/meta")).data;
  } catch (e) {
    showEmpty("Can't reach the server", e.message); return;
  }
  const saved = store.get("bt_params", null);
  S.params = {...S.meta.defaults, ...(saved || {}), costs: {...S.meta.defaults.costs, ...(saved?.costs || {})}};
  if (!saved) {
    const g = S.meta.datasets.groww || {};
    S.params.dataset = g.rows ? "groww" : "synthetic";
  }
  // Unless the user picked an earlier end date, the range always runs to today.
  if (store.get("bt_end_auto", true)) S.params.end_date = S.meta.defaults.end_date;
  writeSettings(); buildFilters();
  const running = S.meta.jobs[0];
  if (running) {
    setBusy(true);
    try { const res = await pollJob(running.id); setBusy(false); res?.hash ? await loadResult(res.hash) : await runBacktest(); }
    catch (e) { banner(e.message); } finally { progress(null); setBusy(false); }
    return;
  }
  const info = S.meta.datasets[S.params.dataset] || {};
  if (!info.rows) {
    showEmpty("No market data yet",
      S.params.dataset === "groww"
        ? (S.meta.keys ? "Download NIFTY 1-minute data from Groww for the selected range (Settings). Option candles are fetched automatically as trades need them."
                       : "keys.txt has no TOTP secret yet, so Groww data can't be downloaded. Add it, or switch to the synthetic demo dataset in Settings to explore the app.")
        : "Generate the synthetic demo dataset to explore the app. It is random-walk data, not market data.");
    return;
  }
  if (info.stale && S.params.end_date >= S.meta.defaults.end_date) return downloadData();
  runBacktest();
}
boot();
})();
