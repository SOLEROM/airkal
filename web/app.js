// Page wiring: WebSocket ingest, fleet table, controls, map + chart refresh.
// All dynamic text goes through textContent — no HTML injection paths.
"use strict";

const state = {
  fleet: {},
  errors: {},
  stats: null,
  lastStatsT: 0,
  lastErrT: 0,
  observer: null,
};

const bwChart = new StripChart(document.getElementById("chart-bw"),
                               { windowS: 180, unit: " B/s" });
const errChart = new StripChart(document.getElementById("chart-err"),
                                { windowS: 180, unit: " m" });
const mapCanvas = document.getElementById("map");
const connBadge = document.getElementById("conn");
const dockerBadge = document.getElementById("docker");

// ── WebSocket ────────────────────────────────────────────────────────────────

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => {
    connBadge.textContent = "live";
    connBadge.className = "badge on";
  };
  ws.onclose = () => {
    connBadge.textContent = "disconnected";
    connBadge.className = "badge off";
    renderDockerBadge(null);
    setTimeout(connect, 1000);
  };
  ws.onmessage = (event) => {
    let snap;
    try { snap = JSON.parse(event.data); } catch { return; }
    ingest(snap);
  };
}

function ingest(snap) {
  state.fleet = snap.fleet || {};
  state.errors = snap.errors || {};
  state.stats = snap.stats;
  renderDockerBadge(snap.docker);

  if (snap.stats && snap.stats.t > state.lastStatsT) {
    state.lastStatsT = snap.stats.t;
    const perChannel = {};
    for (const [name, chan] of Object.entries(snap.stats.channels || {})) {
      // EMA sum: smooth at sub-Hz share rates where the 1 s window is spiky
      perChannel[name] = Object.values(chan.senders || {})
        .reduce((acc, s) => acc + s.ema_bytes_s, 0);
    }
    bwChart.addSample(snap.stats.t, perChannel);
  }
  if (snap.t > state.lastErrT + 0.5) {   // sample pair errors at ~2 Hz
    state.lastErrT = snap.t;
    const perPair = {};
    for (const [pair, e] of Object.entries(state.errors)) {
      perPair[pair] = e.err;
    }
    if (Object.keys(perPair).length) errChart.addSample(snap.t, perPair);
  }
  render();
}

// ── rendering ────────────────────────────────────────────────────────────────

// SITL docker containers seen by the C2 host, next to the conn badge.
function renderDockerBadge(docker) {
  if (!docker || !docker.available) {
    dockerBadge.textContent = "px4-sitl —";
    dockerBadge.className = "badge na";
    dockerBadge.title = docker
      ? "docker unavailable on the C2 host"
      : "no data — waiting for C2 snapshot";
    return;
  }
  const count = docker.count;
  dockerBadge.textContent = count > 0
    ? `live: ${count} px4-sitl running` : "no px4-sitl running";
  dockerBadge.className = "badge " + (count > 0 ? "on" : "off");
  dockerBadge.title = count > 0
    ? (docker.containers || []).map(c => `${c.name}: ${c.status}`).join("\n")
    : "no SITL containers running — make up";
}

function td(text, cls) {
  const cell = document.createElement("td");
  cell.textContent = text;
  if (cls) cell.className = cls;
  return cell;
}

function stateChannelRate(id) {
  const chan = state.stats && state.stats.channels
    && state.stats.channels.state;
  const per = chan && chan.senders && chan.senders[id];
  return per ? per.msgs_1s.toFixed(1) : "—";
}

function renderFleetTable() {
  const tbody = document.querySelector("#fleet-table tbody");
  tbody.replaceChildren();
  for (const [id, tel] of Object.entries(state.fleet)) {
    const row = document.createElement("tr");
    row.appendChild(td(id));
    row.appendChild(td(tel.mode));
    row.appendChild(td(tel.phase || ""));
    row.appendChild(td(tel.armed ? "armed" : "disarmed",
                       tel.armed ? "armed-yes" : "armed-no"));
    row.appendChild(td(tel.p.map(x => x.toFixed(1)).join(", "), "num"));
    row.appendChild(td(`${tel.rate_cmd.toFixed(1)} → ${tel.rate_applied.toFixed(1)} Hz`,
                       "num"));
    row.appendChild(td(stateChannelRate(id), "num"));
    row.appendChild(td(String(tel.counters.tx_msgs), "num"));
    row.appendChild(td(tel.age.toFixed(1) + " s", "num"));
    tbody.appendChild(row);
  }
}

function renderSelectors() {
  const ids = Object.keys(state.fleet);
  for (const selId of ["observer-id", "override-id"]) {
    const sel = document.getElementById(selId);
    const current = sel.value;
    const want = ids.join(",");
    if (sel.dataset.ids === want) continue;
    sel.dataset.ids = want;
    sel.replaceChildren();
    for (const id of ids) {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = "drone " + id;
      sel.appendChild(opt);
    }
    if (ids.includes(current)) sel.value = current;
  }
  state.observer = document.getElementById("observer-id").value || null;
}

function render() {
  renderSelectors();
  renderFleetTable();
  drawMap(mapCanvas, state.fleet, state.observer);
  bwChart.draw();
  errChart.draw();
}

// ── controls ─────────────────────────────────────────────────────────────────

async function post(path, body) {
  const status = document.getElementById("cmd-status");
  try {
    const resp = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const parsed = await resp.json();
    status.textContent = parsed.ok
      ? `ok: ${path} ${JSON.stringify(body)}`
      : `error: ${parsed.error}`;
  } catch (err) {
    status.textContent = "request failed: " + err;
  }
}

// slider is log-scaled over [0.1, 10] Hz
function sliderToHz(pos) {
  const lo = Math.log10(0.1), hi = Math.log10(10);
  return Math.pow(10, lo + (hi - lo) * pos / 100);
}

const slider = document.getElementById("rate-slider");
const rateValue = document.getElementById("rate-value");
let sliderTimer = null;
slider.addEventListener("input", () => {
  const hz = sliderToHz(Number(slider.value));
  rateValue.textContent = hz.toFixed(hz < 1 ? 2 : 1) + " Hz";
  clearTimeout(sliderTimer);
  sliderTimer = setTimeout(
    () => post("/api/rate", { target: "all", hz: Number(hz.toFixed(2)) }), 250);
});

document.getElementById("rate-pause").addEventListener("click",
  () => post("/api/rate", { target: "all", hz: 0 }));

document.getElementById("override-apply").addEventListener("click", () => {
  const id = Number(document.getElementById("override-id").value);
  const hz = Number(document.getElementById("override-hz").value);
  if (Number.isInteger(id) && id >= 1 && Number.isFinite(hz) && hz >= 0) {
    post("/api/rate", { target: id, hz });
  }
});

for (const action of ["start", "stop", "land"]) {
  document.getElementById("pattern-" + action).addEventListener("click",
    () => post("/api/pattern", { target: "all", action }));
}

connect();
