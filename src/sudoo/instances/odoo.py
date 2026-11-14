"""Everything specific to Odoo: compose file, odoo.conf, database parameters, readiness and versions."""

from __future__ import annotations

import base64
import configparser
import hashlib
import json
import re
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from sudoo.config import settings
from sudoo.core.shell import capture, succeeds
from sudoo.instances import store

CUSTOM_ADDONS_MOUNT = "/mnt/extra-addons"  # the instance's repository, inside the Odoo container, read-only
ENTERPRISE_ADDONS_MOUNT = "/mnt/enterprise-addons"  # the Enterprise add-ons, read-only

# What each container may do beyond an unprivileged process (every other capability is dropped). Found by running
# the official images: Odoo runs as the user "odoo" from its first process and needs none; PostgreSQL's entry point
# starts as root, prepares its folders (CHOWN, DAC_OVERRIDE, FOWNER) and switches to the user "postgres" (SETUID,
# SETGID); KILL lets the init process (root) pass stop signals on to PostgreSQL, which runs as another user.
ODOO_CAPABILITIES: tuple[str, ...] = ()
DB_CAPABILITIES = ("CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID", "KILL")
FILESTORE_CAPABILITIES = ("CHOWN", "DAC_OVERRIDE", "FOWNER")  # the short-lived root container of a restore
ODOO_HTTP_PORT = 8069

LABEL_MANAGED = "sh.sudoo.managed"
LABEL_INSTANCE = "sh.sudoo.instance"
LABEL_SERVICE = "sh.sudoo.service"
LABEL_HASH = "sh.sudoo.config-hash"

SERVICE_KEYS = frozenset(
    {
        "image", "restart", "init", "read_only", "security_opt", "cap_drop", "cap_add", "pids_limit", "mem_limit",
        "cpus", "tmpfs", "logging", "labels", "environment", "volumes", "networks", "ports", "depends_on",
    }
)  # fmt: skip
"""The only keys a service of an instance may have; anything else is refused (render_spec)."""

_FORBIDDEN_SOURCES = ("/", "/etc", "/proc", "/sys", "/dev", "/run", "/var/run", "/boot", "/root", "/var/lib/docker")


class UnsafeCompose(ValueError):
    """The compose file about to be written contains something an instance must never have."""


def compose_spec(
    name: str,
    *,
    odoo_image: str,
    db_image: str,
    odoo_port: int | str,
    db_password: str,
    enterprise_folder: Path | None,
    isolated_network: bool,
) -> dict[str, Any]:
    """The instance's two containers as a Compose document (a dict), hardened:

    - no extra privileges (no-new-privileges), every capability dropped except the few the image needs;
    - read-only system files: only the data volumes and small in-memory /tmp folders can be written;
    - the database is only on the instance's internal network: no published port, no way out, no other instance;
    - Odoo is published on 127.0.0.1 only and reaches the database over that internal network;
    - process, memory and processor limits, rotated logs, an init process, a restart policy the panel sets;
    - images pinned by digest, labels that say which instance and which rendering a container belongs to.
    Values are written literally: the file does not depend on the .env next to it.
    """
    folder = store.folder(name)
    logging = {
        "driver": "json-file",
        "options": {"max-size": settings.container_log_max_size, "max-file": str(settings.container_log_max_files)},
    }
    common: dict[str, Any] = {
        "restart": "unless-stopped",
        "init": True,
        "read_only": True,
        "security_opt": ["no-new-privileges:true"],
        "cap_drop": ["ALL"],
        "pids_limit": settings.container_pids_limit,
    }

    def limits(memory: str, cpus: float) -> dict[str, Any]:
        found: dict[str, Any] = {}
        if memory not in ("", "0"):
            found["mem_limit"] = memory
        if cpus > 0:
            found["cpus"] = cpus
        return found

    def labels(service: str) -> dict[str, str]:
        return {LABEL_MANAGED: "true", LABEL_INSTANCE: name, LABEL_SERVICE: service}

    odoo_volumes = [
        "odoo-data:/var/lib/odoo",
        f"{folder / 'config'}:/etc/odoo:ro",
        f"{folder / 'addons'}:{CUSTOM_ADDONS_MOUNT}:ro",
    ]
    if enterprise_folder:
        odoo_volumes.append(f"{enterprise_folder}:{ENTERPRISE_ADDONS_MOUNT}:ro")
    backend: dict[str, Any] = {"internal": True}
    if isolated_network:  # the server itself gets no address on it either (Docker 28 and later)
        backend["driver_opts"] = {"com.docker.network.bridge.gateway_mode_ipv4": "isolated"}
    spec: dict[str, Any] = {
        "name": f"odoo-{name}",
        "services": {
            "db": {
                "image": db_image,
                **common,
                "cap_add": list(DB_CAPABILITIES),
                **limits(settings.db_memory_limit, settings.db_cpu_limit),
                "tmpfs": ["/var/run/postgresql", "/tmp"],
                "labels": labels("db"),
                "environment": {"POSTGRES_USER": "odoo", "POSTGRES_PASSWORD": db_password, "POSTGRES_DB": "postgres"},
                "volumes": ["db-data:/var/lib/postgresql/data"],
                "networks": ["backend"],
                "logging": logging,
            },
            "odoo": {
                "image": odoo_image,
                **common,
                **limits(settings.odoo_memory_limit, settings.odoo_cpu_limit),
                "tmpfs": ["/tmp"],
                "labels": labels("odoo"),
                "environment": {"HOST": "db", "USER": "odoo", "PASSWORD": db_password},
                "volumes": odoo_volumes,
                "networks": ["backend", "default"],
                "ports": [f"127.0.0.1:{odoo_port}:{ODOO_HTTP_PORT}"],
                "depends_on": ["db"],
                "logging": logging,
            },
        },
        "networks": {"backend": backend, "default": {}},
        "volumes": {"db-data": {}, "odoo-data": {}},
    }
    check_spec(spec)
    for service in spec["services"].values():
        service["labels"][LABEL_HASH] = config_hash(spec)
    return spec


def config_hash(spec: dict[str, Any]) -> str:
    """SHA-256 of a rendering (every value, the database password included), without the hash labels themselves."""
    plain = json.loads(json.dumps(spec))
    for service in plain.get("services", {}).values():
        service.get("labels", {}).pop(LABEL_HASH, None)
    return hashlib.sha256(json.dumps(plain, sort_keys=True).encode()).hexdigest()


def check_spec(spec: dict[str, Any]) -> None:
    """Refuse a rendering that gives an instance more than running Odoo and PostgreSQL needs: unknown keys (no
    plugin or person can add any), more capabilities, ports on another address, the Docker socket or a system
    folder, writable folders from the server other than the configuration."""
    services = spec.get("services", {})
    if set(services) != {"db", "odoo"}:
        raise UnsafeCompose(f"an instance has exactly the services db and odoo, not {sorted(services)}")
    if set(spec) - {"name", "services", "networks", "volumes"}:
        raise UnsafeCompose(
            f"unexpected top-level keys: {sorted(set(spec) - {'name', 'services', 'networks', 'volumes'})}"
        )
    allowed_caps = {"db": set(DB_CAPABILITIES), "odoo": set(ODOO_CAPABILITIES)}
    for service_name, service in services.items():
        extra = set(service) - SERVICE_KEYS
        if extra:
            raise UnsafeCompose(f"{service_name}: keys that are not allowed: {sorted(extra)}")
        if service.get("cap_drop") != ["ALL"] or not set(service.get("cap_add", [])) <= allowed_caps[service_name]:
            raise UnsafeCompose(f"{service_name}: capabilities beyond what the image needs")
        if service.get("security_opt") != ["no-new-privileges:true"] or service.get("read_only") is not True:
            raise UnsafeCompose(f"{service_name}: must be read-only and without new privileges")
        for port in service.get("ports", []):
            if service_name != "odoo" or not str(port).startswith("127.0.0.1:"):
                raise UnsafeCompose(f"{service_name}: only Odoo is published, and only on 127.0.0.1 ({port})")
        for volume in service.get("volumes", []):
            source, _, rest = str(volume).partition(":")
            if not source.startswith("/"):
                continue  # a named volume of the instance
            path = Path(source).resolve()
            if "docker.sock" in source or str(path) in _FORBIDDEN_SOURCES or path == Path("/"):
                raise UnsafeCompose(f"{service_name}: {source} cannot be mounted into an instance")
            if not rest.endswith(":ro"):
                raise UnsafeCompose(f"{service_name}: {source} must be mounted read-only")


def to_yaml(value: Any, indent: int = 0) -> str:
    """A Compose file from a dict: block style, every string quoted, "$" escaped (Compose would expand it)."""
    pad = "  " * indent

    def scalar(item: Any) -> str:
        if isinstance(item, bool):
            return "true" if item else "false"
        if isinstance(item, int | float):
            return json.dumps(item)
        return json.dumps(str(item)).replace("$", "$$")

    lines: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, dict | list) and item:
                lines.append(f"{pad}{key}:\n{to_yaml(item, indent + 1)}")
            else:
                lines.append(f"{pad}{key}: {'{}' if item == {} else '[]' if item == [] else scalar(item)}\n")
    else:
        for item in value:
            if isinstance(item, dict | list) and item:
                lines.append(f"{pad}-\n{to_yaml(item, indent + 1)}")
            else:
                lines.append(f"{pad}- {scalar(item)}\n")
    return "".join(lines)


COMPOSE_HEADER = """\
# Generated by Sudoo.sh from its own settings. Do not edit: the panel checks this file and the containers made from
# it, reports any change, and (DRIFT_ACTION=restore) puts its own version back. See docs/SECURITY.md.
"""


def compose_text(spec: dict[str, Any]) -> str:
    return COMPOSE_HEADER + to_yaml(spec)


def hash_master_password(password: str, rounds: int = 600_000) -> str:
    """Odoo's own format for a hashed master password (passlib pbkdf2_sha512), so odoo.conf never holds it readable.

    Odoo checks `admin_passwd` with passlib, which accepts `$pbkdf2-sha512$<rounds>$<salt>$<hash>` with both parts
    in passlib's base64 alphabet ('.' instead of '+', no padding).
    """

    def ab64(raw: bytes) -> str:
        return base64.b64encode(raw).decode().replace("+", ".").rstrip("=")

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha512", password.encode(), salt, rounds)
    return f"$pbkdf2-sha512${rounds}${ab64(salt)}${ab64(digest)}"


def write_config(name: str, db: str, db_password: str, master_password: str) -> None:
    """Write config/odoo.conf for a new instance. The master password is stored as a hash only."""
    conf = configparser.RawConfigParser()
    conf["options"] = {
        "data_dir": "/var/lib/odoo",
        "admin_passwd": hash_master_password(master_password),
        "db_host": "db",
        "db_port": "5432",
        "db_user": "odoo",
        "db_password": db_password,
        # all interfaces inside the container, so Docker's port mapping reaches Odoo (Odoo 20 would otherwise
        # listen on the container's own 127.0.0.1); outside, the port is published on the server's 127.0.0.1
        "http_interface": "0.0.0.0",
        "dbfilter": f"^{re.escape(db)}$",
        "list_db": "False",
        "proxy_mode": "True",
    }
    from sudoo.instances import integrity

    store.config_file(name).parent.mkdir(exist_ok=True)
    with integrity.writing(name, integrity.CONF), open(store.config_file(name), "w") as fh:
        conf.write(fh)


def read_config(name: str) -> configparser.RawConfigParser:
    conf = configparser.RawConfigParser()
    conf.read(store.config_file(name))
    return conf


def set_addons_path(name: str, paths: list[str]) -> str:
    """Write `addons_path` into odoo.conf; return the new value. A hand-edited odoo.conf is replaced by the panel's
    own first, so its changes are never carried on."""
    from sudoo.instances import integrity

    with integrity.writing(name, integrity.CONF):
        integrity.rewrite_if_changed(name)
        conf = read_config(name)
        value = ",".join(paths)
        conf.set("options", "addons_path", value)
        with open(store.config_file(name), "w") as fh:
            conf.write(fh)
    return value


def run_cmd(name: str, *args: str) -> list[str]:
    """Command that runs `odoo <args>` once in a temporary container of the instance (database must be up)."""
    return store.compose(name, "run", "--rm", "--no-deps", "-T", "odoo", "odoo", *args)


def databases(name: str) -> list[str]:
    return [db for db in store.read_env(name).get("DB_NAME", "").split(",") if db]


def wait_for_database(name: str, timeout: float = 30) -> bool:
    """Wait until the instance's PostgreSQL accepts connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if succeeds(["docker", "exec", store.container(name, "db"), "pg_isready", "-q", "-U", "odoo"]):
            return True
        time.sleep(1)
    return False


def parameter_sql(params: dict[str, str]) -> str:
    """SQL that sets Odoo system parameters (ir.config_parameter)."""
    statements = []
    for key, value in params.items():
        quoted = value.replace("'", "''")
        statements.append(
            "INSERT INTO ir_config_parameter (key, value, create_date, write_date) "
            f"VALUES ('{key}', '{quoted}', now(), now()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, write_date = now();"
        )
    return "".join(statements)


def public_address_cmds(name: str, url: str) -> list[list[str]]:
    """Commands that tell each database of the instance its public address.

    web.base.url is used by Odoo for links in e-mails, the portal, payment and webhook URLs; it is frozen so Odoo
    does not replace it with the address an administrator logs in from. report.url makes PDF reports load their
    styles from Odoo itself instead of through the public address.
    """
    sql = parameter_sql({"web.base.url": url, "web.base.url.freeze": "True", "report.url": "http://localhost:8069"})
    return [
        ["docker", "exec", store.container(name, "db"), "psql", "-q", "-U", "odoo", "-d", db, "-c", sql]
        for db in databases(name)
    ]


def responds(port: int | str, timeout: float = 2) -> bool:
    """True when Odoo answers HTTP on 127.0.0.1:<port> (any status code means it is up)."""
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/web/health", timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, OSError):
        return False


def wait_until_ready(port: int | str, timeout: float = 240) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if responds(port):
            return True
        time.sleep(3)
    return False


def recent_log(name: str, lines: int = 300) -> str:
    return capture(store.compose(name, "logs", "--no-color", "--tail", str(lines), "odoo"), timeout=30)


# --------------------------------------------------------------------------- versions and editions

_VERSION_RE = re.compile(r"^(saas-)?\d+\.\d+$")
_VERSIONS_CACHE: tuple[list[str], float] = ([], 0.0)
_VERSIONS_CACHE_SECONDS = 3600


def version_key(version: str) -> tuple[float, ...]:
    """Sort key of an Odoo version: 17.0 < saas-17.2 < 18.0."""
    return tuple(float(part) for part in version.removeprefix("saas-").split("."))


def versions() -> list[str]:
    """The Odoo versions offered for new instances, oldest first.

    ODOO_VERSIONS=auto: every published x.0 version of the official image from ODOO_MIN_VERSION on, read from Docker
    Hub (cached for an hour). Otherwise the comma-separated list in ODOO_VERSIONS, as given.
    """
    if settings.odoo_versions.strip().lower() != "auto":
        return [version.strip() for version in settings.odoo_versions.split(",") if version.strip()]
    global _VERSIONS_CACHE
    published, fetched = _VERSIONS_CACHE
    if not published or time.time() - fetched >= _VERSIONS_CACHE_SECONDS:
        published = sorted((tag for tag in _docker_hub_tags(settings.odoo_image) if re.fullmatch(r"\d+\.0", tag)),
                           key=version_key)  # fmt: skip
        if published:
            _VERSIONS_CACHE = (published, time.time())
    # filtered on every call: ODOO_MIN_VERSION can be changed in the panel
    return [tag for tag in published if version_key(tag) >= version_key(settings.odoo_min_version)]


def _docker_hub_tags(image: str) -> list[str]:
    """Tags of an image on Docker Hub ("odoo" is the official library/odoo)."""
    repository = image if "/" in image else f"library/{image}"
    url: str | None = f"https://hub.docker.com/v2/repositories/{repository}/tags?page_size=100"
    tags: list[str] = []
    while url and len(tags) < 1000:
        try:
            with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - fixed https address
                page = json.loads(response.read())
        except (urllib.error.URLError, OSError, ValueError):
            break
        tags += [str(result["name"]) for result in page.get("results", [])]
        url = page.get("next")
    return tags
