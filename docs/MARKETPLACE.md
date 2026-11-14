# Marketplace

**Audience:** super admins and administrators who add plugins to the panel, and administrators of the server.
**Covers:** the Plugins page, installing free and paid plugins, buying on app.sudoo.sh, licences and what happens
when one ends, linking the panel to an account and logging out of it, how the panel talks to the hub, and what is and
is not protected.

---

## Contents

1. [What the marketplace is](#1-what-the-marketplace-is)
2. [Who can do what](#2-who-can-do-what)
3. [The Plugins page](#3-the-plugins-page)
4. [Installing a free plugin](#4-installing-a-free-plugin)
5. [Buying a paid plugin](#5-buying-a-paid-plugin)
6. [Licences: reminders, grace period, switching off](#6-licences-reminders-grace-period-switching-off)
7. [Updating, switching off and uninstalling](#7-updating-switching-off-and-uninstalling)
8. [Logging out of the account](#8-logging-out-of-the-account)
9. [When the hub cannot be reached](#9-when-the-hub-cannot-be-reached)
10. [How the panel talks to the hub](#10-how-the-panel-talks-to-the-hub)
11. [How a package is checked](#11-how-a-package-is-checked)
12. [Where plugins are kept, and what is protected](#12-where-plugins-are-kept-and-what-is-protected)
13. [Settings and commands](#13-settings-and-commands)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. What the marketplace is

The Sudoo.sh marketplace (marketplace.sudoo.sh) lists plugins that add features to the panel: other sign-in
methods, mailers, backup destinations, notifications and more. Its server, the **hub** (hub.sudoo.sh), keeps the
catalogue, sells paid plugins and **signs every package** after a person at Sudoo.sh has reviewed it. Your panel
installs plugins only from the hub, and only after checking that signature.

| Badge | Meaning |
| :--- | :--- |
| **Official** (the Sudoo.sh mark) | Made by Sudoo.sh itself |
| Green tick (Verified) | Sudoo.sh checked who the publisher is (person or company) and that their support works |
| none | A registered developer whose identity is not confirmed yet; the plugin was still reviewed |

Free plugins need nothing but the panel. Paid plugins need the panel to be **linked** to an account on
app.sudoo.sh, which pays for them ([Buying a paid plugin](#5-buying-a-paid-plugin)).

---

## 2. Who can do what

| Role | Plugins page | Install, buy, update, switch off, uninstall, link |
| :--- | :--- | :--- |
| Super admin | yes | yes, and log out of the account (permission `settings.manage`) |
| Administrator | yes, to look (permission `plugins.view`) | no |
| Maintainer, developer, viewer | no | no |

Uninstalling is a super admin's explicit action and always takes a backup of the panel's data first.

---

## 3. The Plugins page

Open **Plugins** in the sidebar (under Administration). It has three tabs:

| Tab | Shows |
| :--- | :--- |
| **Marketplace** | A **Recommended** row first: plugins the hub suggests for this server, each with the reason ("Because you use Sample mailer", "Made for your country"). Then the catalogue: search, a category list, Free or Paid, and the order (official and verified first, most installed, best rated, newest, name). Each card shows the plugin's icon, the publisher and its badge, the price (the cheapest plan), the rating, how many panels run it, the countries it is made for (or **Made for your country**), and whether it is installed, has an update, needs a newer Sudoo.sh, or its licence ended. Click a card for its details: what it asks permission to do, which other plugins it needs, its plans and prices. Opening a plugin's details tells the hub which plugin was viewed, for better suggestions; the hub keeps it only while the account owner allows personalised recommendations on app.sudoo.sh. |
| **Installed** | Each installed plugin with its version, whether a newer one exists (**Update to vX**), whether it runs, and for a paid plugin its licence: the date it ends and the date it stops. **Manage** switches it off or on, or uninstalls it. |
| **Purchases** | **Receipts**: every payment and renewal of this server's plugins (number, date, plugin, plan, who asked, total) and credit notes for refunds. **Purchases**: every purchase asked for from this server and how it ended (paid, waiting for payment with a link to the payment page, cancelled, expired, failed and why). Each list has **Export CSV** for your accounting; the full receipts (with tax and the invoice) are on app.sudoo.sh. |

When a licence ends soon, is in its grace period or has ended, or when a plugin's files were changed, a banner says
so at the top of every page for super admins and administrators.

---

## 4. Installing a free plugin

1. On **Marketplace**, open the plugin and choose **Install**.
2. A card follows the work: asking the hub, downloading, checking the signature, checking that it suits this
   panel, installing. Nothing else is asked of you.
3. The panel then restarts its backend by itself, which takes a few seconds; the web app, the links and every
   instance keep running. A message says when the plugin is ready.

Installing is refused while other jobs run (a restart would cut them off): wait until they finish. If a step fails,
the card says why in plain words; **Details** shows the technical log.

---

## 5. Buying a paid plugin

**The panel never charges anything.** It asks the hub for a payment page; the account owner pays there, on
app.sudoo.sh, with a saved card or a new one (the bank's 3-D Secure check appears on that page when it asks for
it).

**Link the panel once.** Paid plugins belong to an account, which is billed and receives the e-mails about them. An
account links **one** server.

1. On app.sudoo.sh, open **Servers** and choose **Link a server**. You get a one-time code, valid 15 minutes.
2. In the panel, open **Settings**, section **Marketplace** (or the plugin's details), paste the code and choose
   **Link**. The panel sends it to the hub signed with its own key, so the hub knows which panel it was typed into.

**Buy.** Open the plugin and choose a plan. Each plan shows its price and what it means per month:

| Plan | Shown as |
| :--- | :--- |
| Monthly | `$10/month` |
| Yearly | `$100/year · $8.33/month · save 17%` (saved against the monthly plan) |
| Fixed term | `$30 for 90 days · $10.15/month`, paid once |
| One time | `$250 once, no renewal`: a licence that does not expire |

Then **Buy on app.sudoo.sh**:

1. A new tab opens on the payment page (`app.sudoo.sh/checkout/...`), signed in as the account the server is linked
   to. It shows the plugin, the plan, the server and who asked for it (your name and e-mail).
2. The plugin's details say **Waiting for payment in the other tab**. The panel checks every few seconds, and when
   you come back to its tab.
3. When the payment goes through, the plugin installs by itself, as a free one does. If you closed the details
   meanwhile, nothing is lost: the plugin's button becomes **Install** once paid.
4. A declined card does not end the purchase: the details say why ("The card was declined") and the owner can try
   another card on the same page. A page left unpaid expires after 30 minutes; a purchase cancelled on app.sudoo.sh
   ends too. Nothing is charged then; press the button again to start a new one.

Pressing the button twice, or a network error while asking, never opens two purchases: each press carries its own
key, and the hub answers the same session for the same key.

The button is not offered when the panel is not linked (the details show the link form), when payments are switched
off on the marketplace, or when this server is flagged (see [How the panel talks to the hub](#10-how-the-panel-talks-to-the-hub)).
Subscriptions renew by themselves until they are cancelled on app.sudoo.sh. Uninstalling a plugin does not cancel
its subscription.

---

## 6. Licences: reminders, grace period, switching off

Each paid plugin has a licence for this server. Its dates come from the hub in every heartbeat, signed, and are kept
by the panel, so it knows them even while it cannot reach the hub.

| When | What happens |
| :--- | :--- |
| 7 days before the licence ends | A banner, and an e-mail to every super admin (through the panel's mailer, when e-mail is set up). The hub e-mails the account too. |
| The licence ends without renewal | The plugin keeps running during the grace period (7 days by default); a banner gives the date it stops. |
| The grace period ends (or the panel cannot renew its lease in time, see [When the hub cannot be reached](#9-when-the-hub-cannot-be-reached)) | The panel backs up its own data (and every instance, when the plugin may change instances), **then switches the plugin off, keeping its data and settings**, restarts, and e-mails the super admins. If a backup failed, the e-mail says so; the plugin is switched off anyway. |
| The licence is renewed later | The next heartbeat brings the new dates; the plugin is switched back on by itself and the super admins are told. |

A **one-time** licence never ends; it shows as "Licensed for good". It still needs a lease from time to time, like
every paid plugin (see [When the hub cannot be reached](#9-when-the-hub-cannot-be-reached)).

Nothing is deleted when a licence ends. Turning the server's clock back does not extend a licence: the panel never
counts a time earlier than one it has already seen, nor earlier than the last lease it received.

---

## 7. Updating, switching off and uninstalling

| Action | Where | What happens |
| :--- | :--- | :--- |
| Update | **Installed**, **Update to vX** | The new version is downloaded and checked like a new plugin, replaces the old one, and the panel restarts. |
| Switch off | **Manage**, **Switch off** | The plugin's files and data stay; the panel restarts without it. Refused while another installed plugin needs it. |
| Switch on | **Manage**, **Switch on** | The panel restarts with it. Not possible for a plugin whose files were changed: install it again. |
| Uninstall | **Manage**, **Uninstall**, then type the plugin's id | A backup of the panel's data first (`/opt/odoo/backups/panel/`), then its files and its record are removed and the panel restarts. Refused while another installed plugin needs it. |

---

## 8. Logging out of the account

**Settings**, section **Marketplace**, **Log out of the account** unlinks this server from its app.sudoo.sh account
(the same as unlinking it on app.sudoo.sh, Servers). A confirmation lists what happens:

* **Paid plugins are removed.** Their licences for this server are revoked at once and their subscriptions end
  without a refund. The hub then sends the panel a signed command; the panel backs up its own data (and every
  instance, when one of those plugins may change instances), removes the paid plugins (their files and records; the
  plugins' data stays in the panel's backup), restarts and tells the hub it is done. The super admins are e-mailed.
* **The panel, free plugins and every instance keep running.**
* A server that is off when it is unlinked gets the command when it is back. Each command is carried out once; if
  the hub sends it again, the panel only confirms it again.

To use paid plugins again, link the server again and buy them again.

**A revoked key.** If the account owner revokes this server's key on app.sudoo.sh (for example after a copy of the
server was found), the hub refuses every request signed with it. The panel then makes a new identity (installation id
and key pair), registers it, and asks you to link it again; a banner says so.

---

## 9. When the hub cannot be reached

The panel keeps working without the hub:

* Instances, accounts, backups and every installed **free** plugin work as before.
* Each **paid** plugin keeps running until its `run_until`, which every lease gives: for an active licence, the
  lease's end (72 hours after the heartbeat) plus 96 hours, so about **7 days** after the last heartbeat that passed;
  for a licence in its grace period or cancelled, the lease's end; never after the licence's own end. Then the
  plugin is switched off the same way as at the end of a licence, and switched on again by the next heartbeat that
  passes. The time is measured from the lease's signed issue time, so changing the server's clock does not help.
* The Plugins page says that the marketplace cannot be reached; the catalogue and the purchases cannot be shown,
  the Installed tab still can. The panel tries again every 5 minutes.

The hub can also **refuse** the panel: when its core files differ from the released version
(`integrity_violation`), or when the installation is suspended. Every plugin is then switched off, and a banner
says why.

---

## 10. How the panel talks to the hub

| What | How |
| :--- | :--- |
| Identity | On first use the panel makes an installation id and an **Ed25519 key pair**. The private key is stored in the panel's database, encrypted with the vault key; it never leaves the server. |
| Hub keys | The panel starts from the hub's **root keys** (`HUB_PUBLIC_KEYS`, else the ones this release ships for hub.sudoo.sh; for another hub, while testing, the keys it lists the first time). It reads `GET /api/v1/keys` at every heartbeat: an `active` key is accepted, a `retiring` one until its end date, a `revoked` or `expired` one is dropped at once, and a new key is trusted only when the key before it **endorsed** it (signed it) and that key is trusted and not revoked. So a key rotation on the hub needs no panel update. |
| Signed requests | Every request is signed with the installation key over the method, path, installation id, time, a single-use nonce and the body's SHA-256. The hub refuses old, replayed or altered requests. |
| Signed answers | **Every answer is signed by the hub** (`Sudoo-Signature`), refusals and downloads included, over the request's method, path, installation id and nonce, the status, the time and the body's SHA-256. The panel refuses an answer without a valid signature from an accepted key, or more than 5 minutes from its clock: it counts as "the marketplace cannot be reached", and nothing in it is used. |
| Registration | Once per hub and identity: the panel registers its public key, its version, the hash of its core files and its **hardware fingerprint**. |
| Fingerprint | SHA-256 of the installation's public key, the host's machine id (`/etc/machine-id`, mounted read-only into the container at `/host/etc/machine-id`) and the MAC address of the interface with the default route. Sent at registration and in every heartbeat; the hub keeps only a keyed digest. A missing file is not an error (the part is left empty). If the panel's data is copied to another machine, the fingerprint differs: the hub **flags** the server, withholds its paid licences (they show as **Withheld**, and a banner explains), and e-mails the owner, who accepts the new machine on app.sudoo.sh (Servers) or revokes the key. |
| Heartbeat | Every **15 minutes**: the version, the **core hash** (SHA-256 over the panel's Python files), the fingerprint and the installed plugins with their versions, plus coarse figures for the owner's uptime records on app.sudoo.sh: CPU, memory and disk use (percent), how many instances exist and run, their Odoo versions and edition. Nothing about what instances contain, accounts or your data. |
| Lease | The hub answers with a lease signed by its key (a JWT, EdDSA), for this installation only, valid **72 hours**: the standing of each plugin (`free`, `licensed`, `grace`, `expired`, `unlicensed`, `blocked`, `unknown`), the licence dates of the paid ones with `run_until` and `perpetual`, the **commands** not acknowledged yet and the **flags**. The panel verifies it with an accepted key and keeps only verified values. |
| Commands | Each command is signed on its own and checked before anything is done; see [Logging out of the account](#8-logging-out-of-the-account). |

The heartbeat is also what lets the hub tell a released panel from a modified one: the core hash is compared with
the hash of the released version.

---

## 11. How a package is checked

Before anything is unpacked:

1. The package is downloaded with a signed request into a private folder.
2. Its **SHA-256** must equal the one the hub states.
3. The hub's **Ed25519 signature** over `sudoo-plugin-v1`, the plugin id, the version and that SHA-256 must verify
   with a hub key the panel accepts (active, or retiring before its end). A signature therefore binds the package to one plugin and one version: an old
   release cannot be passed off as an update, nor one plugin as another.
4. Its `manifest.json` must name the same plugin and version; this panel's version must be within its
   `min_sudoo_version` and `max_sudoo_version`, and its `sdk_version` must accept this panel's SDK version (0.1.0).
5. Every plugin it `requires` must be installed and switched on, in a matching version.
6. It must not need **other Python packages**. This version of the panel has no dependency installer, so packages
   that declare dependencies (in `pyproject.toml` or a `requirements*.txt`) are refused; publishers ship plugins
   that use only the Python standard library and what the panel already provides. The one exception is the plugin
   SDK (`sudoo-plugin-sdk`, which every plugin made with it declares): it is accepted when the panel has the SDK
   installed in a version the plugin accepts, and refused with "needs the Sudoo.sh plugin SDK" otherwise.
7. It must not contain compiled code (`.so`, `.pyd`, `.pyc` ...), links, special files, absolute paths or `..`,
   and must stay within 25 MB, 200 MB unpacked and 5,000 files (no archive bombs).
8. Its entry points must be in `sudoo.*` groups, must not take a name another plugin already uses, and its modules
   must not clash with the panel's own or with its libraries. Storage plugins cannot come from the marketplace (the
   installed plugins are recorded in storage).

A package that fails any check is deleted and nothing is installed.

---

## 12. Where plugins are kept, and what is protected

Installed plugins are unpacked into `/opt/odoo/manager/plugins/<id>/<version>/` (folders mode 700, files mode 600,
owned by root). The package file is deleted after unpacking. A hash of every unpacked file is recorded; at every
start, and every 10 minutes, the files are hashed again, and a plugin whose files changed is **not loaded**, is shown
as "Files changed" and the super admins are e-mailed. Installing it again repairs it.

What the panel guarantees:

* **No API returns a plugin's code or package.** The panel lists plugins (name, version, status, licence) and
  nothing else.
* The web container (`sudoo-web`) does not mount `/opt/odoo`, so it cannot read plugin files, and no web path serves
  them.
* Plugins run only from packages the hub signed, checked as above.

What it does **not** protect, said plainly:

* **An administrator with root on the server can read the files** in `/opt/odoo/manager/plugins/`. The panel cannot
  hide files from root. The protection of a plugin's code is that the panel never exposes it, and that the licence
  forbids copying it.
* A plugin runs inside the panel's process, with the panel's rights. The review on the marketplace, the permissions
  a plugin must declare, and the signature are what make that acceptable; install only plugins you need.

---

## 13. Settings and commands

| Setting | Default | Meaning |
| :--- | :--- | :--- |
| `MARKETPLACE` | `off` (until the marketplace opens) | `off`: the panel never contacts the hub. Installed free plugins keep working; paid ones stop at their `run_until`. Also on the Settings page. |
| `HUB_URL` | `https://hub.sudoo.sh` | The hub's address (`.env` only). A new address registers the panel with that hub. |
| `HUB_PUBLIC_KEYS` | empty | The hub's root public keys (`.env` only). Empty: the keys this release ships for hub.sudoo.sh. |

The compose file mounts the host's `/etc/machine-id` read-only at `/host/etc/machine-id` for the fingerprint. It
never creates that file: on a host without it, run `sudo systemd-machine-id-setup` once (or remove the mount; the
fingerprint then uses what the container sees, which may change when it is recreated).

See [Configuration](CONFIGURATION.md#marketplace). On the server:

```bash
docker exec sudoo-panel sudoo.sh marketplace            # the connection, the lease, the installed plugins
docker exec sudoo-panel sudoo.sh marketplace heartbeat  # send a heartbeat now
docker exec sudoo-panel sudoo.sh marketplace repin      # forget the trusted hub keys and start from the root keys
```

New hub keys are learnt by themselves through their endorsement. Use `repin` only when Sudoo.sh announces it (after
a key was revoked, a release ships the new root key): until then, anything signed with an unknown key is refused on
purpose.

The API behind the page is described in [Panel API](PANEL_API.md#plugins-and-the-marketplace).

---

## 14. Troubleshooting

| Message | What to do |
| :--- | :--- |
| The marketplace cannot be reached | Check that the server can open `https://hub.sudoo.sh` (firewall, DNS). The panel retries every 5 minutes; **Send a heartbeat now** under Settings, Marketplace tries at once. |
| The marketplace's answer was not accepted (not signed, 5 minutes, key) | The answer did not come signed from the hub: a proxy in between, a wrong `HUB_URL`, or the server's clock is off. Check the clock (NTP) first. |
| Link this panel to your Sudoo.sh account first | Make a code on app.sudoo.sh, Servers, Link a server, and paste it under Settings, Marketplace. |
| This account already has a server | An account links one server. Unlink the other one on app.sudoo.sh (or log out of the account on that panel) first. |
| This panel has no licence for this plugin yet | Buy it first, or wait for the payment to arrive. |
| Waiting for payment in the other tab, for long | Pay on the page that opened (**Open the payment page again** if you closed it). The page expires after 30 minutes. |
| This server is flagged / Withheld | It reported from another machine than the one it was registered on. The account owner accepts this machine on app.sudoo.sh, Servers (or revokes the key if it is a copy). |
| This server's key was revoked | The panel registered again with a new identity; link it again under Settings, Marketplace. |
| Your account has no e-mail address | Add one under **My account**: the purchase and the receipt name who asked. |
| Jobs are running | Wait until they finish: installing restarts the backend. |
| The package's signature is not valid / SHA-256 does not match | The download was changed on the way or is not from the marketplace. Nothing was installed; try again, and tell Sudoo.sh if it repeats. |
| Signed with a key this panel does not trust | The hub uses a key this panel does not trust and no trusted key endorsed it. Run `sudoo.sh marketplace repin` only if Sudoo.sh announced a new key. |
| This plugin needs other Python packages | Not supported yet; ask the publisher for a version without dependencies. |
| This plugin needs the Sudoo.sh plugin SDK | This panel does not have the SDK (or not a version the plugin accepts). Update Sudoo.sh, or ask the publisher. |
| Files changed | Someone or something changed the plugin's files on the server. Find out why, then install the plugin again. |
| The marketplace refuses this panel (integrity violation) | The panel's own files differ from the released version. Reinstall the released version with `install.sh`. |
