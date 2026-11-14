"""Resource usage and status of the server and of every instance, collected every METRICS_INTERVAL_SECONDS.

Container figures come from one long-running `docker stats` stream (Docker sends new figures about every second),
so a measurement only reads the latest ones instead of starting Docker's slow one-off sampling each time. The git
details of an instance (commit, repository) are read at most once a minute, and right after a job on it ends.

Also keeps each Odoo's public address (web.base.url) in step with its connector, whose address changes when the
connector restarts, and has integrity.py compare the instances with the panel's configuration.

After every measurement it publishes live events (core/events.py): "metrics" with the new numbers, and "instance"
for each instance whose status, code or address changed since the last one.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Any

from sudoo import exposure
from sudoo.config import settings
from sudoo.core import events, jobs
from sudoo.core.shell import capture, succeeds
from sudoo.core.state import STATE
from sudoo.instances import integrity, metrics, odoo, store
from sudoo.repos.gitrepo import git

STATUS: dict[str, dict[str, Any]] = {}  # instance name -> latest measurements
HOST: dict[str, Any] = {"history": deque(maxlen=settings.history_samples)}
HISTORY: defaultdict[str, deque[tuple[int, float, int]]] = defaultdict(
    lambda: deque(maxlen=settings.history_samples)
)  # name -> [(time, cpu %, memory bytes)]
_DISK_CACHE: dict[str, dict[str, Any]] = {}
_KNOWN_ADDRESSES: dict[str, str] = {}
_LAST_SEEN: dict[str, tuple[Any, ...]] = {}  # name -> what clients last heard about it
_STARTED: dict[str, float] = {}  # container id -> Unix time it started
_GIT: dict[str, tuple[float, str, str]] = {}  # instance -> (read at, commit line, repository)
_WAS_BUSY: set[str] = set()
_GIT_SECONDS = 60


_JSON = json.JSONDecoder()


def _stats_line(line: str) -> tuple[str, tuple[float, int, int]] | None:
    """One line of `docker stats --format '{{json .}}'`: the container's name and figures, or None.

    The lines carry terminal control codes around the JSON (`ESC[H` before it, ` ESC[K` after it), so only the
    object itself is read."""
    start = line.find("{")
    if start == -1:
        return None
    try:
        entry, _ = _JSON.raw_decode(line, start)
        used, _, limit = entry["MemUsage"].partition("/")
        return entry["Name"], (float(entry["CPUPerc"].rstrip("%") or 0), _bytes(used), _bytes(limit))
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


class _DockerStats:
    """The latest figures of every running container, from a `docker stats` stream that runs in the background."""

    def __init__(self) -> None:
        self.latest: dict[str, tuple[float, int, int]] = {}  # container -> (cpu % of one core, memory, limit)
        self.updated = 0.0
        self._lock = threading.Lock()
        self._started = False

    def start(self) -> None:
        if not self._started:
            self._started = True
            threading.Thread(target=self._run_forever, daemon=True, name="docker-stats").start()

    def _run_forever(self) -> None:
        while True:
            try:
                with subprocess.Popen(
                    ["docker", "stats", "--format", "{{json .}}"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                ) as proc:
                    assert proc.stdout is not None
                    for line in proc.stdout:
                        parsed = _stats_line(line)
                        if parsed:
                            with self._lock:
                                self.latest[parsed[0]] = parsed[1]
                                self.updated = time.time()
            except OSError as exc:
                print("docker stats stream:", repr(exc), flush=True)
            time.sleep(5)  # Docker restarted or is not reachable yet

    def figures(self) -> dict[str, tuple[float, int, int]] | None:
        """The latest figures, or None when the stream has not delivered for a while."""
        with self._lock:
            return dict(self.latest) if time.time() - self.updated < 15 else None


STATS = _DockerStats()


def _container_figures() -> dict[str, tuple[float, int, int]]:
    STATS.start()
    figures = STATS.figures()
    if figures is not None:
        return figures
    usage: dict[str, tuple[float, int, int]] = {}  # until the stream delivers: one sampling
    for line in capture(["docker", "stats", "--no-stream", "--format", "{{json .}}"], timeout=60).splitlines():
        entry = json.loads(line)
        used, _, limit = entry["MemUsage"].partition("/")
        usage[entry["Name"]] = (float(entry["CPUPerc"].rstrip("%") or 0), _bytes(used), _bytes(limit))
    return usage


def _git_details(name: str, refresh: bool) -> tuple[str, str]:
    """(last commit "sha|subject|age|author", repository) of an instance, read at most once a minute."""
    cached = _GIT.get(name)
    if cached and not refresh and time.time() - cached[0] < _GIT_SECONDS:
        return cached[1], cached[2]
    addons = store.addons_dir(name)
    found = (
        capture(git(addons, "log", "-1", "--format=%h|%s|%cr|%an")),
        capture(git(addons, "remote", "get-url", "origin")),
    )
    _GIT[name] = (time.time(), *found)
    return found


_previous_cpu: tuple[int, int] | None = None

_UNITS = {
    "b": 1,
    "kb": 1e3,
    "mb": 1e6,
    "gb": 1e9,
    "tb": 1e12,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
}


def _bytes(text: str | None) -> int:
    match = re.match(r"\s*([\d.]+)\s*([a-zA-Z]+)", text or "")
    return int(float(match.group(1)) * _UNITS.get(match.group(2).lower(), 1)) if match else 0


def _host_cpu_percent() -> float:
    global _previous_cpu
    with open("/proc/stat") as fh:
        values = [int(v) for v in fh.readline().split()[1:]]
    idle, total = values[3] + values[4], sum(values)
    percent = 0.0
    if _previous_cpu and total > _previous_cpu[0]:
        busy = (total - _previous_cpu[0]) - (idle - _previous_cpu[1])
        percent = 100.0 * busy / (total - _previous_cpu[0])
    _previous_cpu = (total, idle)
    return percent


def _host_memory() -> tuple[int, int]:
    info: dict[str, int] = {}
    with open("/proc/meminfo") as fh:
        for line in fh:
            key, value = line.split(":", 1)
            info[key] = int(value.split()[0]) * 1024
    return info["MemTotal"], info["MemTotal"] - info["MemAvailable"]


def collect() -> None:
    """Measure the server and every instance once."""
    containers: dict[str, dict[str, Any]] = {}
    for line in capture(["docker", "ps", "-a", "--format", "{{json .}}"]).splitlines():
        entry = json.loads(line)
        containers[entry["Names"]] = entry
    usage = _container_figures()  # container -> (cpu % of one core, memory, memory limit)

    cores = os.cpu_count() or 1  # None only when the count cannot be determined
    memory_total, memory_used = _host_memory()
    now = time.time()
    running_now = {entry["ID"]: c for c, entry in containers.items() if entry["State"] == "running"}
    unknown = [c for cid, c in running_now.items() if cid not in _STARTED]
    for container, when in _started_at(unknown).items():
        _STARTED[containers[container]["ID"]] = when
    started = {c: _STARTED[cid] for cid, c in running_now.items() if cid in _STARTED}
    measured_instances: dict[str, metrics.Usage] = {}
    for name in store.names():
        env = store.read_env(name)
        odoo_container = containers.get(store.container(name, "odoo"))
        db_container = containers.get(store.container(name, "db"))
        running = bool(odoo_container and odoo_container["State"] == "running")
        own = (store.container(name, "odoo"), store.container(name, "db"))
        cpu = sum(usage.get(c, (0, 0, 0))[0] for c in own) / cores
        memory = sum(usage.get(c, (0, 0, 0))[1] for c in own)
        limit = min(sum(usage.get(c, (0, 0, 0))[2] for c in own) or memory_total, memory_total)
        busy = jobs.busy(name)
        commit, repo = _git_details(name, refresh=name in _WAS_BUSY and not busy)  # re-read after a job
        _WAS_BUSY.discard(name)
        if busy:
            _WAS_BUSY.add(name)
        STATUS[name] = {
            "running": running,
            "db_running": bool(db_container and db_container["State"] == "running"),
            "healthy": running and odoo.responds(env["ODOO_PORT"]),
            "uptime": odoo_container["Status"] if odoo_container else "",
            "cpu": round(cpu, 2),
            "memory": memory,
            "commit": commit,
            "repo": repo,
        }
        HISTORY[name].append((int(now), round(cpu, 2), memory))
        disk_bytes = None
        if running:
            stored = disk_usage(name)  # measured every 5 minutes at most
            disk_bytes = (stored.get("db") or 0) + (stored.get("files") or 0) or None
        measured_instances[name] = metrics.Usage(
            running, cpu, memory, limit, started.get(store.container(name, "odoo")), disk_bytes
        )

    disk = shutil.disk_usage(settings.odoo_root)
    cpu = _host_cpu_percent()
    HOST.update(
        cpu=round(cpu, 1),
        cores=cores,
        memory_total=memory_total,
        memory_used=memory_used,
        disk_total=disk.total,
        disk_used=disk.used,
    )
    HOST["history"].append((int(now), round(cpu, 1), memory_used))
    metrics.sample(
        {
            "cpu_percent": round(cpu, 1),
            "cores": cores,
            "load_1m": round(os.getloadavg()[0], 2),
            "memory_used_bytes": memory_used,
            "memory_total_bytes": memory_total,
            "memory_percent": round(100 * memory_used / memory_total, 1),
            "disk_used_bytes": disk.used,
            "disk_total_bytes": disk.total,
            "disk_percent": round(100 * disk.used / disk.total, 1),
            "uptime_seconds": _host_uptime(),
            "instances_running": sum(1 for u in measured_instances.values() if u.running),
            "instances_total": len(measured_instances),
        },
        measured_instances,
    )


def _started_at(names: list[str]) -> dict[str, float]:
    """When each running container started, as Unix time."""
    if not names:
        return {}
    found: dict[str, float] = {}
    for line in capture(["docker", "inspect", "-f", "{{.Name}} {{.State.StartedAt}}", *names]).splitlines():
        name, _, when = line.strip().lstrip("/").partition(" ")
        try:
            found[name] = datetime.fromisoformat(when[:26].rstrip("Z") + "+00:00").timestamp()
        except ValueError:
            continue
    return found


def _host_uptime() -> int:
    with open("/proc/uptime") as fh:
        return int(float(fh.read().split()[0]))


def follow_public_addresses() -> None:
    """Write each instance's current public address into its databases when it changed."""
    for name in store.names():
        if not STATUS.get(name, {}).get("db_running") or jobs.busy(name):
            continue
        url = exposure.address(name)
        changed = url and _KNOWN_ADDRESSES.get(name) != url
        if changed and url and all(succeeds(cmd, timeout=60) for cmd in odoo.public_address_cmds(name, url)):
            _KNOWN_ADDRESSES[name] = url


def mark_running(name: str) -> None:
    """Record right away that an instance answers (instead of waiting for the next measurement)."""
    STATUS.setdefault(name, {}).update(running=True, healthy=True)


def mark_stopped(name: str) -> None:
    STATUS.setdefault(name, {})["running"] = False


def publish_changes() -> None:
    """Publish "metrics", and "instance" for every instance that looks different to a client than last time."""
    events.publish("metrics", "", metrics.snapshot())
    for name in store.names():
        state = STATE.get(name)
        seen = (
            status(name),
            STATUS.get(name, {}).get("commit"),
            exposure.address(name),
            state.get("branch_missing"),
            int(state.get("last_visit") or 0) // 60,
        )
        if _LAST_SEEN.get(name) != seen:
            _LAST_SEEN[name] = seen
            events.publish("instance", name)


def run_forever() -> None:
    """Background loop: measure every MONITOR_INTERVAL_SECONDS."""
    while True:
        try:
            collect()
            publish_changes()
            follow_public_addresses()
            integrity.check_all()  # every INTEGRITY_CHECK_INTERVAL seconds: changes made outside the panel
        except Exception as exc:  # noqa: BLE001 - the monitor must keep running; the error is logged
            print("monitor error:", repr(exc), flush=True)
        time.sleep(settings.metrics_interval_seconds)


def status(name: str) -> str:
    """What the panel shows: busy, unknown, online, starting, switched_off, paused or stopped."""
    measured, state = STATUS.get(name), STATE.get(name)
    if jobs.busy(name):
        return "busy"
    if measured is None:
        return "unknown"
    if measured["running"]:
        return "online" if measured["healthy"] else "starting"
    if state.get("switched_off"):
        return "switched_off"
    if state.get("paused"):
        return "paused"
    return "stopped"


def disk_usage(name: str) -> dict[str, Any]:
    """{"db": bytes, "files": bytes} of a running instance (None when not running). Cached 5 minutes."""
    cached = _DISK_CACHE.get(name)
    if cached and time.time() - cached["at"] < 300:
        return cached
    measured = STATUS.get(name, {})
    result: dict[str, Any] = {"db": None, "files": None, "at": time.time()}
    db = odoo.databases(name)[0]
    if measured.get("db_running"):
        out = capture(
            [
                "docker",
                "exec",
                store.container(name, "db"),
                "psql",
                "-U",
                "odoo",
                "-d",
                "postgres",
                "-tAc",
                f"SELECT pg_database_size('{db}')",
            ]
        )
        result["db"] = int(out) if out.strip().isdigit() else None
    if measured.get("running"):
        out = capture(["docker", "exec", store.container(name, "odoo"), "du", "-sb", "/var/lib/odoo"])
        result["files"] = int(out.split()[0]) if out else None
    _DISK_CACHE[name] = result
    return result
