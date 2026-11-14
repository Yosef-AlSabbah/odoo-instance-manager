# Administrator Guide

**Audience:** the person responsible for the server and the panel.
**Covers:** installing, updating, rolling back and uninstalling, the first account, settings, e-mail, links, files and containers, Enterprise
add-ons, backups, daily backups and restores, the command line, checks and troubleshooting.
**You need:** SSH access to the server as root (or with `sudo`).

---

## Contents

1. [The server](#1-the-server)
2. [Installing](#2-installing)
3. [The first account](#3-the-first-account)
4. [Updating, rolling back, uninstalling](#4-updating-rolling-back-uninstalling)
5. [Settings](#5-settings)
6. [E-mail](#6-e-mail)
7. [Public links](#7-public-links)
8. [Containers, files and folders on the server](#8-containers-files-and-folders-on-the-server)
9. [Odoo Enterprise add-ons](#9-odoo-enterprise-add-ons)
10. [Backups](#10-backups)
11. [Accounts from the command line](#11-accounts-from-the-command-line)
12. [Checking that everything works](#12-checking-that-everything-works)
13. [Troubleshooting](#13-troubleshooting)
14. [Moving to permanent links](#14-moving-to-permanent-links)

---

## 1. The server

| Need | Why |
| :--- | :--- |
| Ubuntu 22.04+ or Debian 12+ (others may work, with a warning), amd64 or arm64, booted with systemd | Every part runs in Docker containers ([Docker](concepts/DOCKER.md)); the images exist for both architectures. |
| 2 CPU cores, 2 GB of memory or more (4 GB recommended); about 1 to 1.5 GB per running instance | Odoo and PostgreSQL. Paused instances use none. |
| 20 GB of free disk on `/opt` and on Docker's folder (`/var/lib/docker`) | Odoo images (about 1.5 GB per version), databases, attachments, backups. |
| Docker Engine 24+ with the Compose v2 plugin (the installer installs them after asking) | The panel and every instance are Compose projects. |
| Outgoing HTTPS to github.com, ghcr.io, registry-1.docker.io and Cloudflare (443, 7844); GitHub SSH (22) for private repositories | Releases and code, the Sudoo.sh images, the Odoo images, public links. |
| **No incoming port** | Public access goes through connections the server opens itself ([Tunneling](concepts/TUNNELING.md)). Only SSH is needed, for administration. |

The installer checks all of this before it changes anything. To only check (changes nothing):

```bash
curl -fsSL https://github.com/Sudoo-sh/sudoo.sh/releases/latest/download/sudoo-install.sh | sudo bash -s -- check
```

Each line is marked ✓ (fine), ! (a warning) or ✗ (must be fixed), and every problem has a `Fix:` line;
[section 13](#installer-checks) lists them all.

---

## 2. Installing

On a fresh server, one command does everything:

```bash
curl -fsSL https://github.com/Sudoo-sh/sudoo.sh/releases/latest/download/sudoo-install.sh | sudo bash
```

`sudoo-install.sh` is one file attached to every release; nothing else is downloaded except the release's images. To
read it before running it:

```bash
curl -fsSLO https://github.com/Sudoo-sh/sudoo.sh/releases/latest/download/sudoo-install.sh
curl -fsSLO https://github.com/Sudoo-sh/sudoo.sh/releases/latest/download/SHA256SUMS
sha256sum --check --ignore-missing SHA256SUMS      # must print: sudoo-install.sh: OK
less sudoo-install.sh
sudo bash sudoo-install.sh
```

What it does, in order:

1. **Checks the server** (read only): root, operating system, architecture, systemd, processor, memory, disk, clock,
   the panel's ports, the tools it needs, internet access, Docker. When a check fails it stops, with the fix, before
   changing anything.
2. **Installs what is missing, after asking**: curl, openssl, ca-certificates, Docker Engine (from Docker's
   repository, or the distribution's packages when Docker has none for this release), the Compose and buildx
   plugins, starting Docker. Each question is answered **[y]es**, **[n]o** or **[a]ll** (yes to every later question).
   Without a terminal it stops and prints the command to run again with `--yes` (also `--allow-all`).
3. **Downloads the images** `ghcr.io/sudoo-sh/sudoo-panel` and `ghcr.io/sudoo-sh/sudoo-web`, pinned by digest in the
   installer, and checks their signatures when `cosign` is installed ([Security](SECURITY.md#12-releases-and-signatures)).
4. **Writes the files**: `/opt/odoo/{manager,instances,enterprise}` (root only), `/opt/odoo/manager/.env` from the
   release's settings template (values already there are kept), and `/opt/odoo/manager/compose.yaml`.
5. **Starts** `sudoo-panel` and `sudoo-web` and waits until both are healthy.
6. Prints the panel's link and, on a new server, the **setup code** for the first account ([section 3](#3-the-first-account)).

It keeps a copy of itself as `/opt/odoo/manager/installer/sudoo-install.sh`, on the path as **`sudoo-install`**.

| Option | Meaning |
| :--- | :--- |
| `--version 1.0.0` | Install that release instead of the latest. `edge` follows `main` ([section 4](#following-main-edge)). |
| `--yes`, `--allow-all` | Answer yes to every question (for scripts). |
| `--dry-run` | Show what would be done; change nothing. |
| `--docker-source official` or `distro` | Where a missing Docker comes from. |
| `--force` | Continue although a check failed (not recommended). |

Settings you want from the start (another `PANEL_PORT`, `EXPOSURE=host-ports`...) can be written to
`/opt/odoo/manager/.env` before installing; the installer keeps them and adds the rest.

### Manual installation

Without the installer, on a server with Docker Engine 24+ and the Compose plugin:

```bash
sudo install -d -m 700 /opt/odoo /opt/odoo/manager /opt/odoo/instances /opt/odoo/enterprise
cd /opt/odoo/manager
sudo curl -fsSLO https://github.com/Sudoo-sh/sudoo.sh/releases/latest/download/compose.yaml
sudo curl -fsSL -o .env https://github.com/Sudoo-sh/sudoo.sh/releases/latest/download/env.example
sudo chmod 600 .env compose.yaml          # edit .env now if needed (CONFIGURATION.md)
sudo docker compose pull
sudo docker compose up -d
sudo docker exec sudoo-panel sudoo.sh urls
sudo docker exec sudoo-panel sudoo.sh setup-code
```

The release's `compose.yaml` names both images by digest. `SHA256SUMS` of the same release covers `compose.yaml` and
`env.example`.

### From source

For developers, from a clone of the repository: the README's "From source" section builds the two images with
`docker compose build` and starts them with the same container names, folders and settings.

---

## 3. The first account

A new server has **no accounts and no default passwords**. The installer prints a setup code, for example:

```
Open the panel's address above and create your account with this setup code:

    ABCD-EFGH-JKLM
```

Open the panel's address in a browser. The **Set up Sudoo.sh** page asks for the setup code, first name, last name,
e-mail (required), phone (optional) and a password twice (12 to 128 characters, following the
[password rules](USER_MANUAL.md#password-rules)). There is no user name field: the user name is made from the
e-mail address (`yousef.sabbah@example.com` becomes `yousef.sabbah`, then `-2`, `-3` when taken) and stays the
account's internal key. It creates the first account, a **Super admin**, and signs it in. Everyone signs in with
their e-mail address; the user name works too. The other accounts are then created on the **Accounts** page
([User manual](USER_MANUAL.md#8-accounts-and-roles)).

| Good to know | |
| :--- | :--- |
| Show the code again | `docker exec sudoo-panel sudoo.sh setup-code` |
| The code works once | After the first account exists, the setup page is gone and the command says the panel is already set up. |
| Wrong codes | 5 wrong codes within 15 minutes block the address they came from for 15 minutes. |
| Second factor | By default super admins and administrators must set up a second factor right after signing in. Without e-mail set up, only the authenticator app is offered, so set up e-mail first ([section 6](#6-e-mail)) if you want e-mail codes. |

Keep the setup code private until the first account exists: whoever uses it first becomes super admin.

---

## 4. Updating, rolling back, uninstalling

```bash
sudo sudoo-install update
```

(or, on a server without the `sudoo-install` command, the install command with `-s -- update`). It runs the checks,
downloads the latest release's installer and checks it against that release's `SHA256SUMS`, then:

1. backs up `/opt/odoo/manager` to `/opt/odoo/manager-backup-<date>.tgz`;
2. keeps the running images under a name, for a rollback;
3. adds the new settings to `.env` with their defaults (every value already set is kept) and writes the new
   `compose.yaml`;
4. recreates **only `sudoo-panel` and `sudoo-web`**, waits until both are healthy, and checks that every instance
   and connector container is still the same container with the same start time.

| Kept | Replaced or restarted |
| :--- | :--- |
| Instances, their databases, files and links | `sudoo-panel` and `sudoo-web` (a few seconds) |
| The connector containers, so every public link stays the same | `compose.yaml`; new settings in `.env` |
| Accounts, API tokens, audit log (`sudoo.db`), deploy keys, vault key, secret key | |
| Settings in `.env` and `settings.json` | |

Running instances are not restarted. Read the release notes before updating to a new major version. A specific
version: `sudo sudoo-install update --version 1.2.0`.

### Rolling back

```bash
sudo sudoo-install update --rollback
```

Puts back the images and `compose.yaml` of the version that ran before the last update (the `.env` stays). Running it
again switches forward. The backup of `/opt/odoo/manager` taken by the update is there if data must go back too.

### Following main (edge)

Every commit on `main` that passes the checks publishes images tagged `edge` and `sha-<commit>`. A test server can
follow them:

```bash
sudo sudoo-install update --version edge
```

The images are pinned to their digest at that moment, with the `compose.yaml` and `.env.example` of the same commit.
Later `sudo sudoo-install update` runs keep following `edge`; `--version 1.2.0` goes back to releases.

### Servers installed with the earlier install.sh

Servers installed by the earlier `get.sh` / `install.sh` (images built on the server, the kit in
`/opt/sudoo.sh-kit`) update with the same command. The containers keep their names, `/opt/odoo` and `.env` stay, the
connectors and instances are not touched. The source files in `/opt/odoo/manager` and `/opt/sudoo.sh-kit` are removed
afterwards (they are in the backup), and the images built on the server are kept for `update --rollback`.

### Updating by hand

For a [manual installation](#manual-installation): download the new release's `compose.yaml` into
`/opt/odoo/manager`, add the new keys of its `env.example` to `.env`, then
`sudo docker compose pull && sudo docker compose up -d` there. `docker compose` only recreates `sudoo-panel` and
`sudoo-web`; never use `--remove-orphans` or restart the connectors.

### Uninstalling

```bash
sudo sudoo-install uninstall
```

Removes `sudoo-panel`, `sudoo-web`, their images, the Cloudflare connectors (the public links stop working) and the
`sudoo-install` command, and stops the instances. `/opt/odoo` (settings, accounts, keys, backups) and the instances'
databases and files are kept; installing again brings them back, with new links.

`sudo sudoo-install uninstall --purge` also deletes every instance with its volumes and all of `/opt/odoo`. It asks you
to type `DELETE` (`--yes` does not answer it). Docker stays installed.

---

## 5. Settings

Settings come from two places:

| Where | What |
| :--- | :--- |
| `/opt/odoo/manager/.env` (mode 600) | The base value of every setting, written by the installer. |
| `/opt/odoo/manager/settings.json` | The changes made on the panel's **Settings** page, applied on top of `.env`. Passwords in it are encrypted with the vault key. |

A super admin changes most settings in the browser (**Settings** in the sidebar; [User manual](USER_MANUAL.md#11-settings)).
Every setting belongs to one of three classes:

| Class | Settings | How a change applies |
| :--- | :--- | :--- |
| **Now** | Almost everything: second factor requirement, session times, e-mail (including the mail password), limits, defaults for new instances, daily backups (`DAILY_BACKUPS`, `DAILY_BACKUP_TIME`, `TIMEZONE`), Odoo versions and images, instance containers (limits, `DRIFT_ACTION`), Enterprise paths, update checks, webhook secret, contact, accent colour, `METRICS_INTERVAL_SECONDS`. | At once, when saved on the Settings page. Container limits reach an instance when it next starts or restarts. |
| **Restart** | The settings that choose plugins: `MAILER`, `SECOND_FACTORS`, `UPDATE_TRIGGERS`, `ENTERPRISE_SOURCE`, `AUTH`, `RATE_LIMITER`. | After **Restart the panel** (Settings, Plugins). The restart stops only the backend for a few seconds and is refused while jobs run. |
| **.env only** | `ODOO_ROOT`, `DOCS_DIR`, `MEMORY_DIR`, `EXPOSURE`, `STORAGE`, `PUBLIC_HOST`, `PUBLIC_SCHEME`, all ports (`PANEL_PORT`, `API_PORT`, `EVENTS_PORT`, `GATEWAY_PORT_START`, `ODOO_PORT_START`, connector ports), `CONNECTOR_PREFIX`. | Edit `.env`, then `cd /opt/odoo/manager && docker compose up -d`. The Settings page lists them under **Server**, read only. |

A value changed on the Settings page wins over `.env`. **Use .env** on that page removes the change and brings back
the `.env` value. Editing `.env` by hand therefore has no effect on a setting that was changed in the browser until
someone clicks **Use .env**.

Every setting, with its type, default and meaning, is in [Configuration](CONFIGURATION.md); the template with
comments is `.env.example`. To see what the panel is actually using, and which plugins are installed:

```bash
docker exec sudoo-panel sudoo.sh config
```

A wrong value in `.env` (for example `IDLE_HOURS=soon`) or an unknown plugin name stops the panel at start-up, and
`docker logs sudoo-panel` names the setting. The Settings page checks every value before saving it.

The two choices that shape a server are plugins ([Plugins](PLUGINS.md)):

| Setting | Options |
| :--- | :--- |
| `EXPOSURE` | `cloudflare-quick` (free tunnel per instance, no open port; default) or `host-ports` (open ports, fixed addresses) |
| `ENTERPRISE_SOURCE` | `folder` (default), `git` (a branch per version) or `none` |

Per instance, the **Settings** tab of the instance's page changes automation and lifetime (stored as
`AUTO_UPDATE`, `AUTO_UPGRADE`, `AUTO_PAUSE`, `DELETE_AFTER_DAYS` in the instance's `.env`).

---

## 6. E-mail

The panel sends e-mail for sign-in codes and test messages. Without e-mail the panel works, but the **E-mail code**
second factor is not offered. E-mails are HTML in the style of Odoo's own, with a plain-text part; the code in them
can be selected with one tap, and Gmail's apps add their own **Copy code** button.

### Gmail, step by step

1. On the Google account that will send the e-mails, turn on **2-Step Verification** (myaccount.google.com,
   Security). Google offers app passwords only with it.
2. Open **myaccount.google.com/apppasswords**, create an app password named `Sudoo.sh` and copy the 16 letters
   Google shows once.
3. In the panel, as a super admin, open **Settings, E-mail** and fill in:

   | Field | Value |
   | :--- | :--- |
   | Mail server | `smtp.gmail.com` |
   | Port | `587` |
   | Encryption | STARTTLS |
   | User name | the Gmail address |
   | Password | the app password (not the account's normal password) |
   | Sender | `Sudoo.sh <your.address@gmail.com>` |

4. Click **Save**, then **Send a test** and enter an address. The test e-mail should arrive within a minute (look in
   the spam folder too).

The same in `/opt/odoo/manager/.env` instead of the browser:

```
MAILER=smtp
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=your.address@gmail.com
SMTP_PASSWORD=the16letterapppassword
MAIL_FROM=Sudoo.sh <your.address@gmail.com>
```

Apply and test:

```bash
cd /opt/odoo/manager && docker compose up -d
docker exec sudoo-panel sudoo.sh test-email you@example.com
```

Gmail sends from the signed-in address (or an alias added under Gmail's **Send mail as**), at most about 500
messages a day for a personal account. Other mail servers are described in
[Configuration: Gmail](CONFIGURATION.md#gmail) and the sections after it.

---

## 7. Public links

The panel and every instance have their own link, `https://<words>.trycloudflare.com` (with the default
`EXPOSURE=cloudflare-quick`).

**These Cloudflare quick tunnel links change when the server restarts, or when a connector container restarts.**
The panel always shows the current ones, and tells every Odoo its new address within about 15 seconds (so links
inside Odoo, such as those in e-mails, follow). Links you shared earlier, and webhook addresses registered at other
services, must be updated by hand.

Updating Sudoo.sh does not touch the connector containers, so the links stay the same through an update.

To see the current links on the server:

```bash
docker exec sudoo-panel sudoo.sh urls
```

Administrators can also reach the panel without Cloudflare, through SSH (9000 is the default `PANEL_PORT`):

```bash
ssh -N -L 9000:localhost:9000 <user>@<server>
```

then open `http://localhost:9000`. Why the server needs tunnels at all is explained in
[Tunneling](concepts/TUNNELING.md).

---

## 8. Containers, files and folders on the server

### Containers

| Container | What it is |
| :--- | :--- |
| `sudoo-web` | The web app (React, served by Caddy) on `PANEL_PORT` (9000). Forwards `/api`, `/hooks` and `/docs` to the backend and `/api/v1/events` to the live events. |
| `sudoo-panel` | The backend: the API on `127.0.0.1:API_PORT` (9002), live events on `127.0.0.1:EVENTS_PORT` (9001), the gateways in front of the instances, the monitor and the jobs. |
| `sudoo-connector-panel` | The panel's Cloudflare connector. |
| `sudoo-connector-<name>` | One connector per instance. |
| `odoo-<name>-odoo-1`, `odoo-<name>-db-1` | The instance's Odoo and PostgreSQL. |
| volumes `odoo-<name>_db-data`, `odoo-<name>_odoo-data` | The instance's database and its attachments (filestore). |

Do not restart or recreate the connector containers by hand: their links would change.

### Files and folders

```
/opt/odoo/                                   root only
├── manager/
│   ├── .env                                 settings (mode 600)
│   ├── compose.yaml                         sudoo-panel and sudoo-web, images pinned (written by the installer)
│   ├── installer/                           sudoo-install.sh (the sudoo-install command), the running and the
│   │                                        previous version (release, previous-release)
│   ├── settings.json                        settings changed on the Settings page, on top of .env;
│   │                                        passwords in it are ENCRYPTED
│   ├── sudoo.db                             SQLite: accounts (password HASHES), second factors, API tokens,
│   │                                        audit log, instance state, creation times (mode 600)
│   ├── vault.key                            encrypts stored secrets, peppers password hashes (mode 600)
│   ├── secret_key                           signs session cookies (mode 600)
│   ├── keys/known_hosts                     GitHub's SSH host key, recorded on first use
│   ├── keys/deploy/<owner>__<repo>.key      deploy key, ENCRYPTED (mode 600)
│   ├── keys/deploy/<owner>__<repo>.pub      its public part (what is added on GitHub)
│   ├── keys/deploy/<owner>__<repo>.name     the repository name as written on GitHub
│   └── documentation, code                  none: they are inside the images (the documentation of the running
│                                            version is in sudoo-panel under /app/documentation)
├── manager-backup-<date>.tgz                /opt/odoo/manager before an update or rollback (mode 600)
├── enterprise/<version>/                    Enterprise add-ons (folder source, default ENTERPRISE_PATH)
├── enterprise-git/<version>/                Enterprise add-ons downloaded by the git source
├── backups/                                 Odoo-format backup zips (mode 600)
└── instances/<name>/
    ├── .env                                 version, edition, ports, database, automation, pinned images
    │                                        (mode 600); MASTER_PASSWORD in it is ENCRYPTED
    ├── docker-compose.yml                   the instance's two containers, written by the panel (mode 600)
    ├── config/odoo.conf                     Odoo configuration; master password as a HASH only (mode 600,
    │                                        owned by the Odoo image's user)
    └── addons/                              the repository, with its submodules
```

### Useful commands

| Task | Command |
| :--- | :--- |
| Everything running | `docker ps` |
| Backend log | `docker logs -f sudoo-panel` |
| Web app log | `docker logs -f sudoo-web` |
| Odoo log of an instance | `cd /opt/odoo/instances/<name> && docker compose logs -f odoo` |
| Current links | `docker exec sudoo-panel sudoo.sh urls` |
| Effective settings | `docker exec sudoo-panel sudoo.sh config` |
| Memory | `free -m` |
| Disk per container and volume | `docker system df -v` |

Do not run `docker compose up` or `down` for an instance by hand: use the panel, which also keeps its gateway,
connector and state in step. A change made by hand to an instance's containers or files is found and, with
`DRIFT_ACTION=restore`, undone (next section).

### Hardened containers and changes made by hand

Each instance's `odoo` and `db` containers run with no extra privileges, read-only system files, as few Linux
capabilities as the images need, limits, rotated logs, images pinned by digest, and the database on an internal
network only. What exactly, and what cannot be protected: [Security](SECURITY.md#10-instance-containers).

**Limits.** Set on the Settings page (**Instance containers**) or in `.env`:

| Setting | Default | Meaning |
| :--- | :--- | :--- |
| `ODOO_MEMORY_LIMIT` | `2g` | Memory of each instance's Odoo; `0` for no limit |
| `ODOO_CPU_LIMIT` | `2` | Processor cores of each instance's Odoo; `0` for no limit |
| `DB_MEMORY_LIMIT` | `1g` | Memory of each instance's PostgreSQL; `0` for no limit |
| `DB_CPU_LIMIT` | `2` | Processor cores of each instance's PostgreSQL; `0` for no limit |
| `CONTAINER_PIDS_LIMIT` | `1024` | Processes and threads per container |
| `CONTAINER_LOG_MAX_SIZE`, `CONTAINER_LOG_MAX_FILES` | `10m`, `3` | Log rotation per container |

A change reaches an instance the next time it starts or restarts through the panel; running instances are never
restarted for it. The same is true of instances made before this version: they get the hardened containers at their
next start or restart (the database container is recreated too; its data stays in its volume).

**Images.** An instance keeps the exact Odoo and PostgreSQL images it was created with (pinned by digest in its
`.env` as `ODOO_IMAGE_REF` and `DB_IMAGE_REF`). **Update Odoo and PostgreSQL images** in the instance's menu
(`POST /api/v1/instances/<name>/actions/update-images`, permission `instances.operate`) downloads the same image names
and tags again, pins the new digests and recreates the containers; a paused instance gets them at its next start.
`ODOO_IMAGE` and `POSTGRES_IMAGE` apply to new instances only, so an instance never jumps to another PostgreSQL major
version.

**Changes made by hand (drift).** Every 20 seconds the panel compares each instance with what it applied. When
something differs twice in a row:

* the instance's page shows a red banner, **Changed outside the panel**, listing what differs, and the instance card
  a tag of the same name;
* the audit log gets "configuration changed outside the panel", with the details;
* every super admin with an e-mail address gets a message (when e-mail is set up).

What happens next is `DRIFT_ACTION`:

| `DRIFT_ACTION` | Odoo and database containers, compose file, odoo.conf | Connector, `.env` |
| :--- | :--- | :--- |
| `restore` (default) | A job **Restore the panel's configuration** runs as soon as no other job runs on the instance: database backup first if its container is affected (kind "Before a repair", one kept per instance), the panel's files written back, strange containers stopped, affected containers recreated. A paused instance stays paused. Tried once per set of differences, again after 30 minutes if they remain. | Reported only. |
| `warn` | Reported only; the banner has a **Restore the panel's configuration** button (`instances.operate`, action `repair`). | Reported only. |

The banner goes away by itself once the instance matches again. A connector is never recreated by the panel (its
link would change): undo the change by hand, or remove the connector and let the panel create a new one (new link).
A hand-edited `.env` never changes the containers; **Restore the panel's configuration** accepts it as it is, after
you have checked it.

To see what the check sees, without changing anything:

```bash
docker exec sudoo-panel python -c "from sudoo.instances import integrity; print(*integrity.findings('<name>'), sep='\n')"
```

---

## 9. Odoo Enterprise add-ons

**The Enterprise add-ons are not part of this project** and never go into its repository: they are Odoo's
proprietary code, available to Odoo partners and subscribers. Each server needs its own copy. Where the panel finds
it is chosen by the add-on source plugin (`ENTERPRISE_SOURCE`, see [Plugins](PLUGINS.md#4-add-on-sources-where-enterprise-comes-from)).
The paths and the git address can be changed on the Settings page (**Enterprise add-ons**); changing the source
itself needs **Restart the panel**.

The **Edition** field offers Enterprise for each version the source can provide. The add-ons are mounted read-only
into every Enterprise instance of that version, after the instance's own modules (so a custom module can replace an
Enterprise one), and `web_enterprise` is installed with the database.

**Folder source** (default): a folder per version, wherever you keep them. `ENTERPRISE_PATH` names it, with
`{version}` (19.0) and `{major}` (19) replaced:

| `ENTERPRISE_PATH` | Folder for Odoo 19 |
| :--- | :--- |
| `/opt/odoo/enterprise/{version}` (default) | `/opt/odoo/enterprise/19.0` |
| `/data/odoo-enterprise-{major}` | `/data/odoo-enterprise-19` |

Each folder holds the modules directly:

```
/opt/odoo/enterprise/19.0/
├── web_enterprise/         required: Enterprise is offered only when this module (ENTERPRISE_MARKER) is there
├── account_accountant/
└── ...                     every Enterprise module directly inside, not in a sub-folder
```

| Rule | Right | Wrong |
| :--- | :--- | :--- |
| Modules sit directly inside the version's folder | `19.0/web_enterprise/` | `19.0/enterprise/web_enterprise/` |
| The add-ons match the version | Odoo 19 add-ons for 19.0 | Odoo 18 add-ons for 19.0 |
| Readable by the Odoo containers | `chmod -R a+rX <folder>` | files readable by root only |

**Git source**: set `ENTERPRISE_SOURCE=git`, `ENTERPRISE_GIT_URL` (a private repository you control, with one branch
per version) and `ENTERPRISE_GIT_BRANCH` (for example `{version}`). Give the server a deploy key for that repository
under **GitHub access**. The branch is downloaded when an Enterprise instance of that version is created, and
refreshed the next time.

Adding or updating a version, from a computer that has the add-ons folder (the folder that directly contains
`web_enterprise`, `account_accountant` and so on):

```bash
tar czf - -C "<folder with the add-ons>" . | ssh <user>@<server> \
  'mkdir -p /opt/odoo/enterprise/21.0 && tar xzf - -C /opt/odoo/enterprise/21.0 && chmod -R a+rX /opt/odoo/enterprise/21.0'
```

(for the default `ENTERPRISE_PATH`; use your own path otherwise.) The new version is offered as soon as the Odoo
image of that version is published (`ODOO_VERSIONS=auto`) or listed in `ODOO_VERSIONS`. After updating a version,
restart its Enterprise instances and upgrade modules where needed. Enterprise databases must be registered with an
Odoo subscription or partner code, otherwise Odoo shows its expiry notice after the trial period.

---

## 10. Backups

### Instances

**Instances are backed up by the panel.** Every backup writes one zip per database to `/opt/odoo/backups/`
(`BACKUPS_DIR`):

```
/opt/odoo/backups/<instance>__<database>__<YYYYMMDD-HHMMSS>__<kind>.zip      mode 600
├── dump.sql          the database (pg_dump --no-owner)
├── filestore/        attachments and images
└── manifest.json     database name, Odoo version, edition (backups of this version of Sudoo.sh on), instance
```

The time in the name is when the backup started. Files from earlier versions have no `__<kind>`
part and count as `manual`.

| Kind | Taken | Kept |
| :--- | :--- | :--- |
| `manual` | **Back up now** on an instance's page. | Until someone deletes it. |
| `daily` | Once a day, for each instance used since its last daily backup (below). | Only the latest per instance; the new one replaces the previous. Removed when the instance is deleted. |
| `deletion` | Before every deletion, automatic or by hand. If it fails, the instance is not deleted. | Until someone deletes it. |
| `before-restore` | At the start of every restore: the state just before it, offered as **Rollback**. | Only the latest per instance, for `ROLLBACK_HOURS` (24 by default). Removed when the instance is deleted. |
| `before-rollback` | At the start of every rollback: the state just before it. | Only the latest per instance, for `ROLLBACK_HOURS`. Removed when the instance is deleted. |
| `before-repair` | Before the panel recreates a database container that was changed outside the panel ([drift](#hardened-containers-and-changes-made-by-hand)). | Only the latest per instance. Removed when the instance is deleted. |

This is Odoo's own backup format, with both the database and the filestore: restore it with **Restore Database**
in any Odoo's database manager of the same version, or by hand (`createdb`, `psql -f dump.sql`, copy `filestore/`
into the new Odoo's `filestore/<database>`). The files are listed (with their kind), downloaded and deleted under
**Backups** in the panel; an instance's own backups are also on its **Overview** tab. Copy the ones you want to keep
off the server.

**Daily backups.** Every minute the panel checks whether today's backup time has passed (`DAILY_BACKUP_TIME`,
default `00:00`, in `TIMEZONE`, default `UTC`). When it has, it backs up each instance that was **used** since its
last daily backup: opened through its link, or started or restarted. The panel records the first use after each
daily backup (`used_since` in the instance state) and clears it when the daily backup starts.

* An instance nobody used gets no new daily backup, so its last one stays.
* A running instance keeps running during the backup; a paused one stays paused (only its database container is
  started for the backup, then stopped again).
* An instance with a job running is tried again a minute later. A daily backup that fails waits for the next day.
* If the panel was down at the backup time, the backups run as soon as it is back.
* `DAILY_BACKUPS=false` turns them off. All three settings are on the Settings page under **Backups** and apply at
  once. `TIMEZONE` takes a name of the time zone database, such as `UTC` or `Africa/Cairo` (the panel image includes
  the time zone data).

**Restoring.** Roles with the `instances.restore` permission (maintainer, administrator, super admin) restore an
instance from its **Overview** tab: **Restore the latest** (the newest `manual`, `daily` or `deletion` backup of a
database the instance has) or **Restore** on any backup in the list. The job "Restore a backup":

1. saves the current state as a `before-restore` backup, so the restore can be undone,
2. stops Odoo,
3. drops the database, creates it again and loads `dump.sql`, replaces the filestore with the backup's
   `filestore/`, and sets the instance's current public address in the database again,
4. starts Odoo and waits until it answers.

It takes about a minute or two, depending on the size. The instance is running afterwards. A backup of the
instance itself goes back into the database it was taken from (the instance must still have it).

**Backups of other instances.** **Restore another backup…** on the Backups card (and `{"file"}` of the `restore`
action) takes a backup of any instance, and **Start from a backup** on the New instance page (`from_backup`) starts a
new instance from one. Both need `instances.restore` and `backups.manage` (administrators and super admins; a
maintainer only restores an instance's own backups), and creating also needs `instances.create`. The panel checks:

* the backup exists (only names from the backup folder are accepted, never a path);
* its Odoo series, read from `version` in its `manifest.json`, is the instance's (`17.0` goes only into `17.0`; a
  backup without a readable version is refused);
* an Enterprise backup goes only into an Enterprise instance (backups taken before this version of Sudoo.sh do not
  record the edition and are not checked for it).

The backup's database is loaded under the target instance's database name (the dump has no database name or owner
in it), and its filestore goes to the target's `filestore/<database>`. Then, because the data comes from another
instance, the job neutralises it: on Odoo 16 and later it runs `odoo neutralize -d <database>` in a temporary
container of the instance, which switches off mail servers, scheduled actions, payment providers and the other
integrations each installed app declares; on older versions, or if that command fails, it switches off
`ir_mail_server`, incoming mail servers and every scheduled action except Odoo's database cleanup directly in SQL.
In both cases the copy gets a new `database.uuid` and `database.secret`, so it is not taken for the original and
sessions of the original do not work in it. The job's notes say it was neutralised. Finally web.base.url is set to
the instance's own address, as for every restore. A backup whose instance has the same name as the target (its own,
or one of an earlier instance of that name) is not neutralised.

A new instance started from a backup skips creating an empty database (and demo data). If **Install the
repository's modules** is on, only the repository's modules the backup does not have installed are installed;
modules it has are left at their version (upgrade them with **Upgrade modules** if the code is newer). The backup's
user 2 (the first administrator) gets `ODOO_ADMIN_PASSWORD`, so the instance's **Access** tab is right, and the job's
result shows that user's login.

**Rollback.** For `ROLLBACK_HOURS` (default 24, on the Settings page under **Backups**) after a restore, the
instance's page shows **Rollback to before the restore (until …)**, and the `rollback` action puts back the newest
`before-restore` backup of the instance. A rollback first saves the current state as `before-rollback`, never as
`before-restore`, so it cannot replace the snapshot it restores; if that backup fails (for example after a restore
that failed halfway and left no database), the rollback goes on with a warning. Restoring an instance's own
`before-restore` backup from the list is a rollback too. Every five minutes the panel removes `before-restore` and
`before-rollback` backups older than `ROLLBACK_HOURS`, but never while a job runs (a restore or a creation may be
about to read one); the Rollback offer ends with the file. After a rollback the banner goes away.

**Disk use.** Backups by hand and before deletions add up until someone deletes them. Daily, before-restore and
before-rollback backups stay bounded: at most one of each per instance, the last two only for `ROLLBACK_HOURS`. Plan for about two zips per instance in use on top of the
ones kept by hand, and check `du -sh /opt/odoo/backups` from time to time; the server's disk use is also on the
Instances page.

**Lifetime.** Each instance has `DELETE_AFTER_DAYS` in its `.env` (0: kept). Every 10 minutes the panel deletes the
instances whose lifetime is over, backup first; if the backup fails, the instance is not deleted. New instances get
the default lifetime (30 days; Settings, New instances) unless "Keep until deleted by hand" is chosen; it can be
changed on the instance's Settings tab.

**By hand**, for an instance (database and attachments):

```bash
NAME=sales-main; DB=sales_main
docker exec odoo-$NAME-db-1 pg_dump -U odoo -Fc $DB > $NAME.dump
docker run --rm -v odoo-${NAME}_odoo-data:/data -v "$PWD":/backup alpine tar czf /backup/$NAME-files.tgz -C /data .
```

### The panel itself

Back up `/opt/odoo/manager`. The parts that cannot be recreated:

| File | Holds | Without it |
| :--- | :--- | :--- |
| `sudoo.db` | Accounts, second factors, API tokens, audit log, instance state | Every account and token must be created again. |
| `vault.key` | The key of every encrypted secret | Encrypted deploy keys, master passwords and passwords in `settings.json` cannot be read; account passwords must be reset. |
| `settings.json` | Settings changed in the browser | The `.env` values apply. |
| `.env` | The base settings | The installer writes the defaults. |
| `secret_key` | Signs session cookies | A new one is made; everyone signs in again. |
| `keys/` | Deploy keys (encrypted) | Deploy keys must be created and added on GitHub again. |

`compose.yaml` and `installer/` are written again by the installer; the code and the documentation are in the images.

**The vault key** deserves its own place:

* Store it **separately** from the other backups (for example in the team's password manager, as a file
  attachment). A backup that contains both the encrypted secrets and their key protects nothing.
* Without it, encrypted deploy keys and master passwords cannot be read: deploy keys must be created again and
  added on GitHub again, and the panel's account passwords must be reset (the key also peppers their hashes).

See [Security](SECURITY.md) for why it works this way.

---

## 11. Accounts from the command line

For the first account, and for when nobody can sign in. Every command runs inside the panel's container:

| Command | What it does |
| :--- | :--- |
| `docker exec sudoo-panel sudoo.sh setup-code` | Shows the setup code for the first account, or says the panel is already set up. |
| `docker exec sudoo-panel sudoo.sh create-user NAME ROLE` | Creates an account and prints its password once. `ROLE` is `super_admin`, `admin`, `maintainer`, `developer` or `viewer`. The account has no e-mail address, so it signs in with the user name `NAME`; add an e-mail address on the Accounts page (or in **My account**) to sign in with it. |
| `docker exec sudoo-panel sudoo.sh reset-password NAME` | Sets a new password, prints it once and signs the account out everywhere. The person chooses their own at the next sign-in. |
| `docker exec sudoo-panel sudoo.sh list-users` | Lists the accounts with their role and last sign-in. |
| `docker exec sudoo-panel sudoo.sh create-token NAME SCOPE` | Creates an API token (`SCOPE` is `read` or `write`) and prints the token and signing secret once. |
| `docker exec sudoo-panel sudoo.sh test-email ADDRESS` | Sends a test e-mail with the current mail settings, and says what went wrong if it cannot. |
| `docker exec sudoo-panel sudoo.sh urls` | Prints the panel's and every instance's current link. |
| `docker exec sudoo-panel sudoo.sh config` | Prints the effective settings (secrets hidden) and the installed plugins. |

`sudoo` works as a shorter name for `sudoo.sh`. Commands that change something are recorded in the audit log as
"command line".
Every other account task is done in the panel ([User manual](USER_MANUAL.md#8-accounts-and-roles)): new accounts
need an e-mail address that no other account uses; the password is generated or typed by the administrator
(checked against the [password rules](USER_MANUAL.md#password-rules)); super admins, including your own account,
can be edited; and the last super admin cannot be demoted or deleted.

A person who is locked out by a lost second factor does not need the command line: an administrator uses **Remove
second factors** on the Accounts page. If no administrator can sign in, create a new super admin with
`create-user NAME super_admin`.

---

## 12. Checking that everything works

After installing or updating:

1. `docker ps` shows `sudoo-web`, `sudoo-panel`, `sudoo-connector-panel`, and for each instance its connector, Odoo
   and database (paused and switched-off instances show only their connector).
2. `docker exec sudoo-panel sudoo.sh urls` prints the panel's link and every instance's link.
3. Open the panel's link and sign in (on a new server: the setup page, [section 3](#3-the-first-account)).
4. **Help** in the sidebar opens these pages.
5. As a super admin, **Settings, E-mail, Send a test** delivers a test e-mail (when e-mail is set up).
6. Create a small test instance (no repository, name `check`, the newest version, Community). It should be ready in
   about 2 minutes; open its link and sign in with the login on its **Access** tab.
7. On its page: **Restart**, then **Pause** (menu), then open its link: "Starting up" appears and Odoo opens by
   itself.
8. Delete it (menu, **Delete**). A backup appears under **Backups**, and `docker ps` no longer lists the instance.
9. The logs show no errors: `docker logs sudoo-panel 2>&1 | grep -i error` and `docker logs sudoo-web`.

---

## 13. Troubleshooting

| Symptom | Likely cause | What to do |
| :--- | :--- | :--- |
| The panel's link does not open | The link changed after a restart | `docker exec sudoo-panel sudoo.sh urls` |
| No link at all | `sudoo-panel` or the connector is not running | `docker ps -a`, `docker logs sudoo-panel`, then `cd /opt/odoo/manager && docker compose up -d` |
| The link opens but shows an error, or nothing | `sudoo-web` is not running or not starting | `docker logs sudoo-web`, then `cd /opt/odoo/manager && docker compose up -d` |
| `sudoo-panel` keeps restarting | A wrong value in `.env`, or an unknown plugin name | `docker logs sudoo-panel` names the setting; fix it in `.env` and run `docker compose up -d` in `/opt/odoo/manager` |
| The setup code was lost | It is only printed once by the installer | `docker exec sudoo-panel sudoo.sh setup-code` |
| The setup page refuses even the right code | 5 wrong setup codes within 15 minutes blocked the address | Wait 15 minutes; check the code with `sudoo.sh setup-code` |
| Nobody can sign in (password lost, last super admin locked out) | | `sudoo.sh reset-password NAME`, or `sudoo.sh create-user NAME super_admin` ([section 11](#11-accounts-from-the-command-line)) |
| Lost phone or mailbox with the second factor | | An administrator uses **Remove second factors** on the Accounts page |
| "Too many failed attempts" at sign-in | Sign-in lockout (15 minutes) | Wait, or reset the password |
| "Wrong e-mail address or password" for an account created with `create-user` | The account has no e-mail address | Sign in with the user name, then add the e-mail address in **My account** |
| No daily backup of an instance | Nobody used it since its last daily backup, `DAILY_BACKUPS` is off, or the backup time has not come yet in `TIMEZONE` | Check **Settings, Backups**; the instance's **Activity** tab shows "Daily backup" jobs and why one failed |
| **Restore the latest** is greyed out | The instance has no `manual`, `daily` or `deletion` backup of a database it has | Click **Back up now** to take one, or use **Restore another backup…** for a backup of another instance |
| A backup is greyed out in the backup list | It is of another Odoo version, its version is unknown (no `manifest.json`), or it is an Enterprise backup and the instance is Community | The reason is shown next to it; use an instance of that version and edition |
| A restore failed | The backup file is damaged, or the database did not start | The **Activity** tab shows the step and the reason. Click **Rollback to before the restore** on the instance's page to go back |
| A copy of another instance sends no e-mail | It was neutralised on purpose | In Odoo, switch the outgoing mail servers and the scheduled actions you need back on |
| E-mail codes or the test e-mail do not arrive | Wrong mail settings, or Gmail refuses the normal password | **Send a test** (or `sudoo.sh test-email ADDRESS`) shows the reason. For Gmail, `SMTP_PASSWORD` must be an app password and 2-Step Verification must be on ([section 6](#6-e-mail)). Look in the spam folder. |
| "E-mail code" is not offered | No mail server set, or `email` not in `SECOND_FACTORS` | Set up e-mail ([section 6](#6-e-mail)); after changing `SECOND_FACTORS`, **Restart the panel** |
| A plugin setting changed in the browser has no effect | Plugin settings apply after a restart | Settings, Plugins, **Restart the panel** (refused while jobs run: wait for them) |
| A value changed in `.env` has no effect | The same setting was changed on the Settings page, which wins | Click **Use .env** next to it on the Settings page |
| "Starting up" for several minutes | Odoo fails to start | The instance's **Odoo log** tab |
| An access report line is red on New instance | No deploy key, or not added on GitHub | Create the key, add it on GitHub ([User manual](USER_MANUAL.md#7-github-access-private-repositories)) |
| Update fails: "branch ... no longer exists on GitHub" (or "no such ref was fetched"); the instance page warns about it | The branch was deleted on GitHub, usually after its pull request was merged | Menu, **Switch branch**, choose the branch to follow now (for example `main`) |
| Update fails: "went in different directions" | Something was changed directly in the instance's `addons` folder | A developer resets that folder to the GitHub branch |
| Module changes not visible | The module was not upgraded | **Upgrade modules**, or turn on **Upgrade changed modules** |
| Instance "Stopped" | Odoo crashed, often out of memory | **Start**; pause other instances; `free -m` |
| "Cannot decrypt the value" in a log | `vault.key` was replaced or lost | Restore `vault.key` from its backup; otherwise recreate deploy keys, set the passwords on the Settings page again and reset account passwords |
| Deletion failed: "the database did not start, so no backup could be taken" | The instance's database container is broken | Nothing was deleted. Check `docker logs odoo-<name>-db-1`; to delete anyway, fix or remove the database by hand |
| JSON-2 API: 401 with a valid key | Odoo 20 API key without an expiry date | Create the key with an expiry date ([API](API.md)) |
| Requests over 100 MB, or over 100 seconds, fail | Cloudflare quick tunnel limits | Split uploads; run long operations in the background |


### Installer checks

Every check the installer runs, what a failure means and what to do. A ✗ stops the installer before it changes
anything; a ! is a warning. `sudo sudoo-install check` runs them all without changing anything.

| Check | ✗ or ! means | Fix |
| :--- | :--- | :--- |
| Running as root | It was run without `sudo` | Run it with `sudo` (`... \| sudo bash`) |
| Operating system | ✗ Ubuntu older than 22.04 or Debian older than 12; ! another distribution (not tested) | `sudo do-release-upgrade` (Ubuntu) or upgrade Debian; elsewhere it may work |
| Architecture | Not amd64 (x86_64) or arm64 | Use an x86_64 or arm64 server |
| Service manager: systemd | The system does not boot with systemd (a container, WSL) | Use a server or VM with Ubuntu or Debian |
| Processor | Fewer than 2 cores | A server with 2 or more cores |
| Memory | ✗ under 2 GB; ! under 4 GB | A bigger server; at least add a swap file (`fallocate -l 2G /swapfile`, `mkswap`, `swapon`) |
| Free disk for /opt and /var/lib/docker | Under 20 GB free (5 GB for an update) | Free space (`docker system df`, `docker image prune`) or enlarge the disk |
| Clock | ! The clock is not synchronised | `sudo timedatectl set-ntp true` |
| Port ... is free | Another program listens on `PANEL_PORT`, `API_PORT` or `EVENTS_PORT` | `sudo ss -ltnp 'sport = :9000'` shows it; stop it, or set another port in `/opt/odoo/manager/.env` and run the installer again |
| Tools | curl, tar, openssl or ca-certificates is missing | Answer yes when asked, or `sudo apt-get install -y curl openssl ca-certificates` |
| HTTPS to github.com, ghcr.io, registry-1.docker.io, download.docker.com, api.trycloudflare.com | No connection | Allow outgoing TCP 443; check DNS (`getent hosts ghcr.io`) and any proxy (`HTTPS_PROXY`, and Docker's own proxy settings) |
| Cloudflare tunnel port 7844 | ! Outgoing 7844 is blocked | Allow outgoing TCP and UDP 7844 to `*.argotunnel.com` |
| Docker Engine | Missing, from a snap, not running, or older than 24 | Answer yes to install or start it; a snap: `sudo snap remove docker`, then run again; old: upgrade from Docker's repository |
| Docker Compose | The Compose v2 plugin is missing | Answer yes, or `sudo apt-get install -y docker-compose-plugin` (Ubuntu's `docker.io`: `docker-compose-v2`) |
| Docker buildx | ! Missing (only needed to build images yourself) | `sudo apt-get install -y docker-buildx-plugin` (or `docker-buildx`) |
| Control groups | ! cgroup v1 | Boot with cgroup v2 (`systemd.unified_cgroup_hierarchy=1`), the default on Ubuntu 22.04+ and Debian 12+ |
| Docker starts after a reboot | ! Not enabled | `sudo systemctl enable docker` |

| Message after the checks | What to do |
| :--- | :--- |
| "There is no terminal to ask, so nothing was changed." | Run the printed command (the same, with `--yes`). |
| "Could not download ghcr.io/sudoo-sh/..." | Check access to `ghcr.io`; `docker pull` the image by hand to see Docker's message. |
| "The signature of ... could not be verified" | Do not install it; report it ([Security](SECURITY.md#12-releases-and-signatures)). |
| "Sudoo.sh did not become healthy." | `docker logs sudoo-panel` names the problem (usually `.env`); fix it and run `sudo sudoo-install update`, or go back with `sudo sudoo-install update --rollback`. |
| "These containers changed meanwhile" | The installer does not touch instances or connectors; the panel itself may have started or paused an instance. Check `docker ps`. |
| "No earlier version is kept on this server." | A rollback needs an update made by this installer; install a given version with `update --version X`. |

---

## 14. Moving to permanent links

Quick tunnels are free and need no account, but their addresses change. For addresses that never change:

| Option | How |
| :--- | :--- |
| The server accepts incoming connections | `EXPOSURE=host-ports`, `PUBLIC_HOST=<name or address>`, open the ports. Built in. |
| A domain behind Cloudflare | Buy a domain (about 10 USD a year), create a Cloudflare named tunnel, and write a small exposure plugin that routes `<instance>.<domain>` to each gateway port ([Plugins](PLUGINS.md#6-writing-a-plugin)). |
| A reverse proxy you already run | An exposure plugin like the example in [Plugins](PLUGINS.md#6-writing-a-plugin). |

`EXPOSURE` and `PUBLIC_HOST` are `.env`-only settings: change them in `/opt/odoo/manager/.env` and run
`cd /opt/odoo/manager && docker compose up -d`. The gateway, the instances and the panel stay as they are; only the
exposure plugin changes. The comparison with Tailscale and other options is in
[Tunneling](concepts/TUNNELING.md#7-other-ways-and-why-we-chose-this-one).
