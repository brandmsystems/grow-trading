/* Signal analysis page */
(() => {
"use strict";
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const num = (v, d = 2) => v == null ? "—" : Number(v).toLocaleString("en-IN", {minimumFractionDigits: d, maximumFractionDigits: d});
const pct = v => v == null ? "—" : Number(v).toFixed(1) + "%";
const when = iso => iso ? `${new Date(iso.slice(0, 10) + "T00:00:00Z").toLocaleDateString("en-GB", {day: "2-digit", month: "short", year: "numeric", timeZone: "UTC"})} ${iso.slice(11, 16)}` : "—";
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
};
const S = {strategy: store.get("sig_strategy", "ema_9_21"), tf: store.get("sig_tf", 15), data: null, sel: null};

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
  $("#progress").hidden = !j; $("#buildBtn").disabled = !!j;
  if (j) { $("#pfill").style.width = j.progress * 100 + "%"; $("#ptext").textContent = j.message; }
}
const catCls = s => s == null ? "" : s >= 85 ? "c85" : s >= 70 ? "c70" : s >= 50 ? "c50" : "";
const callCls = c => c === "Bullish" ? "bull" : c === "Bearish" ? "bear" : "flat";
function kpi(l, v, sub) { return `<div class="kpi"><div class="l">${l}</div><div class="v num">${v}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`; }

function renderDetail(s) {
  if (!s) { $("#detail").innerHTML = `<p class="muted pad">No signals.</p>`; return; }
  const mark = v => v === true ? `<span class="y" aria-label="supports">✓</span>` : v === false ? `<span class="n" aria-label="against">✗</span>` : `<span class="z" aria-label="neutral">–</span>`;
  const comp = s.comparable ? `${pct(s.comparable.hit_rate)} hit rate across ${s.comparable.n} past out-of-sample signals in this band` : "No comparable history";
  $("#detail").innerHTML =
    `<div class="card-head"><h2>Signal · ${when(s.ts)}</h2><span class="muted">${s.out_of_sample ? "out-of-sample score" : s.score == null ? "" : "scored by the current model"}</span></div>` +
    `<div class="sig-head"><span class="call ${callCls(s.call)}">${esc(s.call)}</span><span class="muted">${esc(s.direction)} cross</span>` +
    `<span class="score">${s.score == null ? "—" : num(s.score, 1)}</span><span class="cat ${catCls(s.score)}">${esc(s.category)}</span>` +
    (s.strong_alert ? `<span class="cat c70">Strong alert</span>` : "") + `</div>` +
    `<div class="refs"><div><div class="l">Entry ref</div><div class="v">${num(s.entry)}</div></div><div><div class="l">Stop</div><div class="v">${num(s.stop)}</div></div>` +
    `<div><div class="l">Target</div><div class="v">${num(s.target)}</div></div><div><div class="l">Risk / reward</div><div class="v">1 : ${num(s.risk_reward, 1)}</div></div></div>` +
    `<div class="reason">${esc(s.reason)}</div>` +
    `<ul class="ind">${s.indicators.map(i => `<li>${mark(i.supports)}<span>${esc(i.name)}</span><span class="muted">${esc(i.value)}</span></li>`).join("")}</ul>` +
    `<dl class="kv"><dt>Signal expires</dt><dd class="num">${when(s.expires)}</dd><dt>Comparable signals</dt><dd>${esc(comp)}</dd>` +
    `<dt>Outcome</dt><dd class="o-${s.outcome.split(" ")[0]}">${esc(s.outcome)}${s.decided_at ? ` at ${s.decided_at.slice(11, 16)}` : ""}</dd><dt>ATR</dt><dd class="num">${num(s.atr)}</dd></dl>`;
}

function render() {
  const d = S.data, mdl = d.model;
  $("#empty").hidden = true; $("#content").hidden = false;
  $("#kpis").innerHTML =
    kpi("Signals", d.counts.signals.toLocaleString("en-IN"), `${d.strategy_label} · ${d.timeframe}m`) +
    kpi("Scored out-of-sample", d.counts.oos.toLocaleString("en-IN"), "earlier years used for training") +
    kpi("Base hit rate", pct(mdl.base_rate), "target before stop, out-of-sample") +
    kpi("Ranking skill (AUC)", mdl.auc == null ? "—" : num(mdl.auc, 3), "0.5 = no skill") +
    kpi("Brier score", mdl.brier == null ? "—" : num(mdl.brier, 4), `base-rate guess: ${mdl.brier_base == null ? "—" : num(mdl.brier_base, 4)}`) +
    kpi("Data up to", d.asof.slice(11, 16), `${d.asof.slice(0, 10)} · built ${d.generated_at.slice(11, 16)}`);
  const rel = d.reliability;
  $("#relBars").innerHTML = rel.length ? rel.map(r => `<div class="bar-row" title="Scores ${r.from}–${r.to}: ${r.n} signals, mean score ${r.mean_score}, actual hit rate ${r.hit_rate}%">` +
    `<span class="name">score ${num(r.from, 0)}–${num(r.to, 0)} <span class="muted">n=${r.n}</span></span><span class="track"><span class="fill" style="width:${r.hit_rate}%"></span>` +
    `<span class="mark" style="left:${r.mean_score}%" title="mean score"></span></span><span class="val">${pct(r.hit_rate)}</span></div>`).join("") +
    `<p class="hint">Bars show the actual hit rate in each score range; the dark tick marks the average score. If scores were exact probabilities, ticks would sit at the end of the bars.</p>` : `<p class="muted">Not enough out-of-sample signals.</p>`;
  $("#bands").innerHTML = `<thead><tr><th>Band</th><th>Signals</th><th>Average score</th><th>Actual hit rate</th></tr></thead><tbody>` +
    d.calibration.map(c => `<tr><td>${esc(c.band)} <span class="sub">${c.from}–${c.to}</span></td><td>${c.n}</td><td>${c.mean_score == null ? "—" : num(c.mean_score, 1)}</td><td>${pct(c.hit_rate)}</td></tr>`).join("") + "</tbody>";
  const strongN = d.calibration.filter(c => c.from >= 70).reduce((a, c) => a + c.n, 0);
  $("#calNote").textContent = strongN < 30 ? `Only ${strongN} out-of-sample signals scored 70 or more, too few to call "strong" reliable.` : "";
  $("#sigCount").textContent = `· latest ${d.signals.length}`;
  $("#sigTable").innerHTML = `<thead><tr><th>Time</th><th>Cross</th><th>Call</th><th>Score</th><th>Band</th><th>Entry</th><th>Stop</th><th>Target</th><th>Outcome</th></tr></thead><tbody>` +
    d.signals.map(s => `<tr data-id="${esc(s.id)}" class="${s.id === S.sel ? "sel" : ""}"><td class="num">${when(s.ts)}</td><td>${esc(s.direction)}</td>` +
      `<td class="call-sm ${callCls(s.call)}">${esc(s.call)}${s.strong_alert ? " ★" : ""}</td><td class="num">${s.score == null ? "—" : num(s.score, 1)}</td><td>${esc(s.category)}</td>` +
      `<td class="num">${num(s.entry)}</td><td class="num">${num(s.stop)}</td><td class="num">${num(s.target)}</td><td class="o-${s.outcome.split(" ")[0]}">${esc(s.outcome)}</td></tr>`).join("") + "</tbody>";
  $("#folds").innerHTML = `<thead><tr><th>Test year</th><th>Trained on</th><th>Tested</th><th>Hit rate</th><th>AUC</th></tr></thead><tbody>` +
    (mdl.folds.map(f => `<tr><td>${f.year}</td><td>${f.train_signals} earlier signals</td><td>${f.test_signals}</td><td>${pct(f.hit_rate)}</td><td>${f.auc == null ? "—" : num(f.auc, 3)}</td></tr>`).join("") ||
      `<tr><td colspan="5" class="muted">Not enough history for a fold.</td></tr>`) + "</tbody>";
  $("#weights").innerHTML = `<thead><tr><th>Indicator</th><th>Weight</th><th>Measured as</th></tr></thead><tbody>` +
    (mdl.weights || []).map(w => `<tr><td class="lbl">${esc(w.feature)}</td><td class="num ${w.weight > 0 ? "pos" : w.weight < 0 ? "neg" : ""}">${w.weight > 0 ? "+" : ""}${num(w.weight, 3)}</td><td style="white-space:normal;text-align:left" class="muted">${esc(w.detail)}</td></tr>`).join("") + "</tbody>";
  renderDetail(d.signals.find(s => s.id === S.sel) || d.signals[0]);
}

async function load() {
  banner(null);
  const r = await api(`/api/signals?strategy=${S.strategy}&tf=${S.tf}`);
  if (r.job) { progress(r.job); return poll(r.job.id); }
  if (!r.data) { S.data = null; $("#content").hidden = true; $("#empty").hidden = false; return; }
  S.data = r.data; render();
}
async function poll(id) {
  for (;;) {
    const j = (await api(`/api/jobs/${id}`)).data;
    progress(j.state === "done" || j.state === "error" ? null : j);
    if (j.state === "error") { banner(j.error); return; }
    if (j.state === "done") break;
    await new Promise(r => setTimeout(r, 1000));
  }
  await load();
}
async function build() {
  try { const r = await api("/api/signals/build", {method: "POST", body: {strategy: S.strategy, tf: S.tf}}); progress({progress: 0, message: "Starting"}); poll(r.job); }
  catch (e) { banner(e.message); }
}

$("#sigTable").addEventListener("click", e => {
  const tr = e.target.closest("tr[data-id]"); if (!tr) return;
  S.sel = tr.dataset.id; $$("#sigTable tr.sel").forEach(x => x.classList.remove("sel")); tr.classList.add("sel");
  renderDetail(S.data.signals.find(s => s.id === S.sel));
});
$("#buildBtn").onclick = build;
$("#themeBtn").onclick = () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
};
(async function boot() {
  try {
    const meta = (await api("/api/bt/meta")).data;
    $("#f_strategy").innerHTML = Object.entries(meta.strategies).map(([k, l]) => `<option value="${k}">${esc(l)}</option>`).join("");
    $("#f_strategy").value = S.strategy;
    $("#f_strategy").onchange = e => { S.strategy = e.target.value; store.set("sig_strategy", S.strategy); S.sel = null; load().catch(x => banner(x.message)); };
    $("#f_tf").innerHTML = meta.timeframes.map(t => `<button type="button" data-v="${t}" aria-pressed="${t === +S.tf}">${t}m</button>`).join("");
    $("#f_tf").onclick = e => { const b = e.target.closest("button"); if (!b) return; $$("#f_tf button").forEach(x => x.setAttribute("aria-pressed", x === b)); S.tf = +b.dataset.v; store.set("sig_tf", S.tf); S.sel = null; load().catch(x => banner(x.message)); };
    await load();
    if (!S.data && $("#progress").hidden) build();
  } catch (e) { banner(e.message); }
})();
})();
