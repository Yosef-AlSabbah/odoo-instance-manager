"""Hardened instances: the compose file the panel renders, what it refuses, and how changes made outside the panel
are found and undone. Docker is never run: image lookups are replaced, and containers are given as `docker inspect`
documents built from the rendering."""

from __future__ import annotations

import copy
import json
import shutil
import time
from collections.abc import Iterator
from typing import Any

import pytest

from sudoo.config import live
from sudoo.core import jobs
from sudoo.core.state import STATE
from sudoo.instances import integrity, odoo, operations, store

NAME = "hard"
IMAGE_IDS = {"odoo": "sha256:" + "a" * 64, "db": "sha256:" + "b" * 64}
REFS = {"ODOO_IMAGE_REF": "odoo:18.0@sha256:" + "1" * 64, "DB_IMAGE_REF": "postgres:16@sha256:" + "2" * 64}
IMAGE_ENV = {"odoo": ["PATH=/usr/bin", "ODOO_RC=/etc/odoo/odoo.conf"], "db": ["PATH=/usr/bin", "PGDATA=/x"]}


@pytest.fixture(autouse=True)
def instance(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    folder = store.folder(NAME)
    (folder / "config").mkdir(parents=True)
    (folder / "addons").mkdir()
    store.write_env(
        NAME,
        {"ODOO_VERSION": "18.0", "EDITION": "community", "ODOO_PORT": 28100, "GATEWAY_PORT": 8100,
         "DB_NAME": "hard", "DB_PASSWORD": "s3cret$pw", "AUTO_PAUSE": "false", "DELETE_AFTER_DAYS": 0,
         "CREATED_AT": int(time.time()), "GIT_BRANCH": "main", "AUTO_UPDATE": "false", "AUTO_UPGRADE": "false"},
    )  # fmt: skip
    odoo.write_config(NAME, "hard", "s3cret$pw", "master")
    monkeypatch.setattr(integrity, "pin_images", lambda job, name, pull: store.update_env(name, **REFS) or REFS)
    monkeypatch.setattr(integrity, "odoo_user", lambda reference: "100:101")
    monkeypatch.setattr(integrity, "isolated_networks", lambda: True)
    monkeypatch.setattr(
        integrity, "_image", lambda ref: {"Id": IMAGE_IDS["odoo" if "odoo" in ref else "db"], "RepoDigests": []}
    )
    monkeypatch.setattr(
        integrity,
        "image_details",
        lambda image_id: {
            "user": "odoo" if image_id == IMAGE_IDS["odoo"] else "",
            "env": IMAGE_ENV["odoo" if image_id == IMAGE_IDS["odoo"] else "db"],
            "volumes": ["/var/lib/odoo", "/mnt/extra-addons"] if image_id == IMAGE_IDS["odoo"] else [],
        },
    )
    monkeypatch.setattr(integrity, "_connector_name", lambda name: None)
    yield
    shutil.rmtree(folder, ignore_errors=True)
    integrity.forget(NAME)
    STATE.remove(NAME)
    live.change(dict.fromkeys(live.overrides()))


def _apply() -> dict[str, Any]:
    integrity.apply(jobs.Job(NAME, "test", "test", "system"), NAME)
    found = integrity.record(NAME)
    assert found is not None
    return found


def _inspect(service: str, spec: dict[str, Any]) -> dict[str, Any]:
    """The `docker inspect` document of a container Compose made from service `service` of `spec`."""
    want = spec["services"][service]
    mounts = []
    for volume in want["volumes"]:
        source, destination, *mode = volume.split(":")
        if source.startswith("/"):
            mounts.append({"Type": "bind", "Source": source, "Destination": destination, "RW": not mode})
        else:
            mounts.append({"Type": "volume", "Name": f"odoo-{NAME}_{source}", "Destination": destination, "RW": True})
    ports: dict[str, Any] = {}
    for port in want.get("ports", []):
        address, host_port, inside = port.split(":")
        ports[f"{inside}/tcp"] = [{"HostIp": address, "HostPort": host_port}]
    return {
        "Name": "/" + store.container(NAME, service),
        "Image": IMAGE_IDS[service],
        "Config": {
            "Image": want["image"],
            "User": "odoo" if service == "odoo" else "",
            "Labels": {**want["labels"], "com.docker.compose.project": f"odoo-{NAME}"},
            "Env": IMAGE_ENV[service] + [f"{k}={v}" for k, v in want["environment"].items()],
        },
        "HostConfig": {
            "Privileged": False,
            "CapDrop": ["ALL"],
            "CapAdd": [f"CAP_{cap}" for cap in want.get("cap_add", [])] or None,
            "ReadonlyRootfs": True,
            "SecurityOpt": ["no-new-privileges:true"],
            "PidsLimit": want["pids_limit"],
            "Memory": integrity._memory(want.get("mem_limit")),
            "NanoCpus": int(want.get("cpus", 0) * 1e9),
            "RestartPolicy": {"Name": "unless-stopped"},
            "Init": True,
            "Tmpfs": dict.fromkeys(want["tmpfs"], ""),
            "LogConfig": {"Type": "json-file", "Config": want["logging"]["options"]},
            "PortBindings": ports,
            "IpcMode": "private",
        },
        "NetworkSettings": {"Networks": {f"odoo-{NAME}_{n}": {} for n in want["networks"]}},
        "Mounts": mounts,
    }


def _containers(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {store.container(NAME, service): _inspect(service, spec) for service in ("odoo", "db")}


# ---------------------------------------------------------------- the rendering


def test_rendering_is_hardened_and_literal() -> None:
    kept = _apply()
    spec, text = kept["spec"], (store.folder(NAME) / "docker-compose.yml").read_text()
    for service in spec["services"].values():
        assert service["security_opt"] == ["no-new-privileges:true"] and service["cap_drop"] == ["ALL"]
        assert service["read_only"] is True and service["init"] is True and service["restart"] == "unless-stopped"
        assert service["labels"][odoo.LABEL_HASH] == kept["hash"] and service["labels"][odoo.LABEL_INSTANCE] == NAME
        assert service["logging"]["driver"] == "json-file" and service["pids_limit"] == 1024
    db, web = spec["services"]["db"], spec["services"]["odoo"]
    assert "ports" not in db and db["networks"] == ["backend"]
    assert set(db["cap_add"]) == {"CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID", "KILL"}
    assert "cap_add" not in web and web["ports"] == ["127.0.0.1:28100:8069"]
    assert spec["networks"]["backend"]["internal"] is True
    assert all(volume.endswith(":ro") for volume in web["volumes"] if volume.startswith("/"))
    assert web["image"] == REFS["ODOO_IMAGE_REF"] and db["image"] == REFS["DB_IMAGE_REF"]
    assert "${" not in text and '"s3cret$$pw"' in text  # literal values, "$" escaped for Compose
    assert "docker.sock" not in text


def test_unsafe_renderings_are_refused() -> None:
    spec = _apply()["spec"]
    changes = [
        lambda s: s["services"]["odoo"].update(privileged=True),
        lambda s: s["services"]["odoo"].update(network_mode="host"),
        lambda s: s["services"]["db"].update(ports=["5432:5432"]),
        lambda s: s["services"]["odoo"].update(ports=["0.0.0.0:8069:8069"]),
        lambda s: s["services"]["odoo"]["volumes"].append("/var/run/docker.sock:/var/run/docker.sock"),
        lambda s: s["services"]["odoo"]["volumes"].append("/srv/data:/mnt/data"),
        lambda s: s["services"]["odoo"].update(cap_add=["SYS_ADMIN"]),
        lambda s: s["services"].update(shell={"image": "alpine"}),
        lambda s: s.update(configs={}),
    ]
    for change in changes:
        unsafe = copy.deepcopy(spec)
        change(unsafe)
        with pytest.raises(odoo.UnsafeCompose):
            odoo.check_spec(unsafe)


def test_resource_settings_are_rendered() -> None:
    live.change({"odoo_memory_limit": "0", "db_cpu_limit": 0, "container_pids_limit": 300})
    spec = _apply()["spec"]
    assert "mem_limit" not in spec["services"]["odoo"] and "cpus" not in spec["services"]["db"]
    assert spec["services"]["db"]["pids_limit"] == 300
    with pytest.raises(ValueError):
        live.change({"odoo_memory_limit": "lots"})


def test_compose_commands_of_a_hardened_instance_ignore_its_env() -> None:
    assert "--env-file" not in store.compose(NAME, "ps")  # not hardened yet: the .env still fills in values
    _apply()
    command = store.compose(NAME, "ps")
    assert (
        command[command.index("-p") + 1] == f"odoo-{NAME}" and command[command.index("--env-file") + 1] == "/dev/null"
    )


# ---------------------------------------------------------------- files


def test_hand_edited_files_are_put_back_before_compose_starts_anything() -> None:
    kept = _apply()
    compose_file, conf = store.folder(NAME) / "docker-compose.yml", store.config_file(NAME)
    compose_file.write_text(kept["compose"].replace("127.0.0.1:28100", "0.0.0.0:28100"))
    conf.write_text(conf.read_text().replace("list_db = False", "list_db = True"))
    texts = [f.text for f in integrity.findings(NAME, _containers(kept["spec"]))]
    assert "docker-compose.yml was changed outside the panel" in texts
    assert "config/odoo.conf was changed outside the panel" in texts
    store.compose(NAME, "ps")  # reading: nothing is touched
    assert "0.0.0.0" in compose_file.read_text()
    store.compose(NAME, "up", "-d")
    assert compose_file.read_text() == kept["compose"] and "list_db = False" in conf.read_text()
    assert not integrity.findings(NAME, _containers(kept["spec"]))


def test_panel_writes_are_not_drift_but_hand_edits_of_env_are() -> None:
    kept = _apply()
    store.update_env(NAME, AUTO_PAUSE="true")
    odoo.set_addons_path(NAME, ["/mnt/extra-addons"])
    assert not integrity.findings(NAME, _containers(kept["spec"]))
    with open(store.folder(NAME) / ".env", "a") as env:
        env.write("ODOO_IMAGE_REF=evil:latest\n")
    found = integrity.findings(NAME, _containers(kept["spec"]))
    assert [(f.part, f.text, f.restorable) for f in found] == [("env", ".env was changed outside the panel", False)]
    assert integrity.inputs(NAME)["ODOO_IMAGE_REF"] == REFS["ODOO_IMAGE_REF"]  # the record decides, not .env


# ---------------------------------------------------------------- containers


def test_matching_containers_have_no_findings() -> None:
    kept = _apply()
    assert integrity.findings(NAME, _containers(kept["spec"])) == []


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda c: c["HostConfig"].update(Memory=8 * 1024**3), "odoo: memory limit"),
        (lambda c: c["HostConfig"].update(Privileged=True), "odoo: privileged"),
        (lambda c: c["HostConfig"].update(CapAdd=["CAP_SYS_ADMIN"]), "odoo: added capabilities"),
        (lambda c: c["HostConfig"].update(ReadonlyRootfs=False), "odoo: read-only system files"),
        (lambda c: c["HostConfig"].update(RestartPolicy={"Name": "always"}), "odoo: restart policy"),
        (lambda c: c.update(Image="sha256:" + "c" * 64), "odoo: image"),
        (lambda c: c["HostConfig"]["PortBindings"].update({"8072/tcp": [{"HostIp": "", "HostPort": "8072"}]}),
         "odoo: published ports"),
        (lambda c: c["Mounts"].append({"Type": "bind", "Source": "/", "Destination": "/host", "RW": True}),
         "odoo: mounts"),
        (lambda c: c["Config"]["Env"].append("LD_PRELOAD=/tmp/x.so"), "odoo: environment variables changed"),
        (lambda c: c["NetworkSettings"]["Networks"].update(host={}), "odoo: networks"),
        (lambda c: c["Config"].update(User="root"), "odoo: user"),
    ],
)  # fmt: skip
def test_container_changes_are_found(change: Any, expected: str) -> None:
    kept = _apply()
    containers = _containers(kept["spec"])
    change(containers[store.container(NAME, "odoo")])
    texts = [f.text for f in integrity.findings(NAME, containers)]
    assert texts and texts[0].startswith(expected), texts  # a swapped image also brings its own user and variables


def test_strangers_and_removed_containers_are_found() -> None:
    kept = _apply()
    containers = _containers(kept["spec"])
    containers["impostor"] = {"Config": {"Labels": {odoo.LABEL_INSTANCE: NAME}}, "State": {"Running": True}}
    containers["stopped"] = {"Config": {"Labels": {odoo.LABEL_INSTANCE: NAME}}, "State": {"Running": False}}
    del containers[store.container(NAME, "db")]
    found = integrity.findings(NAME, containers)
    assert {(f.part, f.restorable) for f in found} == {("stranger", True), ("db", True)}


def test_connectors_are_only_reported() -> None:
    connector = {"HostConfig": {"Privileged": True, "CapDrop": ["ALL"]}, "Config": {"Labels": {}}, "Mounts": []}
    assert integrity._connector_findings(connector) == ["runs privileged"]
    assert not integrity.Finding("connector", "x").restorable


def test_settings_changed_since_are_not_drift() -> None:
    kept = _apply()
    live.change({"odoo_memory_limit": "3g"})
    assert integrity.findings(NAME, _containers(kept["spec"])) == []


# ---------------------------------------------------------------- reacting


def test_drift_is_confirmed_reported_once_and_repaired(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[Any] = []
    mails: list[Any] = []
    monkeypatch.setattr(jobs, "start", lambda instance, action, kind, fn, *args, user="": started.append((fn, args)))
    monkeypatch.setattr(integrity, "_notify", lambda name, items: mails.append(items))
    found = [integrity.Finding("odoo", "odoo: memory limit: 1 instead of 2")]
    integrity.handle(NAME, found)
    assert not STATE.get(NAME).get("drift") and not started  # seen once: not yet
    integrity.handle(NAME, found)
    time.sleep(0.05)  # the e-mail goes from its own thread
    drift = STATE.get(NAME)["drift"]
    assert drift["action"] == "restore" and drift["items"] == [found[0].text]
    assert started == [(operations.repair, (NAME,))] and mails == [[found[0].text]]
    integrity.handle(NAME, found)
    assert len(started) == 1 and len(mails) == 1  # not again for the same differences
    integrity.handle(NAME, [])
    assert STATE.get(NAME).get("drift") is None


def test_warn_only_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[Any] = []
    monkeypatch.setattr(jobs, "start", lambda *args, **kwargs: started.append(args))
    monkeypatch.setattr(integrity, "_notify", lambda name, items: None)
    live.change({"drift_action": "warn"})
    found = [integrity.Finding("db", "db: privileged: True instead of False")]
    integrity.handle(NAME, found)
    integrity.handle(NAME, found)
    assert STATE.get(NAME)["drift"]["action"] == "warn" and not started


def test_drift_shows_on_the_instance(admin: Any) -> None:
    _apply()
    STATE.update(NAME, drift={"found_at": time.time(), "items": ["odoo: user"], "action": "warn"})
    client, _ = admin
    answer = client.get(f"/api/v1/instances/{NAME}").get_json()
    assert "data" in answer, answer
    shown = answer["data"]["drift"]
    assert shown["items"] == ["odoo: user"] and shown["action"] == "warn"


def test_drift_mail_renders() -> None:
    from sudoo.mail.render import render

    text, html = render("drift", "subject", instance=NAME, items=["odoo: user"], action="restore")
    assert "odoo: user" in text and NAME in html and "puts its own configuration back" in text


def test_record_survives_json() -> None:
    kept = _apply()
    assert json.loads(json.dumps(kept)) == kept
