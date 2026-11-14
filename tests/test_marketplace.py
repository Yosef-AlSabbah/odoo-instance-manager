"""The marketplace, against a fake hub (fake_hub.py) that speaks the hub's v2 contract: signatures, leases, commands
and key endorsements in the hub's formats (vectors made by sudoo-hub), registration and heartbeat with the
fingerprint, signed answers (refused when unsigned, too old or by a key not trusted), key rotation and revocation,
installing (free and paid), tampered packages, compatibility, integrity, licences (expiry, grace, run_until,
perpetual, withheld), checkout sessions paid on app.sudoo.sh, logging out (the hub's remove_paid_plugins command),
a revoked key, plugin views, recommendations, icons, and a hub that cannot be reached."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import shutil
import stat
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from flask import Flask
from flask.testing import FlaskClient

from conftest import RESTARTS, sign_in
from fake_hub import FakeHub, Listing, make_package, plan
from sudoo import accounts, plugin_manager, plugins
from sudoo.config import live, settings
from sudoo.core import jobs
from sudoo.hub import HubRefused, HubUnavailable, client, crypto, marketplace
from sudoo.storage import storage

Client = tuple[FlaskClient, dict[str, str]]
FREE = "com.example.hello"
PAID = "com.example.paid"


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeHub]:
    """A running fake hub, and a panel that has never talked to a hub and has no plugins."""
    fake = FakeHub().start()
    monkeypatch.setattr(client, "hub_url", lambda: fake.url)
    for collection in (plugin_manager.COLLECTION, client.COLLECTION):
        for key in storage().all(collection):
            storage().delete(collection, key)
    shutil.rmtree(plugin_manager.plugins_dir(), ignore_errors=True)
    plugin_manager.LOADED = set()
    plugin_manager._RESTART_PENDING.clear()
    from sudoo.web.v1 import plugins as api

    api._LATEST.clear()
    api._ICONS.clear()
    RESTARTS.clear()
    live.change({"marketplace": True})  # off by default until the marketplace opens
    yield fake
    live.change({"marketplace": None})
    fake.stop()
    plugin_manager._RESTART_PENDING.clear()


def wait(job_id: str, seconds: float = 20) -> jobs.Job:
    job = jobs.JOBS[job_id]
    deadline = time.time() + seconds
    while job.finished is None and time.time() < deadline:
        time.sleep(0.05)
    assert job.finished is not None, "the job did not finish"
    return job


def wait_for(kind: str, seconds: float = 20) -> jobs.Job:
    """The newest job of this kind, once finished."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        found = [j for j in jobs.JOBS.values() if j.kind == kind]
        if found:
            return wait(found[-1].id, seconds)
        time.sleep(0.05)
    raise AssertionError(f"no {kind} job started")


def install(admin: Client, plugin_id: str, **body: Any) -> jobs.Job:
    web, headers = admin
    answer = web.post("/api/v1/plugins", json={"id": plugin_id, **body}, headers=headers)
    assert answer.status_code == 202, answer.get_json()
    return wait(answer.get_json()["data"]["id"])


def free_listing(fake: FakeHub, version: str = "1.0.0", **kwargs: Any) -> Listing:
    return fake.publish(Listing(FREE, "Hello mailer", versions={version: make_package(FREE, version, **kwargs)}))


# ---------------------------------------------------------------- the hub's formats (vectors made by sudoo-hub)

HUB_PUBLIC = "A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg"
HUB_KID = "56475aa75463474c"
NEXT_PUBLIC = "ebVWLo_mVPlAeLES6KmLp5AfhTrmlb7X4OORC60ElmQ"
NEXT_KID = "65b60673d6ed884b"
LEASE = (
    "eyJhbGciOiJFZERTQSIsImtpZCI6IjU2NDc1YWE3NTQ2MzQ3NGMiLCJ0eXAiOiJzdWRvby1sZWFzZStqd3QifQ.eyJpc3MiOiJodHRwczovL2h1Yi5zdWRvby5zaCIsImF1ZCI6InN1ZG9vLXBhbmVsOjEyMzQ1Njc4LTEyMzQtNDIzNC05MjM0LTEyMzQ1Njc4OWFiYyIsInN1YiI6IjEyMzQ1Njc4LTEyMzQtNDIzNC05MjM0LTEyMzQ1Njc4OWFiYyIsImlhdCI6MTc5MzUzNDQwMCwibmJmIjoxNzkzNTM0NDAwLCJleHAiOjE3OTM3OTM2MDAsImp0aSI6IkRaMVFOUS1RVWxuY01tZGUiLCJzdGF0dXMiOiJhY3RpdmUiLCJwbHVnaW5zIjp7ImNvbS5leGFtcGxlLnBhaWQiOiJsaWNlbnNlZCIsImNvbS5leGFtcGxlLmZyZWUiOiJmcmVlIn0sImxpY2Vuc2VzIjp7ImNvbS5leGFtcGxlLnBhaWQiOnsic3RhdGUiOiJhY3RpdmUiLCJleHBpcmVzX2F0IjoxNzk1MDAwMDAwLCJncmFjZV91bnRpbCI6MTc5NTYwNDgwMCwicnVuX3VudGlsIjoxNzk0MTM5MjAwLCJwZXJwZXR1YWwiOmZhbHNlfSwiY29tLmV4YW1wbGUub25jZSI6eyJzdGF0ZSI6ImFjdGl2ZSIsImV4cGlyZXNfYXQiOm51bGwsImdyYWNlX3VudGlsIjpudWxsLCJydW5fdW50aWwiOjE3OTQxMzkyMDAsInBlcnBldHVhbCI6dHJ1ZX19LCJjb21tYW5kcyI6W3siaWQiOiJhYWFhYWFhYS1iYmJiLTRjY2MtOGRkZC1lZWVlZWVlZWVlZWUiLCJraW5kIjoicmVtb3ZlX3BhaWRfcGx1Z2lucyIsImlzc3VlZF9hdCI6MTc5MzUzNDAwMCwicGF5bG9hZCI6eyJwbHVnaW5zIjpbImNvbS5leGFtcGxlLnBhaWQiXSwicmVhc29uIjoidW5saW5rZWQifX1dLCJmbGFncyI6W10sIm5leHRfaGVhcnRiZWF0IjoxNzkzNTM1MzAwfQ"
    ".NzaaPEYiEuh2c8jUWIL3buPGX0c9HUXayo9HpibrKCUKlOS6_b2QF8Aeq5c_DqKDq_DTzV2CDpgoEv6cg1-_BQ"
)
INSTALLATION = "12345678-1234-4234-9234-123456789abc"
COMMAND_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
COMMAND_SIGNATURE = "LKn-76EOO2CWg4q_CI5XutGpxgw7dnsAcQxPLEeqsifsPOv1amzgu954UMT6NmnLvAa-VwbRPZwm-Zb6-AKnCw"
ANSWER_SIGNATURE = (
    "kid=56475aa75463474c, ts=1793534400, "
    "sig=J2RViadqrlVZOewJKtEZA5EsKbkAz5fboz2QmeGTeMSCo1ShrpBd_LAhXrY3fx8lxTnmT_kyEfdcVliZ6LtYBA"
)
ENDORSEMENT = "gchfkYsj3KAj6D3y31YxkP9Jir33IZ_pT8-X6LEAaSCq-LN8y8XwYhgPI5cEZSJNnyV39SN322f2X_U_Z8PoCw"


def test_package_signature_made_by_the_hub_verifies() -> None:
    key = crypto.public_key_from_b64url(HUB_PUBLIC)
    assert crypto.key_id(key) == HUB_KID
    sha = "07531963baeda377d96af8e056cb8d13b9f6e20eba0349410c0026df1b9c6053"
    signature = "ekEmUZINboxfJbHPHQB8X9-v7qqQM64dgdc-efPr-qHhWYW45-PkbFBKyhECVl0BNO_XpvRSBa0LA0jFRNT3Cw"
    assert crypto.verify_package(key, "com.example.hello", "1.2.3", sha, signature)
    # bound to the plugin, the version and the bytes
    assert not crypto.verify_package(key, "com.example.other", "1.2.3", sha, signature)
    assert not crypto.verify_package(key, "com.example.hello", "1.2.2", sha, signature)
    assert not crypto.verify_package(key, "com.example.hello", "1.2.3", "0" * 64, signature)
    assert not crypto.verify_package(key, "com.example.hello", "1.2.3", sha, "not-a-signature")


def test_request_signature_matches_the_hub_format() -> None:
    message = crypto.request_message(
        "POST", "/api/v1/heartbeat", INSTALLATION, 1790000000, "abcdefghijklmnop", b'{"a":1}'
    )
    hub_made = bytes.fromhex(  # hub.services.panels.signing_message with the same values
        "7375646f6f2d6875622d726571756573742d76310a504f53540a2f6170692f76312f6865617274626561740a313233343536"
        "37382d313233342d343233342d393233342d3132333435363738396162630a313739303030303030300a6162636465666768"
        "696a6b6c6d6e6f700a3031356162643766356363353761326464393462373539306630346164383038343237333930356565"
        "3333656335636562656165363232373661393766383632"
        ""
    )
    assert message == hub_made
    key = Ed25519PrivateKey.generate()
    headers = crypto.signed_headers(key, INSTALLATION, "POST", "/api/v1/heartbeat", b"{}", 1790000000)
    signed = crypto.request_message(
        "POST", "/api/v1/heartbeat", INSTALLATION, 1790000000, headers["X-Sudoo-Nonce"], b"{}"
    )
    key.public_key().verify(crypto.from_b64url(headers["X-Sudoo-Signature"]), signed)


def _answer(**change: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "method": "GET",
        "path_with_query": "/api/v1/installations/catalog?limit=5",
        "installation_id": INSTALLATION,
        "nonce": "abcdefghijklmnop",
        "status": 200,
        "body_sha256": hashlib.sha256(b'{"data":[]}').hexdigest(),
        "now": 1793534400.0,
    }
    return {**values, **change}


def test_answer_signature_made_by_the_hub_verifies() -> None:
    keys = {HUB_KID: crypto.public_key_from_b64url(HUB_PUBLIC)}
    assert crypto.verify_answer(keys, ANSWER_SIGNATURE, **_answer()) == HUB_KID
    # bound to the request (method, path, installation, nonce), the status and the body
    for change in ({"method": "POST"}, {"path_with_query": "/api/v1/installations/catalog"},
                   {"installation_id": "87654321-1234-4234-9234-123456789abc"}, {"nonce": "x" * 16},
                   {"status": 403}, {"body_sha256": "0" * 64}):  # fmt: skip
        with pytest.raises(crypto.AnswerError, match="not valid"):
            crypto.verify_answer(keys, ANSWER_SIGNATURE, **_answer(**change))
    with pytest.raises(crypto.AnswerError, match="5 minutes"):
        crypto.verify_answer(keys, ANSWER_SIGNATURE, **_answer(now=1793534400.0 + 301))
    with pytest.raises(crypto.AnswerError, match="does not accept") as unknown:
        crypto.verify_answer({}, ANSWER_SIGNATURE, **_answer())
    assert unknown.value.unknown_key == HUB_KID
    with pytest.raises(crypto.AnswerError, match="not signed"):
        crypto.verify_answer(keys, None, **_answer())


def test_command_and_endorsement_made_by_the_hub_verify() -> None:
    key = crypto.public_key_from_b64url(HUB_PUBLIC)
    payload = {"reason": "unlinked", "plugins": ["com.example.paid"]}  # key order does not matter: canonical JSON
    message = crypto.command_message(COMMAND_ID, INSTALLATION, "remove_paid_plugins", 1793534000, payload)
    assert crypto.verify(key, crypto.from_b64url(COMMAND_SIGNATURE), message)
    other = crypto.command_message(COMMAND_ID, INSTALLATION, "remove_paid_plugins", 1793534000, {**payload, "plugins": []})  # fmt: skip
    assert not crypto.verify(key, crypto.from_b64url(COMMAND_SIGNATURE), other)
    endorsed = crypto.endorsement_message(NEXT_KID, NEXT_PUBLIC, 1793534400)
    assert crypto.verify(key, crypto.from_b64url(ENDORSEMENT), endorsed)
    listed = [{"key_id": NEXT_KID, "public_key": NEXT_PUBLIC, "state": "active", "not_before": 1793534400.0,
               "not_after": None, "endorsed_by": HUB_KID, "endorsement": ENDORSEMENT}]  # fmt: skip
    root = {HUB_KID: {"public_key": HUB_PUBLIC, "state": "active", "not_after": None, "source": "root"}}
    assert set(client.trusted_after(root, listed, 1793534500)) == {HUB_KID, NEXT_KID}
    # never through a revoked key, never without a valid endorsement
    revoked = {HUB_KID: {**root[HUB_KID], "state": "revoked"}}
    assert set(client.trusted_after(revoked, listed, 1793534500)) == {HUB_KID}
    forged = [{**listed[0], "endorsement": COMMAND_SIGNATURE}]
    assert set(client.trusted_after(root, forged, 1793534500)) == {HUB_KID}


def test_lease_made_by_the_hub_verifies() -> None:
    keys = {HUB_KID: crypto.public_key_from_b64url(HUB_PUBLIC)}
    lease = crypto.read_lease(LEASE, keys, "https://hub.sudoo.sh", INSTALLATION, now=1793534500)
    assert lease.plugins == {"com.example.paid": "licensed", "com.example.free": "free"}
    assert lease.licences["com.example.paid"] == {
        "state": "active",
        "expires_at": 1795000000,
        "grace_until": 1795604800,
        "run_until": 1794139200,  # the lease's end plus 96 hours
        "perpetual": False,
    }
    assert lease.licences["com.example.once"]["perpetual"] and lease.licences["com.example.once"]["expires_at"] is None
    assert lease.expires_at - lease.issued_at == 72 * 3600
    assert lease.flags == [] and lease.claims["commands"][0]["kind"] == "remove_paid_plugins"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("expired", "expired"),
        ("other-installation", "another installation"),
        ("other-hub", "another hub"),
        ("unknown-key", "does not trust"),
        ("tampered", "signature"),
        ("alg-none", "Ed25519"),
    ],
)
def test_bad_leases_are_refused(change: str, message: str) -> None:
    keys = {HUB_KID: crypto.public_key_from_b64url(HUB_PUBLIC)}
    token, issuer, installation, now = LEASE, "https://hub.sudoo.sh", INSTALLATION, 1793534500.0
    head, body, signature = token.split(".")
    if change == "expired":
        now = 1793793600 + 1
    elif change == "other-installation":
        installation = "87654321-1234-4234-9234-123456789abc"
    elif change == "other-hub":
        issuer = "https://evil.example.com"
    elif change == "unknown-key":
        keys = {"0000000000000000": keys[HUB_KID]}
    elif change == "tampered":
        claims = json.loads(crypto.from_b64url(body))
        claims["licenses"]["com.example.paid"]["run_until"] = 2_000_000_000
        token = f"{head}.{crypto.b64url(json.dumps(claims).encode())}.{signature}"
    elif change == "alg-none":
        header = crypto.b64url(json.dumps({"alg": "none", "kid": HUB_KID}).encode())
        token = f"{header}.{body}.{signature}"
    with pytest.raises(crypto.LeaseError, match=message):
        crypto.read_lease(token, keys, issuer, installation, now)


def test_fingerprint_layout(tmp_path: Path) -> None:
    public = "A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg"
    expected = hashlib.sha256(f"sudoo-fingerprint-v1\n{public}\nabc123\n52:54:00:12:34:56".encode()).hexdigest()
    assert crypto.fingerprint(public, "abc123", "52:54:00:12:34:56") == expected
    # the primary MAC: the interface of the default route, lower case
    net = tmp_path / "net"
    for name, mac in (("docker0", "02:42:ac:11:00:02"), ("eth0", "52:54:00:AB:CD:EF"), ("lo", "00:00:00:00:00:00")):
        (net / name).mkdir(parents=True)
        (net / name / "address").write_text(mac + "\n")
    routes = tmp_path / "route"
    routes.write_text("Iface\tDestination\tGateway\neth0\t00000000\t0101A8C0\ndocker0\t000011AC\t00000000\n")
    assert client.primary_mac(net, routes) == "52:54:00:ab:cd:ef"
    # no route table: the first physical-looking interface; nothing at all: empty (never an error)
    assert client.primary_mac(net, tmp_path / "missing") == "52:54:00:ab:cd:ef"
    assert client.primary_mac(tmp_path / "none", tmp_path / "missing") == ""


def test_versions_and_specifiers() -> None:
    assert plugin_manager.satisfies("1.4.5", ">=1.0.0,<2.0.0")
    assert not plugin_manager.satisfies("2.0.0", ">=1.0.0,<2.0.0")
    assert plugin_manager.satisfies("1.4.9", "~=1.4.2") and not plugin_manager.satisfies("1.5.0", "~=1.4.2")
    assert plugin_manager.semver_key("1.0.0-rc.1") < plugin_manager.semver_key("1.0.0")
    assert plugin_manager.satisfies("0.1.0", None)


# ---------------------------------------------------------------- identity, registration, heartbeat, signed answers


def test_register_and_heartbeat(hub: FakeHub) -> None:
    current = marketplace.heartbeat()
    me = client.identity()
    stored = storage().get(client.COLLECTION, "identity")
    assert stored is not None and stored["private_key"].startswith("enc:v1:")  # encrypted with the vault key
    assert me.installation_id in hub.installations
    assert set(me.pinned()) == {hub.key_id}  # the hub's key, trusted at first use (no root key configured)
    assert current["lease"] and marketplace.lease() is not None
    report = hub.heartbeats[-1]
    assert len(report["core_hash"]) == 64 and report["plugins"] == []
    assert report["sudoo_version"] == client.sudoo_version()
    # the same fingerprint at registration and in every heartbeat: installation key + machine id + MAC
    assert report["hardware_fingerprint"] == hub.fingerprints[me.installation_id]
    assert report["hardware_fingerprint"] == crypto.fingerprint(
        me.public_key, client.machine_id(), client.primary_mac()
    )
    # the optional server figures
    assert report["instances_total"] == 0 and report["instances_running"] == 0 and report["odoo_versions"] == []
    # every 15 minutes, as the hub asks
    assert 890 <= current["next_heartbeat_at"] - time.time() <= 900
    # a second heartbeat does not register again
    marketplace.heartbeat()
    assert sum(1 for r in hub.requests if r == "POST /api/v1/register") == 1


def test_root_keys_are_trusted_first(hub: FakeHub, monkeypatch: pytest.MonkeyPatch) -> None:
    other = crypto.public_key_b64url(Ed25519PrivateKey.generate().public_key())
    monkeypatch.setattr(client, "root_keys", lambda: [other])  # a root key the hub does not use
    with pytest.raises(HubUnavailable, match="not accepted"):
        marketplace.heartbeat()
    assert hub.installations == {}  # nothing was sent before the hub's keys were trusted
    monkeypatch.setattr(client, "root_keys", lambda: [hub.key.public])
    client.update_identity(hub_keys={}, hub_url=None)
    marketplace.heartbeat()
    assert client.identity().known()[hub.key_id]["source"] == "root"


def test_unsigned_or_stale_answers_are_refused(hub: FakeHub) -> None:
    marketplace.heartbeat()
    hub.unsigned_answers = True
    with pytest.raises(HubUnavailable, match="not signed"):
        marketplace.heartbeat()
    assert marketplace.state()["error_code"] == "unverified"
    with pytest.raises(HubUnavailable, match="not signed"):  # a refusal must be signed too
        client.request("GET", "/api/v1/installations/nothing-here")
    hub.unsigned_answers = False
    hub.answer_skew = 400
    with pytest.raises(HubUnavailable, match="5 minutes"):
        marketplace.heartbeat()
    hub.answer_skew = 0
    with pytest.raises(HubRefused) as refused:  # a signed refusal is believed
        client.request("GET", "/api/v1/installations/nothing-here")
    assert refused.value.status == 404


def test_a_lease_or_answer_from_another_key_is_refused(hub: FakeHub) -> None:
    marketplace.heartbeat()
    hub.keys[0].private = Ed25519PrivateKey.generate()  # the hub (or someone in between) signs with another key
    with pytest.raises(HubUnavailable, match="not accepted"):
        marketplace.heartbeat()
    assert marketplace.state()["error_code"] == "unverified"


def test_a_rotated_key_is_trusted_through_its_endorsement(hub: FakeHub) -> None:
    marketplace.heartbeat()
    first = hub.key_id
    hub.rotate()  # the old key retires, the new one is endorsed by it
    marketplace.heartbeat()  # signed with the new key: the panel reads the keys once and follows the endorsement
    known = client.identity().known()
    assert known[hub.key_id]["source"] == "endorsed" and known[first]["state"] == "retiring"
    assert set(client.identity().pinned()) == {first, hub.key_id}  # retiring: accepted until its not_after
    hub.keys[0].not_after = int(time.time()) - 1  # its time is over
    marketplace.heartbeat()
    assert set(client.identity().pinned()) == {hub.key_id}


def test_a_key_without_a_valid_endorsement_or_after_a_revocation_is_not_trusted(hub: FakeHub) -> None:
    marketplace.heartbeat()
    hub.rotate(endorse=False)
    with pytest.raises(HubUnavailable, match="not accepted"):
        marketplace.heartbeat()
    hub.keys.pop()
    hub.keys[0].state = "active"
    marketplace.heartbeat()
    hub.rotate(revoke_previous=True)  # the key leaked: its endorsement is worth nothing
    with pytest.raises(HubUnavailable, match="not accepted"):
        marketplace.heartbeat()
    assert not client.identity().pinned()  # the revoked key is dropped at once


def test_hub_unreachable_degrades(hub: FakeHub, admin: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    hub.stop()
    web, _ = admin
    with pytest.raises(HubUnavailable):
        marketplace.heartbeat()
    answer = web.get("/api/v1/marketplace/catalog")
    assert answer.status_code == 503
    assert "cannot be reached" in answer.get_json()["detail"]
    assert web.get("/api/v1/plugins").status_code == 200  # installed plugins still listed
    status = web.get("/api/v1/marketplace").get_json()["data"]
    assert status["reachable"] is False and status["lease_valid"] is False
    hub.start = lambda: hub  # type: ignore[method-assign]  # already stopped; the fixture stops it again
    hub.stop = lambda: None  # type: ignore[method-assign]


def test_marketplace_off(hub: FakeHub, admin: Client, monkeypatch: pytest.MonkeyPatch) -> None:

    live.change({"marketplace": False})
    try:
        web, headers = admin
        assert web.get("/api/v1/marketplace/catalog").status_code == 409
        assert web.post("/api/v1/plugins", json={"id": FREE}, headers=headers).status_code == 409
        assert web.get("/api/v1/marketplace").get_json()["data"]["enabled"] is False
        assert web.get("/api/v1/marketplace/recommendations").status_code == 409
    finally:
        live.change({"marketplace": None})
    assert hub.requests == []  # off: the panel never contacts the hub


# ---------------------------------------------------------------- installing


def test_install_a_free_plugin(hub: FakeHub, admin: Client) -> None:
    free_listing(hub)
    job = install(admin, FREE)
    assert job.status == "success", "".join(job.log)
    rec = plugin_manager.record(FREE)
    assert rec is not None and rec["version"] == "1.0.0" and rec["enabled"]
    folder = plugin_manager.folder(rec)
    # private: folders 700, files 600, the package file is gone
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) in (0o700, 0o600) for p in folder.rglob("*"))
    assert not any((plugin_manager.plugins_dir() / ".downloads").iterdir())
    assert stat.S_IMODE(plugin_manager.plugins_dir().stat().st_mode) == 0o700
    # the backend restarts once the job has finished
    deadline = time.time() + 10
    while not RESTARTS and time.time() < deadline:
        time.sleep(0.1)
    assert RESTARTS
    # after the restart: the plugin's entry point is found by plugins.load
    plugin_manager.LOADED = None
    assert FREE in plugin_manager.activate()
    loaded = plugins.load("sudoo.mailers", "hello-mail", settings)
    assert type(loaded).__name__ == "Hello" and loaded.version == "1.0.0"
    # the API lists it without any file or path
    web, _ = admin
    listed = web.get("/api/v1/plugins").get_json()["data"]
    assert [p["id"] for p in listed] == [FREE] and listed[0]["status"] == "active"
    assert "package" not in json.dumps(listed) and str(folder) not in json.dumps(listed)
    # the next heartbeat reports it
    marketplace.heartbeat()
    assert hub.heartbeats[-1]["plugins"] == [{"id": FREE, "version": "1.0.0"}]


def test_install_through_a_storage_redirect_and_update(hub: FakeHub, admin: Client) -> None:
    hub.redirect_downloads = True
    listing = free_listing(hub, module="hello_redirect", entry="hello-redirect")
    assert install(admin, FREE).status == "success"
    listing.versions["1.1.0"] = make_package(FREE, "1.1.0", module="hello_redirect", entry="hello-redirect")
    plugin_manager._RESTART_PENDING.clear()
    marketplace.heartbeat()  # the hub now knows 1.0.0 is installed and offers 1.1.0
    web, headers = admin
    listed = web.get("/api/v1/plugins").get_json()["data"][0]
    assert listed["update_available"] is True and listed["latest_version"] == "1.1.0"
    item = web.get("/api/v1/marketplace/catalog?installed=true").get_json()["data"][0]
    assert item["action"] == "update"
    answer = web.post(f"/api/v1/plugins/{FREE}/update", headers=headers)
    assert wait(answer.get_json()["data"]["id"]).status == "success"
    rec = plugin_manager.record(FREE)
    assert rec is not None and rec["version"] == "1.1.0"
    assert not (plugin_manager.plugins_dir() / FREE / "1.0.0").exists()


def test_a_tampered_package_is_refused(hub: FakeHub, admin: Client) -> None:
    free_listing(hub, module="hello_tampered", entry="hello-tampered")
    hub.tamper_downloads = True
    job = install(admin, FREE)
    assert job.status == "failed"
    assert "SHA-256 does not match" in "".join(job.log)
    assert plugin_manager.record(FREE) is None
    assert not (plugin_manager.plugins_dir() / FREE / "1.0.0").exists()
    assert not any((plugin_manager.plugins_dir() / ".downloads").iterdir())  # the download is deleted too
    assert not RESTARTS


def test_an_unsigned_download_is_refused(hub: FakeHub, admin: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    free_listing(hub, module="hello_unsigned", entry="hello-unsigned")
    marketplace.heartbeat()
    real = client._send

    def strip(method: str, path: str, *args: Any, **kwargs: Any) -> Any:
        hub.unsigned_answers = "/download/" in path
        return real(method, path, *args, **kwargs)

    monkeypatch.setattr(client, "_send", strip)
    job = install(admin, FREE)
    assert job.status == "failed" and "not signed" in "".join(job.log)
    assert plugin_manager.record(FREE) is None


def test_a_package_signed_with_another_key_is_refused(hub: FakeHub, admin: Client) -> None:
    free_listing(hub, module="hello_otherkey", entry="hello-otherkey")
    marketplace.heartbeat()  # registers and trusts the hub's key
    hub.keys[0].private = Ed25519PrivateKey.generate()  # as if someone forged packages and answers
    job = install(admin, FREE)
    assert job.status == "failed"
    assert plugin_manager.record(FREE) is None


def test_modified_files_are_detected(hub: FakeHub, admin: Client) -> None:
    free_listing(hub, module="hello_modified", entry="hello-modified")
    assert install(admin, FREE).status == "success"
    rec = plugin_manager.record(FREE)
    assert rec is not None
    target = plugin_manager.folder(rec) / "package" / "hello_modified" / "plugin.py"
    target.write_text("print('changed')\n")
    plugin_manager.LOADED = None
    assert FREE not in plugin_manager.activate()
    rec = plugin_manager.record(FREE)
    assert rec is not None and rec["tampered"]
    assert any(n["kind"] == "modified" for n in plugin_manager.notices())
    web, headers = admin
    assert web.post(f"/api/v1/plugins/{FREE}/enable", headers=headers).status_code == 409


def _zip(files: dict[str, bytes | str]) -> zipfile.ZipFile:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return zipfile.ZipFile(io.BytesIO(buffer.getvalue()))


def _package(**manifest: Any) -> dict[str, bytes | str]:
    return dict(_entries(make_package(FREE, "1.0.0", manifest=manifest)))


def _entries(package: bytes) -> Iterator[tuple[str, bytes]]:
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        for name in archive.namelist():
            yield name, archive.read(name)


@pytest.mark.parametrize(
    ("files", "message"),
    [
        (_package(min_sudoo_version="99.0.0"), "needs Sudoo.sh 99.0.0"),
        (_package(max_sudoo_version="0.0.1"), "works up to Sudoo.sh 0.0.1"),
        (_package(sdk_version=">=9.0.0"), "plugin SDK"),
        (_package(requires=["com.example.missing"]), "Install and enable com.example.missing first"),
        (_package(entry_points={"sudoo.storage": {"x": "hello_plugin.plugin:Hello"}}), "cannot be installed"),
        (_package(entry_points={"sudoo.mailers": {"smtp": "hello_plugin.plugin:Hello"}}), "already provides"),
        ({**_package(), "pyproject.toml": '[project]\nname="x"\ndependencies=["requests"]\n'}, "other Python packages"),
        ({**_package(), "requirements.txt": "requests==2.0\n"}, "other Python packages"),
        ({**_package(), "hello_plugin/fast.so": b"\x7fELF"}, "compiled code"),
        ({**_package(), "../evil.py": "x"}, "outside its folder"),
        ({**_package(), "/etc/evil.py": "x"}, "outside its folder"),
        ({**_package(), "flask/__init__.py": ""}, "would clash"),
        ({k: v for k, v in _package().items() if k != "manifest.json"}, "no manifest.json"),
        (_package(id="com.example.other"), "another plugin or version"),
    ],
)
def test_packages_that_do_not_suit_are_refused(files: dict[str, bytes | str], message: str) -> None:
    with pytest.raises(plugin_manager.PluginRefused, match=message):
        plugin_manager.check_package(_zip(files), FREE, "1.0.0")


SDK_PYPROJECT = '[project]\nname="x"\ndependencies=["sudoo-plugin-sdk>=0.1.0,<1.0.0"]\n'


@pytest.mark.parametrize(
    ("installed", "extra", "message"),
    [
        ("0.1.0", "", None),  # every plugin made with the SDK declares it: fine when the panel has it
        (None, "", "does not include yet"),
        ("1.2.0", "", "needs plugin SDK >=0.1.0,<1.0.0; this panel has 1.2.0"),
        ("0.1.0", "requests", "other Python packages"),
    ],
)
def test_a_dependency_on_the_plugin_sdk(
    monkeypatch: pytest.MonkeyPatch, installed: str | None, extra: str, message: str | None
) -> None:
    def sdk_version(name: str) -> str:
        assert name == "sudoo-plugin-sdk"
        if installed is None:
            raise plugin_manager.PackageNotFoundError(name)
        return installed

    monkeypatch.setattr(plugin_manager, "package_version", sdk_version)
    pyproject = SDK_PYPROJECT.replace('"]\n', f'", "{extra}"]\n') if extra else SDK_PYPROJECT
    files = {**dict(_entries(make_package(FREE, "1.0.0", module="sdk_hello"))), "pyproject.toml": pyproject}
    if message is None:
        assert plugin_manager.check_package(_zip(files), FREE, "1.0.0")["id"] == FREE
    else:
        with pytest.raises(plugin_manager.PluginRefused, match=re.escape(message)):
            plugin_manager.check_package(_zip(files), FREE, "1.0.0")


def test_a_refused_install_says_why(hub: FakeHub, admin: Client) -> None:
    free_listing(hub, manifest={"min_sudoo_version": "99.0.0"})
    job = install(admin, FREE)
    web, _ = admin
    shown = web.get(f"/api/v1/jobs/{job.id}").get_json()["data"]
    assert shown["status"] == "failed"
    assert "needs Sudoo.sh 99.0.0 or newer" in shown["error"]  # the reason, not a general hint


def test_links_in_a_package_are_refused() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in _package().items():
            archive.writestr(name, content)
        link = zipfile.ZipInfo("hello_plugin/link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "/etc/passwd")
    with pytest.raises(plugin_manager.PluginRefused, match="link"):
        plugin_manager.check_package(zipfile.ZipFile(io.BytesIO(buffer.getvalue())), FREE, "1.0.0")


def test_installing_is_refused_while_jobs_run(hub: FakeHub, admin: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(jobs.ACTIVE_JOB, "demo", jobs.Job("demo", "Restart", "restart", "x"))
    web, headers = admin
    answer = web.post("/api/v1/plugins", json={"id": FREE}, headers=headers)
    assert answer.status_code == 409 and "Jobs are running" in answer.get_json()["detail"]


# ---------------------------------------------------------------- disable, enable, uninstall, permissions


def test_disable_enable_and_uninstall(hub: FakeHub, admin: Client) -> None:
    free_listing(hub, module="hello_switch", entry="hello-switch")
    assert install(admin, FREE).status == "success"
    plugin_manager.LOADED = None
    plugin_manager.activate()
    plugin_manager._RESTART_PENDING.clear()
    web, headers = admin
    off = web.post(f"/api/v1/plugins/{FREE}/disable", headers=headers).get_json()["data"]
    assert off["enabled"] is False and off["status"] == "disabled" and off["restart_pending"] is True
    plugin_manager._RESTART_PENDING.clear()
    on = web.post(f"/api/v1/plugins/{FREE}/enable", headers=headers).get_json()["data"]
    assert on["enabled"] is True and on["status"] == "active"
    plugin_manager._RESTART_PENDING.clear()
    assert web.delete(f"/api/v1/plugins/{FREE}", json={}, headers=headers).status_code == 400  # confirm needed
    answer = web.delete(f"/api/v1/plugins/{FREE}", json={"confirm": FREE}, headers=headers)
    job = wait(answer.get_json()["data"]["id"])
    assert job.status == "success", "".join(job.log)
    assert plugin_manager.record(FREE) is None
    assert not (plugin_manager.plugins_dir() / FREE).exists()
    backups = list(plugin_manager.panel_backups_dir().glob(f"panel__*__before-uninstall-{FREE}.zip"))
    assert backups and stat.S_IMODE(backups[0].stat().st_mode) == 0o600
    with zipfile.ZipFile(backups[0]) as archive:
        assert "sudoo.db" in archive.namelist()


def test_permissions(hub: FakeHub, app: Flask, admin: Client, operator: Client) -> None:
    web, _ = operator  # a developer sees nothing of plugins
    assert web.get("/api/v1/plugins").status_code == 403
    if not accounts.get("admin2"):
        accounts.create("admin2", "admin", "harbour-candle-orbit-58", email="admin2@example.com")
    viewer, headers = sign_in(app, "admin2", "harbour-candle-orbit-58")  # an administrator sees, cannot install
    assert viewer.get("/api/v1/plugins").status_code == 200
    assert viewer.post("/api/v1/plugins", json={"id": FREE}, headers=headers).status_code == 403
    assert viewer.post("/api/v1/marketplace/link", json={"code": "LINKCODE42"}, headers=headers).status_code == 403
    assert viewer.post("/api/v1/marketplace/unlink", json={"confirm": True}, headers=headers).status_code == 403
    body = {"plugin_id": PAID, "plan_id": "x" * 20, "idempotency_key": "k" * 20}
    assert viewer.post("/api/v1/marketplace/checkout-sessions", json=body, headers=headers).status_code == 403


# ---------------------------------------------------------------- linking and buying (checkout on app.sudoo.sh)


def paid_listing(fake: FakeHub, *extra_plans: dict[str, Any]) -> Listing:
    package = make_package(PAID, "2.0.0", module="paid_plugin", entry="paid-mail", tier="paid",
                           manifest={"name": "Paid plugin", "permissions": ["instances.write"]})  # fmt: skip
    plans = [plan("monthly", 1000), *extra_plans]
    return fake.publish(Listing(PAID, "Paid plugin", tier="paid", versions={"2.0.0": package}, plans=plans))


def link(admin: Client) -> None:
    web, headers = admin
    assert web.post("/api/v1/marketplace/link", json={"code": "LINKCODE42"}, headers=headers).status_code == 200


def test_link_with_a_one_time_code(hub: FakeHub, admin: Client) -> None:
    web, headers = admin
    wrong = web.post("/api/v1/marketplace/link", json={"code": "WRONGCODE1"}, headers=headers)
    assert wrong.status_code == 404 and "not valid" in wrong.get_json()["detail"]
    link(admin)
    assert web.get("/api/v1/marketplace").get_json()["data"]["linked"]["account_name"] == "Ada's company"


def open_session(web: FlaskClient, headers: dict[str, str], plan_id: str, key: str = "press-0001-abcdefgh") -> Any:
    body = {"plugin_id": PAID, "plan_id": plan_id, "idempotency_key": key}
    return web.post("/api/v1/marketplace/checkout-sessions", json=body, headers=headers)


def test_buy_through_a_checkout_session_then_install(hub: FakeHub, admin: Client) -> None:
    listing = paid_listing(hub, plan("yearly", 10000), plan("one_time", 25000))
    monthly, yearly, once = listing.plans
    web, headers = admin
    refused = open_session(web, headers, monthly["id"])
    assert refused.status_code == 409 and "Link this panel" in refused.get_json()["detail"]
    billing = web.get("/api/v1/marketplace/billing").get_json()["data"]
    assert billing == {"payments_enabled": True, "linked": False, "account_name": None, "can_buy": False,
                       "reason": "link_required", "currency": "usd", "manage_url": "https://app.sudoo.sh/servers"}  # fmt: skip
    link(admin)
    assert web.get("/api/v1/marketplace/billing").get_json()["data"]["can_buy"] is True
    # prices: monthly equivalent and saving, one-time
    item = next(i for i in web.get("/api/v1/marketplace/catalog").get_json()["data"] if i["id"] == PAID)
    shown = {p["kind"]: p for p in item["plans"]}
    assert (shown["yearly"]["monthly_equivalent_cents"], shown["yearly"]["savings_percent"]) == (833, 17)
    assert shown["one_time"]["perpetual"] is True and shown["one_time"]["interval"] is None
    # ask to buy: a session whose page on app.sudoo.sh the owner opens; nothing is charged from the panel
    answer = open_session(web, headers, yearly["id"])
    assert answer.status_code == 201 and answer.headers["Location"].endswith(answer.get_json()["data"]["id"])
    session = answer.get_json()["data"]
    assert session["status"] == "open" and session["url"].startswith("https://app.sudoo.sh/checkout/")
    assert session["plan"]["savings_percent"] == 17
    sent = hub.sessions[session["id"]]["requested_by"]  # who pressed Buy, shown on the page and the receipt
    assert sent["email"] == "ada@example.com" and sent["name"]
    # the same press again (a retry) answers the same session; the same key for another plan is refused
    assert open_session(web, headers, yearly["id"]).get_json()["data"]["id"] == session["id"]
    reused = open_session(web, headers, monthly["id"])
    assert reused.status_code == 409 and "Press Buy again" in reused.get_json()["detail"]
    # before paying, the hub does not hand out the package
    job = install(admin, PAID)
    assert job.status == "failed" and "no licence" in "".join(job.log)
    plugin_manager._RESTART_PENDING.clear()
    poll = f"/api/v1/marketplace/checkout-sessions/{session['id']}"
    hub.decline(session["id"], "insufficient_funds")  # a declined card: open again, with the reason
    declined = web.get(poll).get_json()["data"]
    assert declined["status"] == "open" and declined["reason"] == "insufficient_funds" and declined["url"]
    hub.pay(session["id"])
    paid = web.get(poll).get_json()["data"]
    assert paid["status"] == "succeeded" and paid["url"] is None and paid["receipt_number"] == "SR-000001"
    # the next lease lists the licence even before the plugin is installed
    marketplace.heartbeat()
    lease = marketplace.lease()
    assert lease is not None and PAID in lease.licences and plugin_manager.record(PAID) is None
    assert install(admin, PAID).status == "success"
    history = web.get("/api/v1/marketplace/checkout-sessions").get_json()["data"]
    assert [(p["status"], p["receipt_number"]) for p in history] == [("succeeded", "SR-000001")]
    receipts = web.get("/api/v1/marketplace/receipts").get_json()["data"]
    assert receipts[0]["number"] == "SR-000001" and receipts[0]["total_cents"] == 10000
    csv = web.get("/api/v1/marketplace/receipts?format=csv")
    assert csv.mimetype == "text/csv" and csv.text.splitlines()[0].startswith("number,kind,issued_at")
    assert web.get("/api/v1/marketplace/checkout-sessions?format=csv").text.startswith("created_at,plugin_name")
    # the old direct purchase is gone
    assert web.post("/api/v1/marketplace/purchases", json={}, headers=headers).status_code in (404, 405)


def test_a_checkout_session_needs_an_idempotency_key(hub: FakeHub, admin: Client) -> None:
    web, headers = admin
    body = {"plugin_id": PAID, "plan_id": "plan-monthly"}
    assert web.post("/api/v1/marketplace/checkout-sessions", json=body, headers=headers).status_code == 400


def test_a_one_time_licence_is_perpetual(hub: FakeHub, admin: Client) -> None:
    listing = paid_listing(hub, plan("one_time", 25000))
    web, headers = admin
    link(admin)
    session = open_session(web, headers, listing.plans[1]["id"]).get_json()["data"]
    hub.pay(session["id"])
    assert install(admin, PAID).status == "success"
    marketplace.heartbeat()
    rec = plugin_manager.record(PAID)
    assert rec is not None and rec["licence"]["perpetual"] and rec["licence"]["expires_at"] is None
    listed = web.get("/api/v1/plugins").get_json()["data"][0]
    assert listed["licence"]["phase"] == "perpetual" and listed["licence"]["perpetual"] is True
    # perpetual, but it follows the offline rule: without a newer lease it stops at run_until
    run_until = rec["licence"]["run_until"]
    assert plugin_manager.allowed(rec, run_until - 1) == (True, "ok")
    assert plugin_manager.allowed(rec, run_until + 1) == (False, "no_lease")


# ---------------------------------------------------------------- licences: expiry, grace, end, renewal


def _paid_installed(hub: FakeHub, admin: Client) -> dict[str, Any]:
    paid_listing(hub)
    link(admin)
    hub.licences[PAID] = {"state": "active", "expires_at": int(time.time()) + 20 * 86400,
                          "grace_until": int(time.time()) + 27 * 86400}  # fmt: skip
    assert install(admin, PAID).status == "success"
    plugin_manager._RESTART_PENDING.clear()
    marketplace.heartbeat()
    plugin_manager.LOADED = {PAID}
    rec = plugin_manager.record(PAID)
    assert rec is not None
    return rec


def test_expiry_grace_and_end(hub: FakeHub, admin: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _paid_installed(hub, admin)
    expires, grace = rec["licence"]["expires_at"], rec["licence"]["grace_until"]
    run_until = rec["licence"]["run_until"]
    assert abs(run_until - (time.time() + (72 + 96) * 3600)) < 60  # the lease's end plus 96 hours offline
    assert plugin_manager.phase(rec, time.time(), True) == "active"
    later = {**rec, "licence": {**rec["licence"], "run_until": grace}}  # as with a newer lease
    assert plugin_manager.phase(later, expires - 3 * 86400, True) == "expiring"
    assert plugin_manager.phase(later, expires + 86400, True) == "grace"
    assert plugin_manager.allowed(rec, run_until - 1) == (True, "ok")
    assert plugin_manager.allowed(rec, run_until + 1) == (False, "no_lease")  # no newer lease: it stops
    assert plugin_manager.allowed(rec, grace + 1) == (False, "licence_ended")

    mails: list[str] = []
    monkeypatch.setattr(plugin_manager, "_mail_super_admins", lambda subject, title, text: mails.append(subject))
    started: list[jobs.Job] = []

    def run_now(instance: str, action: str, kind: str, fn: Any, *args: Any, user: str = "system") -> jobs.Job:
        job = jobs.Job(instance, action, kind, user)
        fn(job, *args)
        started.append(job)
        return job

    def travel(to: float) -> None:
        """The panel and the hub at another time; the panel's heartbeat keeps its lease current."""
        monkeypatch.setattr(marketplace, "trusted_now", lambda: float(to))
        hub.now = float(to)
        marketplace.heartbeat()

    # 3 days before: a reminder, once
    travel(expires - 3 * 86400)
    plugin_manager.watch(start_job=run_now)
    plugin_manager.watch(start_job=run_now)
    assert mails == ["Paid plugin ends soon"]
    assert [n["kind"] for n in plugin_manager.notices()] == ["expiring"]
    # in the grace period: still running, a banner says when it stops
    travel(expires + 86400)
    plugin_manager.watch(start_job=run_now)
    assert not started and [n["kind"] for n in plugin_manager.notices()] == ["grace"]
    # the grace is over: back up, switch off (data kept), tell the super admins, restart
    travel(grace + 60)  # the hub's lease now says expired
    plugin_manager.watch(start_job=run_now)
    assert len(started) == 1 and started[0].kind == "plugin-expired"
    rec = plugin_manager.record(PAID)
    assert rec is not None and rec["switched_off"]["reason"] == "licence" and rec["enabled"] is True
    assert plugin_manager.folder(rec).exists()  # nothing deleted
    assert list(plugin_manager.panel_backups_dir().glob(f"panel__*__before-{PAID}-stops.zip"))
    assert mails[-1] == "Paid plugin was switched off"
    assert plugin_manager.restart_pending()
    assert [n["kind"] for n in plugin_manager.notices()] == ["ended"]
    plugin_manager.watch(start_job=run_now)
    assert len(started) == 1  # switched off once
    # renewed: the next lease says licensed again, the plugin comes back on by itself
    plugin_manager._RESTART_PENDING.clear()
    plugin_manager.LOADED = set()
    hub.licences[PAID] = {
        "state": "active",
        "expires_at": int(grace + 30 * 86400),
        "grace_until": int(grace + 37 * 86400),
    }
    travel(grace + 120)
    plugin_manager.watch(start_job=run_now)
    rec = plugin_manager.record(PAID)
    assert rec is not None and rec["switched_off"] is None
    assert mails[-1] == "Paid plugin is back on"
    assert plugin_manager.restart_pending()  # to load it again


def test_turning_the_clock_back_does_not_extend_a_licence(hub: FakeHub, admin: Client) -> None:
    _paid_installed(hub, admin)
    marketplace._save(high_water=time.time() + 400 * 86400)  # the panel saw a later time before
    assert marketplace.trusted_now() > time.time() + 399 * 86400
    rec = plugin_manager.record(PAID)
    assert rec is not None and plugin_manager.allowed(rec)[0] is False


def test_a_copied_server_is_flagged_and_its_paid_plugins_withheld(hub: FakeHub, admin: Client) -> None:
    _paid_installed(hub, admin)
    me = client.identity()
    hub.fingerprints[me.installation_id] = "0" * 64  # registered from another machine than this one
    marketplace.heartbeat()
    assert marketplace.flags() == ["fingerprint_mismatch"]
    rec = plugin_manager.record(PAID)
    assert rec is not None and rec["standing"] == "blocked"
    assert plugin_manager.allowed(rec) == (False, "withheld")
    web, _ = admin
    listed = web.get("/api/v1/plugins").get_json()["data"][0]
    assert listed["status"] == "withheld" and listed["licence"]["phase"] == "withheld"
    kinds = [n["kind"] for n in web.get("/api/v1/plugins/notices").get_json()["data"]]
    assert "fingerprint_mismatch" in kinds and "withheld" in kinds
    assert web.get("/api/v1/marketplace").get_json()["data"]["flags"] == ["fingerprint_mismatch"]
    billing = web.get("/api/v1/marketplace/billing").get_json()["data"]
    assert billing["can_buy"] is False and billing["reason"] == "fingerprint_mismatch"


def test_integrity_violation_switches_every_plugin_off(hub: FakeHub, admin: Client) -> None:
    free_listing(hub, module="hello_blocked", entry="hello-blocked")
    assert install(admin, FREE).status == "success"
    hub.heartbeat_refusal = "integrity_violation"
    with pytest.raises(HubRefused):
        marketplace.heartbeat()
    rec = plugin_manager.record(FREE)
    assert rec is not None and plugin_manager.allowed(rec) == (False, "blocked")
    assert plugin_manager.notices()[0]["kind"] == "integrity_violation"


# ---------------------------------------------------------------- logging out, commands, a revoked key


def test_log_out_removes_paid_plugins_only(hub: FakeHub, admin: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    free_listing(hub, module="hello_kept", entry="hello-kept")
    assert install(admin, FREE).status == "success"
    plugin_manager._RESTART_PENDING.clear()
    _paid_installed(hub, admin)
    plugin_manager._RESTART_PENDING.clear()
    backed_up: list[str] = []
    monkeypatch.setattr(plugin_manager, "_backup_instances", lambda job, title: backed_up.append(title) or [])
    web, headers = admin
    assert web.post("/api/v1/marketplace/unlink", json={}, headers=headers).status_code == 400  # confirm needed
    answer = web.post("/api/v1/marketplace/unlink", json={"confirm": True}, headers=headers)
    assert answer.status_code == 200 and answer.get_json()["data"]["linked"] is None
    job = wait_for("plugin-remove-paid")
    assert job.status == "success", "".join(job.log)
    # backed up first (the panel, and the instances: the plugin may change them), then only the paid one removed
    assert list(plugin_manager.panel_backups_dir().glob("panel__*__before-removing-paid-plugins.zip"))
    assert backed_up
    assert plugin_manager.record(PAID) is None and not (plugin_manager.plugins_dir() / PAID).exists()
    assert plugin_manager.record(FREE) is not None
    # acknowledged as done, once
    [(command_id, ack)] = hub.acks
    assert ack["status"] == "done" and PAID in ack["detail"]
    assert marketplace.commands_done()[command_id]["acked"] is True
    assert plugin_manager.restart_pending()
    # the hub sends it again (the acknowledgement was lost): only acknowledged again, nothing removed or backed up
    hub.commands[command_id]["acked"] = False
    backups = len(list(plugin_manager.panel_backups_dir().glob("*.zip")))
    marketplace.heartbeat()
    assert [c for c, _ in hub.acks] == [command_id, command_id]
    assert len(list(plugin_manager.panel_backups_dir().glob("*.zip"))) == backups
    assert not [j for j in jobs.JOBS.values() if j.kind == "plugin-remove-paid" and j.id != job.id]


def test_a_command_with_a_bad_signature_is_ignored(hub: FakeHub, admin: Client) -> None:
    marketplace.heartbeat()
    me = client.identity()
    command = hub.command_out(_queue(hub, me.installation_id), me.installation_id)
    assert marketplace.verify_command(command, me)
    forged = {**command, "payload": {"plugins": [FREE], "reason": "unlinked"}}
    assert not marketplace.verify_command(forged, me)
    assert not marketplace.verify_command({**command, "signature": "A" * 86}, me)
    marketplace.carry_out([forged])
    assert hub.acks == [] and marketplace.commands_done() == {}


def _queue(hub: FakeHub, installation: str) -> str:
    hub.commands["c0ffee00-0000-4000-8000-000000000001"] = {
        "kind": "remove_paid_plugins", "issued_at": int(time.time()),
        "payload": {"plugins": [PAID], "reason": "unlinked"}, "acked": False, "installation": installation}  # fmt: skip
    return "c0ffee00-0000-4000-8000-000000000001"


def test_a_command_for_nothing_installed_is_acknowledged(hub: FakeHub) -> None:
    marketplace.heartbeat()
    command_id = _queue(hub, client.identity().installation_id)
    marketplace.heartbeat()
    wait_for("plugin-remove-paid")
    assert hub.acks == [(command_id, {"status": "done", "detail": "Nothing to remove."})]


def test_a_revoked_key_makes_a_new_identity(hub: FakeHub, admin: Client) -> None:
    link(admin)
    marketplace.heartbeat()
    old = client.identity().installation_id
    hub.revoked.add(old)  # the owner revoked this server's key on app.sudoo.sh
    marketplace.heartbeat()
    me = client.identity()
    assert me.installation_id != old and me.installation_id in hub.installations  # registered again
    assert storage().get(client.COLLECTION, "identity")["replaced"] == [old]
    web, _ = admin
    status = web.get("/api/v1/marketplace").get_json()["data"]
    assert status["linked"] is None and status["key_revoked_at"] and status["installation_id"] == me.installation_id
    assert "key_revoked" in [n["kind"] for n in plugin_manager.notices()]


# ---------------------------------------------------------------- catalogue: views, recommendations, icons


def test_catalogue_marks_installed_plugins(hub: FakeHub, admin: Client) -> None:
    free_listing(hub, module="hello_catalogue", entry="hello-catalogue")
    paid_listing(hub)
    assert install(admin, FREE).status == "success"
    web, _ = admin
    items = web.get("/api/v1/marketplace/catalog?q=hello").get_json()["data"]
    assert [(i["id"], i["installed_version"]) for i in items] == [(FREE, "1.0.0")]
    actions = {i["id"]: i["action"] for i in web.get("/api/v1/marketplace/catalog").get_json()["data"]}
    assert actions[PAID] == "buy"
    detail = web.get(f"/api/v1/marketplace/catalog/{PAID}").get_json()["data"]
    assert detail["plans"][0]["kind"] == "monthly" and detail["permissions"] == ["network.outbound"]
    assert detail["installed_version"] is None
    assert web.get("/api/v1/marketplace/catalog?sort=wrong").status_code == 400
    assert web.get("/api/v1/marketplace/categories").get_json()["data"][0]["type"] == "mailer"


def test_views_recommendations_and_icons(hub: FakeHub, admin: Client) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
    hub.publish(Listing(FREE, "Hello mailer", versions={"1.0.0": make_package(FREE, "1.0.0")}, icon=png,
                        countries=["SA"]))  # fmt: skip
    paid_listing(hub)
    web, _ = admin
    marketplace.heartbeat()
    # opening a plugin's page tells the hub (a recommendation signal, kept only with the owner's consent)
    web.get(f"/api/v1/marketplace/catalog/{FREE}")
    deadline = time.time() + 5
    while not hub.views and time.time() < deadline:
        time.sleep(0.05)
    assert hub.views == [FREE]
    picks = web.get("/api/v1/marketplace/recommendations?limit=5").get_json()["data"]
    assert {p["plugin"]["id"] for p in picks} == {FREE, PAID}
    assert picks[0]["reasons"][0] == "Because you use Hello mailer"
    # the icon comes through the panel (the web app loads images from its own address only)
    item = next(i for i in web.get("/api/v1/marketplace/catalog").get_json()["data"] if i["id"] == FREE)
    assert item["icon_url"].startswith(f"/api/v1/marketplace/icons/{FREE}?v=") and item["countries"] == ["SA"]
    icon = web.get(item["icon_url"])
    assert icon.status_code == 200 and icon.mimetype == "image/png" and icon.data == png
    assert web.get(f"/api/v1/marketplace/icons/{FREE}?v=../../x").status_code == 404
    assert (
        next(i for i in web.get("/api/v1/marketplace/catalog").get_json()["data"] if i["id"] == PAID)["icon_url"]
        is None
    )


def test_b64url_round_trip() -> None:
    assert crypto.from_b64url(crypto.b64url(b"\xff\x00abc")) == b"\xff\x00abc"
    assert base64.urlsafe_b64decode(crypto.b64url(b"x") + "===") == b"x"
