---
noteId: "0ac3df00813311f198c7072a98948821"
tags: []

---

# Web UI page-by-page

The front page (`web/`) is plain HTML + vanilla JS — no framework, no build
step. It opens a WebSocket to `/ws` and re-renders on every snapshot
(~5 Hz). All dynamic text goes through `textContent`, so nothing coming off
the wire can inject HTML.

## Header

- **airkal** — title and one-line subtitle.
- **sitl badge** — how many `airkal-demo` docker containers the C2 host
  sees (green = running, red = zero, gray = docker not reachable). Hover
  for per-container names and status.
- **live / disconnected badge** — WebSocket state. The page auto-reconnects
  every second while disconnected.
- **live / design tabs** — switch between the dashboard and these docs.

## Controls panel

- **fleet share rate** — a log-scaled slider over [0.1, 10] Hz that posts
  `{"target":"all","hz":…}` to `/api/rate` (debounced, 250 ms). The number
  next to it is the requested rate; the fleet table shows what each drone
  actually applied. **pause (0 Hz)** stops sharing entirely.
- **per-drone override** — pick a drone, type a rate in Hz, **set**. Lets
  you throttle one drone and compare it against the rest.
- **pattern** — `start`: arm, climb to 30 m + 5 m per drone id, fly a
  shared 40 m-radius orbit (altitude separation keeps it collision-free).
  `stop`: hold position. `land`: auto-land and disarm. The status text
  echoes the last command's result.

## Fleet table

One row per drone, from its 5 Hz telemetry:

| Column | Meaning |
|---|---|
| id | drone id (1-based) |
| mode | PX4 flight mode (e.g. OFFBOARD, AUTO.LAND) |
| phase | flight-driver phase: idle → warmup → arming → takeoff → orbit / hold / landing |
| armed | motor arm state |
| position NED [m] | own fused position (north, east, down — down is negative when flying) |
| rate cmd→applied | requested share rate → what runs after clamping to [0.1, 10] (0 = paused) |
| state msg/s | messages/s actually observed on the state channel (netstats) |
| tx msgs | cumulative state messages sent (agent's own counter) |
| seen | age of the last telemetry packet |

Rows disappear after 10 s without telemetry (stale).

## Map — top-down NED

- **Axes**: horizontal → East [m], vertical ↑ North [m]; grid every 20 m.
  Altitude (the Down component) is not shown — drones orbiting the same
  circle are separated by height.
- **● true position** — every drone's own reported position, one color per id.
- **✕ observer's prediction** — pick an *observer* drone in the dropdown;
  the crosses are where *that drone's* Kalman filters currently place its
  peers.
- **◯ 1σ / 2σ circles** — the observer's uncertainty about each peer. They
  grow between packets and snap tight on every arrival — the lower the share
  rate, the bigger the breathing.

## Charts

- **UDP bytes/s per channel** — from netstats, EMA-smoothed so sub-Hz share
  rates read as a level rather than spikes. Watch the `state` line move as
  you drag the rate slider; `telemetry` and `stats` stay constant.
- **prediction error per pair [m]** — the end-to-end error C2 measures for
  every observer→peer pair (`k→i`). Rises during orbit turns (the CV model's
  honest weakness) and as the share rate drops.

## Design tab

The tab you are probably reading this in. The C2 server lists and serves
the markdown files in `design/` (`GET /api/design`,
`GET /api/design/{file}`); the browser renders them with a small built-in
markdown renderer that builds DOM nodes directly (headings, lists, tables,
code blocks, links — no raw-HTML injection path). Links between pages open
in place; external links open in a new tab.
