"""Talking to the hub: this installation's identity, the hub keys it trusts, and signed, verified HTTP exchanges.

Identity
    On first use the panel makes an installation id (a UUID) and an Ed25519 key pair. The private key is kept in
    the panel's storage, encrypted with the vault key (core/vault.py); the public key is registered with the hub.
    Every request is signed with that key (crypto.signed_headers), so every answer can be signed back.

Hub keys
    The panel starts from root keys: HUB_PUBLIC_KEYS, else the keys this release ships for hub.sudoo.sh, else (for
    another hub, while testing) the hub's keys as first seen. GET /api/v1/keys lists the hub's keys with their
    state; the panel accepts a key that is `active`, or `retiring` until its `not_after`, drops a `revoked` or
    `expired` one at once, and trusts a key it did not know only when its endorsement (signed by the key active
    before it) verifies with a key it already trusts and that is not revoked. Leases, answers, commands and
    packages are verified only with accepted keys.

Answers
    Every answer (refusals and package downloads included) must carry a valid Sudoo-Signature from an accepted key,
    made at most 5 minutes from this server's clock, over the request's method, path, installation and nonce, the
    status and the body's SHA-256 (crypto.verify_answer). An answer signed with a key the panel does not know yet
    makes it read the hub's keys once and check again. Anything else is treated as a failure (UnverifiedAnswer).

A 401 `key_revoked` (the account owner revoked this server's key on app.sudoo.sh) makes the panel stop using its
id and key: it makes a new identity, which registers again and must be linked again.

Every failure to reach the hub (no network, timeout, a 5xx answer, an answer that is not JSON or not verified)
raises HubUnavailable, so callers can say "the marketplace cannot be reached" and carry on. A refusal (4xx)
raises HubRefused with the hub's message and code.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from sudoo.config import PACKAGE_DIR, settings
from sudoo.core import vault
from sudoo.storage import storage

from . import crypto

COLLECTION = "marketplace"
TIMEOUT_SECONDS = 15
MAX_JSON_BYTES = 4 * 1024 * 1024
KEY_STATES = ("active", "retiring", "revoked", "expired")
DEFAULT_HUB = "https://hub.sudoo.sh"
# The root keys this release trusts for hub.sudoo.sh (base64url Ed25519 public keys). Filled in by the release that
# opens the marketplace; while it is empty, HUB_PUBLIC_KEYS or the keys first seen are used.
SHIPPED_KEYS: dict[str, tuple[str, ...]] = {DEFAULT_HUB: ()}
MACHINE_ID_FILES = ("/host/etc/machine-id", "/etc/machine-id", "/var/lib/dbus/machine-id")
_LOCK = threading.RLock()


class HubUnavailable(Exception):
    """The hub cannot be reached right now (or sent an answer the panel cannot trust)."""


class UnverifiedAnswer(HubUnavailable):
    """The hub's answer did not carry a valid signature from a key the panel accepts: it is not believed."""


class HubRefused(Exception):
    """The hub answered with a refusal (4xx): `status`, `code` (when the hub gives one) and `detail`."""

    def __init__(self, status: int, detail: str, code: str | None = None) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.code = code


def hub_url() -> str:
    return settings.hub_url.rstrip("/")


def root_keys() -> list[str]:
    """The keys the panel trusts for the hub before anything else: HUB_PUBLIC_KEYS, else the shipped ones."""
    configured = [key for key in settings.hub_public_keys.split(",") if key]
    return configured or list(SHIPPED_KEYS.get(hub_url(), ()))


# ---------------------------------------------------------------- identity


@dataclass(frozen=True)
class Identity:
    installation_id: str
    key: Ed25519PrivateKey
    public_key: str
    hub_url: str | None  # the hub the keys below belong to
    hub_keys: dict[str, dict[str, Any]]  # key id -> {public_key, state, not_after, source}
    registered_at: float | None

    def known(self) -> dict[str, dict[str, Any]]:
        """The trusted keys of the hub the panel uses now (none when they belong to another hub)."""
        return self.hub_keys if self.hub_url == hub_url() else {}

    def pinned(self, now: float | None = None) -> dict[str, Ed25519PublicKey]:
        """The hub keys accepted now: active, or retiring before their not_after."""
        now = time.time() if now is None else now
        accepted: dict[str, Ed25519PublicKey] = {}
        for kid, entry in self.known().items():
            not_after = entry.get("not_after")
            usable = entry["state"] == "active" or (entry["state"] == "retiring" and not_after and now < not_after)
            if usable:
                accepted[kid] = crypto.public_key_from_b64url(entry["public_key"])
        return accepted


def _label(installation_id: str) -> str:
    return f"hub-identity:{installation_id}"


def _new_identity(previous: dict[str, Any] | None = None) -> dict[str, Any]:
    installation_id = str(uuid.uuid4())
    key = Ed25519PrivateKey.generate()
    doc: dict[str, Any] = {
        "installation_id": installation_id,
        "public_key": crypto.public_key_b64url(key.public_key()),
        "private_key": vault.encrypt(crypto.private_key_bytes(key), _label(installation_id)),
        "created_at": time.time(),
        "hub_url": None,
        "hub_keys": {},
        "registered_at": None,
    }
    if previous:  # the hub keys stay trusted; the old ids are kept for the record
        doc["hub_url"], doc["hub_keys"] = previous.get("hub_url"), previous.get("hub_keys") or {}
        doc["replaced"] = [*(previous.get("replaced") or []), previous["installation_id"]][-10:]
    return doc


def _normalise_keys(raw: Any) -> dict[str, dict[str, Any]]:
    """Key entries as stored; an older panel stored {key id: public key}."""
    keys: dict[str, dict[str, Any]] = {}
    for kid, entry in (raw or {}).items():
        if isinstance(entry, str):
            entry = {"public_key": entry, "state": "active", "not_after": None, "source": "first-use"}
        if isinstance(entry, dict) and entry.get("state") in KEY_STATES and isinstance(entry.get("public_key"), str):
            keys[str(kid)] = entry
    return keys


def identity() -> Identity:
    """This installation's identity, made (and stored) the first time it is needed."""
    with _LOCK:
        doc = storage().get(COLLECTION, "identity")
        if doc is None:
            doc = _new_identity()
            storage().put(COLLECTION, "identity", doc)
        raw = vault.decrypt_bytes(doc["private_key"], _label(doc["installation_id"]))
        return Identity(
            installation_id=doc["installation_id"],
            key=Ed25519PrivateKey.from_private_bytes(raw),
            public_key=doc["public_key"],
            hub_url=doc.get("hub_url"),
            hub_keys=_normalise_keys(doc.get("hub_keys")),
            registered_at=doc.get("registered_at"),
        )


def update_identity(**values: Any) -> None:
    def change(doc: dict[str, Any] | None) -> dict[str, Any]:
        if doc is None:
            raise RuntimeError("no identity yet")
        return {**doc, **values}

    with _LOCK:
        storage().change(COLLECTION, "identity", change)


def replace_identity(revoked_id: str) -> None:
    """The hub says this installation's key was revoked: make a new id and key pair (once for that id)."""

    def change(doc: dict[str, Any] | None) -> dict[str, Any]:
        if doc is None or doc["installation_id"] != revoked_id:
            return doc or _new_identity()  # already replaced by another thread
        return _new_identity(doc)

    with _LOCK:
        storage().change(COLLECTION, "identity", change)


# ---------------------------------------------------------------- the server: fingerprint, version, core hash


def machine_id() -> str:
    """The host's machine id (inside the container, the host's file mounted read-only at /host/etc/machine-id);
    empty when none can be read."""
    for path in MACHINE_ID_FILES:
        try:
            value = Path(path).read_text(encoding="ascii", errors="replace").strip()
        except OSError:
            continue
        if value:
            return value
    return ""


def primary_mac(net: Path = Path("/sys/class/net"), routes: Path = Path("/proc/net/route")) -> str:
    """The MAC address of the interface that holds the default route (lower case, colon-separated); else the
    first physical-looking interface's, by name; empty when none is found."""

    def address(interface: str) -> str:
        try:
            value = (net / interface / "address").read_text().strip().lower()
        except OSError:
            return ""
        valid = re.fullmatch(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}", value) and value != "00:00:00:00:00:00"
        return value if valid else ""

    try:
        for line in routes.read_text().splitlines()[1:]:
            fields = line.split()
            if len(fields) > 2 and fields[1] == "00000000" and (found := address(fields[0])):
                return found
    except OSError:
        pass
    try:
        interfaces = sorted(entry.name for entry in net.iterdir())
    except OSError:
        return ""
    for interface in interfaces:
        virtual = interface == "lo" or interface.startswith(("docker", "br-", "veth", "virbr"))
        if not virtual and (found := address(interface)):
            return found
    return ""


def hardware_fingerprint(public_key: str) -> str:
    """What the hub compares at every heartbeat to tell this server from a copy of its files on another machine
    (the hub keeps only a keyed digest of it)."""
    return crypto.fingerprint(public_key, machine_id(), primary_mac())


def core_hash() -> str:
    """SHA-256 over the panel's own Python files (relative path and content of each, in path order): what the hub
    compares with the hash of the released version."""
    digest = hashlib.sha256()
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        digest.update(path.relative_to(PACKAGE_DIR).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def sudoo_version() -> str:
    return version("sudoo")


# ---------------------------------------------------------------- HTTP


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None  # a redirect is handled by the caller, who decides what to send where


_OPENER = urllib.request.build_opener(_NoRedirect)


@dataclass(frozen=True)
class Answer:
    status: int
    headers: Mapping[str, str]
    data: Any


@dataclass(frozen=True)
class _Sent:
    """What the panel signed, to check the answer against it."""

    method: str
    path: str
    installation_id: str
    nonce: str


def _problem(status: int, body: bytes) -> HubRefused:
    try:
        problem = json.loads(body)
    except ValueError:
        problem = {}
    if not isinstance(problem, dict):
        problem = {}
    detail = str(problem.get("detail") or problem.get("title") or f"The marketplace refused the request ({status}).")
    code = problem.get("code")
    return HubRefused(status, detail[:500], str(code) if code else None)


def _open(request: urllib.request.Request, timeout: float) -> Any:
    try:
        return _OPENER.open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        return error  # an HTTPError is also the response (status, headers, body)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise HubUnavailable(f"The marketplace ({urlsplit(hub_url()).netloc}) cannot be reached.") from error


def _send(method: str, path: str, data: bytes | None, timeout: float, me: Identity | None = None) -> tuple[Any, _Sent]:
    """Open a signed request (`path` starts with /api/v1); the response is not read yet."""
    me = me or identity()
    body = data or b""
    signed = crypto.signed_headers(me.key, me.installation_id, method, path, body, int(time.time()))
    req = urllib.request.Request(hub_url() + path, data=data, method=method)
    headers = {"Accept": "application/json", "User-Agent": f"sudoo/{sudoo_version()}", **signed}
    if data is not None:
        headers["Content-Type"] = "application/json"
    for name, value in headers.items():
        req.add_header(name, value)
    sent = _Sent(method, path, me.installation_id, signed["X-Sudoo-Nonce"])
    return _open(req, timeout), sent


def _check(sent: _Sent, status: int, headers: Mapping[str, str], body_sha256: str) -> None:
    """The answer must be signed by an accepted hub key; an unknown key id makes the panel read the hub's keys
    once (a rotation) and check again. Raises UnverifiedAnswer."""
    header = headers.get(crypto.RESPONSE_HEADER.lower())
    for attempt in (1, 2):
        try:
            crypto.verify_answer(
                identity().pinned(),
                header,
                method=sent.method,
                path_with_query=sent.path,
                installation_id=sent.installation_id,
                nonce=sent.nonce,
                status=status,
                body_sha256=body_sha256,
                now=time.time(),
            )
            return
        except crypto.AnswerError as error:
            if attempt == 1 and error.unknown_key and sent.path != KEYS_PATH:
                try:
                    refresh_keys()
                    continue
                except HubUnavailable:
                    pass
            raise UnverifiedAnswer(f"The marketplace's answer was not accepted: {error}.") from error


def _exchange(
    method: str, path: str, body: Any = None, timeout: float = TIMEOUT_SECONDS
) -> tuple[int, dict[str, str], bytes, _Sent]:
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode()
    response, sent = _send(method, path, data, timeout)
    with response:
        status = response.status
        raw = response.read(MAX_JSON_BYTES + 1)
        headers = {k.lower(): v for k, v in response.headers.items()}
    if status >= 500 or len(raw) > MAX_JSON_BYTES:
        raise HubUnavailable("The marketplace is not answering properly right now. Try again later.")
    return status, headers, raw, sent


def _refused(status: int, raw: bytes, sent: _Sent) -> HubRefused:
    refusal = _problem(status, raw)
    if status == 401 and refusal.code == "key_revoked":
        replace_identity(sent.installation_id)
    return refusal


def request(method: str, path: str, body: Any = None, *, timeout: float = TIMEOUT_SECONDS) -> Answer:
    """Call the hub (`path` starts with /api/v1); JSON in and out, signed both ways. Raises HubUnavailable (also
    for an answer that is not verified) or HubRefused (a verified refusal)."""
    status, headers, raw, sent = _exchange(method, path, body, timeout)
    _check(sent, status, headers, hashlib.sha256(raw).hexdigest())
    if status >= 400:
        raise _refused(status, raw, sent)
    try:
        parsed = json.loads(raw) if raw else None
    except ValueError as error:
        raise HubUnavailable("The marketplace sent an answer the panel does not understand.") from error
    payload = parsed.get("data") if isinstance(parsed, dict) and "data" in parsed else parsed
    if isinstance(parsed, dict) and "meta" in parsed:
        headers = {**headers, "x-sudoo-meta": json.dumps(parsed["meta"])}
    return Answer(status, headers, payload)


def get(path: str) -> Any:
    return request("GET", path).data


def fetch_bytes(path: str, max_bytes: int, timeout: float = TIMEOUT_SECONDS) -> tuple[bytes, str]:
    """A small signed GET that is not JSON (a plugin icon): (bytes, content type). Raises like request()."""
    response, sent = _send("GET", path, None, timeout)
    with response:
        status = response.status
        raw = response.read(max_bytes + 1)
        headers = {k.lower(): v for k, v in response.headers.items()}
    if status >= 500:
        raise HubUnavailable("The marketplace is not answering properly right now. Try again later.")
    if len(raw) > max_bytes:
        raise HubRefused(413, "The marketplace sent more than the panel accepts.")
    _check(sent, status, headers, hashlib.sha256(raw).hexdigest())
    if status >= 400:
        raise _refused(status, raw, sent)
    return raw, headers.get("content-type", "").split(";")[0].strip().lower()


def download(path: str, target: Path, max_bytes: int, timeout: float = 120) -> dict[str, str]:
    """A signed GET of a package into `target` (created mode 600); returns the hub's headers (lower-case names).
    The hub signs a download over its X-Sudoo-Package-SHA256 (the caller checks the bytes against it). A redirect
    to a short-lived storage link (https only) is signed like any answer and followed without the signature
    headers."""
    response, sent = _send("GET", path, None, timeout)
    status = response.status
    hub_headers = {k.lower(): v for k, v in response.headers.items()}
    if status >= 500:
        response.close()
        raise HubUnavailable("The marketplace is not answering properly right now. Try again later.")
    if status != 200:
        with response:
            raw = response.read(MAX_JSON_BYTES)
        _check(sent, status, hub_headers, hashlib.sha256(raw).hexdigest())
        if status >= 400:
            raise _refused(status, raw, sent)
        if status not in (301, 302, 303, 307, 308):
            raise HubUnavailable("The marketplace sent an answer the panel does not understand.")
        location = hub_headers.get("location", "")
        if urlsplit(location).scheme != "https" and urlsplit(hub_url()).scheme == "https":
            raise HubUnavailable("The marketplace sent the package from an address that is not https.")
        response = _open(urllib.request.Request(location, method="GET"), timeout)
        if response.status != 200:
            response.close()
            raise HubUnavailable("The package could not be downloaded. Try again later.")
    else:
        stated = hub_headers.get("x-sudoo-package-sha256", "").lower()
        if not crypto.SHA256_RE.match(stated):
            response.close()
            raise UnverifiedAnswer("The marketplace's answer was not accepted: the package has no stated SHA-256.")
        try:
            _check(sent, status, hub_headers, stated)
        except UnverifiedAnswer:
            response.close()
            raise
    with response:
        written = 0
        with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as fd:
            while chunk := response.read(256 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HubRefused(413, "The package is larger than the panel accepts.")
                fd.write(chunk)
    return hub_headers


# ---------------------------------------------------------------- the hub's keys

KEYS_PATH = "/api/v1/keys"


def _unix(value: Any) -> float | None:
    """An ISO 8601 date (or Unix seconds) of the hub, as Unix seconds."""
    if value is None:
        return None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    try:
        from datetime import datetime

        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _listed(item: Any) -> dict[str, Any] | None:
    """One entry of GET /api/v1/keys, checked: its key id must be the hub's name for its public key."""
    if not isinstance(item, dict) or item.get("algorithm", "Ed25519") != "Ed25519":
        return None
    try:
        public = crypto.public_key_from_b64url(str(item.get("public_key", "")))
    except ValueError:
        return None
    kid = crypto.key_id(public)
    if item.get("key_id") not in (None, kid):
        return None
    state = item.get("state") or "active"
    return {
        "key_id": kid,
        "public_key": crypto.public_key_b64url(public),
        "state": state if state in KEY_STATES else "revoked",
        "not_before": _unix(item.get("not_before")),
        "not_after": _unix(item.get("not_after")),
        "endorsed_by": item.get("endorsed_by"),
        "endorsement": item.get("endorsement"),
    }


def trusted_after(
    known: dict[str, dict[str, Any]], listed: list[dict[str, Any]], now: float
) -> dict[str, dict[str, Any]]:
    """The trusted keys once the hub's list is applied: revocations and expiries first (at once), then states and
    dates of known keys, then new keys whose endorsement verifies with a trusted key that is not revoked (repeated,
    so a chain of rotations is followed)."""
    trusted = {kid: dict(entry) for kid, entry in known.items()}
    by_id = {entry["key_id"]: entry for entry in listed}
    for kid, entry in by_id.items():
        if kid in trusted and trusted[kid]["public_key"] == entry["public_key"]:
            if trusted[kid]["state"] != "revoked":  # a revoked key is never trusted again
                trusted[kid].update(state=entry["state"], not_after=entry["not_after"])
            if entry["state"] == "retiring" and entry["not_after"] and entry["not_after"] <= now:
                trusted[kid]["state"] = "expired"
    changed = True
    while changed:
        changed = False
        for kid, entry in by_id.items():
            if kid in trusted or entry["state"] not in ("active", "retiring"):
                continue
            if entry["state"] == "retiring" and (not entry["not_after"] or entry["not_after"] <= now):
                continue
            endorser = trusted.get(str(entry.get("endorsed_by")))
            if endorser is None or endorser["state"] == "revoked" or entry["not_before"] is None:
                continue
            try:
                signature = crypto.from_b64url(str(entry.get("endorsement") or ""))
            except ValueError:
                continue
            message = crypto.endorsement_message(kid, entry["public_key"], int(entry["not_before"]))
            if crypto.verify(crypto.public_key_from_b64url(endorser["public_key"]), signature, message):
                trusted[kid] = {"public_key": entry["public_key"], "state": entry["state"],
                                "not_after": entry["not_after"], "source": "endorsed"}  # fmt: skip
                changed = True
    return trusted


def refresh_keys() -> Identity:
    """Read the hub's keys (GET /api/v1/keys, signed both ways) and apply them to the trusted ones. The first time
    for a hub, the root keys are the start; without root keys, the keys the hub lists as active (first use)."""
    with _LOCK:
        me = identity()
        status, headers, raw, sent = _exchange("GET", KEYS_PATH)
        try:
            items = json.loads(raw).get("data") if status == 200 else None
        except (ValueError, AttributeError):
            items = None
        if not isinstance(items, list):
            raise HubUnavailable("The marketplace did not send its keys.")
        listed = [entry for entry in map(_listed, items) if entry is not None]
        known = me.known()
        if not known:
            roots = root_keys()
            if roots:
                known = {crypto.key_id(crypto.public_key_from_b64url(key)): {"public_key": key, "state": "active",
                         "not_after": None, "source": "root"} for key in roots}  # fmt: skip
            else:
                known = {e["key_id"]: {"public_key": e["public_key"], "state": "active", "not_after": None,
                         "source": "first-use"} for e in listed if e["state"] == "active"}  # fmt: skip
        trusted = trusted_after(known, listed, time.time())
        candidate = Identity(me.installation_id, me.key, me.public_key, hub_url(), trusted, me.registered_at)
        try:  # the list itself must be signed by a key it leaves trusted
            crypto.verify_answer(
                candidate.pinned(),
                headers.get(crypto.RESPONSE_HEADER.lower()),
                method=sent.method,
                path_with_query=sent.path,
                installation_id=sent.installation_id,
                nonce=sent.nonce,
                status=status,
                body_sha256=hashlib.sha256(raw).hexdigest(),
                now=time.time(),
            )
        except crypto.AnswerError as error:
            # a list the panel cannot verify still takes trust away (a revoked or expired key), never adds any
            ended = [e for e in listed if e["key_id"] in known and e["state"] in ("revoked", "expired")]
            if ended and me.known():
                update_identity(hub_keys=trusted_after(known, ended, time.time()))
            raise UnverifiedAnswer(f"The marketplace's keys were not accepted: {error}.") from error
        if not candidate.pinned():
            raise UnverifiedAnswer("The marketplace has no key this panel can trust.")
        values: dict[str, Any] = {"hub_keys": trusted, "keys_checked_at": time.time()}
        if me.hub_url != hub_url():  # another hub: register with it again
            values |= {"hub_url": hub_url(), "registered_at": None}
        update_identity(**values)
        return identity()
