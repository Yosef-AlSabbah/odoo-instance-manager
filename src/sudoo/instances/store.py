"""Instance folders and their files.

An instance lives in INSTANCES_DIR/<name>/:
    .env                  its settings (version, edition, ports, database, automation switches); mode 600,
                          the Odoo master password in it is encrypted (vault.py)
    docker-compose.yml    its two containers: odoo and db (PostgreSQL)
    config/odoo.conf      Odoo configuration
    addons/               clone of its GitHub repository (with submodules)

Each instance gets three ports on 127.0.0.1, allocated together when it is created:
    GATEWAY_PORT          the gateway listens here; the instance's Cloudflare connector points at it
    ODOO_PORT             Odoo itself, reached only by the gateway
    CONNECTOR_METRICS_PORT  the connector reports its public address here
"""

from __future__ import annotations

import re
import socket
import threading
from collections.abc import Mapping
from pathlib import Path

from sudoo.config import settings

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")


def folder(name: str) -> Path:
    return settings.instances_dir / name


def exists(name: str) -> bool:
    return bool(NAME_RE.match(name or "")) and (folder(name) / "docker-compose.yml").exists()


def names() -> list[str]:
    """Names of all instances, sorted."""
    if not settings.instances_dir.exists():
        return []
    return sorted(p.name for p in settings.instances_dir.iterdir() if exists(p.name))


def addons_dir(name: str) -> Path:
    return folder(name) / "addons"


def config_file(name: str) -> Path:
    return folder(name) / "config" / "odoo.conf"


def read_env(name: str) -> dict[str, str]:
    """The instance's .env file as a dict."""
    env: dict[str, str] = {}
    path = folder(name) / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and not key.startswith("#"):
                env[key.strip()] = value.strip()
    return env


def master_password_label(name: str) -> str:
    """Vault label of the instance's Odoo master password (stored encrypted in .env, hashed in odoo.conf)."""
    return f"master-password:{name}"


def write_env(name: str, env: Mapping[str, object]) -> None:
    """Write the instance's .env file, readable by its owner only (it holds the database password)."""
    from sudoo.instances import integrity

    path = folder(name) / ".env"
    with integrity.writing(name, ".env"):
        path.touch(mode=0o600)
        path.write_text("".join(f"{key}={value}\n" for key, value in env.items()))


def update_env(name: str, **values: object) -> None:
    env = read_env(name)
    env.update({key: str(value) for key, value in values.items()})
    write_env(name, env)


_STARTING = ("up", "run", "create", "start", "restart")  # Compose commands that create or start containers


def compose(name: str, *args: str) -> list[str]:
    """`docker compose` command for the instance's project.

    For an instance the panel has hardened (instances/integrity.py), the compose file and odoo.conf are first put
    back if someone changed them, before any command that creates or starts containers; the project name is fixed
    and the .env file is not read (the compose file holds every value, and .env could otherwise rename the project
    or switch Compose features on)."""
    from sudoo.instances import integrity

    path = folder(name)
    command = ["docker", "compose", "--project-directory", str(path), "-f", str(path / "docker-compose.yml")]
    if integrity.hardened(name):
        if args and args[0] in _STARTING:
            integrity.rewrite_if_changed(name)
        command += ["-p", f"odoo-{name}", "--env-file", "/dev/null"]
    return [*command, *args]


def container(name: str, service: str) -> str:
    """Docker container name of a service ("odoo" or "db") of the instance."""
    return f"odoo-{name}-{service}-1"


# --------------------------------------------------------------------------- ports

_PORT_LOCK = threading.Lock()
_RESERVED: set[int] = set()
_PORT_SUFFIX = "_PORT"  # every .env key ending in _PORT holds a port reserved for the instance


def _free(port: int) -> bool:
    """True when nothing listens on 127.0.0.1:<port>."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _used_ports() -> set[int]:
    used = {settings.panel_port, settings.panel_connector_status_port} | _RESERVED
    for name in names():
        env = read_env(name)
        used |= {int(value) for key, value in env.items() if key.endswith(_PORT_SUFFIX) and value.isdigit()}
    return used


def _next_free(start: int, used: set[int]) -> int:
    port = start
    while port in used or not _free(port):
        port += 1
    return port


def reserve_ports(extra: dict[str, int]) -> dict[str, int]:
    """Reserve ports for a new instance: GATEWAY_PORT, ODOO_PORT and the `extra` ones the exposure plugin needs,
    given as {.env key: first port}. Returns {.env key: port}."""
    wanted = {"GATEWAY_PORT": settings.gateway_port_start, "ODOO_PORT": settings.odoo_port_start, **extra}
    with _PORT_LOCK:
        used = _used_ports()
        ports: dict[str, int] = {}
        for key, start in wanted.items():
            ports[key] = _next_free(start, used)
            used.add(ports[key])
        _RESERVED.update(ports.values())
        return ports


def release_ports(ports: dict[str, int]) -> None:
    """Forget a reservation once the ports are written to the instance's .env (or creation failed)."""
    with _PORT_LOCK:
        _RESERVED.difference_update(ports.values())
