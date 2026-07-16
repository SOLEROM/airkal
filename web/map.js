// Top-down NED map: north up, east right. True positions for every drone,
// plus the selected observer's *predicted* peers with 1σ/2σ circles.
"use strict";

const MAP_COLORS = ["#4fb3ff", "#38c172", "#e3a008", "#e06c6c",
                    "#b57bff", "#4fd6c2", "#ff9d5c", "#9aa7ff"];

function droneColor(id) {
  return MAP_COLORS[(Number(id) - 1 + MAP_COLORS.length) % MAP_COLORS.length];
}

function drawMap(canvas, fleet, observerId) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  const pts = [];
  for (const tel of Object.values(fleet)) pts.push([tel.p[0], tel.p[1]]);
  const observer = fleet[observerId];
  if (observer) {
    for (const est of Object.values(observer.peers || {})) {
      pts.push([est.p_hat[0], est.p_hat[1]]);
    }
  }

  // world→screen: keep aspect, min 120 m span, x(N)→up, y(E)→right
  let cx = 0, cy = 0, span = 120;
  if (pts.length) {
    const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
    cx = (Math.min(...xs) + Math.max(...xs)) / 2;
    cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    span = Math.max(120, (Math.max(...xs) - Math.min(...xs)) * 1.4,
                    (Math.max(...ys) - Math.min(...ys)) * 1.4);
  }
  const scale = Math.min(w, h) / span;
  const sx = (n, e) => w / 2 + (e - cy) * scale;
  const sy = (n, e) => h / 2 - (n - cx) * scale;

  // grid every 20 m
  ctx.strokeStyle = "#1c2634";
  ctx.fillStyle = "#4a5a70";
  ctx.font = "10px ui-monospace, monospace";
  ctx.lineWidth = 1;
  const grid = 20;
  const nMin = cx - span / 2, nMax = cx + span / 2;
  const eMin = cy - span / 2, eMax = cy + span / 2;
  for (let n = Math.ceil(nMin / grid) * grid; n <= nMax; n += grid) {
    ctx.beginPath();
    ctx.moveTo(sx(n, eMin), sy(n, eMin));
    ctx.lineTo(sx(n, eMax), sy(n, eMax));
    ctx.stroke();
    ctx.fillText(n.toFixed(0), 4, sy(n, 0) - 2);
  }
  for (let e = Math.ceil(eMin / grid) * grid; e <= eMax; e += grid) {
    ctx.beginPath();
    ctx.moveTo(sx(nMin, e), sy(nMin, e));
    ctx.lineTo(sx(nMax, e), sy(nMax, e));
    ctx.stroke();
  }

  // observer's predictions of its peers: ✕ + σ circles
  if (observer) {
    for (const [pid, est] of Object.entries(observer.peers || {})) {
      const x = sx(est.p_hat[0], est.p_hat[1]);
      const y = sy(est.p_hat[0], est.p_hat[1]);
      const color = droneColor(pid);
      for (const k of [1, 2]) {
        ctx.beginPath();
        ctx.strokeStyle = color + (k === 1 ? "90" : "45");
        ctx.lineWidth = 1.2;
        ctx.arc(x, y, Math.max(2, est.sigma * k * scale), 0, 2 * Math.PI);
        ctx.stroke();
      }
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.6;
      const r = 5;
      ctx.beginPath();
      ctx.moveTo(x - r, y - r); ctx.lineTo(x + r, y + r);
      ctx.moveTo(x - r, y + r); ctx.lineTo(x + r, y - r);
      ctx.stroke();
    }
  }

  // true positions on top
  for (const [id, tel] of Object.entries(fleet)) {
    const x = sx(tel.p[0], tel.p[1]), y = sy(tel.p[0], tel.p[1]);
    ctx.fillStyle = droneColor(id);
    ctx.beginPath();
    ctx.arc(x, y, id === String(observerId) ? 6 : 4.5, 0, 2 * Math.PI);
    ctx.fill();
    ctx.fillStyle = "#dbe4ee";
    ctx.font = "11px ui-monospace, monospace";
    ctx.fillText(id, x + 7, y - 7);
  }
}
