/* Data Management page */
(() => {
"use strict";
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const int = v => Number(v ?? 0).toLocaleString("en-IN");
const dmy = iso => iso ? new Date(iso.slice(0, 10) + "T00:00:00Z").toLocaleDateString("en-GB", {day: "2-digit", month: "short", year: "numeric", timeZone: "UTC"}) : "—";
const when = iso => iso ? `${dmy(iso)} ${iso.slice(11, 16)}` : "—";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const VERDICT = {none: ["No data", "v-none"], partial: ["Partial", "v-partial"], full: ["Full coverage", "v-full"]};

let polling = false, formFilled = false;

async function api(url, opts = {}) {
  if (opts.body) { opts.body = JSON.stringify(opts.body); opts.headers = {"Content-Type": "application/json"}; }
  let r;
  try { r = await fetch(url, opts); } catch (e) { throw new Error("Server unreachable. Is app.py running?"); }
  const j = await r.json().catch(() => ({ok: false, error: `HTTP ${r.status}`}));
  if (!j.ok) throw new Error(j.error || "Request failed");
  return j;
}
function banner(msg) { const b = $("#banner"); b.textContent = msg || ""; b.style.display = msg ? "block" : "none"; }
function progress(job) {
  $("#progress").hidden = !job;
  if (job) { $("#pfill").style.width = (job.progress * 100) + "%"; $("#ptext").textContent = job.message; }
  $("#stopBtn").hidden = !job; $("#dlBtn").disabled = !!job;
}

function kpi(label, value, sub) { return `<div class="kpi"><div class="l">${label}</div><div class="v num">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`; }
function renderKpis(c) {
  const s = c.summary;
  $("#kpis").innerHTML = [
    kpi("Sessions stored", int(s.sessions), `${int(s.not_downloaded)} not downloaded`),
    kpi("Candles", int(s.candles), "1-minute"),
    kpi("Complete days", int(s.complete), `${int(s.partial)} with gaps`),
    kpi("Missing candles", int(s.missing_minutes), "inside stored sessions"),
    kpi("Invalid candles", int(s.rejected), `${int(s.outside_session)} outside 09:15–15:29, not stored`),
    kpi("Coverage", s.coverage_pct + "%", s.last ? `latest ${when(s.last)}` : "nothing stored yet"),
  ].join("");
}
function renderVerdict(c) {
  const [text, cls] = VERDICT[c.verdict];
  const v = $("#verdict"); v.textContent = text; v.className = "badge " + cls;
  const s = c.summary, range = `${dmy(c.target.from)} to ${dmy(c.target.to)}`;
  $("#verdictBody").innerHTML = c.verdict === "none"
    ? `<p>Target window: <b>${range}</b>. No real candles are stored for it yet.</p><p class="muted">Groww's documentation gives conflicting limits, so the real history will only be known after a download. The result will appear here.</p>`
    : `<p>Target window: <b>${range}</b>.</p><p>Earliest candle stored: <b class="num">${when(s.first)}</b>. Latest: <b class="num">${when(s.last)}</b>.</p>` +
      `<p class="muted">${int(s.no_data)} weekdays returned no candles. Those are usually market holidays, but a real gap looks the same, so they are listed below.` +
      (s.special_sessions ? ` ${s.special_sessions} days had only out-of-hours candles, such as evening Muhurat trading.` : "") + `</p>` +
      `<p class="muted">${int(s.spikes)} price spikes over 5% between adjacent minutes were flagged.</p>`;
}
function renderMonths(c) {
  const by = Object.fromEntries(c.months.map(m => [m.month, m]));
  const years = [...new Set(c.months.map(m => m.month.slice(0, 4)))].sort().reverse();
  const head = `<thead><tr><th scope="col">Year</th>${MONTHS.map(m => `<th scope="col">${m}</th>`).join("")}</tr></thead>`;
  const body = years.map(y => `<tr><th scope="row">${y}</th>` + MONTHS.map((_, i) => {
    const key = `${y}-${String(i + 1).padStart(2, "0")}`, m = by[key];
    if (!m) return `<td><span class="cell blank">·</span></td>`;
    const got = (m.complete || 0) + (m.partial || 0) + (m.in_progress || 0), missing = m.not_downloaded || 0;
    const cls = !got ? (missing ? "c-none" : "c-zero") : (m.partial || missing) ? "c-part" : "c-full";
    const title = `${got} sessions stored, ${m.partial || 0} with gaps, ${m.no_data || 0} weekdays with no candles, ${missing} not downloaded`;
    const last = new Date(Date.UTC(+y, i + 1, 0)).toISOString().slice(0, 10);
    return `<td><a class="cell ${cls}" title="${title}" href="/history?from=${key}-01&to=${last}">${got || missing ? `${got}/${got + missing}` : "none"}</a></td>`;
  }).join("") + "</tr>").join("");
  $("#months").innerHTML = head + `<tbody>${body}</tbody>`;
}
function period(p) { return `<div class="row"><span class="num">${p.from === p.to ? dmy(p.from) : `${dmy(p.from)} → ${dmy(p.to)}`}</span><span class="muted">${p.days} weekday${p.days === 1 ? "" : "s"}</span></div>`; }
function renderLists(c) {
  const nd = c.not_downloaded, no = c.no_data;
  $("#missing").innerHTML = (!nd.length && !no.length) ? `<div class="none">No missing periods in this window.</div>` :
    (nd.length ? `<h3>Not downloaded</h3>` + nd.map(period).join("") : "") +
    (no.length ? `<h3>Groww returned no candles</h3>` + no.map(period).join("") : "") +
    (c.special_sessions.length ? `<h3>Special sessions outside regular hours (not stored)</h3>` +
      c.special_sessions.map(d => period({from: d, to: d, days: 1})).join("") : "");
  $("#partial").innerHTML = c.partial_days.length
    ? c.partial_days.slice().reverse().map(d => `<div class="row"><a class="num" href="/history?from=${d.day}&to=${d.day}">${dmy(d.day)}</a><span class="muted">${d.missing} missing: ${esc(d.ranges.slice(0, 3).map(r => r[0] === r[1] ? r[0] : r.join("–")).join(", "))}${d.ranges.length > 3 ? "…" : ""}</span></div>`).join("")
    : `<div class="none">No partial days stored.</div>`;
}
function renderRuns(runs) {
  $("#runs").innerHTML = !runs.length ? `<tbody><tr><td class="muted" style="text-align:center;padding:24px">No downloads yet.</td></tr></tbody>` :
    `<thead><tr><th>Started</th><th>Range</th><th>Status</th><th>Requests</th><th>New</th><th>Duplicates</th><th>Invalid</th><th>Outside hours</th></tr></thead><tbody>` +
    runs.map(r => `<tr><td class="num">${when(r.started_at)}</td><td class="num">${dmy(r.start_date)} → ${dmy(r.end_date)}</td>` +
      `<td><span class="st-${esc(r.status)}">${esc(r.status)}</span>${r.error ? `<div class="err">${esc(r.error)}</div>` : ""}</td>` +
      `<td class="num">${r.chunks_done}/${r.chunks_total}</td><td class="num">${int(r.rows_new)}</td><td class="num">${int(r.rows_duplicate)}</td><td class="num">${int(r.rows_rejected)}</td><td class="num">${int(r.rows_outside_session)}</td></tr>`).join("") + "</tbody>";
}

async function load() {
  const {data} = await api("/api/data/overview");
  const c = data.coverage;
  if (!formFilled) { $("#d_from").value = c.target.from; $("#d_to").value = c.target.to; formFilled = true; }
  renderKpis(c); renderVerdict(c); renderMonths(c); renderLists(c); renderRuns(data.downloads);
  progress(data.job);
  if (data.job) poll(data.job.id);
}
async function poll(id) {
  if (polling) return;
  polling = true;
  try {
    for (;;) {
      const r = await api(`/api/jobs/${id}`), j = r.data || r;
      progress(j.state === "done" || j.state === "error" ? null : j);
      if (j.state === "error") banner(j.error);
      if (j.state === "done" || j.state === "error") break;
      await new Promise(res => setTimeout(res, 1000));
    }
  } catch (e) { banner(e.message); progress(null); }
  polling = false;
  await load().catch(e => banner(e.message));
}

$("#dlBtn").onclick = async () => {
  banner(null);
  try {
    const {job} = await api("/api/data/download", {method: "POST", body: {from: $("#d_from").value, to: $("#d_to").value}});
    progress({progress: 0, message: "Starting download"});
    poll(job);
  } catch (e) { banner(e.message); }
};
$("#stopBtn").onclick = () => api("/api/data/stop", {method: "POST"}).catch(e => banner(e.message));
$("#themeBtn").onclick = () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
};
$("#kpis").innerHTML = Array(6).fill(`<div class="kpi"><div class="l">Loading</div><div class="v">…</div></div>`).join("");
load().catch(e => banner(e.message));
})();
