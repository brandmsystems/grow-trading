/* Historical candlestick viewer */
(() => {
"use strict";
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const toTime = iso => Math.floor(Date.parse(iso + "Z") / 1000);
const num = v => Number(v).toLocaleString("en-IN", {minimumFractionDigits: 2, maximumFractionDigits: 2});
const iso = d => d.toISOString().slice(0, 10);
const shift = (s, days) => { const d = new Date(s + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + days); return iso(d); };
const span = (a, b) => Math.round((Date.parse(b) - Date.parse(a)) / 86400000) + 1;

const S = {tf: 5, last: null, bars: [], seq: 0};
let chart, series;

async function api(url) {
  let r;
  try { r = await fetch(url); } catch (e) { throw new Error("Server unreachable. Is app.py running?"); }
  const j = await r.json().catch(() => ({ok: false, error: `HTTP ${r.status}`}));
  if (!j.ok) throw new Error(j.error || "Request failed");
  return j.data;
}
function banner(msg) { const b = $("#banner"); b.textContent = msg || ""; b.style.display = msg ? "block" : "none"; }
function chartMsg(msg) { const m = $("#chartMsg"); m.hidden = !msg; m.textContent = msg || ""; }

function theme() {
  return {
    layout: {background: {color: "transparent"}, textColor: css("--text-2"), fontFamily: "Inter, system-ui, sans-serif"},
    grid: {vertLines: {color: css("--grid")}, horzLines: {color: css("--grid")}},
    rightPriceScale: {borderColor: css("--border")},
    timeScale: {borderColor: css("--border"), timeVisible: true, secondsVisible: false},
  };
}
const candleColors = () => ({upColor: css("--gain"), borderUpColor: css("--gain"), wickUpColor: css("--gain"),
  downColor: css("--loss"), borderDownColor: css("--loss"), wickDownColor: css("--loss")});
function ensureChart() {
  if (chart) return true;
  if (!window.LightweightCharts) { chartMsg("The chart library could not load. Check your internet connection and reload."); return false; }
  chart = LightweightCharts.createChart($("#chart"), {...theme(), autoSize: true});
  series = chart.addCandlestickSeries(candleColors());
  chart.subscribeCrosshairMove(p => readout(p.seriesData?.get(series)));
  return true;
}
function readout(b) {
  b = b || S.bars[S.bars.length - 1];
  $("#ohlc").textContent = b ? `O ${num(b.open)}  H ${num(b.high)}  L ${num(b.low)}  C ${num(b.close)}` : "";
}

async function load() {
  const from = $("#h_from").value, to = $("#h_to").value, seq = ++S.seq;
  if (!from || !to) return;
  banner(null);
  if (!ensureChart()) return;
  chartMsg("Loading candles…");
  try {
    const d = await api(`/api/data/candles?from=${from}&to=${to}&tf=${S.tf}`);
    if (seq !== S.seq) return;
    S.bars = d.bars.map(b => ({time: toTime(b.t), open: b.o, high: b.h, low: b.l, close: b.c}));
    series.setData(S.bars);
    if (S.bars.length) { chart.timeScale().fitContent(); chartMsg(null); }
    else chartMsg("No candles stored for this range. It may be a holiday, or not downloaded yet.");
    readout();
    history.replaceState(null, "", `/history?from=${from}&to=${to}&tf=${S.tf}`);
  } catch (e) {
    if (seq !== S.seq) return;
    S.bars = []; series.setData([]); readout(); chartMsg("Couldn't load this range."); banner(e.message);
  }
}
function setTf(v) { S.tf = +v; $$("#h_tf button").forEach(b => b.setAttribute("aria-pressed", String(+b.dataset.v === S.tf))); }
function move(dir) {
  const from = $("#h_from").value, to = $("#h_to").value, n = span(from, to);
  $("#h_from").value = shift(from, dir * n); $("#h_to").value = shift(to, dir * n);
  load();
}
function latest() { if (!S.last) return; $("#h_to").value = S.last; $("#h_from").value = shift(S.last, -6); load(); }

$("#h_tf").onclick = e => { const b = e.target.closest("button"); if (b) { setTf(b.dataset.v); load(); } };
$("#h_from").onchange = $("#h_to").onchange = load;
$("#prevBtn").onclick = () => move(-1);
$("#nextBtn").onclick = () => move(1);
$("#latestBtn").onclick = latest;
document.addEventListener("keydown", e => {
  if (e.target.matches("input,select,textarea")) return;
  if (e.key === "ArrowLeft") move(-1);
  if (e.key === "ArrowRight") move(1);
});
$("#themeBtn").onclick = () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
  if (chart) { chart.applyOptions(theme()); series.applyOptions(candleColors()); }
};

(async function boot() {
  const q = new URLSearchParams(location.search);
  setTf(q.get("tf") || 5);
  try {
    const {coverage: c} = await api("/api/data/overview");
    S.last = c.summary.last ? c.summary.last.slice(0, 10) : null;
    if (!S.last) {
      $("#chartCard").hidden = true; $("#empty").hidden = false;
      $("#emptyMsg").textContent = "No real NIFTY candles are stored yet. Download them on the Data page and they'll appear here.";
      return;
    }
  } catch (e) { banner(e.message); return; }
  $("#h_to").value = q.get("to") || S.last;
  $("#h_from").value = q.get("from") || shift($("#h_to").value, -6);
  load();
})();
})();
