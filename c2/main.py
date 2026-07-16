"""C2 — command & control server.

    python -m c2.main [--port 8080]

Listens on the telemetry and stats channels (observer only — killing C2 never
affects flight or peer tracking), keeps last-known fleet state in memory,
computes pairwise prediction errors, fans out commands over UDP, serves the
web page and pushes snapshots over WebSocket at ~5 Hz.
"""

import argparse
import asyncio
import json
import logging
import time

from aiohttp import web

from c2.api import build_app
from c2.dockerwatch import DockerWatch
from c2.errors import ErrorTracker
from c2.fanout import CmdFanout
from common import config, msg, udpbus

log = logging.getLogger("c2")

FLEET_STALE_S = 10.0
WS_PUSH_HZ = 5.0

class FleetStore:
    def __init__(self, docker: DockerWatch | None = None):
        self._fleet: dict[int, dict] = {}
        self._stats: dict | None = None
        self._stats_seen = 0.0
        self._errors = ErrorTracker()
        self._docker = docker
        self._clients: set[web.WebSocketResponse] = set()
        self.malformed = 0

    # ── UDP ingest ───────────────────────────────────────────────────────────

    def on_telemetry_datagram(self, data: bytes, addr: tuple) -> None:
        try:
            tel = msg.decode(data)
        except msg.MsgError:
            self.malformed += 1
            return
        if tel["ch"] != "telemetry":
            return
        self._fleet[tel["id"]] = dict(tel, seen=time.time())
        self._errors.on_telemetry(tel)

    def on_stats_datagram(self, data: bytes, addr: tuple) -> None:
        try:
            parsed = msg.decode(data)
        except msg.MsgError:
            self.malformed += 1
            return
        if parsed["ch"] != "stats":
            return
        self._stats = parsed
        self._stats_seen = time.time()

    # ── snapshots for API/WS ─────────────────────────────────────────────────

    def fleet(self) -> dict:
        now = time.time()
        return {str(drone_id): dict(tel, age=round(now - tel["seen"], 2))
                for drone_id, tel in sorted(self._fleet.items())
                if now - tel["seen"] < FLEET_STALE_S}

    def stats(self) -> dict | None:
        if self._stats is None or time.time() - self._stats_seen > FLEET_STALE_S:
            return None
        return self._stats

    def errors(self) -> dict:
        return self._errors.snapshot()

    def snapshot(self) -> dict:
        return {"t": time.time(), "fleet": self.fleet(),
                "stats": self.stats(), "errors": self.errors(),
                "docker": self._docker.snapshot() if self._docker else None}

    # ── WebSocket clients ────────────────────────────────────────────────────

    def register_ws(self, ws) -> None:
        self._clients.add(ws)

    def unregister_ws(self, ws) -> None:
        self._clients.discard(ws)

    async def push_loop(self) -> None:
        period = 1.0 / WS_PUSH_HZ
        while True:
            await asyncio.sleep(period)
            if not self._clients:
                continue
            payload = json.dumps(self.snapshot())
            for ws in list(self._clients):
                try:
                    await ws.send_str(payload)
                except (ConnectionError, RuntimeError):
                    self.unregister_ws(ws)

async def run(port: int) -> None:
    docker = DockerWatch()
    store = FleetStore(docker=docker)
    fanout = CmdFanout()
    rx_tel = await udpbus.open_rx(config.PORT_TELEMETRY,
                                  store.on_telemetry_datagram)
    rx_stats = await udpbus.open_rx(config.PORT_STATS,
                                    store.on_stats_datagram)
    app = build_app(store, fanout)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    log.info("serving http://localhost:%d (web page + API + /ws)", port)
    docker_task = asyncio.create_task(docker.poll_loop())
    try:
        await store.push_loop()
    finally:
        docker_task.cancel()
        rx_tel.close()
        rx_stats.close()
        fanout.close()
        await runner.cleanup()

def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="airkal C2 server")
    ap.add_argument("--port", type=int, default=config.C2_HTTP_PORT)
    args = ap.parse_args(argv)
    logging.basicConfig(
        level="INFO", format="%(asctime)s c2 %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(run(args.port))
    except KeyboardInterrupt:
        log.info("stopped")

if __name__ == "__main__":
    main()
