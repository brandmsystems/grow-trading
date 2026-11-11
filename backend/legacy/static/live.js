/* Live trading dashboard: NIFTY feed, 9/21 EMA signal, option recommendation, sizing, alerts, P&L, engine */
(() => {
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const inr = (v, sign = false, d = 2) => v == null || isNaN(v) ? "—" :
  (sign && v > 0 ? "+" : v < 0 ? "−" : "") + "₹" + Math.abs(v).toLocaleString("en-IN", {minimumFractionDigits: d, maximumFractionDigits: d});
const num = (v, d = 2) => v == null || isNaN(v) ? "—" : Number(v).toLocaleString("en-IN", {minimumFractionDigits: d, maximumFractionDigits: d});
const cls = v => v > 0 ? "pos" : v < 0 ? "neg" : "";
const hm = iso => iso ? iso.slice(11, 16) : "—";
const hms = iso => iso ? iso.slice(11, 19) : "—";
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const toTime = iso => Math.floor(Date.parse(iso + "Z") / 1000);      // IST wall clock shown as-is
const localDay = () => { const d = new Date(); return new Date(d - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 10); };
const fmtDate = s => s ? new Date(s + "T00:00:00Z").toLocaleDateString("en-IN", {day: "numeric", month: "short", year: "numeric", timeZone: "UTC"}) : "—";
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
};
const STATE_LABEL = {stopped: "Stopped", waiting: "Waiting for market", running: "Running", halted: "Halted", error: "ERROR: check positions"};
const REASON = {target: "Target hit", stop: "Stop hit", opposite_cross: "Opposite cross", square_off: "15:00 square-off", daily_loss_limit: "Loss limit",
  manual_square_off: "Manual", manual_stop: "Stopped", stale_previous_day: "Stale (prev. day)"};
const POLL_MS = 3000, MAX_POLL_MS = 30000;

const S = {d: null, cfg: null, lastAlertId: null, newIds: new Set(), fails: 0, timer: null, trades: [], tradesAt: 0, tradesKey: ""};

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
  if (!msg) { b.style.display = "none"; b.textContent = ""; return; }
  b.className = "banner" + (info ? " info" : ""); b.textContent = msg; b.style.display = "block";
}

// ------------------------------------------------------------------ settings (engine form + sizing inputs)
const defaults = {trade_mode: "paper", exec_mode: "ATM_BUY", timeframe: 5, entry_start: "09:30", cutoff: "14:30",
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
    roll_on_expiry_day: $("#c_roll_on_expiry_day").checked, signal_mode: "cross", v: 2};
  store.set("live_cfg", c);
  return c;
}
function modeUI() {
  const m = segGet("c_trade_mode");
  $("#replayBox").hidden = m !== "replay";
  $("#liveBox").hidden = m !== "live";
  $("#startBtn").classList.toggle("live", m === "live");
  $("#startBtn").textContent = m === "live" ? "Start AUTO-TRADING" : m === "replay" ? "Start replay" : "Start paper trading";
  $("#modeHint").textContent = {
    paper: "Live Groww prices, simulated fills. No orders are sent.",
    live: "The engine places real orders in your Groww account by itself.",
    replay: "Replays a stored trading day quickly with simulated fills.",
  }[m];
}
function lockForm(running) {
  $$("#cfgForm input, #cfgForm select, #cfgForm button, #c_timeframe button").forEach(el => el.disabled = running);
  $("#startBtn").disabled = running;
  $("#stopBtn").disabled = !running; $("#sqBtn").disabled = !running;
}

// ------------------------------------------------------------------ engine actions
async function startEngine() {
  banner(null);
  const c = readForm();
  if (c.trade_mode === "live" && !confirm(`Enable AUTO-TRADING with ${c.lots} lot(s)? The engine will place real orders on its own.`)) return;
  $("#startBtn").disabled = true;
  try {
    await api("/api/live/start", {method: "POST", body: {config: c, confirm: $("#r_confirm").value,
      replay_day: $("#r_day").value, replay_speed: $("#r_speed").value}});
    $("#r_confirm").value = "";
    S.tradesAt = 0; poll(true);
  } catch (e) { banner(e.message); $("#startBtn").disabled = false; }
}
async function stopEngine() {
  if (!confirm("Stop the engine? Any open position will be squared off first.")) return;
  try { await api("/api/live/stop", {method: "POST"}); S.tradesAt = 0; poll(true); } catch (e) { banner(e.message); }
}
async function squareOff() {
  if (!confirm("Square off the open position now? The engine keeps running and will act on the next crossover.")) return;
  try { await api("/api/live/squareoff", {method: "POST"}); S.tradesAt = 0; poll(true); } catch (e) { banner(e.message); }
}
async function brokerPositions() {
  const pre = $("#brokerPre"); pre.hidden = false; pre.textContent = "Loading…";
  try { pre.textContent = JSON.stringify(await api("/api/live/broker"), null, 2); }
  catch (e) { pre.textContent = "Could not load: " + e.message; }
}

// ------------------------------------------------------------------ alerts: sound, desktop, flash
const isEntry = a => /^(BUY|SELL) (CE|PE)$/.test(a.action);
const isExit = a => a.action === "SELL" || a.action === "BUY BACK";
function actionClass(action, direction) {
  if (action === "BUY CE") return "bull";
  if (action === "BUY PE") return "bear";
  if (action === "SELL" || action === "BUY BACK") return "exit";
  if (/^SELL (CE|PE)$/.test(action)) return direction === "Bullish" ? "bull" : "bear";
  return "";
}
function contractText(a) { return a.strike != null ? `NIFTY ${Number(a.strike).toFixed(0)} ${a.opt_type}` : ""; }
function summary(a) {
  if (a.mode === "signal") {
    const c = a.symbol ? ` · ${contractText(a)} ${a.expiry ? fmtDate(a.expiry) : ""} @ ${num(a.premium)}` : "";
    return `${a.reason || ""}${c}`;
  }
  if (isEntry(a)) return `${contractText(a)} filled @ ${num(a.entry_price)} · NIFTY ${num(a.nifty)}`;
  if (isExit(a)) return `${contractText(a)} @ ${num(a.exit_price)} · ${REASON[a.reason] || a.reason} · net ${inr(a.net, true)}`;
  return `Not traded: ${a.reason}${a.nifty != null ? ` · NIFTY ${num(a.nifty)}` : ""}`;
}

let audio = null;
const soundOn = () => store.get("alert_sound", true);
function ensureAudio() {
  try { audio = audio || new (window.AudioContext || window.webkitAudioContext)(); if (audio.state === "suspended") audio.resume(); } catch (e) {}
}
function beep(a) {
  if (!soundOn() || !audio) return;
  const notes = a.action === "BUY CE" ? [660, 880] : a.action === "BUY PE" ? [880, 660] : [520, 520];
  notes.forEach((f, i) => {
    const o = audio.createOscillator(), g = audio.createGain(), t = audio.currentTime + i * 0.2;
    o.frequency.value = f; o.type = "sine";
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.25, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.18);
    o.connect(g).connect(audio.destination); o.start(t); o.stop(t + 0.19);
  });
}
function notify(a) {
  beep(a);
  const hero = $("#hero"); hero.classList.remove("flash"); void hero.offsetWidth; hero.classList.add("flash");
  if (document.hidden) document.title = `● ${a.action} · Live Trading`;
  if (soundOn() && "Notification" in window && Notification.permission === "granted") {
    try { new Notification(`${a.action} · ${hm(a.signal_ts || a.ts)}`, {body: summary(a), tag: `sig-${a.id}`}); } catch (e) {}
  }
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) document.title = "Live Trading"; });
document.addEventListener("pointerdown", ensureAudio, {once: true});

// Only strategy signals ring (the engine's fills for the same signal are listed, silently),
// and an alert id rings once: the newest id seen is remembered across reloads.
function checkNewAlerts(alerts) {
  const sig = alerts.filter(a => a.mode === "signal");
  const newest = Math.max(0, ...alerts.map(a => a.id));
  if (S.lastAlertId == null) S.lastAlertId = store.get("last_alert_id", null);
  if (S.lastAlertId == null) { S.lastAlertId = newest; store.set("last_alert_id", newest); return; }
  alerts.filter(a => a.id > S.lastAlertId).forEach(a => S.newIds.add(a.id));
  sig.filter(a => a.id > S.lastAlertId).reverse().forEach(notify);
  if (newest > S.lastAlertId) { S.lastAlertId = newest; store.set("last_alert_id", newest); }
}

// ------------------------------------------------------------------ chart
let chart, candles, e9, e21, chartKey = "", barsKey = "";
function chartTheme() {
  return {layout: {background: {color: "transparent"}, textColor: css("--text-2"), fontFamily: "Inter, system-ui, sans-serif"},
    grid: {vertLines: {color: css("--grid")}, horzLines: {color: css("--grid")}},
    rightPriceScale: {borderColor: css("--border")}, timeScale: {borderColor: css("--border"), timeVisible: true, secondsVisible: false}};
}
function candleColors() {
  return {upColor: css("--gain"), borderUpColor: css("--gain"), wickUpColor: css("--gain"),
    downColor: css("--loss"), borderDownColor: css("--loss"), wickDownColor: css("--loss")};
}
function chartMsg(msg) { const m = $("#chartMsg"); m.hidden = !msg; m.textContent = msg || ""; }
function ensureChart() {
  if (chart) return true;
  if (!window.LightweightCharts) { chartMsg("The chart library could not load. Check your internet connection and reload."); return false; }
  chart = LightweightCharts.createChart($("#chart"), {...chartTheme(), autoSize: true});
  candles = chart.addCandlestickSeries(candleColors());
  e9 = chart.addLineSeries({color: css("--s1"), lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false});
  e21 = chart.addLineSeries({color: css("--s4"), lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false});
  return true;
}
function applyChartTheme() {
  if (!chart) return;
  chart.applyOptions(chartTheme()); candles.applyOptions(candleColors());
  e9.applyOptions({color: css("--s1")}); e21.applyOptions({color: css("--s4")});
  barsKey = "";      // markers use theme colours: redraw
}
function renderChart(f) {
  const ch = f.chart || {}, bars = ch.bars || [];
  $("#lgTf").textContent = `${f.timeframe}-minute`;
  $("#chartDay").textContent = ch.day && ch.day !== localDay() ? `· last session ${fmtDate(ch.day)}` : "";
  if (!ensureChart()) return;
  if (!bars.length && !ch.forming) { chartMsg(f.bars_error ? `NIFTY candles unavailable: ${f.bars_error}` : "No candles yet today."); return; }
  chartMsg(null);
  const key = `${ch.day}|${f.timeframe}`;
  const bk = `${key}|${bars.length}|${bars.at(-1)?.t}|${bars.at(-1)?.c}`;
  if (bk !== barsKey) {
    candles.setData(bars.map(b => ({time: toTime(b.t), open: b.o, high: b.h, low: b.l, close: b.c})));
    e9.setData(bars.map(b => ({time: toTime(b.t), value: b.e9})));
    e21.setData(bars.map(b => ({time: toTime(b.t), value: b.e21})));
    // marker on the bar whose close produced the cross (bar start = close - timeframe)
    const tfSec = f.timeframe * 60;
    candles.setMarkers((f.crosses || []).map(c => ({time: toTime(c.ts) - tfSec, position: c.direction > 0 ? "belowBar" : "aboveBar",
      shape: c.direction > 0 ? "arrowUp" : "arrowDown", color: c.direction > 0 ? css("--gain") : css("--loss"),
      text: c.direction > 0 ? "Bull" : "Bear"})).filter(m => bars.some(b => toTime(b.t) === m.time)));
    barsKey = bk;
    if (key !== chartKey) { chart.timeScale().fitContent(); chartKey = key; }
  }
  if (ch.forming) {
    const t = toTime(ch.forming.t);
    if (!bars.length || t > toTime(bars.at(-1).t))
      candles.update({time: t, open: ch.forming.o, high: ch.forming.h, low: ch.forming.l, close: ch.forming.c});
  }
}

// ------------------------------------------------------------------ 1. price
const CHIP = {live: "LIVE", delayed: "DELAYED", closed: "MARKET CLOSED", unavailable: "UNAVAILABLE"};
function renderPrice(f) {
  const q = f.quote || {};
  $("#px").textContent = num(q.price);
  const up = q.change > 0, dn = q.change < 0;
  $("#chg").className = "chg " + (up ? "pos" : dn ? "neg" : "");
  $("#chg").textContent = q.change == null ? "" : `${up ? "▲" : dn ? "▼" : "■"} ${num(Math.abs(q.change))} (${num(Math.abs(q.change_pct))}%)`;
  $("#ohlc").textContent = q.price == null ? (q.error ? `Price unavailable: ${q.error}` : "Price unavailable") :
    `Open ${num(q.open)} · High ${num(q.high)} · Low ${num(q.low)} · Prev close ${num(q.prev_close)}`;
  const st = q.state || "unavailable";
  const chip = $("#liveChip");
  chip.className = "chip " + st;
  chip.textContent = st === "delayed" ? `DELAYED · ${q.age_sec ?? "?"}s old` : CHIP[st];
  chip.title = st === "delayed" ? `Last good quote at ${hms(q.as_of)}${q.error ? `. Latest attempt failed: ${q.error}` : ""}` :
    q.as_of ? `Quote as of ${hms(q.as_of)}` : "";
}

// ------------------------------------------------------------------ 2. strategy
function kv(l, v, s = "", c = "", full = false) {
  return `<div class="${full ? "full" : ""}"><div class="l">${l}</div><div class="v ${c}">${v}</div>${s ? `<div class="s">${s}</div>` : ""}</div>`;
}
function renderStrategy(f) {
  const e = f.ema, last = (f.crosses || []).at(-1);
  $("#stratTf").textContent = `${f.timeframe}m bars · window ${f.entry_start}–${f.cutoff}`;
  if (!e) { $("#strategy").innerHTML = `<p class="note full">${esc(f.bars_error ? "EMAs unavailable: " + f.bars_error : "No completed bars yet.")}</p>`; return; }
  const trend = e.gap > 0 ? 1 : e.gap < 0 ? -1 : 0;
  $("#strategy").innerHTML =
    kv("Trend", trend > 0 ? "▲ Bullish" : trend < 0 ? "▼ Bearish" : "Flat", trend > 0 ? "EMA 9 above EMA 21" : trend < 0 ? "EMA 9 below EMA 21" : "EMAs equal",
       trend > 0 ? "pos big" : trend < 0 ? "neg big" : "big") +
    kv("EMA gap (9 − 21)", (e.gap > 0 ? "+" : "") + num(e.gap), "", cls(e.gap)) +
    kv("EMA 9", num(e.fast)) + kv("EMA 21", num(e.slow)) +
    kv("Last bar close", hm(e.bar_close), `NIFTY ${num(e.close)}`) +
    kv("Last crossover", last ? `${hm(last.ts)} ${last.direction > 0 ? "▲" : "▼"}` : "None", last ? `${last.direction > 0 ? "Bullish" : "Bearish"} · NIFTY ${num(last.close)}` : "on this session",
       last ? (last.direction > 0 ? "pos" : "neg") : "") +
    `<p class="note full">A crossover inside the entry window opens a trade: bullish → buy CE, bearish → buy PE. The trade is held until the opposite crossover or the 15:00 square-off. Signals use completed bars only.</p>`;
}

// ------------------------------------------------------------------ 3. option + 4. sizing + 5. signal
function renderSignal(f, s) {
  const g = f.signal || {action: "HOLD", reason: f.error || "Feed unavailable"};
  const ac = actionClass(g.action, g.direction);
  $("#sigWhen").textContent = g.since ? `since ${hm(g.since)}` : "";
  $("#hero").innerHTML = `<span class="action ${ac}">${esc(g.action)}</span>` +
    `<p class="reason">${esc(g.reason || "")}</p>` + (g.late ? `<p class="note warn">${esc(g.late)}</p>` : "");

  const r = g.rec;
  const vc = $("#verChip");
  if (g.action === "HOLD" || !r) {
    vc.className = "chip sm"; vc.textContent = "";
    $("#option").innerHTML = `<div><span class="action md">HOLD</span></div><p class="note">No option to buy right now. ${esc(g.reason || "")}</p>`;
    $("#sizing").innerHTML = `<p class="note full">Sizing appears with a BUY CE / BUY PE signal and a verified option quote.</p>`;
    return;
  }
  vc.className = "chip sm " + (r.verified ? "live" : "bad");
  vc.textContent = r.verified ? `QUOTE VERIFIED ${hms(r.quote_as_of)}` : "NOT VERIFIED";
  const head = `<div><span class="action md ${ac}">${esc(g.action)}</span></div>`;
  const contract = r.expiry ? `<div class="contract">NIFTY ${num(r.strike, 0)} ${r.opt_type} · ${fmtDate(r.expiry)}` +
    `<span class="sym">${esc(r.symbol || "")} · ${esc(r.strike_rule || "")}</span></div>` : "";
  if (!r.verified || r.error && r.premium == null) {
    $("#option").innerHTML = head + contract + `<p class="note bad">${esc(r.error || "Quote not verified.")}</p>`;
    $("#sizing").innerHTML = `<p class="note full bad">No order size without a verified option quote.</p>`;
    return;
  }
  $("#option").innerHTML = head + contract + `<div class="kv">` +
    kv("Strike", num(r.strike, 0)) + kv("Option type", r.opt_type) +
    kv("Expiry", fmtDate(r.expiry)) + kv("Current premium", num(r.premium), `Groww quote · Δ ${num(r.delta)} · IV ${num(r.iv, 1)}%`) +
    kv("Entry price", num(r.entry), esc(r.entry_basis)) +
    kv("Stop loss", r.stop != null ? num(r.stop) : "—", r.nifty_stop != null ? `≈ NIFTY ${num(r.nifty_stop)} (1× ATR)` : "", "neg") +
    kv("Target", r.target != null ? num(r.target) : "—", r.nifty_target != null ? `≈ NIFTY ${num(r.nifty_target)} (2× ATR)` : "", "pos") +
    kv("NIFTY ATR", num(r.atr), `${f.timeframe}m bars`) +
    `</div>` + (r.error ? `<p class="note bad">${esc(r.error)}</p>` : "") +
    `<p class="note">Reason: ${esc(g.reason)} Stop and target are estimates from ATR × option delta; the strategy's own exit is the opposite crossover or 15:00.</p>`;

  const z = r.sizing;
  if (!z) { $("#sizing").innerHTML = `<p class="note full ${r.sizing_error ? "bad" : ""}">${esc(r.sizing_error || r.error || "No sizing available.")}</p>`; return; }
  const limitTxt = {risk: "your risk budget", margin: "available margin", capital: "your capital"}[z.limited_by];
  const avail = z.available != null ? `Groww option-buy balance ${inr(z.available, false, 0)}` : `Groww balance unavailable${z.margin_error ? ": " + z.margin_error : ""}`;
  if (!z.lots) {
    $("#sizing").innerHTML = kv("Lots", "0", "", "big") + kv("Lot size", z.lot_size) +
      `<p class="note full bad">${esc(z.note)}</p><p class="note full">${esc(avail)}</p>`;
    return;
  }
  $("#sizing").innerHTML =
    kv("Recommended lots", z.lots, `limited by ${limitTxt}`, "big") + kv("Lot size", z.lot_size, "Groww contract") +
    kv("Total quantity", z.qty) + kv("Required investment", inr(z.investment), `${z.qty} × ${num(r.entry)}`) +
    kv("Brokerage & charges", inr(z.charges_target), "round trip, est.") +
    kv("Maximum risk", inr(z.max_risk), `budget ${inr(z.risk_budget, false, 0)} (${num(+$("#riskPct").value, 1)}% of ${inr(z.capital, false, 0)})`, "neg") +
    kv("Profit at target", inr(z.target_profit, true), "after charges", "pos") +
    kv("Loss at stop", inr(z.stop_loss, true), "after charges", "neg") +
    `<p class="note full">${esc(avail)}. Estimates only, not guaranteed: fills, slippage and gaps change the result. No order is placed for you; place it yourself in Groww after checking.</p>`;
}

function renderHistory(s) {
  const al = s.alerts || [];
  $("#histNote").textContent = al.length ? `last ${al.length}` : "";
  const today = localDay();
  $("#history").innerHTML = al.length ? al.map(a => `<li class="${S.newIds.has(a.id) ? "new" : ""}">` +
    `<span class="t">${a.day !== today ? a.day.slice(5) : hm(a.signal_ts || a.ts)}</span>` +
    `<span class="action sm ${actionClass(a.action, a.direction)}">${esc(a.action)}</span>` +
    `<span class="d" title="${esc(summary(a))}">${a.mode !== "signal" ? `<span class="m">${esc(a.mode)}</span>` : ""}${esc(summary(a))}</span></li>`).join("")
    : `<li class="empty">No notifications yet. A new BUY CE, BUY PE or HOLD signal rings once here.</li>`;
}

// ------------------------------------------------------------------ 6. daily P&L
async function loadTrades(mode) {
  const key = `${mode}|${localDay()}|${S.lastAlertId}`;
  if (key === S.tradesKey && Date.now() - S.tradesAt < 20000) return;
  S.tradesKey = key; S.tradesAt = Date.now();
  try { S.trades = await api(`/api/live/trades?mode=${mode}&day=${localDay()}`); } catch (e) { S.trades = null; }
}
function renderPnl(s, mode) {
  const running = s.state !== "stopped";
  const rows = S.trades || [];
  const closed = rows.filter(t => t.status === "CLOSED");
  const realised = running ? s.realised_today || 0 : closed.reduce((a, t) => a + (t.net || 0), 0);
  const mtm = running && s.position ? s.position.mtm : null;
  const total = realised + (mtm || 0);
  const wins = closed.filter(t => t.net > 0).length;
  $("#pnlMode").textContent = `${{live: "auto-trade (real)", paper: "paper", replay: "replay"}[mode] || mode} · ${running ? "engine running" : "engine stopped"}`;
  $("#pnl").innerHTML =
    `<div><div class="l">Net today</div><div class="v big ${cls(total)}">${inr(total, true)}</div></div>` +
    `<div><div class="l">Realised</div><div class="v ${cls(realised)}">${inr(realised, true)}</div></div>` +
    `<div><div class="l">Open position</div><div class="v ${cls(mtm)}">${s.position ? inr(mtm, true) : "None"}</div></div>` +
    `<div><div class="l">Trades</div><div class="v">${rows.length}</div><div class="kv-s muted">${closed.length ? `${wins} win · ${closed.length - wins} loss` : ""}</div></div>`;
  $("#pnlTable").innerHTML = `<thead><tr><th>Time</th><th>Contract</th><th>Qty</th><th>Entry</th><th>Exit</th><th>Net</th></tr></thead><tbody>` +
    (S.trades == null ? `<tr class="empty"><td colspan="6">Trades could not be loaded.</td></tr>` :
     rows.length ? rows.map(t => `<tr><td>${hm(t.entry_ts)}${t.exit_ts ? "–" + hm(t.exit_ts) : ""}</td><td>${esc(t.side)} ${num(t.strike, 0)} ${esc(t.opt_type)}</td>` +
      `<td>${t.qty}</td><td>${num(t.entry_price)}</td><td>${t.exit_price != null ? num(t.exit_price) : "open"}</td>` +
      `<td class="${cls(t.net)}">${t.net != null ? inr(t.net, true) : "—"}</td></tr>`).join("")
     : `<tr class="empty"><td colspan="6">No ${mode} trades today. Start the engine below to trade the signals.</td></tr>`) + `</tbody>`;
}

// ------------------------------------------------------------------ status bar + warnings
function renderStatus(s, f, mode) {
  const running = s.state !== "stopped", q = f.quote || {}, mk = f.market || {};
  const ok = q.state === "live" || q.state === "closed";
  const connMsg = f.error || q.error || "";
  $("#statusBar").innerHTML =
    `<span class="item"><span class="dot ${ok ? "ok" : q.state === "delayed" ? "mid" : "bad"}"></span><b>${ok ? "Groww connected" : q.state === "delayed" ? "Reconnecting to Groww" : "Groww not connected"}</b>` +
    `${!ok && connMsg ? ` <span title="${esc(connMsg)}">${esc(connMsg.slice(0, 80))}</span>` : ""}</span>` +
    `<span class="item"><span class="dot ${mk.state === "open" ? "ok" : mk.state === "preopen" ? "mid" : ""}"></span>Market <b>${esc(mk.label || "—")}</b></span>` +
    `<span class="item">Engine <span class="pill-state ${s.state}">${STATE_LABEL[s.state] || s.state}</span>` +
    `${running ? ` <span class="badge ${mode}">${{live: "AUTO-TRADING: REAL MONEY", paper: "PAPER", replay: "REPLAY"}[mode]}</span>` : ""}</span>` +
    `<span class="spacer"></span>` +
    `<button class="btn" id="soundBtn" aria-pressed="${soundOn()}">${soundOn() ? "🔔 Alerts on" : "🔕 Alerts off"}</button>`;
  $("#soundBtn").onclick = () => {
    const on = !soundOn(); store.set("alert_sound", on); ensureAudio();
    if (on && "Notification" in window && Notification.permission === "default") Notification.requestPermission();
    renderStatus(s, f, mode);
  };
  $("#statePill").className = `pill-state ${s.state}`; $("#statePill").textContent = STATE_LABEL[s.state] || s.state;
  const w = f.warnings || [];
  $("#dataWarn").hidden = !w.length;
  $("#dataWarn").innerHTML = w.map(x => `<p>⚠ ${esc(x)}</p>`).join("");
}

// ------------------------------------------------------------------ polling with backoff
function currentMode(s) { return s && s.state !== "stopped" && s.config ? s.config.trade_mode : segGet("c_trade_mode"); }
function query() {
  const c = readForm(), mode = currentMode(S.d);
  const p = new URLSearchParams({mode, tf: c.timeframe, entry_start: c.entry_start, cutoff: c.cutoff,
    exec_mode: c.exec_mode, roll: c.roll_on_expiry_day ? "1" : "0", risk_pct: $("#riskPct").value || "1"});
  const cap = +$("#capital").value; if (cap > 0) p.set("capital", cap);
  return p.toString();
}
async function poll(now = false) {
  clearTimeout(S.timer);
  if (now !== true && document.hidden && S.d) { S.timer = setTimeout(poll, POLL_MS); return; }
  try {
    const s = await api(`/api/live/dashboard?${query()}`);
    S.d = s; S.fails = 0;
    if (s.state !== "stopped" && s.config && JSON.stringify(s.config) !== JSON.stringify(S.cfg)) {
      S.cfg = s.config; writeForm({...defaults, ...s.config}); if (s.replay_day) $("#r_day").value = s.replay_day;
    }
    const mode = currentMode(s);
    checkNewAlerts(s.alerts || []);
    await loadTrades(mode);
    render(s, mode);
    if ($("#banner").dataset.kind === "conn") { banner(null); $("#banner").dataset.kind = ""; }
  } catch (e) {
    S.fails++;
    banner(`${e.message} Reconnecting in ${Math.round(Math.min(MAX_POLL_MS, POLL_MS * 2 ** S.fails) / 1000)}s (attempt ${S.fails}). Prices on screen are not live.`);
    $("#banner").dataset.kind = "conn";
    const chip = $("#liveChip"); chip.className = "chip unavailable"; chip.textContent = "DISCONNECTED";
  }
  S.timer = setTimeout(poll, S.fails ? Math.min(MAX_POLL_MS, POLL_MS * 2 ** S.fails) : POLL_MS);
}
function render(s, mode) {
  const f = s.feed || {};
  const running = s.state !== "stopped";
  lockForm(running);
  $("#liveCap").textContent = s.live_max_lots; $("#phrase").textContent = s.confirm_phrase;
  if (s.halt_reason) { banner(s.halt_reason); $("#banner").dataset.kind = "halt"; }
  else if ($("#banner").dataset.kind === "halt") { banner(null); $("#banner").dataset.kind = ""; }
  renderStatus(s, f, mode);
  if (f.error && !f.quote) {
    $("#liveChip").className = "chip unavailable"; $("#liveChip").textContent = "UNAVAILABLE";
    $("#ohlc").textContent = f.kind === "keys" ? f.error : `Groww data unavailable: ${f.error}`;
    chartMsg(f.kind === "keys" ? f.error : "Groww data unavailable.");
  } else {
    renderPrice(f); renderChart(f); renderStrategy(f);
  }
  renderSignal(f, s); renderHistory(s); renderPnl(s, mode);
}

function wire() {
  for (const id of ["c_trade_mode", "c_timeframe"])
    $(`#${id}`).onclick = e => { const b = e.target.closest("button"); if (!b || b.disabled) return; segSet(id, b.dataset.v); modeUI(); readForm(); S.tradesAt = 0; poll(true); };
  $$("#cfgForm select, #cfgForm input").forEach(el => el.addEventListener("change", () => { readForm(); poll(true); }));
  for (const id of ["capital", "riskPct"]) $(`#${id}`).addEventListener("change", () => {
    store.set("sizing", {capital: $("#capital").value, risk: $("#riskPct").value}); poll(true);
  });
  $("#startBtn").onclick = startEngine; $("#stopBtn").onclick = stopEngine; $("#sqBtn").onclick = squareOff;
  $("#brokerBtn").onclick = brokerPositions;
  $("#themeBtn").onclick = () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
    applyChartTheme(); if (S.d?.feed) renderChart(S.d.feed);
  };
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(true); });
}

wire();
const saved = store.get("live_cfg", {});
writeForm({...defaults, ...saved, ...(saved.v === 2 ? {} : {timeframe: 5}), signal_mode: "cross"});
const sz = store.get("sizing", {});
if (sz.capital) $("#capital").value = sz.capital;
if (sz.risk) $("#riskPct").value = sz.risk;
const d = new Date(); d.setDate(d.getDate() - 3); while ([0, 6].includes(d.getDay())) d.setDate(d.getDate() - 1);
$("#r_day").value = d.toISOString().slice(0, 10);
poll(true);
})();
