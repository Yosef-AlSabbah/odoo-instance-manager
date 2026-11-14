"""What the panel can do with an instance. Every function here runs as a job (see jobs.py): fn(job, ...).

Each function is one straight sequence of steps; a failing step raises JobError and the job stops there.
"""

from __future__ import annotations

import secrets
import shutil
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from sudoo import addons as addons_sources
from sudoo import exposure
from sudoo.config import settings
from sudoo.core import vault
from sudoo.core.jobs import Job, JobError
from sudoo.core.shell import capture
from sudoo.core.state import STATE
from sudoo.instances import backups, gateway, integrity, monitor, odoo, store
from sudoo.instances.store import compose
from sudoo.repos.gitrepo import branch_on_github, changed_modules, git, module_folders, own_modules, snapshot

# --------------------------------------------------------------------------- helpers


def refresh_addons_path(job: Job, name: str) -> None:
    """Point Odoo's addons_path at every folder of the repository that contains modules, then Enterprise.

    The instance's own modules come first, so one of them can replace an Enterprise module of the same name.
    """
    addons = store.addons_dir(name)
    paths = [
        odoo.CUSTOM_ADDONS_MOUNT if folder == addons else f"{odoo.CUSTOM_ADDONS_MOUNT}/{folder.relative_to(addons)}"
        for folder in module_folders(addons)
    ]
    if store.read_env(name)["EDITION"] == "enterprise":
        paths.append(odoo.ENTERPRISE_ADDONS_MOUNT)
    job.write(f"addons_path = {odoo.set_addons_path(name, paths)}\n")


def _remove_leftovers(job: Job, name: str) -> None:
    """Remove containers and volumes of an earlier instance with the same name, so nothing old is reused."""
    label = f"label=com.docker.compose.project=odoo-{name}"
    containers = capture(["docker", "ps", "-aq", "--filter", label]).split()
    volumes = capture(["docker", "volume", "ls", "-q", "--filter", label]).split()
    if containers:
        job.run(["docker", "rm", "-f", *containers])
    if volumes:
        job.run(["docker", "volume", "rm", "-f", *volumes])


def _paused(name: str) -> bool:
    return not monitor.STATUS.get(name, {}).get("running") and bool(
        STATE.get(name).get("paused") or STATE.get(name).get("switched_off")
    )


def _wait_until_ready(job: Job, name: str) -> None:
    if odoo.wait_until_ready(store.read_env(name)["ODOO_PORT"]):
        monitor.mark_running(name)
    else:
        job.note(
            "Odoo is taking longer than usual to answer. It may still be starting; check the logs if it does "
            "not come up in a few minutes.",
            "warning",
        )


def _start_odoo(job: Job, name: str, restart: bool = False) -> None:
    """Start the instance (database and Odoo), restart Odoo if asked, and wait until Odoo answers.

    Its connector is started too, in case it was stopped, so the instance keeps its public link.
    """
    refresh_addons_path(job, name)
    integrity.apply(job, name)  # current settings and hardening; Compose recreates what changed
    exposure.ensure(name)
    job.run(compose(name, "up", "-d", "--remove-orphans"), timeout=900)
    if restart:
        job.run(compose(name, "restart", "odoo"), timeout=300)
    STATE.update(name, paused=False, switched_off=False)
    STATE.record_visit(name)
    job.step("Waiting for Odoo to be ready")
    _wait_until_ready(job, name)


# --------------------------------------------------------------------------- create and delete


def create(job: Job, plan: dict[str, Any]) -> None:
    """Create an instance from `plan` (see web/api_instances.py). On failure everything created is removed."""
    name, folder = plan["name"], store.folder(plan["name"])
    try:
        folder.mkdir(parents=True)  # claims the name; the cleanup below never touches another instance
    except FileExistsError as error:
        store.release_ports(plan["ports"])
        raise JobError("An instance with this name already exists. Choose another name.") from error
    try:
        _create(job, plan)
    except Exception:
        job.write("\nRemoving the half-created instance so the same name can be used again.\n")
        if (folder / "docker-compose.yml").exists():
            job.run_unchecked(compose(name, "down", "-v", "--remove-orphans"), timeout=300)
        gateway.remove(name)
        exposure.remove(name)
        shutil.rmtree(folder, ignore_errors=True)
        STATE.remove(name)
        integrity.forget(name)
        raise
    finally:
        store.release_ports(plan["ports"])


def _create(job: Job, plan: dict[str, Any]) -> None:
    name, db, version = plan["name"], plan["db_name"], plan["version"]
    enterprise = plan["edition"] == "enterprise"
    addons = store.addons_dir(name)
    source = _backup_to_start_from(plan)
    foreign = source is not None and source["instance"] != name

    job.expect(
        7  # preparing, Odoo image, database container, Odoo database, public link, starting Odoo, waiting
        + bool(plan["repo"])
        + enterprise
        + bool(plan["install_modules"] and plan["repo"])
        + (settings.odoo_admin_password != "admin" or bool(source))
        + foreign
    )
    job.step("Preparing the instance")
    (store.folder(name) / "config").mkdir()
    _remove_leftovers(job, name)
    if plan["repo"]:
        job.step("Downloading the code from GitHub")
        job.run(
            ["git", "clone", "--recurse-submodules", "-b", plan["branch"], "--", plan["repo"], str(addons)],
            timeout=1800,
        )
    else:
        job.run(["git", "init", "-q", "-b", plan["branch"], str(addons)])

    enterprise_folder: Path | None = None
    if enterprise:
        job.step(f"Preparing the Odoo {version} Enterprise add-ons")
        enterprise_folder = addons_sources.prepare(version, job.write)

    db_password, master_password = secrets.token_urlsafe(18), secrets.token_urlsafe(16)
    store.write_env(
        name,
        {
            "ODOO_VERSION": version,
            "EDITION": plan["edition"],
            **{key: str(port) for key, port in plan["ports"].items()},
            "DB_NAME": db,
            "DB_PASSWORD": db_password,
            "GIT_BRANCH": plan["branch"],
            "ODOO_ADMIN_PASSWORD": settings.odoo_admin_password,
            "MASTER_PASSWORD": vault.encrypt(master_password, store.master_password_label(name)),
            "AUTO_UPDATE": str(plan["auto_update"]).lower(),
            "AUTO_UPGRADE": str(plan["auto_upgrade"]).lower(),
            "AUTO_PAUSE": str(plan["auto_pause"]).lower(),
            "DELETE_AFTER_DAYS": plan["delete_after_days"],  # 0: keep until deleted by hand
            "CREATED_AT": int(time.time()),
            "CREATED_BY": plan.get("created_by", ""),
            "ENTERPRISE_FOLDER": str(enterprise_folder or ""),
        },
    )
    odoo.write_config(name, db, db_password, master_password)
    refresh_addons_path(job, name)
    STATE.update(name, last_visit=time.time(), paused=False, switched_off=False)

    job.step(f"Downloading Odoo {version} (the first time can take a few minutes)")
    integrity.apply(job, name, pull=True)  # images pinned by digest, hardened compose file, protected files

    job.step("Starting the database")
    job.run(compose(name, "up", "-d", "db"), timeout=300)

    if source:
        taken = datetime.fromtimestamp(source["created"], settings.zone).strftime("%Y-%m-%d %H:%M")
        job.step(f"Loading the backup of {source['instance']} of {taken} into database {db}")
        backups.restore(job, name, source, db)
        if foreign:
            job.step("Neutralising the copied data")
            job.note(backups.neutralize(job, name, db))
    else:
        job.step(f"Creating the Odoo {'Enterprise' if enterprise else 'Community'} database (about 1-2 minutes)")
        # web_enterprise turns the database into Enterprise: Enterprise interface and apps
        init = ["-d", db, "-i", "base,web_enterprise" if enterprise else "base", "--stop-after-init", "--no-http"]
        if plan["demo"]:
            init.append("--with-demo")
        job.run(odoo.run_cmd(name, *init), timeout=1800)

    modules = own_modules(addons) if plan["install_modules"] else []
    if modules and source:  # the backup's database may have them already: those are kept as they are
        installed = backups.installed_modules(name, db)
        already = [module for module in modules if module in installed]
        modules = [module for module in modules if module not in installed]
        if already:
            job.note(f"Already installed in the backup, so not installed again: {', '.join(already)}")
        if not modules:
            job.step("The repository's modules are all installed already")
    if modules:
        job.step(f"Installing the repository's modules ({len(modules)})")
        if job.run_unchecked(
            odoo.run_cmd(name, "-d", db, "-i", ",".join(modules), "--stop-after-init", "--no-http"), timeout=3600
        ):
            job.note(
                "Some of the repository's modules could not be installed. Odoo works; install them from Apps "
                "after a developer has looked at the technical log.",
                "warning",
            )

    # a new database already has the login admin / admin; a backup's administrator (user 2) gets the panel's
    # password too, so the instance's credentials in the panel work for it
    login = "admin"
    if settings.odoo_admin_password != "admin" or source:
        job.step("Setting the admin password")
        if source:
            login = _adopt_admin(job, name, db)
        else:
            _set_admin_password(job, name, db)

    job.step("Creating the public link")
    gateway.add(name)
    exposure.ensure(name)
    url = exposure.wait_for_address(name)
    if not url:
        raise JobError("Cloudflare did not provide a public address for this instance.")
    for cmd in odoo.public_address_cmds(name, url):
        job.run(cmd, timeout=60)

    job.step("Starting Odoo")
    job.run(compose(name, "up", "-d"), timeout=600)
    _wait_until_ready(job, name)
    job.result = {"name": name, "url": url, "login": login, "password": settings.odoo_admin_password, "db": db}
    if source:
        job.note(f"Started from the backup {source['file']}")


def _backup_to_start_from(plan: dict[str, Any]) -> dict[str, Any] | None:
    """The backup a new instance starts from (plan["from_backup"]), checked again; None for an empty database."""
    if not plan.get("from_backup"):
        return None
    source = next((b for b in backups.all_backups() if b["file"] == plan["from_backup"]), None)
    if source is None:
        raise JobError("The backup to start from no longer exists.")
    problem = backups.problem(source["file"], plan["version"], plan["edition"])
    if problem:
        raise JobError(problem)
    return source


def _set_admin_password(job: Job, name: str, db: str) -> None:
    """Give the administrator (user 2) of database `db` the instance's admin password (ODOO_ADMIN_PASSWORD)."""
    password = store.read_env(name).get("ODOO_ADMIN_PASSWORD") or settings.odoo_admin_password
    script = f"env['res.users'].browse(2).write({{'password': {password!r}}})\nenv.cr.commit()\n"
    job.run(odoo.run_cmd(name, "shell", "-d", db), timeout=600, input=script)


def _adopt_admin(job: Job, name: str, db: str) -> str:
    """After another instance's data was loaded into database `db`: its administrator (user 2) gets this instance's
    admin password, and its login is recorded (ODOO_ADMIN_LOGIN), so the credentials the panel shows work. Returns
    the login."""
    _set_admin_password(job, name, db)
    return _record_admin_login(name, db)


def _record_admin_login(name: str, db: str) -> str:
    """Read the login of the administrator (user 2) of database `db` and keep it as ODOO_ADMIN_LOGIN (shown with the
    instance's credentials). When it cannot be read, the login kept so far is left as it is and returned."""
    sql = "SELECT login FROM res_users WHERE id = 2"
    container = store.container(name, "db")
    kept = store.read_env(name).get("ODOO_ADMIN_LOGIN") or "admin"
    login = capture(["docker", "exec", container, "psql", "-U", "odoo", "-d", db, "-tAc", sql]).strip()
    if login and login != kept:
        store.update_env(name, ODOO_ADMIN_LOGIN=login)
    return login or kept


def delete(job: Job, name: str) -> None:
    """Back up every database, then remove the instance completely. No backup, no deletion."""
    job.expect(3)
    job.step("Backing up the database and files")
    saved = backups.create(job, name, "deletion")
    job.note(f"Backup kept: {', '.join(path.name for path in saved)}")
    job.step("Removing Odoo, its database and its files")
    job.run(compose(name, "down", "-v", "--remove-orphans"), timeout=600)
    gateway.remove(name)
    exposure.remove(name)
    job.step("Removing the instance folder")
    shutil.rmtree(store.folder(name))
    STATE.remove(name)
    integrity.forget(name)
    backups.remove_daily(name)  # the backup above is newer


def backup(job: Job, name: str, kind: str = "manual") -> None:
    job.step("Backing up the database and files")
    paused = _paused(name)
    if kind == "daily":
        STATE.update(name, used_since=None)  # visits from now on count for the next one
    saved = backups.create(job, name, kind)
    if paused:
        job.run(compose(name, "stop"), timeout=300)  # leave a paused instance paused
    job.note(f"Backup saved: {', '.join(path.name for path in saved)}")


def daily_backup(job: Job, name: str) -> None:
    """The daily backup of an instance used since its last one; replaces the previous daily backup."""
    backup(job, name, "daily")


def chosen_backup(name: str, file_name: str | None) -> dict[str, Any]:
    """The backup a restore of instance `name` puts back: `file_name` (a backup of any instance), or the latest
    restorable backup of the instance. Raises JobError when it cannot go into this instance."""
    if file_name:
        chosen = next((b for b in backups.all_backups() if b["file"] == file_name), None)
    else:
        chosen = backups.latest(name)
    if chosen is None:
        raise JobError("There is no such backup to restore." if file_name else "There is no backup of this instance.")
    env = store.read_env(name)
    problem = backups.problem(chosen["file"], env["ODOO_VERSION"], env.get("EDITION", "community"))
    if problem:
        raise JobError(problem)
    if chosen["instance"] == name and chosen["db"] not in odoo.databases(name):
        raise JobError(f"The backup is of database {chosen['db']}, which this instance does not have.")
    return chosen


def target_database(name: str, backup: dict[str, Any]) -> str:
    """The database of instance `name` a backup goes into: its own database for a backup of this instance, the
    instance's (first) database for a backup of another one."""
    return backup["db"] if backup["instance"] == name else odoo.databases(name)[0]


def restore(job: Job, name: str, file_name: str | None = None) -> None:
    """Put a backup back (the latest of this instance, or `file_name`, which may be another instance's): the
    current state is backed up first (before-restore, offered as Rollback for ROLLBACK_HOURS), then the database
    and the filestore are replaced and Odoo starts. Another instance's data is loaded under this instance's
    database name and neutralised.

    Restoring the instance's own before-restore backup is a rollback (see rollback): taking a new before-restore
    first would replace the very file being restored."""
    chosen = chosen_backup(name, file_name)
    if chosen["instance"] == name and chosen["kind"] == "before-restore":
        _rollback(job, name, [chosen])
        return
    taken = datetime.fromtimestamp(chosen["created"], settings.zone).strftime("%Y-%m-%d %H:%M")
    foreign = chosen["instance"] != name
    db = target_database(name, chosen)
    job.expect(5 + 2 * foreign)  # the last step, waiting for Odoo, is _start_odoo's
    job.step("Saving the current state first")
    saved = backups.create(job, name, "before-restore")
    hours = f"{settings.rollback_hours:g}"
    job.note(f"The state before the restore is kept for {hours} hours as {', '.join(p.name for p in saved)}")
    job.step("Stopping Odoo")
    job.run(compose(name, "stop", "odoo"), timeout=300)
    job.step(f"Restoring the backup of {taken}" + (f" from {chosen['instance']}" if foreign else ""))
    backups.restore(job, name, chosen, db)
    if foreign:
        job.step("Neutralising the copied data")
        job.note(backups.neutralize(job, name, db))
        job.step("Setting the admin password")
        login = _adopt_admin(job, name, db)
        job.note(f"The administrator ({login}) now has this instance's admin password, shown on its Access tab.")
    _finish_restore(job, name)
    job.note(f"Restored {chosen['file']}" + (f" into database {db}" if db != chosen["db"] else ""))


def rollback(job: Job, name: str) -> None:
    """Put back the state the instance had before its last restore (the before-restore backup, while it is kept).

    The current state is saved as before-rollback first, never as before-restore: that would replace the snapshot
    being restored. The snapshot itself stays until it expires: the action is offered once per restore, but the
    snapshot can still be put back by restoring its file."""
    snapshot = backups.rollback_snapshot(name)
    if not snapshot:
        raise JobError(
            "There is nothing to roll back to: no restore in the last "
            f"{settings.rollback_hours:g} hours, or the instance was rolled back already."
        )
    _rollback(job, name, snapshot)


def _rollback(job: Job, name: str, snapshot: list[dict[str, Any]]) -> None:
    taken = datetime.fromtimestamp(snapshot[0]["created"], settings.zone).strftime("%Y-%m-%d %H:%M")
    databases = odoo.databases(name)
    snapshot = [b for b in snapshot if b["db"] in databases]
    if not snapshot:
        raise JobError("The state before the restore is of a database this instance no longer has.")
    job.expect(5)
    job.step("Saving the current state first")
    try:
        saved = backups.create(job, name, "before-rollback")
        job.note(f"The state before the rollback is kept as {', '.join(p.name for p in saved)}")
    except JobError as error:
        # a rollback is also the way back from a restore that failed halfway, when the database may be gone and
        # cannot be backed up: that must not block it
        job.note(f"The current state could not be saved first ({error}); rolling back anyway.", "warning")
    job.step("Stopping Odoo")
    job.run(compose(name, "stop", "odoo"), timeout=300)
    job.step(f"Rolling back to {taken}, before the restore")
    for chosen in snapshot:
        backups.restore(job, name, chosen)
    _finish_restore(job, name)
    STATE.update(name, rolled_back=snapshot[0]["file"])
    job.note(f"Rolled back to {', '.join(b['file'] for b in snapshot)}")


def _finish_restore(job: Job, name: str) -> None:
    """After a restore: the database gets this instance's public address again, the administrator's login is read
    again (a rollback may bring back another one), and Odoo starts."""
    _record_admin_login(name, odoo.databases(name)[0])
    url = exposure.address(name)
    if url:
        for cmd in odoo.public_address_cmds(name, url):
            job.run(cmd, timeout=60)
    job.step("Starting Odoo")
    _start_odoo(job, name)


def expires_at(env: dict[str, str]) -> int | None:
    """When the instance is deleted automatically (a timestamp), or None when it is kept."""
    days = int(env["DELETE_AFTER_DAYS"])
    return int(env["CREATED_AT"]) + days * 86400 if days > 0 else None


# --------------------------------------------------------------------------- running state


def restart(job: Job, name: str) -> None:
    job.expect(2)
    job.step("Restarting Odoo")
    _start_odoo(job, name, restart=True)


def wake(job: Job, name: str) -> None:
    job.expect(2)
    job.step("Starting Odoo")
    _start_odoo(job, name)


def pause(job: Job, name: str) -> None:
    job.step("Pausing to free server resources")
    job.run(compose(name, "stop"), timeout=300)
    STATE.update(name, paused=True, switched_off=False)
    monitor.mark_stopped(name)


def switch_off(job: Job, name: str) -> None:
    job.step("Switching off")
    job.run(compose(name, "stop"), timeout=300)
    STATE.update(name, switched_off=True, paused=False)
    monitor.mark_stopped(name)


# --------------------------------------------------------------------------- configuration and images


def repair(job: Job, name: str) -> None:
    """Put the panel's own configuration back after the instance was changed outside the panel (integrity.py):
    back up the database first when its container is affected, write the panel's files back, stop containers that
    pretend to belong to the instance, and recreate the affected containers. A paused instance stays paused."""
    found = integrity.findings(name)
    restorable = [finding for finding in found if finding.restorable]
    job.expect(3 + any(finding.part == "db" for finding in restorable))
    job.step("Comparing the instance with the panel's configuration")
    for finding in found:
        job.write(f"- {finding.text}\n")
    if any(finding.part == "env" for finding in found):
        integrity.accept_env(name)
        job.note(
            "The .env file was changed by hand. The values that shape the containers (images, ports, passwords) "
            "still come from the panel's own record; the rest of the file is used as it is now.",
            "warning",
        )
    if not restorable:
        job.note("Nothing else to restore: the containers and files match the panel's configuration.")
        return
    services = {finding.part for finding in restorable} & {"odoo", "db"}
    if any(finding.part == "files" for finding in restorable):
        services = {"odoo", "db"}  # the files shape both containers
    if any(finding.part == "db" for finding in restorable):
        job.step("Backing up the database first")
        saved = backups.create(job, name, "before-repair")
        job.note(f"Backup taken before the repair: {', '.join(path.name for path in saved)}")
    job.step("Putting the panel's configuration back")
    put_back = integrity.rewrite_if_changed(name)
    integrity.protect(name, integrity.inputs(name).get("ODOO_USER", ""))
    stopped = integrity.stop_strangers(job, name)
    if stopped:
        job.note(
            f"Stopped containers that pretended to belong to this instance (kept for review): {', '.join(stopped)}"
        )
    paused = _paused(name)
    if services:
        job.step("Recreating " + " and ".join(sorted(services)) + " from the panel's configuration")
        if paused:
            job.run(compose(name, "create", "--force-recreate", *sorted(services)), timeout=600)
        else:
            job.run(compose(name, "up", "-d", "--force-recreate", "--remove-orphans", *sorted(services)), timeout=900)
            _wait_until_ready(job, name)
    left = [finding.text for finding in integrity.findings(name) if finding.restorable]
    if left:
        job.note(f"Still different after the repair: {'; '.join(left)}", "warning")
    from sudoo.core import audit

    audit.record("system", None, "configuration restored", name, ok=not left,
                 detail="; ".join([*put_back, *stopped, *sorted(services)]))  # fmt: skip


def update_images(job: Job, name: str) -> None:
    """Download the instance's Odoo and PostgreSQL images again (same names and tags), pin the new digests and
    recreate the containers with them. A paused instance gets them when it next starts."""
    job.expect(3)
    job.step("Downloading the images")
    paused = _paused(name)
    integrity.apply(job, name, pull=True)
    if paused:
        job.note("The instance stays paused and uses the new images when someone opens it.")
        return
    job.step("Starting Odoo with the new images")
    _start_odoo(job, name)


# --------------------------------------------------------------------------- code updates


def _pull(job: Job, addons: Path) -> None:
    job.run(git(addons, "pull", "--ff-only"), timeout=900)
    job.run(git(addons, "submodule", "sync", "--recursive"))
    job.run(git(addons, "submodule", "update", "--init", "--recursive"), timeout=1800)


def upgrade_modules(job: Job, name: str, modules: list[str], stay_paused: bool = False) -> None:
    """Run `odoo -u <modules>` on every database of the instance, with Odoo stopped meanwhile."""
    job.step(f"Upgrading modules: {', '.join(modules)}")
    refresh_addons_path(job, name)
    job.run(compose(name, "up", "-d", "db"), timeout=300)
    job.run(compose(name, "stop", "odoo"), timeout=300)
    for db in odoo.databases(name):
        job.run(odoo.run_cmd(name, "-d", db, "-u", ",".join(modules), "--stop-after-init", "--no-http"), timeout=3600)
    if stay_paused:
        job.run(compose(name, "stop"), timeout=300)
        job.note("The instance stays paused and uses the new code when someone opens it.")
    else:
        job.step("Starting Odoo")
        _start_odoo(job, name)


def update_code(job: Job, name: str, submodules_only: bool = False) -> None:
    """Get new code from GitHub (or move submodules to their latest commit), upgrade what changed, restart."""
    addons = store.addons_dir(name)
    if not capture(git(addons, "remote", "get-url", "origin")):
        raise JobError("This instance has no GitHub repository.")
    paused = _paused(name)
    before = snapshot(addons)
    if submodules_only:
        job.step("Moving the submodules to their latest version")
        job.run(git(addons, "submodule", "update", "--init", "--remote", "--recursive"), timeout=1800)
    else:
        job.step("Downloading the latest code from GitHub")
        _require_branch(job, name, addons)
        _pull(job, addons)
    after = snapshot(addons)
    if before == after:
        job.note("Already up to date: there is nothing new on GitHub.")
        return
    modules = changed_modules(addons, before, after)
    job.note(f"Changed modules: {', '.join(modules)}" if modules else "New code downloaded.")
    if modules and store.read_env(name)["AUTO_UPGRADE"] == "true":
        upgrade_modules(job, name, modules, stay_paused=paused)
    elif paused:
        refresh_addons_path(job, name)
        job.note("The instance stays paused and uses the new code when someone opens it.")
    else:
        restart(job, name)


def _require_branch(job: Job, name: str, addons: Path) -> None:
    """Stop with a clear message when the instance's branch was deleted on GitHub (often after a merged pull
    request); git itself only says "no such ref was fetched"."""
    branch = store.read_env(name)["GIT_BRANCH"]
    exists = branch_on_github(addons, branch)
    STATE.update(name, branch_missing=exists is False)
    if exists is False:
        job.write(f"The branch {branch} no longer exists on GitHub.\n")
        raise JobError(f"branch {branch} no longer exists on GitHub")


def switch_branch(job: Job, name: str, branch: str) -> None:
    addons = store.addons_dir(name)
    job.step(f"Switching the code to branch {branch}")
    job.run(git(addons, "fetch", "origin", branch), timeout=900)
    job.run(git(addons, "checkout", "-B", branch, f"origin/{branch}"))
    job.run(git(addons, "branch", f"--set-upstream-to=origin/{branch}", branch))
    job.run(git(addons, "submodule", "update", "--init", "--recursive"), timeout=1800)
    store.update_env(name, GIT_BRANCH=branch)
    STATE.update(name, branch_missing=False)
    if not _paused(name):
        restart(job, name)


def _apply_code_change(job: Job, name: str) -> None:
    """After the code changed: a paused instance only gets the new addons_path, a running one restarts."""
    if _paused(name):
        refresh_addons_path(job, name)
    else:
        restart(job, name)


def _save_to_github(job: Job, addons: Path, undo: Callable[[], None]) -> None:
    """Push the last commit; if GitHub refuses, run `undo` so the server matches GitHub again, and fail."""
    if not capture(git(addons, "remote", "get-url", "origin")):
        return
    job.step("Saving the change to GitHub")
    if job.run_unchecked(git(addons, "push"), timeout=300):
        undo()
        raise JobError(
            "GitHub refused the change. The repository's deploy key needs write access "
            "(tick 'Allow write access' for it on GitHub). The change was undone on the server."
        )


def add_submodule(job: Job, name: str, url: str, path: str, branch: str | None) -> None:
    addons = store.addons_dir(name)
    job.step(f"Adding submodule {path}")
    job.run(git(addons, "submodule", "add", *(["-b", branch] if branch else []), "--", url, path), timeout=1800)
    job.run(git(addons, "submodule", "update", "--init", "--recursive", path), timeout=1800)
    job.run(git(addons, "commit", "-m", f"Add submodule {path}"))

    def undo() -> None:
        job.run_unchecked(git(addons, "reset", "--hard", "HEAD~1"))
        job.run_unchecked(git(addons, "submodule", "deinit", "-f", path))
        shutil.rmtree(addons / ".git" / "modules" / path, ignore_errors=True)
        shutil.rmtree(addons / path, ignore_errors=True)

    _save_to_github(job, addons, undo)
    _apply_code_change(job, name)


def remove_submodule(job: Job, name: str, path: str) -> None:
    addons = store.addons_dir(name)
    job.step(f"Removing submodule {path}")
    job.run(git(addons, "submodule", "deinit", "-f", path))
    job.run(git(addons, "rm", "-f", path))
    shutil.rmtree(addons / ".git" / "modules" / path, ignore_errors=True)
    job.run(git(addons, "commit", "-m", f"Remove submodule {path}"))

    def undo() -> None:
        job.run_unchecked(git(addons, "reset", "--hard", "HEAD~1"))
        job.run_unchecked(git(addons, "submodule", "update", "--init", "--recursive", path))

    _save_to_github(job, addons, undo)
    _apply_code_change(job, name)
