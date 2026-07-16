"""HTTP/WebSocket API and static web page for the C2 server (aiohttp).

Consistent response envelope: {"ok": bool, "data": …, "error": …}.
All inputs validated; a light per-client rate limit guards the POST
endpoints (LAN demo, not an internet-facing service).
"""

import asyncio
import json
import logging
import re
import time
from pathlib import Path

from aiohttp import WSMsgType, web

log = logging.getLogger("c2.api")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
DESIGN_DIR = Path(__file__).resolve().parent.parent / "design"
RATE_LIMIT_PER_S = 20.0
RATE_LIMIT_BURST = 40.0

# One plain path segment ending in .md; no dotfiles, and the resolve() check
# below is the real traversal guard.
_DESIGN_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.md$")

def _strip_frontmatter(text: str) -> str:
    """Drop a leading YAML frontmatter block (--- … ---) if present."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() in ("---", "..."):
            return "".join(lines[i + 1:]).lstrip("\n")
    return text

def _page_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback

def _read_design_page(path: Path) -> dict:
    markdown = _strip_frontmatter(path.read_text("utf-8"))
    return {"file": path.name,
            "title": _page_title(markdown, path.stem),
            "markdown": markdown}

def _inside(path: Path, root: Path) -> Path | None:
    """Resolved path if it stays under root (symlink/traversal guard)."""
    try:
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    return resolved

def _list_design_pages(design_dir: Path) -> list[dict]:
    if not design_dir.is_dir():
        return []
    pages = []
    for path in sorted(design_dir.glob("*.md")):
        if not _DESIGN_NAME_RE.match(path.name) or not _inside(path, design_dir):
            continue
        page = _read_design_page(path)
        pages.append({"file": page["file"], "title": page["title"]})
    return pages

def ok(data) -> web.Response:
    return web.json_response({"ok": True, "data": data, "error": None})

def fail(status: int, error: str) -> web.Response:
    return web.json_response({"ok": False, "data": None, "error": error},
                             status=status)

class _Buckets:
    """Token bucket per remote address."""

    def __init__(self, rate: float, burst: float):
        self._rate, self._burst = rate, burst
        self._buckets: dict[str, tuple[float, float]] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        level, last = self._buckets.get(key, (self._burst, now))
        level = min(self._burst, level + (now - last) * self._rate)
        if level < 1.0:
            self._buckets[key] = (level, now)
            return False
        self._buckets[key] = (level - 1.0, now)
        return True

@web.middleware
async def _envelope_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception:
        log.exception("unhandled error on %s %s", request.method, request.path)
        return fail(500, "internal error")

async def _json_body(request: web.Request) -> dict:
    # Requiring the JSON content type forces a CORS preflight, which defeats
    # cross-site form POSTs (text/plain CSRF) against the command endpoints.
    if request.content_type != "application/json":
        raise web.HTTPBadRequest(text="Content-Type must be application/json")
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text="body must be JSON")
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="body must be a JSON object")
    return body

def _parse_target(body: dict):
    target = body.get("target", "all")
    if target == "all":
        return target
    if isinstance(target, int) and not isinstance(target, bool) and target >= 1:
        return target
    raise web.HTTPBadRequest(text='"target" must be "all" or a drone id >= 1')

def build_app(store, fanout, design_dir: Path = DESIGN_DIR) -> web.Application:
    """store: FleetStore-like (fleet(), stats(), errors(), register_ws(),
    unregister_ws()); fanout: CmdFanout; design_dir: markdown docs folder."""
    app = web.Application(middlewares=[_envelope_middleware])
    buckets = _Buckets(RATE_LIMIT_PER_S, RATE_LIMIT_BURST)

    def limited(request: web.Request) -> None:
        if not buckets.allow(request.remote or "?"):
            raise web.HTTPTooManyRequests(text="rate limit exceeded")

    async def post_rate(request: web.Request) -> web.Response:
        limited(request)
        body = await _json_body(request)
        target = _parse_target(body)
        hz = body.get("hz")
        if not isinstance(hz, (int, float)) or isinstance(hz, bool) \
                or not (0.0 <= float(hz) <= 100.0):
            return fail(400, '"hz" must be a number in [0, 100]')
        sent = fanout.send_rate(target, float(hz))
        log.info("rate command: target=%s hz=%s", target, hz)
        return ok({"sent": sent})

    async def post_pattern(request: web.Request) -> web.Response:
        limited(request)
        body = await _json_body(request)
        target = _parse_target(body)
        action = body.get("action")
        if action not in ("start", "stop", "land"):
            return fail(400, '"action" must be start | stop | land')
        sent = fanout.send_pattern(target, action)
        log.info("pattern command: target=%s action=%s", target, action)
        return ok({"sent": sent})

    async def get_fleet(request: web.Request) -> web.Response:
        return ok(store.fleet())

    async def get_stats(request: web.Request) -> web.Response:
        return ok({"stats": store.stats(), "errors": store.errors()})

    async def get_design_index(request: web.Request) -> web.Response:
        pages = await asyncio.to_thread(_list_design_pages, design_dir)
        return ok({"pages": pages})

    async def get_design_page(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        if not _DESIGN_NAME_RE.match(name):
            return fail(400, "invalid page name")

        def load() -> dict | str:
            path = _inside(design_dir / name, design_dir)
            if path is None:
                return "invalid"
            if not path.is_file():
                return "missing"
            return _read_design_page(path)

        page = await asyncio.to_thread(load)
        if page == "invalid":
            return fail(400, "invalid page name")
        if page == "missing":
            return fail(404, "no such page")
        return ok(page)

    async def websocket(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20.0)
        await ws.prepare(request)
        store.register_ws(ws)
        try:
            async for message in ws:      # inbound messages are ignored
                if message.type == WSMsgType.ERROR:
                    break
        finally:
            store.unregister_ws(ws)
        return ws

    async def index(request: web.Request) -> web.FileResponse:
        return web.FileResponse(WEB_DIR / "index.html")

    app.router.add_post("/api/rate", post_rate)
    app.router.add_post("/api/pattern", post_pattern)
    app.router.add_get("/api/fleet", get_fleet)
    app.router.add_get("/api/stats", get_stats)
    app.router.add_get("/api/design", get_design_index)
    app.router.add_get("/api/design/{name}", get_design_page)
    app.router.add_get("/ws", websocket)
    app.router.add_get("/", index)
    app.router.add_static("/", WEB_DIR)
    return app
