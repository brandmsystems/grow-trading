/* Live / paper engine console */
(() => {
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const inr = (v, sign = false) => v == null || isNaN(v) ? "—" :
  (sign && v > 0 ? "+" : v < 0 ? "−" : "") + "₹" + Math.abs(v).toLocaleString("en-IN", {minimumFractionDigits: 2, maximumFractionDigits: 2});
const num = (v, d = 2) => v == null || isNaN(v) ? "—" : Number(v).toLocaleString("en-IN", {minimumFractionDigits: d, maximumFractionDigits: d});
const cls = v => v > 0 ? "pos" : v < 0 ? "neg" : "";
const hms = iso => iso ? iso.slice(11, 19) : "—";
const toTime = iso => Math.floor(Date.parse(iso + "Z") / 1000);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
};
const STATE_LABEL = {stopped: "Stopped", waiting: "Waiting for market", running: "Running", halted: "Halted", error: "ERROR: check positions"};
const REASON = {opposite_cross: "Opposite cross", square_off: "15:00 square-off", daily_loss_limit: "Loss limit",
  manual_square_off: "Manual", manual_stop: "Stopped", stale_previous_day: "Stale (prev. day)"};

let S = {status: null, trades: [], cfg: null, lastTradesKey: ""};

async function api(url, opts = {}) {
  if (opts.body && typeof opts.body !== "string") { opts.body = JSON.stringify(opts.body); opts.headers = {"Content-Type": "application/json"}; }
  let r;
  try { r = await fetch(url, opts); } catch (e) { throw new Error("Server unreachable. Is app.py running?"); }
  const j = await r.json().catch(() => ({ok: false, error: `HTTP ${r.status}`}));
  if (!j.ok) throw new Error(j.error || "Request failed");
  return j.data;
}
function banner(msg, info = false) {
  const b = $("#banner");
  if (!msg) { b.style.display = "none"; return; }
  b.className = "banner" + (info ? " info" : ""); b.textContent = msg; b.style.display = "block";
}

// ------------------------------------------------------------------ config form
const defaults = {trade_mode: "paper", exec_mode: "ATM_BUY", timeframe: 15, entry_start: "09:30", cutoff: "14:30",
  lots: 1, max_trades_per_day: 6, max_daily_loss: 5000, roll_on_expiry_day: true};
function segSet(id, v) { $$(`#${id} button`).forEach(b => b.setAttribute("aria-pressed", String(b.dataset.v) === String(v))); }
function segGet(id) { return $(`#${id} button[aria-pressed="true"]`)?.dataset.v; }
function writeForm(c) {
  segSet("c_trade_mode", c.trade_mode); segSet("c_timeframe", c.timeframe);
  for (const k of ["exec_mode", "entry_start", "cutoff", "lots", "max_trades_per_day", "max_daily_loss"]) $(`#c_${k}`).value = c[k];
  $("#c_roll_on_expiry_day").checked = !!c.roll_on_expiry_day;
  modeUI();
}
function readForm() {
  const c = {trade_mode: segGet("c_trade_mode"), timeframe: +segGet("c_timeframe"), exec_mode: $("#c_exec_mode").value,
    entry_start: $("#c_entry_start").value, cutoff: $("#c_cutoff").value, lots: +$("#c_lots").value,
    max_trades_per_day: +$("#c_max_trades_per_day").value, max_daily_loss: +$("#c_max_daily_loss").value,
    roll_on_expiry_day: $("#c_roll_on_expiry_day").checked};
  store.set("live_cfg", c);
  return c;
}
function modeUI() {
  const m = segGet("c_trade_mode");
  $("#replayBox").hidden = m !== "replay";
  $("#liveBox").hidden = m !== "live";
  $("#startBtn").classList.toggle("live", m === "live");
  $("#startBtn").textContent = m === "live" ? "Start LIVE trading" : m === "replay" ? "Start replay" : "Start paper trading";
  $("#modeHint").textContent = {
    paper: "Real-time Groww prices, simulated fills at LTP with modelled slippage and charges. No orders are sent.",
    live: "Places real orders in your Groww account.",
    replay: "Demo: replays a stored synthetic day fast so you can watch the engine work.",
  }[m];
}
function lockForm(running) {
  $$("#cfgForm input, #cfgForm select, #cfgForm button").forEach(el => el.disabled = running);
  $("#startBtn").disabled = running;
  $("#stopBtn").disabled = !running; $("#sqBtn").disabled = !running;
}

// ------------------------------------------------------------------ actions
async function startEngine() {
  banner(null);
  const c = readForm();
  if (c.trade_mode === "live" && !confirm(`Start LIVE trading with ${c.lots} lot(s), ${c.exec_mode}? Real orders will be placed.`)) return;
  $("#startBtn").disabled = true;
  try {
    await api("/api/live/start", {method: "POST", body: {config: c, confirm: $("#r_confirm").value,
      replay_day: $("#r_day").value, replay_speed: $("#r_speed").value}});
    $("#r_confirm").value = "";
    await refresh();
  } catch (e) { banner(e.message); $("#startBtn").disabled = false; }
}
async function stopEngine() {
  if (!confirm("Stop the engine? Any open position will be squared off first.")) return;
  try { await api("/api/live/stop", {method: "POST"}); await refresh(); } catch (e) { banner(e.message); }
}
async function squareOff() {
  if (!confirm("Square off the open position now? The engine keeps running and will act on the next crossover.")) return;
  try { await api("/api/live/squareoff", {method: "POST"}); await refresh(); } catch (e) { banner(e.message); }
}
async function brokerPositions() {
  $("#brokerCard").hidden = false; $("#brokerPre").textContent = "Loading…";
  try { $("#brokerPre").textContent = JSON.stringify(await api("/api/live/broker"), null, 2); }
  catch (e) { $("#brokerPre").textContent = "Could not load: " + e.message; }
}

// ------------------------------------------------------------------ rendering
function M(l, v, c = "") { return `<div class="m"><div class="ml">${l}</div><div class="mv num ${c}">${v}</div></div>`; }
function kpi(l, v, c = "", sub = "") { return `<div class="kpi"><div class="l">${l}</div><div class="v num ${c}">${v}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`; }

function render() {
  const s = S.status; if (!s) return;
  const running = s.state !== "stopped";
  const mode = s.config?.trade_mode || segGet("c_trade_mode");
  lockForm(running);
  if (running && s.config && JSON.stringify(s.config) !== JSON.stringify(S.cfg)) { S.cfg = s.config; writeForm(s.config); if (s.replay_day) $("#r_day").value = s.replay_day; }
  $("#liveCap").textContent = s.live_max_lots; $("#phrase").textContent = s.confirm_phrase;

  const pill = $("#statePill");
  pill.className = "pill-state " + s.state; pill.textContent = STATE_LABEL[s.state] || s.state;
  const badge = $("#modeBadge");
  badge.className = "badge " + (running ? mode : "");
  badge.textContent = running ? {live: "LIVE: REAL MONEY", paper: "PAPER", replay: "REPLAY: SYNTHETIC"}[mode] : "Engine off";

  const le = s.last_eval;
  const diff = le ? le.ema9 - le.ema21 : null;
  $("#strip").innerHTML = M("Engine clock", hms(s.now)) + M("Next evaluation", hms(s.next_eval)) +
    M("Last bar closed", le ? hms(le.bar_close) : "—") + M("NIFTY close", le ? num(le.close) : "—") +
    M("EMA 9 / 21", le ? `${num(le.ema9)} / ${num(le.ema21)}` : "—") +
    M("Trend", diff == null ? "—" : diff > 0 ? "▲ 9 above 21" : diff < 0 ? "▼ 9 below 21" : "Equal", diff > 0 ? "pos" : diff < 0 ? "neg" : "");
  if (s.halt_reason) banner(s.halt_reason); else if ($("#banner").textContent === S.lastHalt) banner(null);
  S.lastHalt = s.halt_reason;

  const p = s.position;
  const mtm = p?.mtm ?? 0;
  const dayNet = (s.realised_today || 0) + (p?.mtm || 0);
  $("#liveKpis").innerHTML =
    kpi("Position", p ? `${p.side} ${p.opt_type}` : "Flat", "", p ? `${p.trading_symbol}` : "") +
    kpi("Open MTM (net)", p ? inr(mtm, true) : "—", cls(mtm)) +
    kpi("Realised today", inr(s.realised_today, true), cls(s.realised_today)) +
    kpi("Day net", inr(dayNet, true), cls(dayNet)) +
    kpi("Trades today", s.trades_today ?? 0, "", s.config ? `limit ${s.config.max_trades_per_day}` : "");

  $("#posCard").innerHTML = p
    ? `<div class="card-head"><h2>Open position</h2>${p.exit_failures ? `<span class="tag">EXIT RETRY ${p.exit_failures}</span>` : ""}</div><div class="posgrid">` +
      M("Contract", esc(p.trading_symbol)) + M("Direction", `${p.direction} · ${p.side}`, p.direction === "Bullish" ? "pos" : "neg") +
      M("Qty", p.qty) + M("Entry", `${num(p.entry_price)} @ ${hms(p.entry_ts)}`) + M("LTP", num(p.ltp)) +
      M("MTM (after costs)", inr(p.mtm, true), cls(p.mtm)) + M("Expiry", p.expiry) + "</div>"
    : `<div class="card-head"><h2>Open position</h2></div><div class="empty-row">${running ? "Flat: waiting for a crossover inside the entry window." : "Engine is stopped."}</div>`;

  $("#log").innerHTML = (s.events || []).map(e => `<div><span class="t">${hms(e.ts)}</span><span class="${e.level}">${esc(e.message)}</span></div>`).join("")
    || `<div class="empty-row" style="display:block">No events yet.</div>`;
  $("#chartTf").textContent = s.config ? `· ${s.config.timeframe}-minute` : "";
  Chart.update(s.bars || [], S.trades);
}

function renderTrades() {
  const t = S.trades;
  $("#tradesNote").textContent = t.length ? `${t.length} · ${t[0].trade_mode}` : "";
  $("#tradesTable").innerHTML = t.length ? `<thead><tr><th>Signal</th><th>Contract</th><th>Side</th><th>Entry</th><th>Exit</th><th>Reason</th><th>Net</th></tr></thead><tbody>` +
    t.map(r => `<tr><td class="num">${hms(r.signal_ts)}</td><td class="num">${esc(r.trading_symbol)}</td><td>${r.side}</td>
      <td class="num">${num(r.entry_price)}</td><td class="num">${r.exit_price == null ? "open" : num(r.exit_price)}</td>
      <td>${REASON[r.exit_reason] || (r.status === "OPEN" ? "—" : esc(r.exit_reason))}</td>
      <td class="num ${cls(r.net)}">${r.net == null ? "—" : inr(r.net, true)}</td></tr>`).join("") + "</tbody>"
    : `<tbody><tr><td class="empty-row">No trades today.</td></tr></tbody>`;
}

// ------------------------------------------------------------------ chart
const Chart = (() => {
  const LW = window.LightweightCharts;
  let chart, candles, e9, e21, lastKey = "";
  const opts = () => ({
    layout: {background: {type: "solid", color: css("--surface")}, textColor: css("--text-2"), fontFamily: "Inter, system-ui, sans-serif", fontSize: 11},
    grid: {vertLines: {color: css("--grid")}, horzLines: {color: css("--grid")}},
    rightPriceScale: {borderColor: css("--border")}, timeScale: {borderColor: css("--border"), timeVisible: true, secondsVisible: false},
    autoSize: true,
  });
  const cOpts = () => ({upColor: css("--gain"), downColor: css("--loss"), borderVisible: false, wickUpColor: css("--gain"), wickDownColor: css("--loss")});
  function init() {
    if (chart || !LW) return !!chart;
    chart = LW.createChart($("#liveChart"), opts());
    candles = chart.addCandlestickSeries(cOpts());
    e9 = chart.addLineSeries({color: css("--s1"), lineWidth: 2, priceLineVisible: false, lastValueVisible: false});
    e21 = chart.addLineSeries({color: css("--s2"), lineWidth: 2, priceLineVisible: false, lastValueVisible: false});
    return true;
  }
  function msg(text) {
    let m = $("#liveChart .chart-msg");
    if (!text) { m?.remove(); return; }
    if (!m) { m = document.createElement("div"); m.className = "chart-msg"; $("#liveChart").appendChild(m); }
    m.textContent = text;
  }
  function update(bars, trades) {
    if (!init()) { msg("Chart library failed to load."); return; }
    const key = (bars.at(-1)?.c_ts || "") + bars.length + "|" + trades.map(t => t.id + (t.exit_ts || "")).join(",");
    if (key === lastKey) return;
    lastKey = key;
    if (!bars.length) { candles.setData([]); e9.setData([]); e21.setData([]); msg("Bars appear after the first evaluation in market hours."); return; }
    msg(null);
    candles.setData(bars.map(b => ({time: toTime(b.t), open: b.o, high: b.h, low: b.l, close: b.c})));
    e9.setData(bars.map(b => ({time: toTime(b.t), value: b.e9})));
    e21.setData(bars.map(b => ({time: toTime(b.t), value: b.e21})));
    const barAt = iso => { const ts = toTime(iso); let best = null; for (const b of bars) if (toTime(b.t) <= ts) best = toTime(b.t); return best; };
    const mk = [];
    for (const t of trades) {
      const bull = t.direction === "Bullish";
      const a = barAt(t.entry_ts);
      if (a) mk.push({time: a, position: bull ? "belowBar" : "aboveBar", color: bull ? css("--gain") : css("--loss"), shape: bull ? "arrowUp" : "arrowDown", text: `${t.side} ${t.opt_type}`});
      const x = t.exit_ts && barAt(t.exit_ts);
      if (x) mk.push({time: x, position: bull ? "aboveBar" : "belowBar", color: css("--text-2"), shape: "square", text: "Exit"});
    }
    candles.setMarkers(mk.sort((p, q) => p.time - q.time));
    chart.timeScale().fitContent();
  }
  function retheme() { if (!chart) return; chart.applyOptions(opts()); candles.applyOptions(cOpts()); e9.applyOptions({color: css("--s1")}); e21.applyOptions({color: css("--s2")}); lastKey = ""; }
  return {update, retheme};
})();

// ------------------------------------------------------------------ polling
async function refresh() {
  try {
    S.status = await api("/api/live/status");
    const s = S.status, mode = s.config?.trade_mode || segGet("c_trade_mode");
    const day = s.day || new Date().toISOString().slice(0, 10);
    const key = `${mode}|${day}|${s.trades_today}|${s.position ? 1 : 0}|${s.realised_today}`;
    if (key !== S.lastTradesKey) {
      S.lastTradesKey = key;
      S.trades = (await api(`/api/live/trades?mode=${mode}&day=${day}`)).reverse();
      renderTrades();
    }
    render();
  } catch (e) { banner(e.message); }
}

function wire() {
  for (const id of ["c_trade_mode", "c_timeframe"])
    $(`#${id}`).onclick = e => { const b = e.target.closest("button"); if (!b || b.disabled) return; segSet(id, b.dataset.v); modeUI(); readForm(); S.lastTradesKey = ""; refresh(); };
  $("#startBtn").onclick = startEngine; $("#stopBtn").onclick = stopEngine; $("#sqBtn").onclick = squareOff;
  $("#brokerBtn").onclick = brokerPositions;
  $("#themeBtn").onclick = () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
    Chart.retheme();
  };
}

wire();
writeForm({...defaults, ...store.get("live_cfg", {})});
const d = new Date(); d.setDate(d.getDate() - 3); while ([0, 6].includes(d.getDay())) d.setDate(d.getDate() - 1);
$("#r_day").value = d.toISOString().slice(0, 10);
refresh();
setInterval(refresh, 1500);
})();
