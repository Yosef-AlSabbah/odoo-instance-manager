"""A small stand-in for hub.sudoo.sh, served on 127.0.0.1 for the tests.

It speaks the hub's panel contract v2 (sudoo-hub README: "Signed panel requests", "Signed answers", "Signing keys",
"Leases", "Linking", "Panel contract"): it checks every signed request the way the hub does (Ed25519 over method,
path, installation, timestamp, nonce and body hash; 5-minute window; nonces once; a current lease for
/installations/*) and **signs every answer** to a signed request (refusals and package downloads included) with its
active key. It lists its keys with states and endorsements and can rotate or revoke them; registers installations
with their fingerprint, flags a heartbeat from another machine, answers heartbeats with 72-hour EdDSA leases
(licences with run_until and perpetual, commands, flags), links and unlinks (queueing a signed remove_paid_plugins
command), takes acknowledgements, revokes keys (401 key_revoked), serves the panel catalogue with each plugin's
action, plans with monthly equivalents and savings, icons and recommendations, the billing context, install answers
and signed packages (optionally through a redirect, as with S3), and opens checkout sessions that the test then pays,
declines, cancels or lets expire. It is written apart from the panel's code, so the tests check both sides agree.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

LEASE_HOURS = 72
OFFLINE_GRACE_HOURS = 96


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def raw_public(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def iso(timestamp: float | None) -> str | None:
    return None if timestamp is None else datetime.fromtimestamp(timestamp, UTC).isoformat()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def make_package(
    plugin_id: str,
    version: str,
    *,
    module: str = "hello_plugin",
    group: str = "sudoo.mailers",
    entry: str = "hello-mail",
    tier: str = "free",
    extra: dict[str, bytes] | None = None,
    manifest: dict[str, Any] | None = None,
) -> bytes:
    """A .sudoo package (zip): manifest.json, pyproject.toml and a module with one plugin class."""
    data = {
        "id": plugin_id,
        "name": "Hello mailer",
        "version": version,
        "sdk_version": ">=0.1.0",
        "min_sudoo_version": "0.1.0",
        "author": {"name": "Test"},
        "description": "A mailer that only says hello, for tests.",
        "license": "MIT",
        "type": "mailer",
        "entry_points": {group: {entry: f"{module}.plugin:Hello"}},
        "permissions": [],
        "tier": tier,
        **({"price": 500} if tier == "paid" else {}),
        **(manifest or {}),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(data))
        archive.writestr("pyproject.toml", f'[project]\nname = "{module}"\nversion = "{version}"\n')
        archive.writestr(f"{module}/__init__.py", "")
        archive.writestr(
            f"{module}/plugin.py",
            "class Hello:\n"
            "    ready = True\n"
            "    def __init__(self, settings):\n"
            "        self.settings = settings\n"
            f"    version = {version!r}\n",
        )
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    return buffer.getvalue()


def plan(kind: str, price_cents: int, **extra: Any) -> dict[str, Any]:
    """A plan as the hub lists it (with its interval, monthly equivalent; savings are filled in by the listing)."""
    interval = {"monthly": "month", "yearly": "year", "fixed_term": "days", "one_time": None}[kind]
    monthly = {"monthly": price_cents, "yearly": round(price_cents / 12), "one_time": None}.get(kind)
    if kind == "fixed_term":
        monthly = round(price_cents * (365.25 / 12) / extra.get("period_days", 30))
    return {"id": str(uuid.uuid4()), "kind": kind, "price_cents": price_cents, "currency": "usd",
            "period_days": extra.get("period_days"), "interval": interval, "perpetual": kind == "one_time",
            "monthly_equivalent_cents": monthly, "savings_percent": None, **extra}  # fmt: skip


@dataclass
class Listing:
    id: str
    name: str
    tier: str = "free"
    type: str = "mailer"
    versions: dict[str, bytes] = field(default_factory=dict)
    plans: list[dict[str, Any]] = field(default_factory=list)
    publisher: dict[str, Any] = field(
        default_factory=lambda: {"name": "Sudoo.sh", "slug": "sudoo", "verified": True, "official": True}
    )
    icon: bytes | None = None
    countries: list[str] = field(default_factory=list)

    @property
    def latest(self) -> str:
        return sorted(self.versions, key=lambda v: tuple(int(p) for p in v.split(".")))[-1]


@dataclass
class HubKey:
    private: Ed25519PrivateKey
    state: str = "active"
    not_before: int = field(default_factory=lambda: int(time.time()) - 60)
    not_after: int | None = None
    endorsed_by: str | None = None
    endorsement: str | None = None

    @property
    def public(self) -> str:
        return b64url(raw_public(self.private.public_key()))

    @property
    def key_id(self) -> str:
        return hashlib.sha256(raw_public(self.private.public_key())).hexdigest()[:16]

    def sign(self, message: bytes) -> str:
        return b64url(self.private.sign(message))


class FakeHub:
    def __init__(self) -> None:
        self.keys: list[HubKey] = [HubKey(Ed25519PrivateKey.generate())]
        self.installations: dict[str, Ed25519PublicKey] = {}
        self.fingerprints: dict[str, str] = {}
        self.flagged: set[str] = set()
        self.revoked: set[str] = set()
        self.nonces: set[tuple[str, str]] = set()
        self.listings: dict[str, Listing] = {}
        self.licences: dict[str, dict[str, Any]] = {}  # plugin id -> {state, expires_at, grace_until, perpetual}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.receipts: list[dict[str, Any]] = []
        self.commands: dict[str, dict[str, Any]] = {}  # id -> {kind, issued_at, payload, acked}
        self.acks: list[tuple[str, dict[str, Any]]] = []
        self.views: list[str] = []
        self.reported: dict[str, str] = {}  # plugin id -> version, from the last heartbeat
        self.heartbeat_seen = False
        self.link_codes = {"LINKCODE42": "Ada's company"}
        self.linked: str | None = None
        self.payments_enabled = True
        self.heartbeat_refusal: str | None = None  # e.g. "integrity_violation"
        self.tamper_downloads = False
        self.redirect_downloads = False
        self.unsigned_answers = False  # an answer without Sudoo-Signature, as if from a proxy in between
        self.answer_skew = 0  # seconds added to the signed time of answers
        self.now: float | None = None  # the hub's clock for leases (None: real time)
        self.heartbeats: list[dict[str, Any]] = []
        self.requests: list[str] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> FakeHub:
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def publish(self, listing: Listing) -> Listing:
        monthly = next((p["price_cents"] for p in listing.plans if p["kind"] == "monthly"), None)
        for item in listing.plans:  # the hub's savings_percent: saved against the monthly plan
            if monthly and item["kind"] != "monthly" and item["monthly_equivalent_cents"]:
                saved = round(100 * (monthly - item["monthly_equivalent_cents"]) / monthly)
                item["savings_percent"] = saved if saved > 0 else None
        self.listings[listing.id] = listing
        return listing

    # ------------------------------------------------------------ keys

    @property
    def key(self) -> HubKey:
        return next(k for k in self.keys if k.state == "active")

    @property
    def key_id(self) -> str:
        return self.key.key_id

    def rotate(self, *, revoke_previous: bool = False, endorse: bool = True) -> HubKey:
        """`sudoo-hub keys rotate`: a new active key endorsed by the previous one, which retires (or is revoked)."""
        previous = self.key
        previous.state = "revoked" if revoke_previous else "retiring"
        previous.not_after = int(time.time()) + 30 * 86400
        new = HubKey(Ed25519PrivateKey.generate(), not_before=int(time.time()), endorsed_by=previous.key_id)
        message = "\n".join(("sudoo-hub-key-v1", new.key_id, new.public, str(new.not_before))).encode()
        new.endorsement = previous.sign(message) if endorse else b64url(b"\0" * 64)
        self.keys.append(new)
        return new

    def keys_out(self) -> list[dict[str, Any]]:
        now = time.time()
        return [{"algorithm": "Ed25519", "key_id": k.key_id, "public_key": k.public,
                 "state": "expired" if k.state == "retiring" and k.not_after and k.not_after <= now else k.state,
                 "not_before": iso(k.not_before), "not_after": iso(k.not_after), "revoked_at": None,
                 "endorsed_by": k.endorsed_by, "endorsement": k.endorsement} for k in self.keys]  # fmt: skip

    # ------------------------------------------------------------ the hub's rules

    def _clock(self) -> float:
        return self.now if self.now is not None else time.time()

    def standing(self, plugin_id: str, installation: str | None = None) -> str:
        listing = self.listings.get(plugin_id)
        if listing is None:
            return "unknown"
        if listing.tier == "free":
            return "free"
        if installation in self.flagged:
            return "blocked"
        licence = self.licences.get(plugin_id)
        if licence is None or licence["state"] == "revoked":
            return "unlicensed"
        if licence.get("perpetual"):
            return "licensed"
        now = self._clock()
        end = licence.get("grace_until") or licence.get("expires_at") or now + 1
        in_grace = licence.get("expires_at") and licence["expires_at"] <= now < end
        return "grace" if in_grace else "licensed" if now < end else "expired"

    def usable(self, plugin_id: str) -> bool:
        return self.standing(plugin_id) in ("licensed", "grace")

    def lease_licences(self, installation: str, expires: int) -> dict[str, dict[str, Any]]:
        if installation in self.flagged:
            return {}
        out = {}
        for plugin_id, licence in self.licences.items():
            if licence["state"] == "revoked":
                continue
            end = licence.get("grace_until") or licence.get("expires_at")
            offline = expires + (OFFLINE_GRACE_HOURS * 3600 if self.usable(plugin_id) else 0)
            out[plugin_id] = {"state": licence["state"], "expires_at": licence.get("expires_at"),
                              "grace_until": licence.get("grace_until"), "perpetual": bool(licence.get("perpetual")),
                              "run_until": offline if end is None else min(offline, int(end))}  # fmt: skip
        return out

    def command_out(self, command_id: str, installation: str) -> dict[str, Any]:
        command = self.commands[command_id]
        digest = hashlib.sha256(canonical(command["payload"])).hexdigest()
        message = "\n".join(("sudoo-hub-command-v1", command_id, installation, command["kind"],
                             str(command["issued_at"]), digest)).encode()  # fmt: skip
        return {"id": command_id, "kind": command["kind"], "issued_at": iso(command["issued_at"]),
                "payload": command["payload"], "key_id": self.key_id, "signature": self.key.sign(message)}  # fmt: skip

    def pending(self, installation: str) -> list[str]:
        return [cid for cid, c in self.commands.items() if c["installation"] == installation and not c["acked"]]

    def lease(self, installation_id: str, plugins: list[dict[str, str]]) -> tuple[str, dict[str, Any]]:
        now = int(self._clock())
        expires = now + LEASE_HOURS * 3600
        licences = self.lease_licences(installation_id, expires)
        flags = ["fingerprint_mismatch"] if installation_id in self.flagged else []
        commands = [{**self.commands[cid], "id": cid} for cid in self.pending(installation_id)]
        header = {"alg": "EdDSA", "kid": self.key_id, "typ": "sudoo-lease+jwt"}
        claims = {
            "iss": self.url,
            "aud": f"sudoo-panel:{installation_id}",
            "sub": installation_id,
            "iat": now,
            "nbf": now,
            "exp": expires,
            "jti": uuid.uuid4().hex,
            "status": "active",
            "plugins": {item["id"]: self.standing(item["id"], installation_id) for item in plugins},
            "licenses": licences,  # every licence held, installed or not
            "commands": [{"id": c["id"], "kind": c["kind"], "issued_at": c["issued_at"], "payload": c["payload"]}
                         for c in commands],  # fmt: skip
            "flags": flags,
            "next_heartbeat": now + 900,
        }
        signing_input = f"{b64url(json.dumps(header).encode())}.{b64url(json.dumps(claims).encode())}"
        return f"{signing_input}.{self.key.sign(signing_input.encode())}", {"licenses": licences, "flags": flags}

    def sign_package(self, plugin_id: str, version: str, package: bytes) -> tuple[str, str]:
        sha = hashlib.sha256(package).hexdigest()
        message = b"\n".join((b"sudoo-plugin-v1", plugin_id.encode(), version.encode(), sha.encode()))
        return sha, self.key.sign(message)

    def install_info(self, listing: Listing, version: str) -> dict[str, Any]:
        sha, signature = self.sign_package(listing.id, version, listing.versions[version])
        return {"plugin_id": listing.id, "version": version, "tier": listing.tier,
                "download_path": f"/api/v1/catalog/{listing.id}/download/{version}", "package_sha256": sha,
                "package_size": len(listing.versions[version]), "signature": signature,
                "signing_key_id": self.key_id, "requires": [], "license": self.licences.get(listing.id)}  # fmt: skip

    def unlink(self, installation: str, reason: str = "unlinked") -> None:
        """What the hub does on POST /unlink or DELETE /account/installations/{id}."""
        paid = sorted(self.licences)
        for licence in self.licences.values():
            licence["state"] = "revoked"
        self.linked = None
        command_id = str(uuid.uuid4())
        self.commands[command_id] = {"kind": "remove_paid_plugins", "issued_at": int(time.time()),
                                     "payload": {"plugins": paid, "reason": reason}, "acked": False,
                                     "installation": installation}  # fmt: skip

    # ------------------------------------------------------------ checkout sessions (paid on app.sudoo.sh)

    def pay(self, session_id: str) -> None:
        """The account owner paid on the checkout page: the licence and the receipt exist."""
        session = self.sessions[session_id]
        now = int(self._clock())
        perpetual = session["plan_kind"] == "one_time"
        licence = {"state": "active", "perpetual": perpetual,
                   "expires_at": None if perpetual else now + 30 * 86400,
                   "grace_until": None if perpetual else now + 37 * 86400}  # fmt: skip
        self.licences[session["plugin_id"]] = licence
        number = f"SR-{len(self.receipts) + 1:06d}"
        listing = self.listings[session["plugin_id"]]
        session.update(status="succeeded", url=None, reason=None, completed_at=iso(now), receipt_number=number,
                       license={k: iso(v) if k.endswith(("_at", "_until")) else v for k, v in licence.items()},
                       install=self.install_info(listing, listing.latest))  # fmt: skip
        self.receipts.append({"id": uuid.uuid4().hex, "kind": "receipt", "number": number, "issued_at": iso(now),
                              "plugin_id": listing.id, "plugin_name": listing.name,
                              "plan_kind": session["plan_kind"], "payment_kind": "purchase",
                              "total_cents": session["amount_cents"], "currency": "usd",
                              "requested_by_name": session["requested_by"]["name"]})  # fmt: skip

    def decline(self, session_id: str, reason: str = "card_declined") -> None:
        """A card was declined: the session is open again with the reason."""
        self.sessions[session_id].update(status="open", reason=reason, method="saved_card")

    def action(self, listing: Listing) -> str:
        installed = self.reported.get(listing.id)
        if installed:
            return "update" if installed != listing.latest else "installed"
        if listing.tier == "free" or self.usable(listing.id):
            return "install"
        return "renew" if listing.id in self.licences else "buy"

    # ------------------------------------------------------------ HTTP

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        hub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _send(self, status: int, data: Any = None, headers: dict[str, str] | None = None, raw: bytes | None = None) -> None:  # fmt: skip
                body = raw if raw is not None else (b"" if status == 204 else json.dumps(data).encode())
                headers = dict(headers or {})
                package_sha = headers.get("X-Sudoo-Package-SHA256") if status == 200 else None
                installation = self.headers.get("X-Sudoo-Installation", "")
                nonce = self.headers.get("X-Sudoo-Nonce", "")
                if installation and nonce and not hub.unsigned_answers:
                    ts = int(time.time()) + hub.answer_skew
                    digest = package_sha or hashlib.sha256(body).hexdigest()
                    message = "\n".join(("sudoo-hub-response-v1", self.command, self.path, installation, nonce,
                                         str(status), str(ts), digest)).encode()  # fmt: skip
                    headers["Sudoo-Signature"] = f"kid={hub.key_id}, ts={ts}, sig={hub.key.sign(message)}"
                self.send_response(status)
                if status != 204:
                    self.send_header("Content-Type", "application/zip" if raw is not None else "application/json")
                self.send_header("Content-Length", str(len(body)))
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)

            def _problem(self, status: int, detail: str, code: str | None = None) -> None:
                self._send(status, {"type": "about:blank", "status": status, "detail": detail, "code": code})

            def _body(self) -> bytes:
                return self.rfile.read(int(self.headers.get("Content-Length") or 0))

            def _signed(self, body: bytes, key: Ed25519PublicKey | None = None, lease: bool = False) -> str | None:
                """The installation id when the request is signed as the hub requires (and, with `lease`, the
                panel has a current lease); None after answering with a refusal."""
                installation = self.headers.get("X-Sudoo-Installation", "")
                timestamp = self.headers.get("X-Sudoo-Timestamp", "")
                nonce = self.headers.get("X-Sudoo-Nonce", "")
                if installation in hub.revoked:
                    self._problem(401, "This installation's key was revoked by its owner.", "key_revoked")
                    return None
                key = key or hub.installations.get(installation)
                if key is None:
                    self._problem(401, "This installation is not registered.", "unknown_installation")
                    return None
                if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > 300:
                    self._problem(401, "Clock skew.", "clock_skew")
                    return None
                message = "\n".join(
                    ("sudoo-hub-request-v1", self.command, self.path, installation, timestamp, nonce,
                     hashlib.sha256(body).hexdigest())
                ).encode()  # fmt: skip
                try:
                    key.verify(unb64url(self.headers.get("X-Sudoo-Signature", "")), message)
                except (InvalidSignature, ValueError):
                    self._problem(401, "The request signature is not valid.", "bad_signature")
                    return None
                if (installation, nonce) in hub.nonces:
                    self._problem(401, "Replay.", "replay")
                    return None
                hub.nonces.add((installation, nonce))
                if lease and not hub.heartbeat_seen:
                    self._problem(403, "The panel has no current lease. Send a heartbeat first.", "lease_expired")
                    return None
                return installation

            def _plugin_out(self, listing: Listing) -> dict[str, Any]:
                icon = f"{hub.url}/api/v1/catalog/{listing.id}/icon?v={hashlib.sha256(listing.icon).hexdigest()[:12]}" if listing.icon else None  # fmt: skip
                return {"id": listing.id, "name": listing.name, "description": "A plugin for tests.",
                        "type": listing.type, "tier": listing.tier, "tags": [], "icon_url": icon,
                        "price_cents": listing.plans[0]["price_cents"] if listing.plans else None, "currency": "usd",
                        "publisher": listing.publisher, "requires": [], "avg_rating": 4.5, "rating_count": 2,
                        "install_count": 3, "countries": listing.countries, "languages": [], "odoo_versions": [],
                        "local": ("SA" in listing.countries) if listing.countries else None}  # fmt: skip

            def _panel_item(self, listing: Listing) -> dict[str, Any]:
                latest = {"version": listing.latest, "min_sudoo_version": "0.1.0", "max_sudoo_version": None,
                          "package_sha256": hashlib.sha256(listing.versions[listing.latest]).hexdigest(),
                          "package_size": len(listing.versions[listing.latest]), "published_at": None}  # fmt: skip
                return {**self._plugin_out(listing), "plans": listing.plans, "latest_version": latest,
                        "compatible_version": latest, "installed_version": hub.reported.get(listing.id),
                        "license": hub.licences.get(listing.id), "action": hub.action(listing)}  # fmt: skip

            def _page(self, items: list[Any]) -> None:
                self._send(200, {"data": items, "meta": {"total": len(items), "count": len(items), "limit": 50, "offset": 0}})  # fmt: skip

            def _session_out(self, session: dict[str, Any]) -> dict[str, Any]:
                return {k: v for k, v in session.items() if k != "idempotency_key"}

            def do_GET(self) -> None:  # noqa: N802 - the name http.server calls
                hub.requests.append(f"GET {self.path}")
                path = urlsplit(self.path).path
                query = parse_qs(urlsplit(self.path).query)
                parts = path.strip("/").split("/")
                if path == "/api/v1/keys":
                    return self._send(200, {"data": hub.keys_out()})
                if path == "/api/v1/categories":
                    return self._send(200, {"data": [{"type": "mailer", "count": len(hub.listings)}]})
                if parts[:3] == ["api", "v1", "catalog"] and len(parts) == 5 and parts[4] == "icon":
                    listing = hub.listings.get(parts[3])
                    if listing is None or listing.icon is None:
                        return self._problem(404, "This plugin has no icon.")
                    return self._send(200, raw=listing.icon, headers={"Content-Type": "image/png"})
                if parts[:3] == ["api", "v1", "catalog"] and len(parts) == 4:  # the public page of one plugin
                    listing = hub.listings.get(parts[3])
                    if listing is None:
                        return self._problem(404, "No such plugin.")
                    detail = {**self._plugin_out(listing), "plans": listing.plans, "permissions": ["network.outbound"],
                              "screenshots": [], "developer": {}, "latest_version": {"version": listing.latest}}  # fmt: skip
                    return self._send(200, {"data": detail})
                if parts[:3] == ["api", "v1", "catalog"] and len(parts) == 6 and parts[4] == "download":
                    return self._download(parts[3], parts[5])
                if parts[:2] == ["objects", "pkg"]:
                    return self._send(200, raw=self._bytes(hub.listings[parts[2]], parts[3]))
                if path == "/api/v1/recommendations":
                    if self._signed(b"", lease=True) is None:
                        return None
                    picks = [{"plugin": self._plugin_out(listing), "score": 1.5,
                              "reasons": ["Because you use Hello mailer", "From a verified publisher"]}
                             for listing in hub.listings.values() if listing.id not in hub.reported]  # fmt: skip
                    return self._send(200, {"data": picks[: int(query.get("limit", ["8"])[0])]})
                if parts[:3] != ["api", "v1", "installations"]:
                    return self._problem(404, "Not found.")
                installation = self._signed(b"", lease=True)
                if installation is None:
                    return None
                if path == "/api/v1/installations/catalog":
                    items = [self._panel_item(listing) for listing in hub.listings.values()]
                    if "q" in query:
                        items = [i for i in items if query["q"][0].lower() in i["name"].lower()]
                    if query.get("installed") == ["true"]:
                        items = [i for i in items if i["installed_version"]]
                    return self._page(items)
                if path == "/api/v1/installations/billing":
                    reason = ("payments_disabled" if not hub.payments_enabled else "link_required"
                              if hub.linked is None else "fingerprint_mismatch" if installation in hub.flagged
                              else None)  # fmt: skip
                    return self._send(200, {"data": {
                        "payments_enabled": hub.payments_enabled, "linked": hub.linked is not None,
                        "account_name": hub.linked, "can_buy": reason is None, "reason": reason, "currency": "usd",
                        "manage_url": "https://app.sudoo.sh/servers"}})  # fmt: skip
                if path == "/api/v1/installations/checkout-sessions":
                    return self._page([self._session_out(s) for s in reversed(hub.sessions.values())])
                if path == "/api/v1/installations/receipts":
                    return self._page(list(reversed(hub.receipts)))
                if len(parts) == 5 and parts[3] == "checkout-sessions":
                    found = hub.sessions.get(parts[4])
                    return self._send(200, {"data": self._session_out(found)}) if found else self._problem(404, "No such session.")  # fmt: skip
                return self._problem(404, "Not found.")

            def _bytes(self, listing: Listing, version: str) -> bytes:
                package = listing.versions[version]
                return package + b"tampered" if hub.tamper_downloads else package

            def _download(self, plugin_id: str, version: str) -> None:
                installation = self._signed(b"", lease=True)
                if installation is None:
                    return
                listing = hub.listings.get(plugin_id)
                if listing is None or version not in listing.versions:
                    return self._problem(404, "No such version.")
                if listing.tier == "paid":
                    if installation in hub.flagged:
                        return self._problem(403, "This server reported from another machine.", "fingerprint_mismatch")  # fmt: skip
                    if not hub.usable(plugin_id):
                        return self._problem(403, "No licence.", "license_required")
                sha, signature = hub.sign_package(plugin_id, version, listing.versions[version])
                headers = {"X-Sudoo-Plugin-Id": plugin_id, "X-Sudoo-Plugin-Version": version,
                           "X-Sudoo-Package-SHA256": sha, "X-Sudoo-Signature": signature,
                           "X-Sudoo-Signing-Key": hub.key_id}  # fmt: skip
                if hub.redirect_downloads:
                    return self._send(307, {}, {**headers, "Location": f"{hub.url}/objects/pkg/{plugin_id}/{version}"})
                return self._send(200, raw=self._bytes(listing, version), headers=headers)

            def do_POST(self) -> None:  # noqa: N802
                hub.requests.append(f"POST {self.path}")
                body = self._body()
                data = json.loads(body or b"{}")
                if self.path == "/api/v1/register":
                    key = Ed25519PublicKey.from_public_bytes(unb64url(data["public_key"]))
                    if self._signed(body, key) is None:
                        return None
                    hub.installations[data["installation_id"]] = key
                    hub.fingerprints.setdefault(data["installation_id"], data["hardware_fingerprint"])
                    out = {"installation_id": data["installation_id"], "status": "active",
                           "hub_key": {"key_id": hub.key_id}, "heartbeat_interval_seconds": 900}  # fmt: skip
                    return self._send(201, {"data": out})
                if self.path == "/api/v1/heartbeat":
                    installation = self._signed(body)
                    if installation is None:
                        return None
                    hub.heartbeats.append(data)
                    if data.get("hardware_fingerprint") != hub.fingerprints.get(installation):
                        hub.flagged.add(installation)
                    if hub.heartbeat_refusal:
                        return self._problem(403, "Refused.", hub.heartbeat_refusal)
                    hub.heartbeat_seen = True
                    hub.reported = {item["id"]: item["version"] for item in data.get("plugins", [])}
                    lease, signed = hub.lease(installation, data.get("plugins", []))
                    expires = int(hub._clock()) + LEASE_HOURS * 3600
                    out = {"installation_id": installation, "status": "active", "integrity": "ok", "lease": lease,
                           "lease_expires_at": iso(expires),
                           "plugins": {i["id"]: hub.standing(i["id"], installation) for i in data.get("plugins", [])},
                           "licenses": {pid: {**item, **{k: iso(item[k]) for k in ("expires_at", "grace_until", "run_until")}}
                                        for pid, item in signed["licenses"].items()},
                           "commands": [hub.command_out(cid, installation) for cid in hub.pending(installation)],
                           "flags": signed["flags"], "next_heartbeat_seconds": 900}  # fmt: skip
                    return self._send(200, {"data": out})
                if self.path == "/api/v1/link":
                    installation = self._signed(body)
                    if installation is None:
                        return None
                    account = hub.link_codes.pop(data.get("code", ""), None)
                    if account is None:
                        return self._problem(404, "This code is not valid or has expired.", "bad_link_code")
                    hub.linked = account
                    return self._send(200, {"data": {"installation_id": installation, "account_name": account,
                                                     "linked_at": "2026-11-14T10:00:00Z"}})  # fmt: skip
                if self.path == "/api/v1/unlink":
                    installation = self._signed(body)
                    if installation is None:
                        return None
                    if hub.linked is not None:
                        hub.unlink(installation)
                    return self._send(204)
                if self.path.startswith("/api/v1/commands/") and self.path.endswith("/ack"):
                    installation = self._signed(body)
                    if installation is None:
                        return None
                    command_id = self.path.split("/")[4]
                    command = hub.commands.get(command_id)
                    if command is None or command["installation"] != installation:
                        return self._problem(404, "There is no such command for this installation.")
                    command["acked"] = True
                    hub.acks.append((command_id, data))
                    return self._send(204)
                installation = self._signed(body, lease=True)
                if installation is None:
                    return None
                if self.path == "/api/v1/installations/views":
                    hub.views.append(data.get("plugin_id", ""))
                    return self._send(204)
                if self.path == "/api/v1/installations/install":
                    listing = hub.listings.get(data.get("plugin_id", ""))
                    if listing is None:
                        return self._problem(404, "No such plugin.")
                    if listing.tier == "paid":
                        if hub.linked is None:
                            return self._problem(403, "Link this panel first.", "link_required")
                        if installation in hub.flagged:
                            return self._problem(403, "Flagged.", "fingerprint_mismatch")
                        if not hub.usable(listing.id):
                            return self._problem(403, "Buy it first.", "license_required")
                    version = data.get("version") or listing.latest
                    if version not in listing.versions:
                        return self._problem(404, "No such version.")
                    return self._send(200, {"data": hub.install_info(listing, version)})
                if self.path == "/api/v1/installations/checkout-sessions":
                    return self._checkout(data, installation)
                return self._problem(404, "Not found.")

            def _checkout(self, data: dict[str, Any], installation: str) -> None:
                if set(data) != {"plugin_id", "plan_id", "idempotency_key", "requested_by"}:
                    return self._problem(422, "The body takes plugin_id, plan_id, idempotency_key, requested_by.")
                if not hub.payments_enabled:
                    return self._problem(503, "Payments are switched off.", "payments_disabled")
                if hub.linked is None:
                    return self._problem(403, "Link this panel first.", "link_required")
                if installation in hub.flagged:
                    return self._problem(403, "Flagged.", "fingerprint_mismatch")
                for existing in hub.sessions.values():
                    if existing["idempotency_key"] == data["idempotency_key"]:
                        if (existing["plugin_id"], existing["plan_id"]) != (data["plugin_id"], data["plan_id"]):
                            return self._problem(409, "Key used for another plan.", "idempotency_key_reused")
                        return self._send(200, {"data": self._session_out(existing)})
                listing = hub.listings.get(data["plugin_id"])
                chosen = next((p for p in (listing.plans if listing else []) if p["id"] == data["plan_id"]), None)
                if listing is None or chosen is None:
                    return self._problem(404, "No such plugin or plan.")
                if hub.usable(listing.id):
                    return self._problem(409, "Already licensed.", "already_licensed")
                for existing in hub.sessions.values():  # the same plan while one is open: that session
                    if existing["plugin_id"] == listing.id and existing["status"] == "open":
                        if existing["plan_id"] == chosen["id"]:
                            return self._send(200, {"data": self._session_out(existing)})
                        existing.update(status="cancelled", url=None)
                session_id = str(uuid.uuid4())
                now = time.time()
                session: dict[str, Any] = {
                    "id": session_id, "installation_id": installation, "status": "open",
                    "url": f"https://app.sudoo.sh/checkout/{b64url(uuid.uuid4().bytes)}",
                    "expires_at": iso(now + 1800), "plugin_id": listing.id, "plugin_name": listing.name,
                    "plan_id": chosen["id"], "plan_kind": chosen["kind"], "plan": chosen,
                    "amount_cents": chosen["price_cents"], "currency": chosen["currency"], "method": None,
                    "reason": None, "requested_by": data["requested_by"], "license": None, "receipt_number": None,
                    "install": None, "created_at": iso(now), "completed_at": None,
                    "idempotency_key": data["idempotency_key"],
                }  # fmt: skip
                hub.sessions[session_id] = session
                return self._send(201, {"data": self._session_out(session)})

        return Handler
