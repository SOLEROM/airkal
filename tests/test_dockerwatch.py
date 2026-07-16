import asyncio

import pytest

from c2.dockerwatch import DockerWatch, parse_ps_output

# ── parsing ──────────────────────────────────────────────────────────────────

def test_parse_ps_output_extracts_name_and_status():
    out = "airkal-sitl-2\tUp 4 minutes\nairkal-sitl-1\tUp 4 minutes\n"
    assert parse_ps_output(out) == [
        {"name": "airkal-sitl-1", "status": "Up 4 minutes"},
        {"name": "airkal-sitl-2", "status": "Up 4 minutes"},
    ]

def test_parse_ps_output_empty_and_blank_lines():
    assert parse_ps_output("") == []
    assert parse_ps_output("\n \n") == []

def test_parse_ps_output_line_without_status():
    assert parse_ps_output("airkal-sitl-1\n") == [
        {"name": "airkal-sitl-1", "status": ""},
    ]

# ── snapshot state machine ───────────────────────────────────────────────────

def test_snapshot_before_first_poll_reports_unavailable():
    watch = DockerWatch()
    assert watch.snapshot() == {"available": False, "count": 0,
                                "containers": []}

def test_update_with_containers_reports_running():
    watch = DockerWatch()
    containers = [{"name": "airkal-sitl-1", "status": "Up 2 minutes"}]
    watch.update(containers)
    snap = watch.snapshot()
    assert snap["available"] is True
    assert snap["count"] == 1
    assert snap["containers"] == containers

def test_update_with_none_marks_docker_unavailable():
    watch = DockerWatch()
    watch.update([{"name": "airkal-sitl-1", "status": "Up 1 second"}])
    watch.update(None)
    assert watch.snapshot() == {"available": False, "count": 0,
                                "containers": []}

def test_snapshot_returns_copies_not_internal_state():
    watch = DockerWatch()
    watch.update([{"name": "airkal-sitl-1", "status": "Up 1 second"}])
    snap = watch.snapshot()
    snap["containers"].append({"name": "intruder", "status": ""})
    assert watch.snapshot()["count"] == 1

# ── polling ──────────────────────────────────────────────────────────────────

def test_poll_once_handles_missing_docker_binary(monkeypatch):
    async def boom(*args, **kwargs):
        raise FileNotFoundError("docker not installed")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)
    watch = DockerWatch()
    asyncio.run(watch.poll_once())
    assert watch.snapshot()["available"] is False

def test_poll_once_handles_nonzero_exit(monkeypatch):
    class FakeProc:
        returncode = 1
        async def communicate(self):
            return b"", b"Cannot connect to the Docker daemon"
    async def fake_exec(*args, **kwargs):
        return FakeProc()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    watch = DockerWatch()
    asyncio.run(watch.poll_once())
    assert watch.snapshot()["available"] is False

def test_poll_once_parses_successful_ps(monkeypatch):
    class FakeProc:
        returncode = 0
        async def communicate(self):
            return b"airkal-sitl-1\tUp 9 minutes\n", b""
    async def fake_exec(*args, **kwargs):
        assert args[0] == "docker"
        return FakeProc()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    watch = DockerWatch()
    asyncio.run(watch.poll_once())
    snap = watch.snapshot()
    assert snap == {"available": True, "count": 1,
                    "containers": [{"name": "airkal-sitl-1",
                                    "status": "Up 9 minutes"}]}
