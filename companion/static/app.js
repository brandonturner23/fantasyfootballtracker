/* Fantasy Companion dashboard. Vanilla JS + Chart.js. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n, d = 1) => (n === null || n === undefined || Number.isNaN(n) ? "–" : Number(n).toFixed(d));
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const POS_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF"];
const STATUS = { Q: ["Questionable", "warning"], D: ["Doubtful", "serious"], O: ["Out", "critical"], IR: ["IR", "critical"],
  SUSP: ["Suspended", "critical"], "PUP-R": ["PUP", "critical"], NA: ["Inactive", "critical"] };
let DATA = null, STATUS_INFO = null, WEEK = null;
const charts = {};

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch (_) {}
    const err = new Error(msg); err.status = res.status; throw err;
  }
  return res.json();
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 3500);
}
function kickoff(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });
}
function statusBadge(s) {
  if (!s) return "";
  const [label, cls] = STATUS[s] || [s, "warning"];
  return `<span class="badge ${cls}">${esc(label)}</span>`;
}
function tagBadges(tags = []) {
  const cls = { Hot: "good", Cold: "serious", Bye: "critical", "Smash spot": "good", Trending: "good", "Boom/Bust": "warning" };
  return tags.filter((t) => !STATUS[t] && t !== "Q").map((t) => `<span class="badge ${cls[t] || ""}">${esc(t)}</span>`).join("");
}
function oppText(p) {
  if (p.on_bye) return `<span class="badge critical">BYE</span>`;
  if (!p.opponent) return "–";
  return `${p.home ? "vs" : "@"} ${esc(p.opponent)}`;
}

/* ------------------------------------------------------------------ boot */
async function boot() {
  STATUS_INFO = await api("/api/status");
  $("#demoBanner").hidden = !STATUS_INFO.demo;
  if (!STATUS_INFO.authenticated) return showConnect();
  $("#tabs").hidden = false; $("#main").hidden = false;
  await load();
}

async function showConnect() {
  $("#loading").hidden = true;
  $("#connect").hidden = false;
  const { url } = await api("/api/auth/url");
  const link = $("#yahooLink");
  link.href = url;
  if (!STATUS_INFO.oob) $("#codeStep").firstChild.textContent =
    "After approving, copy the code= value from the address bar of the page Yahoo sends you to and paste it here: ";
  $("#codeForm").onsubmit = async (e) => {
    e.preventDefault();
    try { await api("/api/auth/code", { method: "POST", body: JSON.stringify({ code: $("#codeInput").value }) }); location.reload(); }
    catch (err) { $("#connectError").textContent = err.message; }
  };
}

async function load(refresh = false) {
  $("#loading").hidden = false;
  try {
    const q = new URLSearchParams();
    if (WEEK) q.set("week", WEEK);
    if (refresh) q.set("refresh", "1");
    DATA = await api(`/api/dashboard?${q}`);
    WEEK = DATA.week;
    render();
  } catch (err) {
    if (err.status === 401) return showConnect();
    toast(`Couldn't load data: ${err.message}`);
  } finally { $("#loading").hidden = true; }
}

function render() {
  const d = DATA;
  $("#leagueName").textContent = `${d.my_team.name} · ${d.league.name}`;
  const sel = $("#weekSelect");
  const last = Math.max(d.league.end_week || 17, d.league.current_week || d.week);
  sel.innerHTML = Array.from({ length: last - (d.league.start_week || 1) + 1 }, (_, i) => i + (d.league.start_week || 1))
    .map((w) => `<option value="${w}" ${w === d.week ? "selected" : ""}>${w}${w === d.league.current_week ? " (now)" : ""}</option>`).join("");
  renderOverview(); renderLineup(); renderPlayers(); renderTrends(); renderTrades(); renderByes(); renderAlerts();
}

/* -------------------------------------------------------------- overview */
function renderOverview() {
  const d = DATA, st = d.my_team.standing || {}, m = d.matchup || {}, lu = d.lineup;
  const rec = `${st.wins ?? 0}-${st.losses ?? 0}${st.ties ? "-" + st.ties : ""}`;
  const played = d.matchups.filter((x) => x.status === "postevent");
  const avg = played.length ? played.reduce((a, x) => a + (x.points || 0), 0) / played.length : 0;
  const tiles = [
    ["Record", rec, st.rank ? `Rank ${st.rank} of ${d.standings.length}` : ""],
    ["Points for", fmt(st.points_for, 1), `${fmt(avg, 1)} per week`],
    [`Week ${d.week} vs ${m.opp_name || "–"}`, `${fmt(m.points ?? 0, 1)} – ${fmt(m.opp_points ?? 0, 1)}`,
      `Proj ${fmt(m.projected)} – ${fmt(m.opp_projected)}`],
    ["Optimal lineup", fmt(lu.total, 1), lu.gain > 0.05 ? `<span class="up">+${fmt(lu.gain)} vs your current lineup</span>` : "Your lineup is already optimal"],
  ];
  $("#tiles").innerHTML = tiles.map(([l, v, f]) => `<div class="tile"><div class="label">${esc(l)}</div><div class="value">${v}</div><div class="foot">${f}</div></div>`).join("");
  const notes = lu.notes.filter((n) => n.level !== "info").slice(0, 6);
  $("#ovNotes").innerHTML = notes.length ? notes.map((n) => `<li class="${n.level}">${esc(n.text)}</li>`).join("") : `<li class="info">Lineup looks good. Nothing to change.</li>`;
  $("#ovAlerts").innerHTML = alertItems(d.alerts.slice(0, 5)) || `<li class="p4">No alerts yet. Run a check from the Alerts tab.</li>`;
  $("#ovWaivers").innerHTML = d.trade.waivers.slice(0, 5).map((w) => `<div class="list-row"><div><span class="pname">${esc(w.name)}</span> <span class="pmeta">${w.position} · ${w.nfl_team}</span> ${statusBadge(w.status)}
     <div class="why">${w.trending ? `Added in ${w.trending.toLocaleString()} leagues · ` : ""}last 3: ${fmt(w.last3_avg)} · proj ${fmt(w.projection)}</div></div>
     <div class="num">${w.upgrade > 0 ? `<span class="up">+${fmt(w.upgrade)}</span>` : ""}</div></div>`).join("") || `<p class="empty">No standout pickups right now.</p>`;
  $("#standings").innerHTML = `<table class="table"><tr><th>#</th><th>Team</th><th class="num">W-L</th><th class="num">PF</th></tr>${d.standings.map((s) =>
    `<tr class="${s.is_mine ? "mine" : ""}"><td>${s.rank ?? ""}</td><td>${esc(s.name)}</td><td class="num">${s.wins}-${s.losses}${s.ties ? "-" + s.ties : ""}</td><td class="num">${fmt(s.points_for)}</td></tr>`).join("")}</table>`;
  weeklyChart("ovChart");
}

function alertItems(list) {
  return list.map((a) => `<li class="p${a.priority}"><b>${esc(a.title)}</b> <span class="when">${new Date(a.created_at * 1000).toLocaleString()}</span><div class="msg">${esc(a.message)}</div></li>`).join("");
}

/* --------------------------------------------------------------- charts */
function baseOptions(extra = {}) {
  const grid = css("--grid"), muted = css("--muted"), ink = css("--ink-2");
  Chart.defaults.font.family = css("--font") || "Inter, system-ui, sans-serif";
  return {
    responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { labels: { color: ink, usePointStyle: true, boxWidth: 8, boxHeight: 8 } },
      tooltip: { backgroundColor: css("--surface-3"), titleColor: css("--ink"), bodyColor: ink, borderColor: css("--axis"), borderWidth: 1, padding: 10, usePointStyle: true },
    },
    scales: {
      x: { grid: { display: false }, ticks: { color: muted }, border: { color: css("--axis") } },
      y: { grid: { color: grid }, ticks: { color: muted }, border: { display: false }, beginAtZero: true },
    },
    ...extra,
  };
}
function draw(id, config) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(document.getElementById(id), config);
}
function weeklyChart(id) {
  const ms = DATA.matchups.filter((m) => m.points !== null && m.points !== undefined && (m.status === "postevent" || m.points > 0));
  draw(id, {
    type: "line",
    data: {
      labels: ms.map((m) => `Wk ${m.week}`),
      datasets: [
        { label: "You", data: ms.map((m) => m.points), borderColor: css("--s1"), backgroundColor: css("--s1"), borderWidth: 2, pointRadius: 4, tension: 0.25 },
        { label: "Opponent", data: ms.map((m) => m.opp_points), borderColor: css("--s2"), backgroundColor: css("--s2"), borderWidth: 2, pointRadius: 4, tension: 0.25 },
        { label: "Your projection", data: ms.map((m) => m.projected), borderColor: css("--muted"), backgroundColor: css("--muted"), borderWidth: 2, borderDash: [5, 4], pointRadius: 0, tension: 0.25 },
      ],
    },
    options: baseOptions({ plugins: { ...baseOptions().plugins, tooltip: { ...baseOptions().plugins.tooltip,
      callbacks: { afterTitle: (items) => { const m = ms[items[0].dataIndex]; return m.opp_name ? `vs ${m.opp_name}` : ""; } } } } }),
  });
}
function renderTrends() {
  weeklyChart("trendChart");
  const wb = DATA.weekly_breakdown.filter((w) => w.week < DATA.league.current_week || w.started > 0);
  const seriesVars = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6"];
  draw("posChart", {
    type: "bar",
    data: { labels: wb.map((w) => `Wk ${w.week}`),
      datasets: POS_ORDER.map((pos, i) => ({ label: pos, data: wb.map((w) => w.by_position[pos] || 0), backgroundColor: css(seriesVars[i]),
        borderColor: css("--surface"), borderWidth: { top: 2 }, borderRadius: 2, maxBarThickness: 36 })) },
    options: baseOptions({ scales: { x: { stacked: true, grid: { display: false }, ticks: { color: css("--muted") } }, y: { stacked: true, grid: { color: css("--grid") }, ticks: { color: css("--muted") }, border: { display: false } } } }),
  });
  draw("benchChart", {
    type: "bar",
    data: { labels: wb.map((w) => `Wk ${w.week}`), datasets: [{ label: "Points left on bench", data: wb.map((w) => w.left_on_bench), backgroundColor: css("--s2"), borderRadius: 4, maxBarThickness: 36 }] },
    options: baseOptions({ plugins: { ...baseOptions().plugins, legend: { display: false } } }),
  });
  const starters = DATA.players.filter((p) => p.recommended_slot && !["BN", "IR"].includes(p.recommended_slot) && p.position !== "K" && p.position !== "DEF");
  const weeks = []; for (let w = DATA.league.start_week || 1; w < DATA.week; w++) weeks.push(w);
  const vars = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6", "--s7", "--s8"];
  draw("playerTrendChart", {
    type: "line",
    data: { labels: weeks.map((w) => `Wk ${w}`),
      datasets: starters.slice(0, 8).map((p, i) => ({ label: p.name, data: weeks.map((w) => p.history[w] ?? null), spanGaps: false,
        borderColor: css(vars[i]), backgroundColor: css(vars[i]), borderWidth: 2, pointRadius: 3, tension: 0.2 })) },
    options: baseOptions(),
  });
}

/* --------------------------------------------------------------- lineup */
function renderLineup() {
  const lu = DATA.lineup;
  const curBy = Object.fromEntries(DATA.players.map((p) => [p.key, p.selected_position]));
  $("#lineupSummary").innerHTML = `Projected <b>${fmt(lu.total)}</b> pts · your current lineup projects ${fmt(lu.current_total)}` +
    (lu.gain > 0.05 ? ` · <span class="up">+${fmt(lu.gain)} if you apply this</span>` : "");
  const row = (slot, p) => !p ? `<tr><td><span class="slot">${esc(slot)}</span></td><td colspan="4" class="down">Empty: pick someone up</td></tr>` :
    `<tr class="click" data-key="${esc(p.key)}"><td><span class="slot">${esc(slot)}</span></td>
      <td><span class="pname">${esc(p.name)}</span> ${p.locked ? "🔒" : ""}<div class="pmeta">${p.position} · ${esc(p.nfl_team)} ${curBy[p.key] && curBy[p.key] !== slot ? `· now ${esc(curBy[p.key])}` : ""}</div></td>
      <td>${oppText(p)} ${statusBadge(p.status)}</td><td class="hide-sm pmeta">${kickoff(p.kickoff)}</td><td class="num"><b>${fmt(p.projection)}</b></td></tr>`;
  $("#lineupTable").innerHTML = `<tr><th>Slot</th><th>Player</th><th>Matchup</th><th class="hide-sm">Kickoff</th><th class="num">Proj</th></tr>` +
    lu.slots.map((s) => row(s.slot, s.player)).join("");
  $("#lineupTable").innerHTML += `<tr><th colspan="5">Bench</th></tr>` + lu.bench.map((p) => row(p.selected_position === "IR" ? "IR" : "BN", p)).join("");
  $("#lineupNotes").innerHTML = lu.notes.map((n) => `<li class="${n.level}">${esc(n.text)}</li>`).join("") || `<li class="info">Nothing to change.</li>`;
  $("#applyBtn").disabled = lu.gain <= 0.05 && !lu.notes.some((n) => n.level === "change" || n.level === "critical");
  $("#timeline").innerHTML = `<div class="timeline">${DATA.game_day.map((g) => `<div class="slotrow"><div class="time">${kickoff(g.kickoff)}</div><div>${g.players.map((p) =>
    `<div class="${p.starting ? "" : "bn"}">${p.starting ? "▶" : "·"} ${esc(p.name)} <span class="pmeta">${p.position} ${p.home ? "vs" : "@"} ${esc(p.opponent)} · ${esc(p.slot)}${p.state !== "pre" ? " · " + (p.state === "post" ? "final" : "in progress") : ""}</span></div>`).join("")}</div></div>`).join("")}</div>`;
  bindPlayerRows($("#lineupTable"));
}

/* -------------------------------------------------------------- players */
function renderPlayers() {
  const rows = DATA.players.map((p) => {
    const r = p.report;
    const trend = r.trend > 0.05 ? `<span class="up">▲ ${fmt(r.trend)}</span>` : r.trend < -0.05 ? `<span class="down">▼ ${fmt(Math.abs(r.trend))}</span>` : "–";
    return `<tr class="click" data-key="${esc(p.key)}"><td><span class="slot">${esc(p.recommended_slot || "BN")}</span></td>
      <td><span class="pname">${esc(p.name)}</span> ${statusBadge(p.status)}<div class="pmeta">${p.position} · ${esc(p.nfl_team)} · bye ${p.bye_week ?? "–"}</div></td>
      <td>${oppText(p)}</td><td class="num"><b>${fmt(r.projection)}</b></td><td class="num">${fmt(r.last3_avg)}</td><td class="num">${fmt(r.season_avg)}</td>
      <td class="num">${trend}</td><td><span class="grade ${r.matchup_grade}">${r.matchup_grade}</span></td><td>${esc(r.tier)}</td><td>${tagBadges(r.tags)}</td></tr>`;
  });
  $("#playersTable").innerHTML = `<tr><th>Rec</th><th>Player</th><th>Opp</th><th class="num">Proj</th><th class="num">Last 3</th><th class="num">Season</th><th class="num">Trend</th><th>Matchup</th><th>Verdict</th><th>Tags</th></tr>${rows.join("")}`;
  bindPlayerRows($("#playersTable"));
}
function bindPlayerRows(el) { $$("tr.click", el).forEach((tr) => (tr.onclick = () => openPlayer(tr.dataset.key))); }

async function openPlayer(key) {
  let p = DATA.players.find((x) => x.key === key);
  if (!p) { try { p = await api(`/api/player/${encodeURIComponent(key)}?week=${WEEK}`); } catch (e) { return toast(e.message); } }
  const r = p.report;
  const watched = DATA.watchlist.some((w) => w.key === key);
  $("#playerBody").innerHTML = `<h2>${esc(p.name)} ${statusBadge(p.status)}</h2>
    <div class="pmeta">${p.position} · ${esc(p.nfl_team)} · bye week ${p.bye_week ?? "–"}${p.owner ? " · " + esc(p.owner) : ""}${p.injury_note ? " · " + esc(p.injury_note) : ""}</div>
    <p>${esc(r.outlook)}</p>
    <div class="statgrid">
      <div><b>${fmt(r.projection)}</b><span>Projection</span></div><div><b>${fmt(r.last3_avg)}</b><span>Last 3 avg</span></div>
      <div><b>${fmt(r.season_avg)}</b><span>Season avg</span></div><div><b>${fmt(r.floor)}–${fmt(r.ceiling)}</b><span>Floor–ceiling</span></div>
      <div><b><span class="grade ${r.matchup_grade}">${r.matchup_grade}</span></b><span>Matchup${r.matchup_rank ? ` (#${r.matchup_rank})` : ""}</span></div>
      <div><b>${r.consistency === null ? "–" : Math.round(r.consistency * 100) + "%"}</b><span>Consistent weeks</span></div>
    </div>
    <div>${tagBadges(r.tags)}</div>
    <p><button class="small ${watched ? "ghost" : ""}" id="watchToggle">${watched ? "Remove from watchlist" : "★ Add to watchlist"}</button></p>`;
  $("#watchToggle").onclick = async () => {
    if (watched) await api(`/api/watchlist/${encodeURIComponent(key)}`, { method: "DELETE" });
    else await api("/api/watchlist", { method: "POST", body: JSON.stringify({ player_key: key, name: p.name }) });
    $("#playerDialog").close(); toast(watched ? "Removed from watchlist" : "Added to watchlist"); load(true);
  };
  $("#playerDialog").showModal();
  const weeks = Object.keys(p.history).map(Number).sort((a, b) => a - b);
  draw("playerChart", {
    type: "bar",
    data: { labels: weeks.map((w) => `Wk ${w}`), datasets: [
      { type: "bar", label: "Fantasy points", data: weeks.map((w) => p.history[w]), backgroundColor: css("--s1"), borderRadius: 4, maxBarThickness: 28, order: 2 },
      { type: "line", label: "Season average", data: weeks.map(() => r.season_avg), borderColor: css("--muted"), borderDash: [5, 4], borderWidth: 2, pointRadius: 0, order: 1 },
    ] },
    options: baseOptions(),
  });
}

/* --------------------------------------------------------------- trades */
function playerChip(p) { return `<div><span class="pname">${esc(p.name)}</span> ${statusBadge(p.status)}<div class="pmeta">${p.position} · ${esc(p.nfl_team)} · value ${fmt(p.value)}</div></div>`; }
function renderTrades() {
  const t = DATA.trade;
  const max = Math.max(...t.needs.map((n) => Math.max(n.mine, n.league_avg)), 1);
  $("#needs").innerHTML = t.needs.slice().sort((a, b) => POS_ORDER.indexOf(a.position) - POS_ORDER.indexOf(b.position)).map((n) =>
    `<div class="need"><b>${n.position}</b><div class="bar" title="You ${fmt(n.mine)} vs league avg ${fmt(n.league_avg)}"><div class="mine" style="width:${(n.mine / max) * 100}%"></div><div class="avg" style="left:${(n.league_avg / max) * 100}%"></div></div>
     <div class="num ${n.delta >= 0 ? "up" : "down"}">${n.delta >= 0 ? "+" : ""}${fmt(n.delta)} · #${n.rank}</div></div>`).join("") +
    `<p class="sub">Bar = your starters' weekly value, line = league average, #rank among ${DATA.standings.length} teams.</p>`;
  $("#proposals").innerHTML = t.proposals.map((p) => `<div class="trade"><div class="pmeta">with ${esc(p.team)}</div>
    <div class="swap"><div><div class="pmeta">You give</div>${playerChip(p.give)}</div><div class="arrow">⇄</div><div><div class="pmeta">You get</div>${playerChip(p.get)}</div></div>
    <div><span class="gain">+${fmt(p.my_gain)} pts/wk</span> <span class="pmeta">for you · ${p.their_gain >= 0 ? "+" : ""}${fmt(p.their_gain)} for them</span></div>
    <div class="why pmeta">${esc(p.pitch)}</div></div>`).join("") || `<p class="empty">No trades found that clearly help both sides. Check back after this week's games.</p>`;
  const lst = (arr, extra) => arr.map((x) => `<div class="list-row click" data-key="${esc(x.key)}"><div><span class="pname">${esc(x.name)}</span> <span class="pmeta">${x.position} · ${esc(x.nfl_team)}${extra(x)}</span><div class="why">${esc(x.reason)}</div></div></div>`).join("");
  $("#buyLow").innerHTML = lst(t.buy_low, (x) => ` · ${esc(x.team)}`) || `<p class="empty">No buy-low candidates this week.</p>`;
  $("#sellHigh").innerHTML = lst(t.sell_high, () => "") || `<p class="empty">Nobody on your roster is clearly overperforming.</p>`;
  $$(".list-row.click").forEach((el) => (el.onclick = () => openPlayer(el.dataset.key)));
  $("#waiverTable").innerHTML = `<tr><th>Player</th><th class="num">Proj</th><th class="num">Last 3</th><th class="num">Trending</th><th class="num">Upgrade</th><th></th></tr>` +
    t.waivers.map((w) => `<tr class="click" data-key="${esc(w.key)}"><td><span class="pname">${esc(w.name)}</span> ${statusBadge(w.status)}<div class="pmeta">${w.position} · ${esc(w.nfl_team)}</div></td>
      <td class="num">${fmt(w.projection)}</td><td class="num">${fmt(w.last3_avg)}</td><td class="num">${w.trending ? "+" + w.trending.toLocaleString() : "–"}</td>
      <td class="num">${w.upgrade > 0 ? `<span class="up">+${fmt(w.upgrade)}</span>` : `<span class="pmeta">${fmt(w.upgrade)}</span>`}</td>
      <td>${w.fills_need ? '<span class="badge good">Fills need</span>' : ""}</td></tr>`).join("");
  bindPlayerRows($("#waiverTable"));
  $("#watchlist").innerHTML = DATA.watchlist.map((w) => w.missing ? `<div class="list-row"><span>${esc(w.name)} <span class="pmeta">(no longer found)</span></span></div>` :
    `<div class="list-row click" data-key="${esc(w.key)}"><div><span class="pname">${esc(w.name)}</span> ${statusBadge(w.status)} <span class="pmeta">${w.position} · ${esc(w.nfl_team)} · ${esc(w.owner)}</span>
      <div class="why">proj ${fmt(w.projection)} · last 3 ${fmt(w.last3_avg)} · season ${fmt(w.season_avg)}${w.trending ? ` · +${w.trending.toLocaleString()} adds` : ""}</div></div></div>`).join("") ||
    `<p class="empty">Open any player and tap "Add to watchlist" to track him.</p>`;
  $$("#watchlist .list-row.click").forEach((el) => (el.onclick = () => openPlayer(el.dataset.key)));
}

/* ----------------------------------------------------------------- byes */
function renderByes() {
  $("#byeGrid").innerHTML = DATA.bye_planner.map((b) => `<div class="bye-week ${b.holes.length ? "hole" : ""}"><h3>Week ${b.week}</h3>
    ${b.on_bye.length ? b.on_bye.map((p) => `<div>${esc(p.name)} <span class="pmeta">${p.position} · ${esc(p.nfl_team)}</span></div>`).join("") : `<div class="empty">Nobody on bye</div>`}
    ${b.holes.length ? `<p class="down"><b>Can't fill: ${b.holes.map(esc).join(", ")}</b></p>` : ""}
    <p class="pmeta">Projected lineup strength ${fmt(b.projected_strength)}</p></div>`).join("");
}

/* --------------------------------------------------------------- alerts */
function renderAlerts() {
  $("#alertList").innerHTML = alertItems(DATA.alerts) || `<li class="p4">No alerts yet.</li>`;
  const ch = STATUS_INFO.channels;
  $("#channelInfo").textContent = (ch.length ? `Sending to: ${ch.join(", ")}. ` : "No notification channels configured yet (add ntfy, Discord, Slack or email in .env). ") +
    (STATUS_INFO.monitor_minutes > 0 ? `Automatic check every ${STATUS_INFO.monitor_minutes} minutes while the app runs.` : "Automatic checks are off.");
  $("#testNotifyBtn").disabled = !ch.length;
  if (!STATUS_INFO.demo) loadLeagues();
}
async function loadLeagues() {
  try {
    const leagues = await api("/api/leagues");
    $("#leagueCard").hidden = false;
    $("#leagueSelect").innerHTML = leagues.map((l) => `<option value="${esc(l.league_key)}" ${l.league_key === DATA.league.league_key ? "selected" : ""}>${esc(l.name)} (${esc(l.season)})</option>`).join("");
  } catch (_) {}
}

/* ---------------------------------------------------------------- wiring */
$$("#tabs button").forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));
$$("[data-goto]").forEach((b) => (b.onclick = () => showTab(b.dataset.goto)));
function showTab(name) {
  $$("#tabs button").forEach((x) => x.classList.toggle("active", x.dataset.tab === name));
  $$(".panel").forEach((p) => p.classList.toggle("active", p.dataset.panel === name));
  Object.values(charts).forEach((c) => c.resize());
  try { localStorage.setItem("tab", name); } catch (_) {}
}
$("#weekSelect").onchange = (e) => { WEEK = Number(e.target.value); load(); };
$("#refreshBtn").onclick = () => load(true);
$("#applyBtn").onclick = async () => {
  if (!confirm("Set your Yahoo lineup to the recommended lineup?")) return;
  $("#applyBtn").disabled = true;
  try { const r = await api("/api/lineup/apply", { method: "POST", body: JSON.stringify({ week: WEEK }) }); toast(`Lineup saved (${r.moved} players set).`); await load(true); }
  catch (e) { toast(e.message); $("#applyBtn").disabled = false; }
};
$("#checkBtn").onclick = async () => {
  $("#checkBtn").disabled = true;
  try { const r = await api("/api/check", { method: "POST" }); toast(`${r.new_alerts} new alert(s)${r.channels.length ? `, sent to ${r.channels.join(", ")}` : ""}.`); await load(true); }
  catch (e) { toast(e.message); } finally { $("#checkBtn").disabled = false; }
};
$("#testNotifyBtn").onclick = async () => {
  try { const r = await api("/api/notify/test", { method: "POST" }); toast(Object.entries(r).map(([k, v]) => `${k}: ${v}`).join(" · ")); }
  catch (e) { toast(e.message); }
};
$("#leagueSelect").onchange = async (e) => { await api("/api/league", { method: "POST", body: JSON.stringify({ league_key: e.target.value }) }); WEEK = null; load(true); };
$("#logoutBtn").onclick = async () => { await api("/api/auth/logout", { method: "POST" }); location.reload(); };
/* ---------------------------------------------------------------- styles */
const STYLE_FONTS = {
  turf: "Barlow:wght@400;500;600;700&family=Barlow+Condensed:wght@600;700",
  primetime: "Oswald:wght@500;600;700",
  scoreboard: "JetBrains+Mono:wght@400;500;700",
  aurora: "Plus+Jakarta+Sans:wght@400;500;600;700;800",
};
function setStyle(name, save = true) {
  name = name || "midnight";
  document.documentElement.setAttribute("data-style", name);
  $("#styleSelect").value = name;
  const fam = STYLE_FONTS[name];
  if (fam && !document.querySelector(`link[data-font="${name}"]`)) {
    const l = document.createElement("link");
    l.rel = "stylesheet"; l.dataset.font = name;
    l.href = `https://fonts.googleapis.com/css2?family=${fam}&display=swap`;
    l.onload = () => DATA && render();
    document.head.appendChild(l);
  }
  if (save) { try { localStorage.setItem("style", name); } catch (_) {} }
  if (DATA) render();
}
$("#styleSelect").onchange = (e) => setStyle(e.target.value);
setStyle(document.documentElement.getAttribute("data-style"), false);
try { const t = localStorage.getItem("tab"); if (t) showTab(t); } catch (_) {}
boot();
