// Minimal multi-series strip chart on a canvas. No dependencies.
"use strict";

const CHART_COLORS = ["#4fb3ff", "#38c172", "#e3a008", "#e06c6c",
                      "#b57bff", "#4fd6c2", "#ff9d5c", "#9aa7ff"];

class StripChart {
  constructor(canvas, { windowS = 180, unit = "" } = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.windowS = windowS;
    this.unit = unit;
    this.series = new Map();   // name -> [{t, v}]
    this.colors = new Map();
  }

  addSample(t, values) {
    for (const [name, v] of Object.entries(values)) {
      if (!Number.isFinite(v)) continue;
      if (!this.series.has(name)) {
        this.series.set(name, []);
        this.colors.set(name,
          CHART_COLORS[this.colors.size % CHART_COLORS.length]);
      }
      const buf = this.series.get(name);
      buf.push({ t, v });
      while (buf.length && buf[0].t < t - this.windowS) buf.shift();
    }
  }

  draw() {
    const { ctx, canvas } = this;
    const w = canvas.width, h = canvas.height;
    const padL = 56, padR = 8, padT = 8, padB = 18;
    ctx.clearRect(0, 0, w, h);
    if (!this.series.size) return;

    let tMax = -Infinity, vMax = 0;
    for (const buf of this.series.values()) {
      if (buf.length) tMax = Math.max(tMax, buf[buf.length - 1].t);
      for (const s of buf) vMax = Math.max(vMax, s.v);
    }
    if (!Number.isFinite(tMax)) return;
    vMax = vMax * 1.15 || 1;
    const tMin = tMax - this.windowS;

    const px = (t) => padL + (w - padL - padR) * (t - tMin) / this.windowS;
    const py = (v) => padT + (h - padT - padB) * (1 - v / vMax);

    ctx.strokeStyle = "#263143";
    ctx.fillStyle = "#7f8fa3";
    ctx.font = "11px ui-monospace, monospace";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const v = vMax * i / 4, y = py(v);
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
      ctx.fillText(fmtVal(v) + this.unit, 4, y + 4);
    }

    for (const [name, buf] of this.series) {
      if (buf.length < 2) continue;
      ctx.strokeStyle = this.colors.get(name);
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      buf.forEach((s, i) => {
        const x = px(s.t), y = py(s.v);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }

    let lx = padL + 6;
    for (const [name] of this.series) {
      ctx.fillStyle = this.colors.get(name);
      ctx.fillText("— " + name, lx, h - 5);
      lx += ctx.measureText("— " + name).width + 16;
    }
  }
}

function fmtVal(v) {
  if (v >= 10000) return (v / 1000).toFixed(0) + "k";
  if (v >= 100) return v.toFixed(0);
  return v.toFixed(1);
}
