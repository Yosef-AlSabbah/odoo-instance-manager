"""The panel's side of the marketplace: registration, the signed heartbeat, the lease, commands, linking and
checkout sessions (the hub's "Panel contract", sudoo-hub README).

Heartbeat
    Every 15 minutes (the hub's `next_heartbeat_seconds`) the panel sends its version, the hash of its core files,
    its hardware fingerprint and the installed plugins, with coarse server figures (CPU, memory and disk use, how
    many instances run, their Odoo versions and edition), signed with the installation key. The hub answers with a
    lease (crypto.Lease, 72 hours): the standing of each plugin and the licence dates of the paid ones, including
    `run_until`, when a paid plugin must stop unless a newer lease arrives. The lease is verified with the trusted
    hub keys and kept in storage, so the panel acts on it while offline.

Commands
    The heartbeat's answer also carries the hub's commands not acknowledged yet, each signed on its own. The one
    command today is `remove_paid_plugins` (the server was unlinked from its account): back up, remove the listed
    paid plugins, acknowledge (plugin_manager.carry_out). A command already carried out is only acknowledged again.

When the hub cannot be reached
    Nothing stops: instances, free plugins and the panel keep working; the Plugins page says the marketplace cannot
    be reached. Each paid plugin runs until its `run_until` (an active licence: the lease's end plus 96 hours).

Clock
    Licences are compared with `trusted_now()`: the later of the server's clock, the signed issue time of the last
    lease plus the time measured since (monotonic), and the latest time the panel has seen, kept in storage. Turning
    the clock back does not extend a licence.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import threading
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from sudoo.config import settings
from sudoo.storage import storage

from . import client, crypto
from .client import COLLECTION, HubRefused, HubUnavailable

log = logging.getLogger("sudoo.hub")

HEARTBEAT_SECONDS = 15 * 60  # until the hub says otherwise (next_heartbeat_seconds)
RETRY_SECONDS = 5 * 60
LEASE_WARNING_HOURS = 24
BLOCKING = ("integrity_violation", "installation_suspended")  # hub answers that switch every plugin off
PANEL = "/api/v1/installations"  # the hub's panel contract (sudoo-hub README, "Panel contract"), all signed
ODOO_VERSION_RE = re.compile(r"^(saas-)?\d{1,2}\.\d{1,2}$")

_LOCK = threading.Lock()
_HEARTBEAT_LOCK = threading.Lock()
_LEASE_SEEN: dict[str, float] = {}  # "iat" of the lease received in this process -> time.monotonic() then
_WAKE = threading.Event()


def state() -> dict[str, Any]:
    return storage().get(COLLECTION, "state") or {}


def _save(**values: Any) -> dict[str, Any]:
    def change(doc: dict[str, Any] | None) -> dict[str, Any]:
        return {**(doc or {}), **values}

    with _LOCK:
        return storage().change(COLLECTION, "state", change) or {}


def enabled() -> bool:
    return bool(settings.marketplace)


# ---------------------------------------------------------------- time


def trusted_now() -> float:
    """Now, never earlier than what the panel already saw (see the module's description)."""
    current = state()
    candidates = [time.time(), float(current.get("high_water") or 0)]
    iat = current.get("lease_iat")
    if iat and str(iat) in _LEASE_SEEN:
        candidates.append(float(iat) + time.monotonic() - _LEASE_SEEN[str(iat)])
    elif iat:
        candidates.append(float(iat))
    return max(candidates)


def remember_time() -> None:
    """Keep the latest time seen (called now and then by the watchdog)."""
    now = trusted_now()
    if now > float(state().get("high_water") or 0):
        _save(high_water=now)


# ---------------------------------------------------------------- lease


def lease() -> crypto.Lease | None:
    """The stored lease while it verifies with the trusted keys and has not expired; None otherwise."""
    token = state().get("lease")
    if not token:
        return None
    try:
        me = client.identity()
        now = trusted_now()
        return crypto.read_lease(token, me.pinned(now), client.hub_url(), me.installation_id, now)
    except (crypto.LeaseError, ValueError):
        return None


def blocked() -> str | None:
    """integrity_violation or installation_suspended while the hub's last answer said so; None otherwise."""
    status = state().get("hub_status")
    return status if status in BLOCKING else None


def flags() -> list[str]:
    """What the last lease flagged: ["fingerprint_mismatch"] when the hub withholds licences from this server."""
    return [str(flag) for flag in state().get("flags") or []]


# ---------------------------------------------------------------- registration and heartbeat


def register() -> client.Identity:
    """Register this installation with the hub (once per hub and identity); returns the identity with the trusted
    hub keys."""
    me = client.identity()
    if not me.pinned():
        me = client.refresh_keys()
    if me.registered_at and me.hub_url == client.hub_url():
        return me
    body = {
        "installation_id": me.installation_id,
        "public_key": me.public_key,
        "hardware_fingerprint": client.hardware_fingerprint(me.public_key),
        "sudoo_version": client.sudoo_version(),
        "core_hash": client.core_hash(),
    }
    answer = client.request("POST", "/api/v1/register", body).data or {}
    hub_key = (answer.get("hub_key") or {}) if isinstance(answer, dict) else {}
    if hub_key.get("key_id") not in me.pinned():
        me = client.refresh_keys()
        if hub_key.get("key_id") not in me.pinned():
            raise HubRefused(409, "The marketplace answered with a key this panel does not trust.", "key_mismatch")
    client.update_identity(registered_at=time.time())
    return client.identity()


def installed_report() -> list[dict[str, str]]:
    from sudoo import plugin_manager

    return [{"id": r["id"], "version": r["version"]} for r in plugin_manager.records().values()]


def _percent(value: Any) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return round(min(100.0, max(0.0, float(value))), 1)
    return None


def server_report() -> dict[str, Any]:
    """The optional heartbeat figures (coarse, for the owner's uptime records and for recommendations): CPU,
    memory and disk use of the server, how many instances exist and run, their Odoo versions and edition. Nothing
    about what instances contain."""
    try:
        from sudoo.instances import metrics, monitor, store

        report: dict[str, Any] = {}
        for key in ("cpu_percent", "memory_percent", "disk_percent"):
            if (value := _percent(metrics.SERVER.get(key))) is not None:
                report[key] = value
        names = store.names()
        report["instances_total"] = min(len(names), 100_000)
        report["instances_running"] = min(sum(1 for n in names if monitor.STATUS.get(n, {}).get("running")), 100_000)
        versions: set[str] = set()
        editions: set[str] = set()
        for name in names:
            try:
                env = store.read_env(name)
            except OSError:
                continue
            if ODOO_VERSION_RE.match(env.get("ODOO_VERSION", "")):
                versions.add(env["ODOO_VERSION"])
            editions.add("enterprise" if env.get("EDITION") == "enterprise" else "community")
        report["odoo_versions"] = sorted(versions)[:20]
        if editions:
            report["odoo_edition"] = editions.pop() if len(editions) == 1 else "mixed"
        return report
    except Exception:  # noqa: BLE001 - the figures are optional; the heartbeat goes without them
        log.exception("marketplace: could not gather the server figures")
        return {}


def _forget_link(**values: Any) -> None:
    _save(linked=None, lease=None, lease_iat=None, lease_exp=None, flags=[], **values)


def heartbeat() -> dict[str, Any]:
    """Register when needed, send the heartbeat, keep the lease, carry out the hub's commands. Raises
    HubUnavailable or HubRefused; the state records the outcome either way."""
    with _HEARTBEAT_LOCK:
        _save(last_attempt_at=time.time())
        try:
            try:
                return _heartbeat_once()
            except HubRefused as error:
                if error.code == "key_revoked":  # the owner revoked this server's key: a new identity, registered
                    log.warning("marketplace: this server's key was revoked; registering with a new identity")
                    _forget_link(key_revoked_at=time.time())
                elif error.code == "unknown_installation":  # the hub does not know this id (any more)
                    client.update_identity(registered_at=None)
                else:
                    raise
                return _heartbeat_once()
        except HubRefused as error:
            values: dict[str, Any] = {"error": error.detail, "error_code": error.code}
            if error.code in BLOCKING or error.code == "unknown_version":
                values["hub_status"] = error.code
            _save(**values)
            _changed()
            raise
        except HubUnavailable as error:
            code = "unverified" if isinstance(error, client.UnverifiedAnswer) else "unreachable"
            _save(error=str(error), error_code=code)
            _changed()
            raise


def _heartbeat_once() -> dict[str, Any]:
    me = register()
    with contextlib.suppress(HubRefused):
        me = client.refresh_keys()  # revoked keys are dropped at once, new ones learnt before they sign
    body = {
        "sudoo_version": client.sudoo_version(),
        "core_hash": client.core_hash(),
        "hardware_fingerprint": client.hardware_fingerprint(me.public_key),
        "plugins": installed_report(),
        **server_report(),
    }
    answer = client.request("POST", "/api/v1/heartbeat", body).data or {}
    token = answer.get("lease") if isinstance(answer, dict) else None
    if not isinstance(token, str):
        raise HubUnavailable("The marketplace's answer had no lease.")
    try:
        verified = crypto.read_lease(token, me.pinned(), client.hub_url(), me.installation_id, trusted_now())
    except crypto.LeaseError as error:
        raise HubRefused(502, f"The marketplace's lease was refused: {error}.", "bad_lease") from error
    _LEASE_SEEN[str(verified.issued_at)] = time.monotonic()
    interval = answer.get("next_heartbeat_seconds")
    interval = int(interval) if isinstance(interval, int) and 60 <= interval <= 86400 else HEARTBEAT_SECONDS
    current = _save(
        lease=token,
        lease_iat=verified.issued_at,
        lease_exp=verified.expires_at,
        last_heartbeat_at=time.time(),
        next_heartbeat_at=time.time() + interval,
        integrity=answer.get("integrity"),
        hub_status=str(verified.claims.get("status") or "active"),
        flags=verified.flags,
        error=None,
        error_code=None,
        high_water=max(float(state().get("high_water") or 0), float(verified.issued_at)),
    )
    from sudoo import plugin_manager

    plugin_manager.apply_lease(verified)
    commands = answer.get("commands")
    carry_out(commands if isinstance(commands, list) else [], verified)
    _changed()
    return current


def _changed() -> None:
    from sudoo.core import events

    events.publish("marketplace", "status", {"changed": True})


def heartbeat_forever() -> None:
    """Background loop: heartbeat at start, then every 15 minutes (as the hub asks), retrying every 5 minutes while
    the hub cannot be reached. Never raises."""
    while True:
        wait = float(RETRY_SECONDS)
        if enabled():
            try:
                current = heartbeat()
                wait = max(60.0, float(current.get("next_heartbeat_at") or 0) - time.time())
                wait = min(wait, HEARTBEAT_SECONDS)
            except HubRefused as error:
                log.warning("marketplace heartbeat refused: %s", error.detail)
            except HubUnavailable as error:
                log.info("marketplace heartbeat: %s", error)
            except Exception:  # noqa: BLE001 - the loop must survive anything
                log.exception("marketplace heartbeat failed")
        _WAKE.wait(wait)
        _WAKE.clear()


def wake() -> None:
    """Send a heartbeat soon (after a plugin was installed or removed)."""
    _WAKE.set()


# ---------------------------------------------------------------- commands


def _unix(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return int((when if when.tzinfo else when.replace(tzinfo=UTC)).timestamp())


def verify_command(command: Any, me: client.Identity, lease_issued: dict[str, int] | None = None) -> bool:
    """Whether a command is signed by an accepted hub key, for this installation."""
    if not isinstance(command, dict):
        return False
    command_id, kind = str(command.get("id") or ""), str(command.get("kind") or "")
    key = me.pinned().get(str(command.get("key_id") or ""))
    issued = (lease_issued or {}).get(command_id) or _unix(command.get("issued_at"))
    if key is None or issued is None or not command_id or not kind or not isinstance(command.get("payload"), dict):
        return False
    try:
        signature = crypto.from_b64url(str(command.get("signature") or ""))
    except ValueError:
        return False
    message = crypto.command_message(command_id, me.installation_id, kind, issued, command["payload"])
    return crypto.verify(key, signature, message)


def commands_done() -> dict[str, dict[str, Any]]:
    """Commands carried out: id -> {kind, status, detail, at, acked}."""
    return dict(state().get("commands") or {})


def record_command(command_id: str, **values: Any) -> None:
    def change(doc: dict[str, Any] | None) -> dict[str, Any]:
        doc = dict(doc or {})
        done = dict(doc.get("commands") or {})
        done[command_id] = {**done.get(command_id, {}), **values}
        doc["commands"] = dict(list(done.items())[-50:])
        return doc

    with _LOCK:
        storage().change(COLLECTION, "state", change)


def acknowledge(command_id: str, status: str, detail: str | None = None) -> bool:
    """Tell the hub a command was carried out (done) or could not be (failed); True when the hub took it."""
    body: dict[str, Any] = {"status": status}
    if detail:
        body["detail"] = detail[:500]
    try:
        client.request("POST", f"/api/v1/commands/{command_id}/ack", body)
    except (HubUnavailable, HubRefused) as error:
        log.info("marketplace: command %s not acknowledged yet: %s", command_id, error)
        return False
    record_command(command_id, acked=True)
    return True


def carry_out(commands: list[Any], verified: crypto.Lease | None = None) -> None:
    """Act on the hub's commands: each must verify; one already carried out is only acknowledged again."""
    from sudoo import plugin_manager

    me = client.identity()
    signed_times: dict[str, int] = {}
    for item in (verified.claims.get("commands") if verified else None) or []:
        if isinstance(item, dict) and isinstance(item.get("issued_at"), int):
            signed_times[str(item.get("id"))] = item["issued_at"]
    done = commands_done()
    for command in commands:
        if not verify_command(command, me, signed_times):
            log.warning("marketplace: a command whose signature does not verify was ignored")
            continue
        command_id, kind = str(command["id"]), str(command["kind"])
        previous = done.get(command_id) or {}
        if previous.get("status") in ("done", "failed"):  # the hub did not get the acknowledgement: again
            acknowledge(command_id, previous["status"], previous.get("detail"))
            continue
        if kind == "remove_paid_plugins":
            plugin_manager.start_command(command_id, command["payload"])
        else:
            record_command(command_id, kind=kind, status="failed", detail="This panel does not know this command.",
                           at=time.time())  # fmt: skip
            acknowledge(command_id, "failed", "This panel does not know this command.")


# ---------------------------------------------------------------- linking, catalogue, checkout


def link(code: str) -> dict[str, Any]:
    """Link this panel to the app.sudoo.sh account that made the one-time code (sent signed)."""
    register()
    answer = client.request("POST", "/api/v1/link", {"code": code}).data or {}
    linked = {"account_name": answer.get("account_name"), "linked_at": answer.get("linked_at")}
    _save(linked=linked, key_revoked_at=None)
    _changed()
    return linked


def unlink() -> None:
    """Log out of the account (POST /api/v1/unlink): the hub revokes this server's paid licences and sends the
    command to remove its paid plugins, which the heartbeat sent right after carries out."""
    register()
    client.request("POST", "/api/v1/unlink")
    _save(linked=None, unlinked_at=time.time())
    _changed()
    try:
        heartbeat()
    except (HubUnavailable, HubRefused) as error:  # the next heartbeat carries the command
        log.info("marketplace: heartbeat after logging out: %s", error)


def _for_panel(method: str, path: str, body: Any = None) -> client.Answer:
    """A signed call of the panel contract. The hub serves it only with a current lease: when it says the lease
    expired, send a heartbeat and try once more."""
    register()
    try:
        return client.request(method, path, body)
    except HubRefused as error:
        if error.code not in ("lease_expired", "key_revoked", "unknown_installation"):
            raise
    heartbeat()
    return client.request(method, path, body)


def _object(answer: client.Answer) -> dict[str, Any]:
    if not isinstance(answer.data, dict):
        raise HubUnavailable("The marketplace sent an answer the panel does not understand.")
    return answer.data


def _list(answer: client.Answer) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta = answer.headers.get("x-sudoo-meta")
    items = [item for item in answer.data if isinstance(item, dict)] if isinstance(answer.data, list) else []
    return items, (json.loads(meta) if meta else {})


def catalog(query: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The catalogue for this panel: each plugin with `plans`, `latest_version`, `compatible_version`,
    `installed_version`, `license` and `action` (install, update, installed, buy, renew, incompatible)."""
    path = f"{PANEL}/catalog?{urlencode(query)}" if query else f"{PANEL}/catalog"
    return _list(_for_panel("GET", path))


def plugin(plugin_id: str) -> dict[str, Any]:
    """The public page of one plugin: permissions, screenshots, plans."""
    register()
    data = client.get(f"/api/v1/catalog/{plugin_id}")
    if not isinstance(data, dict):
        raise HubUnavailable("The marketplace sent an answer the panel does not understand.")
    return data


def categories() -> list[dict[str, Any]]:
    register()
    data = client.get("/api/v1/categories")
    return data if isinstance(data, list) else []


def recommendations(limit: int = 8) -> list[dict[str, Any]]:
    """Plugins the hub suggests for this server: [{plugin, score, reasons}] (reasons most important first)."""
    return _list(_for_panel("GET", f"/api/v1/recommendations?limit={limit}"))[0]


def report_view(plugin_id: str) -> None:
    """Tell the hub a plugin's page was shown (kept only with the account owner's consent); never raises."""
    try:
        _for_panel("POST", f"{PANEL}/views", {"plugin_id": plugin_id})
    except (HubUnavailable, HubRefused) as error:
        log.debug("marketplace: view not reported: %s", error)


def icon(plugin_id: str, version_tag: str) -> tuple[bytes, str]:
    """A plugin's icon (PNG or SVG, at most 256 KB), signed like every answer."""
    register()
    return client.fetch_bytes(f"/api/v1/catalog/{plugin_id}/icon?v={version_tag}", 256 * 1024)


def billing() -> dict[str, Any]:
    """Whether a checkout session can be opened now: {payments_enabled, linked, account_name, can_buy, reason,
    currency, manage_url}."""
    return _object(_for_panel("GET", f"{PANEL}/billing"))


def install_info(plugin_id: str, version: str | None) -> dict[str, Any]:
    """May this plugin be installed, and the package to download: download_path, package_sha256, signature,
    signing_key_id, version, tier, requires, license."""
    body: dict[str, Any] = {"plugin_id": plugin_id}
    if version:
        body["version"] = version
    return _object(_for_panel("POST", f"{PANEL}/install", body))


def open_checkout(plugin_id: str, plan_id: str, idempotency_key: str, requested_by: dict[str, str]) -> dict[str, Any]:
    """Ask to buy a paid plugin: a checkout session whose `url` (app.sudoo.sh) the account owner opens to pay. The
    panel never charges anything. The same idempotency key always answers the same session."""
    body = {
        "plugin_id": plugin_id,
        "plan_id": plan_id,
        "idempotency_key": idempotency_key,
        "requested_by": requested_by,
    }
    return _object(_for_panel("POST", f"{PANEL}/checkout-sessions", body))


def checkout_session(session_id: str) -> dict[str, Any]:
    return _object(_for_panel("GET", f"{PANEL}/checkout-sessions/{session_id}"))


def checkout_sessions(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    return _list(_for_panel("GET", f"{PANEL}/checkout-sessions?limit={limit}&offset={offset}"))[0]


def receipts(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    return _list(_for_panel("GET", f"{PANEL}/receipts?limit={limit}&offset={offset}"))[0]


# ---------------------------------------------------------------- what the web app shows


def status() -> dict[str, Any]:
    """The marketplace as the Plugins page and Settings → Marketplace show it."""
    current = state()
    held = lease()
    try:
        me = client.identity()
        installation_id: str | None = me.installation_id
        registered = bool(me.registered_at and me.hub_url == client.hub_url())
        keys = sorted(me.pinned())
    except Exception:  # noqa: BLE001 - the vault key may be missing on a broken install; the page still opens
        installation_id, registered, keys = None, False, []
    lease_exp = float(held.expires_at) if held else None
    running = [c for c in commands_done().values() if c.get("status") == "running"]
    return {
        "enabled": enabled(),
        "hub_url": client.hub_url(),
        "installation_id": installation_id,
        "registered": registered,
        "hub_keys": keys,
        "reachable": current.get("error_code") != "unreachable" if current.get("last_attempt_at") else None,
        "error": current.get("error"),
        "error_code": current.get("error_code"),
        "hub_status": current.get("hub_status"),
        "flags": flags(),
        "linked": current.get("linked"),
        "key_revoked_at": current.get("key_revoked_at"),
        "removing_paid_plugins": bool(running),
        "last_heartbeat_at": current.get("last_heartbeat_at"),
        "next_heartbeat_at": current.get("next_heartbeat_at"),
        "lease_expires_at": lease_exp,
        "lease_valid": held is not None,
        "lease_ending_soon": bool(lease_exp and lease_exp - trusted_now() < LEASE_WARNING_HOURS * 3600),
    }
