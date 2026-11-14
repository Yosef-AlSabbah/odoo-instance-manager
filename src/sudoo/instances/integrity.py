"""Instances stay exactly as the panel made them: hardened containers, protected files, and changes made by hand
found, reported and (DRIFT_ACTION=restore) undone.

When the panel starts an instance it renders the instance's compose file (odoo.compose_spec), pins the images by
digest and keeps a record of what it applied (storage collection "instance_integrity"): the values that shape the
containers, the compose file and odoo.conf as written, the SHA-256 of every file it wrote, and the image of each
container. The values that shape the containers come from that record from then on, never from the .env file, so
a hand-edited .env cannot change an image, a port or a password; the panel changes them on purpose only (creation,
"Update Odoo and PostgreSQL images").

Every INTEGRITY_CHECK_INTERVAL seconds (from the monitor) the panel compares, for each instance that is not busy:

    files       docker-compose.yml, config/odoo.conf and .env against the hashes it recorded, and their modes
    containers  `docker inspect` of odoo and db against the rendering: image, capabilities, read-only system files,
                privileges, user, mounts, networks, published ports, environment, labels, limits, restart policy,
                log rotation, init process
    strangers   containers that carry the instance's label or Compose project but are not the panel's
    connector   the instance's connector (when the exposure plugin has one): no privileges, mounts or added
                capabilities; reported only, never recreated (its public address would change)

A difference seen in two checks in a row is drift: it goes to the audit log, the live events (the instance shows a
banner), and an e-mail to every super admin with an address. With DRIFT_ACTION=restore a "Restore the panel's
configuration" job then runs as soon as nothing else runs on the instance: it backs the database up first when the
database container is affected, writes the panel's own files back, stops strange containers and recreates the
affected containers. The panel itself never applies a compose file or odoo.conf it did not write: before every
Compose command that creates or starts containers, a changed file is replaced by the recorded one.

Root, and anyone in the docker group, can still change everything on the server; see docs/SECURITY.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sudoo.config import settings
from sudoo.core import audit, events, jobs
from sudoo.core.jobs import Job, JobError
from sudoo.core.shell import capture
from sudoo.core.state import STATE
from sudoo.instances import odoo, store
from sudoo.storage import storage

COLLECTION = "instance_integrity"
COMPOSE = "docker-compose.yml"
CONF = "config/odoo.conf"
ENV = ".env"
RESTORABLE_FILES = (COMPOSE, CONF)  # the panel can write these again; .env holds data only the panel knows

# .env keys that shape the containers; taken from the record once there is one
_INPUTS = ("ODOO_IMAGE_REF", "DB_IMAGE_REF", "ODOO_PORT", "DB_PASSWORD", "ENTERPRISE_FOLDER", "ODOO_USER")

_LOCK = threading.RLock()  # writing an instance's files and comparing them never overlap
_SEEN: dict[str, tuple[str, ...]] = {}  # instance -> differences found by the previous check, not yet confirmed
_ATTEMPTED: dict[str, tuple[tuple[str, ...], float]] = {}  # instance -> (differences, when) of the last repair
_REPAIR_RETRY_SECONDS = 1800
_last_check = 0.0
_IMAGES: dict[str, dict[str, Any]] = {}  # image id -> {"user", "env", "volumes"}
_DOCKER_VERSION: list[int] = []


@dataclass(frozen=True)
class Finding:
    """One difference between what the panel applied and what is there."""

    part: str  # "odoo", "db", "files", "stranger" (restorable); "env", "connector" (reported only)
    text: str

    @property
    def restorable(self) -> bool:
        return self.part in ("odoo", "db", "files", "stranger")


# --------------------------------------------------------------------------- the record


def record(name: str) -> dict[str, Any] | None:
    """What the panel last applied to the instance, or None for an instance not started since this version."""
    return storage().get(COLLECTION, name)


def hardened(name: str) -> bool:
    return record(name) is not None


def forget(name: str) -> None:
    """Remove the record (when the instance is deleted)."""
    storage().delete(COLLECTION, name)
    _SEEN.pop(name, None)
    _ATTEMPTED.pop(name, None)


def _sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def note_written(name: str, relative: str) -> None:
    """The panel itself has just written `relative` (.env or config/odoo.conf): remember its new hash and text."""
    with _LOCK:
        found = record(name)
        if found is None:
            return
        path = store.folder(name) / relative
        found["files"][relative] = _sha(path)
        if relative == CONF:
            found["conf"] = path.read_text()
        storage().put(COLLECTION, name, found)


@contextmanager
def writing(name: str, relative: str) -> Iterator[None]:
    """Around a write of the panel to `relative`: no check compares the file meanwhile; its hash is kept after."""
    with _LOCK:
        yield
        note_written(name, relative)


def rewrite_if_changed(name: str) -> list[str]:
    """Put back the compose file and odoo.conf the panel wrote, if they were changed by hand. Called before every
    Compose command that creates or starts containers, so the panel never applies a file it did not write. Returns
    the files put back."""
    with _LOCK:
        found = record(name)
        if found is None:
            return []
        folder, restored = store.folder(name), []
        for relative, key in ((COMPOSE, "compose"), (CONF, "conf")):
            path = folder / relative
            if found.get(key) is not None and _sha(path) != found["files"].get(relative):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(found[key])
                restored.append(relative)
        if restored:
            protect(name, found["inputs"].get("ODOO_USER", ""))
            audit.record("system", None, "configuration file put back", name, detail=", ".join(restored))
        return restored


# --------------------------------------------------------------------------- images


def _normal(repository: str) -> str:
    return repository.removeprefix("docker.io/").removeprefix("library/")


def _repository(reference: str) -> str:
    """ "odoo" of "odoo:18.0", "odoo:18.0@sha256:..." or "registry:5000/team/odoo:18.0"."""
    base = reference.split("@")[0]
    last = base.rsplit("/", 1)[-1]
    return base[: len(base) - len(last)] + last.split(":")[0]


def _image(reference: str) -> dict[str, Any] | None:
    found = capture(["docker", "image", "inspect", "--format", "{{json .}}", reference], timeout=60)
    try:
        return json.loads(found) if found else None
    except ValueError:
        return None


def pinned(reference: str, image: dict[str, Any]) -> str:
    """`reference` pinned to the digest of `image` (odoo:18.0@sha256:...); the reference as it is when the image
    has no digest from a registry (built on this server)."""
    repository = _repository(reference)
    digests = [d for d in image.get("RepoDigests") or [] if _normal(d.split("@")[0]) == _normal(repository)]
    if not digests:
        return reference
    return f"{reference.split('@')[0]}@{digests[0].split('@')[1]}"


def image_details(image_id: str) -> dict[str, Any]:
    """{"user", "env", "volumes"} of an image (what a container gets from it unless told otherwise)."""
    if image_id not in _IMAGES:
        image = _image(image_id) or {}
        config = image.get("Config") or {}
        _IMAGES[image_id] = {
            "user": config.get("User") or "",
            "env": list(config.get("Env") or []),
            "volumes": sorted(config.get("Volumes") or {}),
        }
    return _IMAGES[image_id]


def _container_image(container: str) -> str:
    """The image id an existing container runs ("" when there is no such container)."""
    return capture(["docker", "inspect", "--format", "{{.Image}}", container])


def pin_images(job: Job, name: str, pull: bool) -> dict[str, str]:
    """Image references of the instance, pinned by digest, written to its .env (ODOO_IMAGE_REF, DB_IMAGE_REF).

    pull=True (creation, "Update images"): download the images and pin what arrived; an instance keeps the image
    names and tags it was made with.
    pull=False (first start of an instance made before images were pinned): pin what its containers run now, so
    nothing changes but the hardening; references already pinned stay."""
    env = store.read_env(name)
    wanted = {
        "ODOO_IMAGE_REF": (f"{settings.odoo_image}:{env['ODOO_VERSION']}", "odoo"),
        "DB_IMAGE_REF": (settings.postgres_image, "db"),
    }
    found = record(name)
    values: dict[str, str] = {}
    for key, (configured, service) in wanted.items():
        current = (found or {}).get("inputs", {}).get(key) or env.get(key)
        if current and not pull:
            values[key] = current
            continue
        if current:  # keep the image name and tag the instance was made with (a new PostgreSQL major version
            configured = current.split("@")[0]  # could not open its data); only the digest is refreshed
        image: dict[str, Any] | None = None
        if pull:
            job.run(["docker", "pull", configured], timeout=1800)
        else:
            running = _container_image(store.container(name, service))
            image = _image(running) if running else None
            if image:  # the tag the old compose file named, at the digest the container runs
                configured = _legacy_reference(name, service, env) or configured
        image = image or _image(configured)
        if image is None:
            job.run(["docker", "pull", configured], timeout=1800)
            image = _image(configured)
        if image is None:
            raise JobError(f"The image {configured} is not available.")
        values[key] = pinned(configured, image)
        job.write(f"{service} image: {values[key]}\n")
    store.update_env(name, **values)
    return values


def _legacy_reference(name: str, service: str, env: dict[str, str]) -> str | None:
    """The image an instance made before this version names in its compose file."""
    if service == "odoo":
        return f"{settings.odoo_image}:{env['ODOO_VERSION']}"
    text = (store.folder(name) / COMPOSE).read_text() if (store.folder(name) / COMPOSE).exists() else ""
    match = re.search(r"^\s+image:\s*(\S+)\s*$", text, re.M)
    return match[1].strip("\"'") if match and "$" not in match[1] else None


def odoo_user(reference: str) -> str:
    """ "uid:gid" of the user "odoo" in the Odoo image (owner of odoo.conf, so Odoo can read it and nobody else)."""
    command = ["docker", "run", "--rm", "--network", "none", "--cap-drop", "ALL", "--entrypoint", "id", reference]
    uid, gid = capture([*command, "-u"], timeout=120), capture([*command, "-g"], timeout=120)
    return f"{uid}:{gid}" if uid.isdigit() and gid.isdigit() else ""


def isolated_networks() -> bool:
    """True when Docker can keep the server itself off an internal network (Docker 28 and later)."""
    if not _DOCKER_VERSION:
        version = capture(["docker", "version", "--format", "{{.Server.Version}}"])
        _DOCKER_VERSION.extend(int(part) for part in re.findall(r"\d+", version)[:2] or ["0"])
    return _DOCKER_VERSION[0] >= 28


# --------------------------------------------------------------------------- applying


def _enterprise_folder(name: str, env: dict[str, str]) -> str:
    """The Enterprise folder mounted into the instance ("" for Community), also for instances made before it was
    kept in .env (read from their compose file)."""
    if env.get("EDITION") != "enterprise":
        return ""
    if env.get("ENTERPRISE_FOLDER"):
        return env["ENTERPRISE_FOLDER"]
    path = store.folder(name) / COMPOSE
    text = path.read_text() if path.exists() else ""
    match = re.search(rf"^\s+-\s*\"?([^\":\s]+):{re.escape(odoo.ENTERPRISE_ADDONS_MOUNT)}:ro", text, re.M)
    return match[1] if match else ""


def inputs(name: str) -> dict[str, str]:
    """The values that shape the instance's containers: from the panel's record when there is one (a hand-edited
    .env changes nothing), else from .env."""
    env = store.read_env(name)
    kept = (record(name) or {}).get("inputs", {})
    return {key: str(kept.get(key, env.get(key, ""))) for key in _INPUTS}


def render(name: str, values: dict[str, str]) -> dict[str, Any]:
    enterprise = values.get("ENTERPRISE_FOLDER")
    return odoo.compose_spec(
        name,
        odoo_image=values["ODOO_IMAGE_REF"],
        db_image=values["DB_IMAGE_REF"],
        odoo_port=values["ODOO_PORT"],
        db_password=values["DB_PASSWORD"],
        enterprise_folder=Path(enterprise) if enterprise else None,
        isolated_network=isolated_networks(),
    )


def apply(job: Job, name: str, pull: bool = False) -> None:
    """Render the instance's hardened compose file with the current settings and write it, protect the instance's
    files and record all of it. Containers change when Compose next starts them (the caller does that)."""
    env = store.read_env(name)
    refs = pin_images(job, name, pull)
    with _LOCK:
        values = inputs(name) | refs
        if not values.get("ENTERPRISE_FOLDER"):
            values["ENTERPRISE_FOLDER"] = _enterprise_folder(name, env)
        if pull or not values.get("ODOO_USER"):
            values["ODOO_USER"] = odoo_user(values["ODOO_IMAGE_REF"]) or values.get("ODOO_USER", "")
        store.update_env(name, **{k: v for k, v in values.items() if env.get(k) != v})
        spec = render(name, values)
        text = odoo.compose_text(spec)
        folder = store.folder(name)
        (folder / COMPOSE).write_text(text)
        protect(name, values["ODOO_USER"])
        images = {}
        for service, key in (("odoo", "ODOO_IMAGE_REF"), ("db", "DB_IMAGE_REF")):
            image = _image(values[key])
            images[service] = image["Id"] if image else ""
        storage().put(
            COLLECTION,
            name,
            {
                "inputs": values,
                "hash": odoo.config_hash(spec),
                "spec": spec,
                "compose": text,
                "conf": (folder / CONF).read_text() if (folder / CONF).exists() else None,
                "files": {relative: _sha(folder / relative) for relative in (COMPOSE, CONF, ENV)},
                "images": images,
                "applied_at": time.time(),
            },
        )
        _SEEN.pop(name, None)
    job.write(f"Configuration {odoo.config_hash(spec)[:12]} written (hardened containers, pinned images).\n")


def protect(name: str, odoo_owner: str) -> None:
    """Instance folder 0700, .env and the compose file 0600; config/ and odoo.conf 0700/0600 owned by the Odoo
    image's user, so Odoo (which gets the folder read-only) reads its configuration and nobody else on the server
    does. When the panel does not run as root (development), odoo.conf stays readable for everyone instead."""
    folder = store.folder(name)
    os.chmod(folder, 0o700)
    for relative in (ENV, COMPOSE):
        if (folder / relative).exists():
            os.chmod(folder / relative, 0o600)
    config, conf = folder / "config", folder / CONF
    uid, _, gid = odoo_owner.partition(":")
    try:
        if not (uid.isdigit() and gid.isdigit()):
            raise PermissionError("unknown Odoo user")
        os.chown(config, int(uid), int(gid))
        if conf.exists():
            os.chown(conf, int(uid), int(gid))
            os.chmod(conf, 0o600)
        os.chmod(config, 0o700)
    except PermissionError:
        os.chmod(config, 0o755)
        if conf.exists():
            os.chmod(conf, 0o644)


def _modes(name: str, odoo_owner: str) -> list[str]:
    """Files whose protection was loosened by hand."""
    folder = store.folder(name)
    expected = {"": 0o700, ENV: 0o600, COMPOSE: 0o600}
    if os.geteuid() == 0 and odoo_owner:
        expected |= {"config": 0o700, CONF: 0o600}
    loose = []
    for relative, mode in expected.items():
        try:
            if (folder / relative).stat().st_mode & 0o777 != mode:
                loose.append(relative or "the instance folder")
        except OSError:
            continue
    return loose


# --------------------------------------------------------------------------- comparing


def _caps(values: list[str] | None) -> set[str]:
    return {value.upper().removeprefix("CAP_") for value in values or []}


def _memory(text: str | None) -> int:
    if not text or text == "0":
        return 0
    units = {"b": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
    return int(float(text[:-1]) * units[text[-1].lower()])


def _expected_mounts(name: str, service: dict[str, Any]) -> set[tuple[str, str, str, bool]]:
    found = set()
    for volume in service.get("volumes", []):
        source, destination, *mode = volume.split(":")
        if source.startswith("/"):
            found.add(("bind", source, destination, not mode))
        else:
            found.add(("volume", f"odoo-{name}_{source}", destination, True))
    return found


def compare(name: str, service: str, spec: dict[str, Any], kept: dict[str, Any], c: dict[str, Any]) -> list[str]:
    """What differs between the container `c` (docker inspect) and service `service` of the rendering."""
    want = spec["services"][service]
    host, config = c.get("HostConfig") or {}, c.get("Config") or {}
    image = image_details(c.get("Image", ""))
    labels = config.get("Labels") or {}
    differences = []

    def differs(what: str, actual: Any, expected: Any) -> None:
        if actual != expected:
            differences.append(f"{what}: {actual!r} instead of {expected!r}")

    differs("image", c.get("Image"), kept["images"].get(service))
    differs("image reference", config.get("Image"), want["image"])
    for key, value in want["labels"].items():
        differs(f"label {key}", labels.get(key), value)
    differs("privileged", bool(host.get("Privileged")), False)
    differs("dropped capabilities", sorted(_caps(host.get("CapDrop"))), ["ALL"])
    differs("added capabilities", sorted(_caps(host.get("CapAdd"))), sorted(want.get("cap_add", [])))
    differs("read-only system files", bool(host.get("ReadonlyRootfs")), True)
    differs("security options", sorted(host.get("SecurityOpt") or []), sorted(want["security_opt"]))
    differs("process limit", host.get("PidsLimit") or 0, want["pids_limit"])
    differs("memory limit", host.get("Memory") or 0, _memory(want.get("mem_limit")))
    differs("processor limit", host.get("NanoCpus") or 0, int(float(want.get("cpus", 0)) * 1e9))
    differs("restart policy", (host.get("RestartPolicy") or {}).get("Name"), want["restart"])
    differs("init process", bool(host.get("Init")), True)
    differs("devices", host.get("Devices") or [], [])
    for mode in ("PidMode", "UsernsMode", "UTSMode"):
        differs(mode, host.get(mode) or "", "")
    if (host.get("IpcMode") or "private") not in ("private", "shareable"):
        differs("IpcMode", host.get("IpcMode"), "private")
    differs("in-memory folders", sorted(host.get("Tmpfs") or {}), sorted(want.get("tmpfs", [])))
    log = host.get("LogConfig") or {}
    differs("log driver", log.get("Type"), want["logging"]["driver"])
    differs("log rotation", log.get("Config") or {}, want["logging"]["options"])
    ports = {
        port: sorted((b.get("HostIp", ""), b.get("HostPort", "")) for b in bindings or [])
        for port, bindings in (host.get("PortBindings") or {}).items()
    }
    expected_ports: dict[str, list[tuple[str, str]]] = {}
    for port in want.get("ports", []):
        address, host_port, inside = port.split(":")
        expected_ports.setdefault(f"{inside}/tcp", []).append((address, host_port))
    differs("published ports", ports, expected_ports)
    networks = sorted((c.get("NetworkSettings") or {}).get("Networks") or {})
    differs("networks", networks, sorted(f"odoo-{name}_{network}" for network in want["networks"]))
    mounts = set()
    for mount in c.get("Mounts") or []:
        anonymous = mount.get("Type") == "volume" and re.fullmatch(r"[0-9a-f]{64}", mount.get("Name", ""))
        if anonymous and mount.get("Destination") in image["volumes"]:
            continue  # an anonymous volume the image declares, for a folder the rendering does not mount
        key = mount.get("Name") if mount.get("Type") == "volume" else mount.get("Source")
        mounts.add((mount.get("Type", ""), key or "", mount.get("Destination", ""), bool(mount.get("RW"))))
    if mounts != _expected_mounts(name, want):
        added = sorted(mounts - _expected_mounts(name, want))
        missing = sorted(_expected_mounts(name, want) - mounts)
        differences.append(f"mounts: added {added or 'none'}, missing {missing or 'none'}")
    differs("user", config.get("User") or "", image["user"])
    expected_env = set(image["env"]) | {f"{key}={value}" for key, value in want["environment"].items()}
    actual_env = set(config.get("Env") or [])
    if actual_env != expected_env:
        names = sorted({entry.split("=")[0] for entry in actual_env ^ expected_env})
        differences.append(f"environment variables changed: {', '.join(names)}")
    return differences


def _connector_findings(c: dict[str, Any]) -> list[str]:
    host = c.get("HostConfig") or {}
    labels = (c.get("Config") or {}).get("Labels") or {}
    problems = []
    if host.get("Privileged"):
        problems.append("runs privileged")
    if c.get("Mounts"):
        problems.append(f"has mounts: {sorted(m.get('Destination', '') for m in c['Mounts'])}")
    if _caps(host.get("CapAdd")):
        problems.append(f"has added capabilities: {sorted(_caps(host.get('CapAdd')))}")
    if host.get("PortBindings"):
        problems.append("publishes ports")
    if labels.get(odoo.LABEL_MANAGED) == "true":  # made by this version: hardened from the start
        if _caps(host.get("CapDrop")) != {"ALL"}:
            problems.append("no longer drops every capability")
        if not host.get("ReadonlyRootfs"):
            problems.append("no longer has read-only system files")
        if "no-new-privileges:true" not in (host.get("SecurityOpt") or []):
            problems.append("may gain privileges")
    return problems


def _inspect_all() -> dict[str, dict[str, Any]]:
    """docker inspect of every container the checks look at, by name: those of the instances' Compose projects,
    those labelled as Sudoo's, and the connectors."""
    ids: set[str] = set()
    for flt in (f"label={odoo.LABEL_MANAGED}", f"label={odoo.LABEL_INSTANCE}", "label=com.docker.compose.project"):
        ids |= set(capture(["docker", "ps", "-aq", "--filter", flt]).split())
    prefix = getattr(settings, "connector_prefix", "")
    if prefix:
        ids |= set(capture(["docker", "ps", "-aq", "--filter", f"name=^{prefix}"]).split())
    if not ids:
        return {}
    found = capture(["docker", "inspect", *sorted(ids)], timeout=60)
    try:
        return {c["Name"].lstrip("/"): c for c in json.loads(found)} if found else {}
    except (ValueError, KeyError, TypeError):
        return {}


def findings(name: str, containers: dict[str, dict[str, Any]] | None = None) -> list[Finding]:
    """Every difference between what the panel applied to the instance and what is there now ([] for an instance
    the panel has not hardened yet)."""
    kept = record(name)
    if kept is None:
        return []
    containers = _inspect_all() if containers is None else containers
    found: list[Finding] = []
    folder = store.folder(name)
    with _LOCK:
        for relative in (COMPOSE, CONF, ENV):
            if _sha(folder / relative) != kept["files"].get(relative):
                # .env shapes no container (the record does) and only a person can tell which values are right
                found.append(
                    Finding("env" if relative == ENV else "files", f"{relative} was changed outside the panel")
                )
        loose = _modes(name, kept["inputs"].get("ODOO_USER", ""))
        if loose:
            found.append(Finding("files", f"protection loosened on {', '.join(loose)}"))
    spec = kept["spec"]  # what was applied; changed settings apply at the next start, they are not drift
    expected = {store.container(name, service): service for service in ("odoo", "db")}
    for container, service in expected.items():
        c = containers.get(container)
        if c is None:
            found.append(Finding(service, f"the {service} container was removed"))
            continue
        found += [Finding(service, f"{service}: {text}") for text in compare(name, service, spec, kept, c)]
    connector = _connector_name(name)
    for container in _strangers(name, containers, connector):
        found.append(Finding("stranger", f"a container that is not the panel's carries this instance's label: "
                                         f"{container}"))  # fmt: skip
    if connector and connector in containers:
        found += [
            Finding("connector", f"connector {connector} {p}") for p in _connector_findings(containers[connector])
        ]
    return found


def _connector_name(name: str) -> str | None:
    from sudoo import exposure

    provider = exposure.provider()
    container = getattr(provider, "container", None)
    if container is None:
        return None
    try:
        return str(container(exposure.target(name)))
    except (KeyError, ValueError, OSError):
        return None


# --------------------------------------------------------------------------- reacting


def check_all(force: bool = False) -> None:
    """Compare every instance that is not busy (at most every INTEGRITY_CHECK_INTERVAL seconds); report drift seen
    twice in a row, and start a repair when DRIFT_ACTION=restore."""
    global _last_check
    if not force and time.time() - _last_check < settings.integrity_check_interval_seconds:
        return
    _last_check = time.time()
    containers = _inspect_all()
    for name in store.names():
        if jobs.busy(name):
            _SEEN.pop(name, None)
            continue
        handle(name, findings(name, containers))  # [] for an instance not hardened yet


def handle(name: str, found: list[Finding]) -> None:
    signature = tuple(sorted(f.text for f in found))
    reported = STATE.get(name).get("drift")
    if not found:
        _SEEN.pop(name, None)
        if reported:
            STATE.update(name, drift=None)
            audit.record("system", None, "configuration matches the panel again", name)
            events.publish("instance", name)
        return
    if _SEEN.get(name) != signature:  # first sighting: containers may be changing state; confirm next time
        _SEEN[name] = signature
        return
    if not reported or tuple(reported.get("items", ())) != signature:
        restoring = settings.drift_action == "restore" and any(f.restorable for f in found)
        new = [item for item in signature if item not in (reported or {}).get("items", ())]
        STATE.update(
            name,
            drift={
                "found_at": (reported or {}).get("found_at") if not new else time.time(),
                "items": list(signature),
                "action": "restore" if restoring else "warn",
            },
        )
        events.publish("instance", name)
        if new:  # what was reported already (a connector that is only ever reported, say) is not sent again
            audit.record("system", None, "configuration changed outside the panel", name, ok=False,
                         detail="; ".join(new))  # fmt: skip
            threading.Thread(target=_notify, args=(name, new), daemon=True, name="drift-mail").start()
    _maybe_repair(name, found, signature)


def _maybe_repair(name: str, found: list[Finding], signature: tuple[str, ...]) -> None:
    if settings.drift_action != "restore" or not any(f.restorable for f in found) or jobs.busy(name):
        return
    attempted = _ATTEMPTED.get(name)
    if attempted and attempted[0] == signature and time.time() - attempted[1] < _REPAIR_RETRY_SECONDS:
        return  # tried already for these very differences; again after a while, or when they change
    _ATTEMPTED[name] = (signature, time.time())
    from sudoo.instances import operations

    jobs.start(name, "Restore the panel's configuration", "repair", operations.repair, name, user="system")


def _notify(name: str, items: list[str]) -> None:
    """E-mail every super admin who has an address."""
    from sudoo import accounts
    from sudoo.mail import MailError, send_template

    action = "restore" if settings.drift_action == "restore" else "warn"
    for account in accounts.all_users().values():
        if account.get("role") != "super_admin" or not account.get("email"):
            continue
        try:
            send_template(
                account["email"],
                "drift",
                f"Sudoo.sh: instance {name} was changed outside the panel",
                preheader=f"Someone changed {name} by hand.",
                instance=name,
                items=items,
                action=action,
            )
        except (MailError, OSError) as error:
            print("drift e-mail:", repr(error), flush=True)


def _strangers(name: str, containers: dict[str, dict[str, Any]], connector: str | None) -> list[str]:
    """Running containers that carry the instance's label or Compose project but are neither its odoo and db nor its
    connector (a stopped one can do nothing; the panel stops them and keeps them for whoever looks into it)."""
    own = {store.container(name, service) for service in ("odoo", "db")} | ({connector} if connector else set())
    found = []
    for container, c in sorted(containers.items()):
        labels = (c.get("Config") or {}).get("Labels") or {}
        ours = labels.get(odoo.LABEL_INSTANCE) == name or labels.get("com.docker.compose.project") == f"odoo-{name}"
        running = (c.get("State") or {}).get("Running") or (c.get("State") or {}).get("Restarting")
        if ours and container not in own and running:
            found.append(container)
    return found


def stop_strangers(job: Job, name: str) -> list[str]:
    """Stop containers that pretend to belong to the instance (they are kept, stopped, for whoever looks into it)."""
    stopped = []
    for container in _strangers(name, _inspect_all(), _connector_name(name)):
        job.run_unchecked(["docker", "update", "--restart", "no", container])
        job.run_unchecked(["docker", "stop", container], timeout=120)
        stopped.append(container)
    return stopped


def accept_env(name: str) -> None:
    """Take the .env as it is now (after a repair reported it): the values that shape the containers still come from
    the record."""
    note_written(name, ENV)
