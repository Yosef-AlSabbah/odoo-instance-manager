"""Exposure plugin "cloudflare-quick": a free Cloudflare quick tunnel per target, no account, no domain, no open port.

The server needs no incoming connection: a connector container (`cloudflared`) makes an outgoing connection to
Cloudflare, which gives it a random address https://<words>.trycloudflare.com and sends every visit to that address
back through the connection. One connector per target:

    <connector_prefix>panel     -> the panel        (127.0.0.1:PANEL_PORT)
    <connector_prefix><name>    -> instance gateway (127.0.0.1:GATEWAY_PORT of the instance)

Each connector reports its address on its status port (GET /quicktunnel). The address changes only when the
connector itself restarts; restarting the panel or an instance keeps it. See docs/concepts/TUNNELING.md.
"""

from __future__ import annotations

import json
import time
import urllib.request

from sudoo.config import Settings
from sudoo.core.shell import capture, succeeds
from sudoo.exposure.base import Target

STATUS_PORT_KEY = "CONNECTOR_METRICS_PORT"  # .env key of an instance's connector status port
_CACHE_SECONDS = 20


class CloudflareQuickTunnel:
    """One `cloudflared` quick-tunnel container per target."""

    listen_host = "127.0.0.1"  # connectors reach the panel and the gateways locally
    https = True
    client_ip_header = "CF-Connecting-IP"  # set by Cloudflare: the visitor's real address

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._addresses: dict[str, tuple[str | None, float]] = {}

    def instance_ports(self) -> dict[str, int]:
        return {STATUS_PORT_KEY: self.settings.connector_status_port_start}

    def panel_env(self) -> dict[str, str]:
        return {STATUS_PORT_KEY: str(self.settings.panel_connector_status_port)}

    def container(self, target: Target) -> str:
        return f"{self.settings.connector_prefix}{target.name}"

    def ensure(self, target: Target) -> None:
        """Create the connector, or start it if it was stopped. A running connector is left alone (same address)."""
        state = capture(["docker", "inspect", "-f", "{{.State.Status}}", self.container(target)])
        if state == "running":
            return
        succeeds(["docker", "start", self.container(target)] if state else self._run_command(target), timeout=300)

    def remove(self, target: Target) -> None:
        succeeds(["docker", "rm", "-f", self.container(target)], timeout=120)
        self._addresses.pop(target.name, None)

    def address(self, target: Target) -> str | None:
        """The connector's https address, read from its status port. Cached 20 s, except while it has none."""
        cached = self._addresses.get(target.name)
        if cached and cached[0] and time.time() - cached[1] < _CACHE_SECONDS:
            return cached[0]
        try:
            url = f"http://127.0.0.1:{target.env[STATUS_PORT_KEY]}/quicktunnel"
            with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310 - fixed local http address
                hostname = str(json.loads(response.read()).get("hostname", ""))
        except (OSError, ValueError, KeyError):
            hostname = ""
        result = f"https://{hostname}" if hostname.endswith(".trycloudflare.com") else None
        self._addresses[target.name] = (result, time.time())
        return result

    def _run_command(self, target: Target) -> list[str]:
        """A new connector: host network (it reaches the gateway on 127.0.0.1), and otherwise as little as
        possible: no capabilities, no new privileges, read-only system files, limits, rotated logs. Connectors that
        exist already are never recreated (their address would change); they get this at their next creation."""
        return [
            "docker", "run", "-d", "--name", self.container(target), "--restart", "unless-stopped",
            "--network", "host", "--label", "sudoo=connector",
            "--label", "sh.sudoo.managed=true", "--label", "sh.sudoo.service=connector",
            "--label", f"sh.sudoo.instance={target.name}",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--read-only", "--tmpfs", "/tmp",
            "--pids-limit", "256", "--memory", "256m", "--init",
            "--log-driver", "json-file", "--log-opt", "max-size=10m", "--log-opt", "max-file=3",
            self.settings.cloudflared_image,
            "tunnel", "--no-autoupdate", "--metrics", f"127.0.0.1:{target.env[STATUS_PORT_KEY]}",
            "--url", f"http://127.0.0.1:{target.port}",
        ]  # fmt: skip
