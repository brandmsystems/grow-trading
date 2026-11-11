/* Strategy comparison page */
(() => {
"use strict";
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const inr = (v, sign = true) => v == null || isNaN(v) ? "—" :
  (sign && v > 0 ? "+" : v < 0 ? "−" : "") + "₹" + Math.abs(Math.round(v)).toLocaleString("en-IN");
const pct = v => v == null ? "—" : Number(v).toFixed(1) + "%";
const cls = v => v > 0 ? "pos" : v < 0 ? "neg" : "";
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
};
const MODES = {ITM5_BUY: "ITM 5 buy", ATM_BUY: "ATM buy", ATM_SELL: "ATM sell"};
const SLOTS = ["--s1", "--s2", "--s3", "--s4"];
const S = {meta: null, data: null, mode: store.get("cmp_mode", "ATM_BUY"), tf: store.get("cmp_tf", 15),
  start: "09:30", cutoff: "14:30", picked: store.get("cmp_picked", null)};
let eq, eqLines = [], mon, monSeries;

async function api(url, opts = {}) {
  if (opts.body) { opts.body = JSON.stringify(opts.body); opts.headers = {"Content-Type": "application/json"}; }
  let r;
  try { r = await fetch(url, opts); } catch (e) { throw new Error("Server unreachable. Is app.py running?"); }
  const j = await r.json().catch(() => ({ok: false, error: `HTTP ${r.status}`}));
  if (!j.ok) throw new Error(j.error || "Request failed");
  return j;
}
function banner(m) { const b = $("#banner"); b.textContent = m || ""; b.style.display = m ? "block" : "none"; }
function progress(j) {
  $("#progress").hidden = !j; $("#runBtn").disabled = !!j;
  if (j) { $("#pfill").style.width = j.progress * 100 + "%"; $("#ptext").textContent = j.message; }
}
const key = c => `${c.strategy}|${c.timeframe}`;
const m = c => c.summary?.modes?.[S.mode];

function seg(el, items, cur, on) {
  el.innerHTML = items.map(([v, l]) => `<button type="button" data-v="${v}" aria-pressed="${String(v) === String(cur)}">${l}</button>`).join("");
  el.onclick = e => { const b = e.target.closest("button"); if (!b) return; $$(`#${el.id} button`).forEach(x => x.setAttribute("aria-pressed", x === b)); on(b.dataset.v); };
}

function renderMatrix() {
  const cells = S.data.cells, tfs = [...new Set(cells.map(c => c.timeframe))].sort((a, b) => a - b);
  const strats = [...new Map(cells.map(c => [c.strategy, c.label])).entries()];
  const done = cells.filter(m);
  const best = done.length ? key(done.reduce((a, b) => (m(b).net_pnl > m(a).net_pnl ? b : a))) : null;
  if (!S.picked) S.picked = done.length ? [...done].sort((a, b) => m(b).net_pnl - m(a).net_pnl).slice(0, 3).map(key) : [];
  if (!S.picked.includes("ema_9_21|15") && S.picked.length < 4 && done.some(c => key(c) === "ema_9_21|15")) S.picked.push("ema_9_21|15");
  const by = Object.fromEntries(cells.map(c => [key(c), c]));
  $("#matrix").innerHTML = `<thead><tr><th>Strategy</th>${tfs.map(t => `<th>${t}m</th>`).join("")}</tr></thead><tbody>` +
    strats.map(([s, label]) => `<tr><td class="lbl">${esc(label)}</td>` + tfs.map(tf => {
      const c = by[`${s}|${tf}`], x = c && m(c);
      if (!x) return `<td class="missing">not run</td>`;
      const k = key(c);
      return `<td class="cell ${k === best ? "best" : ""}" data-k="${k}" title="Open in Backtest">` +
        `<label onclick="event.stopPropagation()"><input type="checkbox" data-pick="${k}" ${S.picked.includes(k) ? "checked" : ""} aria-label="Chart ${esc(label)} ${tf}m"></label>` +
        `<span class="num ${cls(x.net_pnl)}">${inr(x.net_pnl)}</span>` +
        `<span class="sub">${x.trades} trades · ${pct(x.win_rate)} won · PF ${x.profit_factor ?? "—"}</span>` +
        `<span class="sub">max DD ${inr(-x.max_drawdown, false)}${x.skipped ? ` · ${x.skipped} skipped` : ""}</span></td>`;
    }).join("") + "</tr>").join("") + "</tbody>";
  const any = cells.find(m);
  $("#range").textContent = any ? `· ${any.start_date} → ${any.end_date}` : "";
}

function renderBars() {
  const rows = S.data.cells.filter(c => c.timeframe === +S.tf && m(c));
  $$(".tfName").forEach(e => e.textContent = `· ${S.tf}m · ${MODES[S.mode]}`);
  if (!rows.length) { $("#winBars").innerHTML = $("#ddBars").innerHTML = `<p class="muted pad">No results for ${S.tf}m yet.</p>`; return; }
  const maxDd = Math.max(...rows.map(c => m(c).max_drawdown), 1);
  $("#winBars").innerHTML = rows.map(c => `<div class="bar-row" title="${esc(c.label)}: ${pct(m(c).win_rate)} of ${m(c).trades} trades"><span class="name">${esc(c.label)}</span>` +
    `<span class="track"><span class="fill" style="width:${m(c).win_rate}%"></span><span class="mark" style="left:50%" title="50%"></span></span><span class="val">${pct(m(c).win_rate)}</span></div>`).join("");
  $("#ddBars").innerHTML = rows.map(c => `<div class="bar-row" title="${esc(c.label)}: ${inr(-m(c).max_drawdown, false)} (${pct(m(c).max_drawdown_pct)})"><span class="name">${esc(c.label)}</span>` +
    `<span class="track"><span class="fill dd" style="width:${m(c).max_drawdown / maxDd * 100}%"></span></span><span class="val">${inr(-m(c).max_drawdown, false)}</span></div>`).join("");
  const years = [...new Set(rows.flatMap(c => Object.keys(m(c).yearly)))].sort();
  $("#years").innerHTML = `<thead><tr><th>Strategy</th>${years.map(y => `<th>${y}</th>`).join("")}<th>Total</th></tr></thead><tbody>` +
    rows.map(c => `<tr><td class="lbl">${esc(c.label)}</td>` + years.map(y => {
      const v = m(c).yearly[y];
      return `<td>${v ? `<span class="num ${cls(v.net)}">${inr(v.net)}</span><span class="sub">${v.trades} · ${pct(v.win_rate)}</span>` : "—"}</td>`;
    }).join("") + `<td><span class="num ${cls(m(c).net_pnl)}">${inr(m(c).net_pnl)}</span></td></tr>`).join("") + "</tbody>";
}

function chartOpts() {
  return {autoSize: true, layout: {background: {color: "transparent"}, textColor: css("--text-2"), fontFamily: "Inter, system-ui, sans-serif"},
    grid: {vertLines: {visible: false}, horzLines: {color: css("--grid")}}, rightPriceScale: {borderColor: css("--border")},
    timeScale: {borderColor: css("--border")},
    localization: {priceFormatter: v => (v < 0 ? "−" : "") + "₹" + (Math.abs(v) >= 1e5 ? (Math.abs(v) / 1e5).toFixed(2) + "L" : Math.round(Math.abs(v)).toLocaleString("en-IN"))}};
}
function renderCharts() {
  if (!window.LightweightCharts) { $("#eqChart").textContent = "Chart library failed to load."; return; }
  if (!eq) { eq = LightweightCharts.createChart($("#eqChart"), chartOpts()); mon = LightweightCharts.createChart($("#monthlyChart"), chartOpts()); monSeries = mon.addHistogramSeries({priceLineVisible: false, lastValueVisible: false}); }
  eqLines.forEach(l => eq.removeSeries(l)); eqLines = [];
  const by = Object.fromEntries(S.data.cells.map(c => [key(c), c]));
  const picked = S.picked.map(k => by[k]).filter(c => c && m(c));
  $("#eqLegend").innerHTML = picked.map((c, i) => `<span class="sw" style="background:var(${SLOTS[i]})"></span>${esc(c.label)} ${c.timeframe}m`).join("");
  picked.forEach((c, i) => {
    const line = eq.addLineSeries({color: css(SLOTS[i]), lineWidth: 2, priceLineVisible: false, lastValueVisible: false});
    let cum = 0;
    line.setData(m(c).daily.map(([d, v]) => ({time: d, value: (cum += v)})));
    eqLines.push(line);
  });
  eq.timeScale().fitContent();
  const first = picked[0];
  $("#monthlyName").textContent = first ? `· ${first.label} ${first.timeframe}m` : "";
  monSeries.setData(first ? Object.entries(m(first).monthly).map(([mo, v]) => ({time: mo + "-01", value: v, color: v >= 0 ? css("--gain") : css("--loss")})) : []);
  mon.timeScale().fitContent();
}

function renderWf() {
  const wf = S.data.walk_forward[S.mode];
  if (!wf.rows.length) { $("#wf").innerHTML = ""; $("#wfNote").textContent = "Needs results for at least two calendar years."; return; }
  $("#wfNote").textContent = `Each year uses the configuration with the best net P&L on all earlier years (${wf.configs} configurations compared), then records what it made in that year. ` +
    `Out-of-sample total: ${inr(wf.total_oos)}. EMA 9/21 at 15m over the same years: ${inr(wf.baseline_total)}.`;
  $("#wf").innerHTML = `<thead><tr><th>Test year</th><th>Chosen using</th><th>Chosen configuration</th><th>Earlier-years P&amp;L</th><th>P&amp;L in test year</th><th>EMA 9/21 15m</th><th>Best in hindsight</th></tr></thead><tbody>` +
    wf.rows.map(r => `<tr><td>${r.year}</td><td>${r.trained_on}</td><td class="lbl">${esc(r.pick.label)} ${r.pick.timeframe}m</td>` +
      `<td class="num ${cls(r.insample_net)}">${inr(r.insample_net)}</td><td class="num ${cls(r.oos_net)}">${inr(r.oos_net)}</td>` +
      `<td class="num ${cls(r.baseline_net)}">${inr(r.baseline_net)}</td><td>${esc(r.hindsight_best.label)} ${r.hindsight_best.timeframe}m <span class="sub">${inr(r.hindsight_best.net)}</span></td></tr>`).join("") + "</tbody>";
}

function render() {
  const n = S.data.cells.filter(c => c.summary).length;
  $("#status").textContent = `${n} of ${S.data.cells.length} configurations computed.` + (n < S.data.cells.length ? " Run missing to compute the rest; the first run downloads option candles, so it can take a long time." : "");
  renderMatrix(); renderBars(); renderCharts(); renderWf();
}

async function load() {
  const r = await api(`/api/research?entry_start=${S.start}&cutoff=${S.cutoff}`);
  S.data = r.data; render();
  if (r.job) poll(r.job.id);
}
async function poll(id) {
  for (;;) {
    const j = (await api(`/api/jobs/${id}`)).data;
    progress(j.state === "done" || j.state === "error" ? null : j);
    if (j.state === "error") { banner(j.error); break; }
    if (j.state === "done") break;
    await new Promise(r => setTimeout(r, 2000));
  }
  await load();
}

$("#matrix").addEventListener("change", e => {
  const k = e.target.dataset.pick; if (!k) return;
  S.picked = e.target.checked ? [...S.picked, k] : S.picked.filter(x => x !== k);
  if (S.picked.length > 4) { S.picked.shift(); renderMatrix(); }
  store.set("cmp_picked", S.picked); renderCharts();
});
$("#matrix").addEventListener("click", e => {
  const td = e.target.closest("td.cell"); if (!td || e.target.closest("label")) return;
  const [strategy, tf] = td.dataset.k.split("|"), c = S.data.cells.find(x => key(x) === td.dataset.k);
  location.href = `/?strategy=${strategy}&tf=${tf}&start_date=${c.start_date}&end_date=${c.end_date}&entry_start=${S.start}&cutoff=${S.cutoff}&mode=${S.mode}`;
});
$("#runBtn").onclick = async () => {
  banner(null);
  try { const r = await api("/api/research/run", {method: "POST", body: {entry_start: S.start, cutoff: S.cutoff}}); progress({progress: 0, message: "Starting"}); poll(r.job); }
  catch (e) { banner(e.message); }
};
$("#themeBtn").onclick = () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
  if (eq) { eq.applyOptions(chartOpts()); mon.applyOptions(chartOpts()); renderCharts(); }
};

(async function boot() {
  try {
    S.meta = (await api("/api/bt/meta")).data;
    seg($("#f_mode"), Object.entries(MODES), S.mode, v => { S.mode = v; store.set("cmp_mode", v); render(); });
    seg($("#f_tf"), S.meta.timeframes.map(t => [t, t + "m"]), S.tf, v => { S.tf = +v; store.set("cmp_tf", S.tf); renderBars(); });
    $("#f_start").innerHTML = S.meta.starts.map(s => `<option>${s}</option>`).join("");
    $("#f_cutoff").innerHTML = S.meta.cutoffs.map(s => `<option>${s}</option>`).join("");
    $("#f_start").value = S.start; $("#f_cutoff").value = S.cutoff;
    $("#f_start").onchange = e => { S.start = e.target.value; S.picked = null; load().catch(x => banner(x.message)); };
    $("#f_cutoff").onchange = e => { S.cutoff = e.target.value; S.picked = null; load().catch(x => banner(x.message)); };
    await load();
  } catch (e) { banner(e.message); }
})();
})();
