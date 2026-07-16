import asyncio

from aiohttp.test_utils import TestClient, TestServer

from c2.api import build_app

class FakeStore:
    def __init__(self):
        self._fleet = {"1": {"p": [0, 0, -30], "mode": "OFFBOARD"}}
        self.ws_clients = set()

    def fleet(self):
        return self._fleet

    def stats(self):
        return {"channels": {}}

    def errors(self):
        return {}

    def register_ws(self, ws):
        self.ws_clients.add(ws)

    def unregister_ws(self, ws):
        self.ws_clients.discard(ws)

class FakeFanout:
    def __init__(self):
        self.calls = []

    def send_rate(self, target, hz):
        self.calls.append(("rate", target, hz))
        return {"target": target, "hz": hz}

    def send_pattern(self, target, action):
        self.calls.append(("pattern", target, action))
        return {"target": target, "action": action}

def with_client(test_coro):
    async def run():
        store, fanout = FakeStore(), FakeFanout()
        client = TestClient(TestServer(build_app(store, fanout)))
        await client.start_server()
        try:
            return await test_coro(client, store, fanout)
        finally:
            await client.close()
    return asyncio.run(run())

def test_post_rate_accepts_valid_and_fans_out():
    async def scenario(client, store, fanout):
        resp = await client.post("/api/rate", json={"target": "all", "hz": 1.5})
        body = await resp.json()
        assert resp.status == 200 and body["ok"]
        assert fanout.calls == [("rate", "all", 1.5)]
    with_client(scenario)

def test_post_rate_rejects_bad_inputs():
    async def scenario(client, store, fanout):
        for payload in ({"target": "all"}, {"target": "all", "hz": -1},
                        {"target": "all", "hz": 1e9}, {"target": 0, "hz": 1},
                        {"target": True, "hz": 1}):
            resp = await client.post("/api/rate", json=payload)
            assert resp.status == 400, payload
        resp = await client.post("/api/rate", data=b"not json",
                                 headers={"Content-Type": "application/json"})
        assert resp.status == 400
        assert fanout.calls == []
    with_client(scenario)

def test_post_rejects_non_json_content_type_csrf_vector():
    async def scenario(client, store, fanout):
        # text/plain form posts must be rejected (browser CSRF without preflight)
        resp = await client.post(
            "/api/pattern",
            data=b'{"target":"all","action":"land","x":"="}',
            headers={"Content-Type": "text/plain"})
        assert resp.status == 400
        assert fanout.calls == []
    with_client(scenario)

def test_post_pattern_and_get_endpoints():
    async def scenario(client, store, fanout):
        resp = await client.post("/api/pattern",
                                 json={"target": 2, "action": "start"})
        assert (await resp.json())["ok"]
        assert fanout.calls == [("pattern", 2, "start")]
        resp = await client.post("/api/pattern", json={"action": "explode"})
        assert resp.status == 400

        fleet = await (await client.get("/api/fleet")).json()
        assert fleet["ok"] and "1" in fleet["data"]
        stats = await (await client.get("/api/stats")).json()
        assert stats["ok"] and "stats" in stats["data"]
    with_client(scenario)

def test_websocket_registers_and_unregisters():
    async def scenario(client, store, fanout):
        ws = await client.ws_connect("/ws")
        await asyncio.sleep(0.05)
        assert len(store.ws_clients) == 1
        await ws.close()
        await asyncio.sleep(0.05)
        assert len(store.ws_clients) == 0
    with_client(scenario)

def test_index_serves_web_page():
    async def scenario(client, store, fanout):
        resp = await client.get("/")
        text = await resp.text()
        assert resp.status == 200 and "<title>airkal" in text
    with_client(scenario)
