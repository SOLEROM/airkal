import asyncio
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from c2.api import build_app
from tests.test_api import FakeFanout, FakeStore

def with_design_client(design_dir: Path, test_coro):
    async def run():
        store, fanout = FakeStore(), FakeFanout()
        app = build_app(store, fanout, design_dir=design_dir)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            return await test_coro(client)
        finally:
            await client.close()
    return asyncio.run(run())

def make_design_dir(tmp_path: Path) -> Path:
    design = tmp_path / "design"
    design.mkdir()
    (design / "02-beta.md").write_text("# Beta page\n\nsecond\n")
    (design / "01-alpha.md").write_text(
        "---\nnoteId: \"abc\"\ntags: []\n---\n\n# Alpha page\n\nfirst body\n")
    (design / "notes.txt").write_text("not markdown")
    (tmp_path / "secret.md").write_text("# TOP SECRET\noutside the folder\n")
    return design

def test_design_index_lists_md_pages_sorted_with_titles(tmp_path):
    async def scenario(client):
        body = await (await client.get("/api/design")).json()
        assert body["ok"]
        assert body["data"]["pages"] == [
            {"file": "01-alpha.md", "title": "Alpha page"},
            {"file": "02-beta.md", "title": "Beta page"},
        ]
    with_design_client(make_design_dir(tmp_path), scenario)

def test_design_page_returns_markdown_without_frontmatter(tmp_path):
    async def scenario(client):
        body = await (await client.get("/api/design/01-alpha.md")).json()
        assert body["ok"]
        data = body["data"]
        assert data["file"] == "01-alpha.md"
        assert data["title"] == "Alpha page"
        assert data["markdown"].startswith("# Alpha page")
        assert "noteId" not in data["markdown"]
    with_design_client(make_design_dir(tmp_path), scenario)

def test_design_page_missing_is_404(tmp_path):
    async def scenario(client):
        resp = await client.get("/api/design/nope.md")
        body = await resp.json()
        assert resp.status == 404 and not body["ok"]
    with_design_client(make_design_dir(tmp_path), scenario)

def test_design_page_rejects_non_md_and_traversal(tmp_path):
    async def scenario(client):
        for name in ("notes.txt", "..%2Fsecret.md", ".hidden.md",
                     "%2e%2e%2fsecret.md", "..secret.md%00.md"):
            resp = await client.get(f"/api/design/{name}")
            assert resp.status in (400, 404), name
            assert "TOP SECRET" not in await resp.text(), name
        # a path with a real slash never routes to the page handler
        resp = await client.get("/api/design/../secret.md")
        assert "TOP SECRET" not in await resp.text()
    with_design_client(make_design_dir(tmp_path), scenario)

def test_design_index_skips_symlinks_escaping_the_folder(tmp_path):
    design = make_design_dir(tmp_path)
    (design / "evil.md").symlink_to(tmp_path / "secret.md")
    async def scenario(client):
        body = await (await client.get("/api/design")).json()
        titles = {p["file"]: p["title"] for p in body["data"]["pages"]}
        assert "evil.md" not in titles
        assert "TOP SECRET" not in str(titles)
    with_design_client(design, scenario)

def test_design_index_empty_when_dir_missing(tmp_path):
    async def scenario(client):
        body = await (await client.get("/api/design")).json()
        assert body["ok"] and body["data"]["pages"] == []
    with_design_client(tmp_path / "does-not-exist", scenario)

def test_default_design_dir_serves_repo_docs():
    async def run():
        store, fanout = FakeStore(), FakeFanout()
        client = TestClient(TestServer(build_app(store, fanout)))
        await client.start_server()
        try:
            body = await (await client.get("/api/design")).json()
            files = [p["file"] for p in body["data"]["pages"]]
            assert "01-overview.md" in files
        finally:
            await client.close()
    asyncio.run(run())
