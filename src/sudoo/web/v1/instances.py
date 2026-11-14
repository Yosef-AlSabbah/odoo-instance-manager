"""Instances, jobs and Odoo versions.

    GET    /api/v1/instances?limit=&offset=          list
    GET    /api/v1/instances/<name>                  one instance, with commits, submodules and recent jobs
    GET    /api/v1/instances/<name>/credentials      Odoo admin and master passwords, ports
    GET    /api/v1/instances/<name>/logs?lines=      the end of Odoo's log
    POST   /api/v1/instances                         create; {"from_backup"} optional -> 202, Location: job
    PATCH  /api/v1/instances/<name>                  change automation settings and lifetime
    POST   /api/v1/instances/<name>/actions/<action> restart, update, pause, ...    -> 202, Location: job
                                                     restore: {"file"} optional (any instance's backup of the
                                                     same Odoo series), the latest backup otherwise
                                                     rollback: back to before the last restore (ROLLBACK_HOURS)
    DELETE /api/v1/instances/<name>                  delete after a backup; body {"confirm": "<name>"} -> 202
    GET    /api/v1/instance-plan?repo=&branch=&name= the name and database a new instance would get
    GET    /api/v1/instance-quota                    how many instances the caller may still create, and when
    GET    /api/v1/jobs?instance=&limit=&offset=     recent jobs, newest first
    GET    /api/v1/jobs/<id>?include=log             a job
    GET    /api/v1/jobs/<id>/log?offset=             its technical log from a line on
    GET    /api/v1/versions                          Odoo versions and Enterprise availability

Every endpoint names the permission it needs (roles.py); each action has its own (ACTIONS). Putting another
instance's backup into an instance, or starting a new instance from a backup, also needs backups.manage, the
permission that shows every backup (_usable_backup).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any, cast

from flask import Blueprint, Response, abort, g, request

from sudoo import addons, exposure
from sudoo.config import settings
from sudoo.core import events, jobs, vault
from sudoo.instances import backups, odoo, operations, store
from sudoo.limits import quotas
from sudoo.repos import github

from .. import validation as check
from ..security import can, log, message_for_user, refuse_unless, require
from .resources import instance_resource, job_resource
from .responses import PREFIX, ok, page

blueprint = Blueprint("instances", __name__)

# action -> (title shown in the activity list, job kind, permission needed)
ACTIONS = {
    "update": ("Get latest code", "update", "instances.update"),
    "update-submodules": ("Update submodules", "update", "instances.update"),
    "restart": ("Restart", "restart", "instances.update"),
    "start": ("Start", "wake", "instances.update"),
    "add-submodule": ("Add submodule", "submodule", "instances.update"),
    "pause": ("Pause", "pause", "instances.operate"),
    "switch-off": ("Switch off", "stop", "instances.operate"),
    "upgrade": ("Upgrade modules", "upgrade", "instances.operate"),
    "remove-submodule": ("Remove submodule", "submodule", "instances.operate"),
    "switch-branch": ("Switch branch", "update", "instances.operate"),
    "backup": ("Back up", "backup", "instances.operate"),
    "update-images": ("Update Odoo and PostgreSQL images", "update", "instances.operate"),
    "repair": ("Restore the panel's configuration", "repair", "instances.operate"),
    "restore": ("Restore a backup", "restore", "instances.restore"),
    "rollback": ("Roll back the restore", "restore", "instances.restore"),
    "delete": ("Delete instance", "delete", "instances.delete"),
}


def existing(name: str) -> str:
    """`name` when that instance exists; 404 otherwise."""
    if not store.exists(check.instance_name(name)):
        abort(404, "This instance does not exist.")
    return name


def _accepted(job: jobs.Job) -> Response:
    """202 Accepted for work that continues in the background; Location points to the job."""
    response = ok(job_resource(job), status=202)
    response.headers["Location"] = f"{PREFIX}/jobs/{job.id}"
    return response


def _limits(default: int = 100) -> tuple[int, int]:
    limit = check.whole_number(request.args.get("limit", str(default)), "limit", minimum=1, maximum=500)
    return limit, check.whole_number(request.args.get("offset", "0"), "offset")


# ---------------------------------------------------------------- reading


@blueprint.get("/instances")
@require("instances.view")
def list_instances() -> Response:
    limit, offset = _limits()
    return page(store.names(), limit, offset, instance_resource)


@blueprint.get("/instances/<name>")
@require("instances.view")
def instance(name: str) -> Response:
    return ok(instance_resource(existing(name), full=True))


@blueprint.get("/instances/<name>/credentials")
@require("instances.credentials")
def credentials(name: str) -> Response:
    env = store.read_env(existing(name))
    log("instance credentials viewed", instance=name)
    return ok(
        {
            "login": env.get("ODOO_ADMIN_LOGIN") or "admin",  # another login when started from a backup
            "admin_password": env["ODOO_ADMIN_PASSWORD"],
            "master_password": vault.decrypt(env["MASTER_PASSWORD"], store.master_password_label(name)),
            "ports": {key.lower(): int(env[key]) for key in env if key.endswith("_PORT") and env[key].isdigit()},
        }
    )


@blueprint.get("/instances/<name>/logs")
@require("instances.logs")
def odoo_log(name: str) -> Response:
    lines = check.whole_number(request.args.get("lines", "300"), "lines", minimum=1, maximum=5000)
    return ok({"text": odoo.recent_log(existing(name), lines) or ""})


# ---------------------------------------------------------------- creating


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _plan_name(repo: str, branch: str, custom_name: str) -> tuple[str, str]:
    """Instance name (from the custom name, or repository + branch), made unique, and its database name."""
    if custom_name:
        base = _slug(custom_name)
    else:
        repository = (github.repo_name(repo) or "").split("/")[-1]
        base = "-".join(part for part in (_slug(repository), _slug(branch)) if part)
    base = base[:28].strip("-") or "odoo"
    name, counter = base, 2
    while store.folder(name).exists():
        name, counter = f"{base[:26].strip('-')}-{counter}", counter + 1
    return name, name.replace("-", "_")


def _usable_backup(file_name: str, version: str, edition: str, instance: str | None = None) -> str:
    """`file_name` when that backup exists, the caller may use it and it fits Odoo `version` and `edition`.

    A backup of `instance` itself needs nothing more than the action's permission; any other backup (another
    instance's, or one to start a new instance from) also needs backups.manage, which shows every backup."""
    # the permission first: without backups.manage, other instances' backups must not even be found (404 or not)
    match = backups.FILE_RE.match(file_name)
    if instance is None or match is None or match["instance"] != instance:
        refuse_unless("backups.manage", f"use backup {file_name[:80]}" + (f" for {instance}" if instance else ""))
    path = check.backup_file(file_name)  # 404 for an unknown file or anything that is not a backup name
    problem = backups.problem(path.name, version, edition)
    if problem:
        abort(400, problem)
    return path.name


@blueprint.get("/instance-plan")
@require("instances.create")
def plan() -> Response:
    """What a new instance would be called, before it is created."""
    name, database = _plan_name(
        check.text(request.args, "repo"),
        check.text(request.args, "branch"),
        check.custom_name(check.text(request.args, "name", max_length=40)),
    )
    defaults = {
        key: getattr(settings, key) for key in ("delete_after_days", "auto_update", "auto_upgrade", "auto_pause")
    }
    return ok({"name": name, "database": database, "login": "admin", "defaults": defaults})


@blueprint.get("/instance-quota")
@require("instances.view")
def quota() -> Response:
    return ok(quotas.usage(g.user["name"]))


@blueprint.post("/instances")
@require("instances.create")
def create() -> Response:
    data = check.body()
    repo = check.repo_address(check.text(data, "repo"), required=False)
    branch = check.branch(check.text(data, "branch", default="main"))
    version = check.one_of(check.text(data, "version"), odoo.versions(), "Choose an Odoo version from the list.")
    edition = check.one_of(check.text(data, "edition"), ("community", "enterprise"), "Choose Community or Enterprise.")
    custom_name = check.custom_name(check.text(data, "name", max_length=40))
    if not repo and not custom_name:
        abort(400, "Enter a GitHub repository or a name for the instance.")
    if edition == "enterprise" and not addons.available(version):
        abort(400, f"Odoo {version} Enterprise is not available on this server.")
    from_backup = check.text(data, "from_backup", max_length=200) or None
    if from_backup:
        refuse_unless("instances.restore", "create an instance from a backup")
        from_backup = _usable_backup(from_backup, version, edition)
    try:
        quotas.claim(g.user["name"])
    except quotas.QuotaError as error:
        g.retry_after = error.retry_after
        log("instance creation refused (limit)", ok=False, detail=error.message)
        abort(error.status, error.message)
    name, db_name = _plan_name(repo, branch, custom_name)
    plan_data = {
        "name": name,
        "db_name": db_name,
        "repo": repo,
        "branch": branch,
        "version": version,
        "edition": edition,
        "demo": check.flag(data, "demo"),
        "install_modules": check.flag(data, "install_modules"),
        "delete_after_days": check.days(data, "delete_after_days"),
        # automation switches: the panel's defaults (AUTO_PAUSE, AUTO_UPDATE, AUTO_UPGRADE) unless sent
        **{key: check.flag(data, key, getattr(settings, key)) for key in ("auto_update", "auto_upgrade", "auto_pause")},
        "ports": store.reserve_ports(exposure.provider().instance_ports()),
        "created_by": g.user["name"],
        "from_backup": from_backup,
    }
    job = jobs.start(name, "Create instance", "create", operations.create, plan_data, user=g.user["name"])
    log(
        "Create instance",
        instance=name,
        detail=f"Odoo {version} {edition}" + (f" from {from_backup}" if from_backup else ""),
    )
    response = _accepted(job)
    response.headers["Content-Location"] = f"{PREFIX}/instances/{name}"
    return response


# ---------------------------------------------------------------- changing


@blueprint.patch("/instances/<name>")
@require("instances.operate")
def change(name: str) -> Response:
    """Change only the settings that are sent; the others keep their value."""
    existing(name)
    data = check.body()
    switches = {"auto_update": "AUTO_UPDATE", "auto_upgrade": "AUTO_UPGRADE", "auto_pause": "AUTO_PAUSE"}
    values: dict[str, object] = {
        key: str(check.flag(data, field)).lower() for field, key in switches.items() if field in data
    }
    if "delete_after_days" in data:
        values["DELETE_AFTER_DAYS"] = check.days(data, "delete_after_days")
    if not values:
        abort(400, "Send at least one of: auto_update, auto_upgrade, auto_pause, delete_after_days.")
    store.update_env(name, **values)
    log("instance settings changed", instance=name, detail=", ".join(sorted(values)))
    events.publish("instance", name)
    return ok(instance_resource(name, full=True))


def _job_for(action: str, name: str, data: Mapping[str, Any]) -> tuple[Callable[..., Any], tuple[Any, ...]]:
    """(function, arguments) of the job for `action`, after validating the request data."""
    simple: dict[str, tuple[Callable[..., Any], tuple[Any, ...]]] = {
        "update": (operations.update_code, (name,)),
        "update-submodules": (operations.update_code, (name, True)),
        "restart": (operations.restart, (name,)),
        "start": (operations.wake, (name,)),
        "pause": (operations.pause, (name,)),
        "backup": (operations.backup, (name,)),
        "switch-off": (operations.switch_off, (name,)),
        "update-images": (operations.update_images, (name,)),
        "repair": (operations.repair, (name,)),
    }
    if action in simple:
        return simple[action]
    if action == "delete":
        if check.text(data, "confirm", max_length=40) != name:
            abort(400, "Type the instance name exactly to confirm.")
        return operations.delete, (name,)
    if action == "restore":
        file_name = check.text(data, "file", max_length=200) or None
        if file_name:
            env = store.read_env(name)
            file_name = _usable_backup(file_name, env["ODOO_VERSION"], env.get("EDITION", "community"), name)
        elif backups.latest(name) is None:
            abort(409, "This instance has no backup to restore.")
        return operations.restore, (name, file_name)
    if action == "rollback":
        if not backups.rollback_snapshot(name):
            abort(
                409,
                "There is nothing to roll back to: no restore in the last "
                f"{settings.rollback_hours:g} hours, or the instance was rolled back already.",
            )
        return operations.rollback, (name,)
    if action == "upgrade":
        return operations.upgrade_modules, (name, check.module_list(check.text(data, "modules", max_length=4000)))
    if action == "switch-branch":
        return operations.switch_branch, (name, check.branch(check.text(data, "branch")))
    path = check.text(data, "path")
    if action == "add-submodule":
        url = check.repo_address(check.text(data, "url"))
        branch = check.branch(check.text(data, "branch"), required=False)
        path = check.submodule_path(path or cast(str, github.repo_name(url)).split("/")[-1])
        return operations.add_submodule, (name, url, path, branch)
    return operations.remove_submodule, (name, check.submodule_path(path))


def run(name: str, action: str) -> Response:
    existing(name)
    if action not in ACTIONS:
        abort(404, "Unknown action.")
    title, kind, permission = ACTIONS[action]
    refuse_unless(permission, f"{action} on {name}")
    fn, args = _job_for(action, name, check.body())
    job = jobs.start(name, title, kind, fn, *args, user=g.user["name"])
    log(title, instance=name)
    return _accepted(job)


@blueprint.post("/instances/<name>/actions/<action>")
def action(name: str, action: str) -> Response:
    return run(name, action)


@blueprint.delete("/instances/<name>")
def delete(name: str) -> Response:
    return run(name, "delete")


# ---------------------------------------------------------------- jobs


@blueprint.get("/jobs")
@require("instances.view")
def list_jobs() -> Response:
    limit, offset = _limits(default=30)
    instance_name = request.args.get("instance")
    if instance_name:
        check.instance_name(instance_name)
    found = [j for j in reversed(jobs.JOBS.values()) if not instance_name or j.instance == instance_name]
    return page(found, limit, offset, job_resource)


def _job(job_id: str) -> jobs.Job:
    return jobs.JOBS.get(job_id) or abort(404, "This job does not exist or is too old to be kept.")


@blueprint.get("/jobs/<job_id>")
@require("instances.view")
def job(job_id: str) -> Response:
    include_log = request.args.get("include") == "log" and can("instances.logs")
    found = job_resource(_job(job_id), include_log=include_log)
    if found["error"]:
        found["error"] = message_for_user(found["error"])
    return ok(found)


@blueprint.get("/jobs/<job_id>/log")
@require("instances.logs")
def job_log(job_id: str) -> Response:
    """The job's log from line `offset` on; `meta.next_offset` is where to continue."""
    found = _job(job_id)
    offset = check.whole_number(request.args.get("offset", "0"), "offset")
    lines = found.log[:]
    return ok({"text": "".join(lines[offset:])}, meta={"offset": offset, "next_offset": len(lines)})


# ---------------------------------------------------------------- versions


@blueprint.get("/versions")
@require("instances.view")
def versions() -> Response:
    return ok([{"version": v, "enterprise": addons.available(v)} for v in odoo.versions()])
