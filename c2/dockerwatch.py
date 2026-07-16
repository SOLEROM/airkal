"""Docker container watch — polls `docker ps` for the SITL containers.

Observer only, like the rest of C2: the web page header shows how many
airkal SITL containers are up. Filters on the same label the lifecycle
scripts apply (scripts/lib.sh: DOCKER_LABEL), so it tracks exactly what
`make up` started. Degrades gracefully when docker is missing or the
daemon is down.
"""

import asyncio
import logging

log = logging.getLogger("c2.dockerwatch")

DOCKER_LABEL = "airkal-demo"
POLL_PERIOD_S = 3.0
PS_TIMEOUT_S = 5.0
PS_FORMAT = "{{.Names}}\t{{.Status}}"

def parse_ps_output(stdout: str) -> list[dict]:
    """Parse `docker ps --format '{{.Names}}\\t{{.Status}}'` output into
    a name-sorted list of {"name", "status"} dicts."""
    containers = []
    for line in stdout.splitlines():
        name, sep, status = line.strip().partition("\t")
        if not name:
            continue
        containers.append({"name": name, "status": status if sep else ""})
    return sorted(containers, key=lambda c: c["name"])

class DockerWatch:
    """Latest `docker ps` view of the labeled SITL containers."""

    def __init__(self, label: str = DOCKER_LABEL):
        self._label = label
        self._available = False
        self._containers: list[dict] = []

    def update(self, containers: list[dict] | None) -> None:
        """None means docker itself was unreachable (vs an empty fleet)."""
        self._available = containers is not None
        self._containers = [dict(c) for c in containers or []]

    def snapshot(self) -> dict:
        return {"available": self._available,
                "count": len(self._containers),
                "containers": [dict(c) for c in self._containers]}

    async def poll_once(self) -> None:
        self.update(await self._ps())

    async def poll_loop(self) -> None:
        while True:
            await self.poll_once()
            await asyncio.sleep(POLL_PERIOD_S)

    async def _ps(self) -> list[dict] | None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "ps", "--filter", f"label={self._label}",
                "--format", PS_FORMAT,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL)
        except OSError as exc:
            log.debug("docker unavailable: %s", exc)
            return None
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(),
                                               PS_TIMEOUT_S)
        except asyncio.TimeoutError:
            proc.kill()
            log.warning("docker ps timed out after %.0f s", PS_TIMEOUT_S)
            return None
        if proc.returncode != 0:
            log.debug("docker ps exited %s", proc.returncode)
            return None
        return parse_ps_output(stdout.decode("utf-8", "replace"))
