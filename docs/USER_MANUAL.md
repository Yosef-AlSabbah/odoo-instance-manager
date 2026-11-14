# User Manual

**Audience:** everyone who uses the Sudoo.sh panel in a browser: super admins, administrators, maintainers,
developers and viewers.
**Covers:** the first run, signing in, every page and button of the panel, roles, passwords, backups and restores,
settings, step by step.
**You need:** the panel's link and an account (or, on a new server, the setup code). Nothing has to be installed on
your computer.

---

## Contents

1. [First run and signing in](#1-first-run-and-signing-in)
2. [The Instances page](#2-the-instances-page)
3. [An instance's page](#3-an-instances-page)
4. [Creating an instance](#4-creating-an-instance)
5. [Keeping the code up to date](#5-keeping-the-code-up-to-date)
6. [Submodules](#6-submodules)
7. [GitHub access (private repositories)](#7-github-access-private-repositories)
8. [Accounts and roles](#8-accounts-and-roles)
9. [My account](#9-my-account)
10. [Backups and audit log](#10-backups-and-audit-log)
11. [Settings](#11-settings)
12. [Help pages and appearance](#12-help-pages-and-appearance)
13. [When something goes wrong](#13-when-something-goes-wrong)
14. [Questions and answers](#14-questions-and-answers)

Words used in this manual:

| Word | Meaning |
| :--- | :--- |
| **Instance** | One Odoo with its own database and its own link. |
| **Panel** | This website, where instances are managed. |
| **Repository** | The GitHub project that holds the custom modules of an instance. |
| **Branch** | A line of work inside a repository, for example `main` or `19.0`. |
| **Link** | The public https address of an instance, for example `https://river-stone-apple.trycloudflare.com`. |
| **Job** | One action on an instance (create, get latest code, restart...), with its steps and log. |

The panel only shows the pages and buttons your role may use ([section 8](#8-accounts-and-roles)). If something
described here is missing for you, your role does not include it.

---

## 1. First run and signing in

### The first run: Set up Sudoo.sh

A new server has no accounts. The first person to open the panel's link sees the **Set up Sudoo.sh** page and
creates the first account, which is a **Super admin**.

1. Ask the server administrator for the **setup code**. The installer prints it (it looks like `ABCD-EFGH-JKLM`);
   it can be shown again on the server with `docker exec sudoo-panel sudoo.sh setup-code`.
2. Open the panel's link and fill in:

   | Field | What to enter |
   | :--- | :--- |
   | **Setup code** | The code from the installer. |
   | **First name**, **Last name** | Your name. |
   | **E-mail** | Required. You sign in with it, and it can later receive sign-in codes. |
   | **Phone** | Optional. |
   | **Password**, **Password again** | 12 to 128 characters that follow the [password rules](#password-rules). A few unrelated words make a strong one. |

3. Click the button at the bottom. The account is created and you are signed in.

You do not choose a user name. The panel makes one from your e-mail address (`yousef.sabbah@example.com` becomes
`yousef.sabbah`; when it is taken, `yousef.sabbah-2`, `-3` and so on). It is the account's internal key: it appears
in small monospace letters under your name, in the audit log and in the API. You can also sign in with it.

The setup code works once: after the first account exists, the page no longer appears. After 5 wrong codes within
15 minutes, the address you use is blocked for 15 minutes.

### Signing in

1. Open the panel's link.
2. Enter your **e-mail address** in the **E-mail** field and your **password**, then click **Sign in**. Your user
   name also works in this field, for example for an older account that has no e-mail address.
3. If your account has a second factor, the **Enter your code** step follows:
   * **E-mail code**: a 6-digit code is sent to your e-mail address at once. **Send a new code** becomes available
     after 60 seconds.
   * **Authenticator app**: open the app and type the 6-digit code shown for Sudoo.sh.
   * When your account has both, switch between them with the buttons above the code.
   * Type the code (it is checked as soon as the sixth digit is in) or click **Verify and sign in**. **Back**
     returns to the e-mail address and password.

### Before anything else opens

Two things can be asked of you right after signing in. Until they are done, no other page opens.

| Situation | What you do |
| :--- | :--- |
| Your account is new, or an administrator set a new password for you | **Choose your password**: enter the password you were given, then your own new password twice. An administrator who typed your password can leave this step out. |
| The server requires a second factor for your role, and you have none | **Set up a second factor**: an authenticator app or an e-mail code ([section 9](#9-my-account)). |

By default super admins and administrators must use a second factor. A super admin can change this
(**Settings, Sign-in and security**).

### Good to know

* A wrong e-mail address and a wrong password give the same message: "Wrong e-mail address or password." The panel
  does not tell which of the two was wrong.
* After **5 wrong passwords** for the same account from the same place, or 20 from the same place, signing in is
  blocked for **15 minutes**. Wait, or ask an administrator to set a new password for you.
* You are signed out after **60 minutes without activity**, and after **12 hours** in any case. A super admin can
  change both times on the Settings page.
* **Sign out** (your name at the bottom of the sidebar, or **My account**) ends the session at once. Use it on
  shared computers.
* The panel's link can change when the server restarts. If the link you saved stops working, ask the administrator
  for the new one ([why links change](concepts/TUNNELING.md#5-why-the-link-changes)).

---

## 2. The Instances page

This is the first page after signing in. The sidebar on the left leads to the other pages:

| Sidebar | Pages | Shown to |
| :--- | :--- | :--- |
| Top | **Instances**, **New instance**, **Help** | everyone (New instance: roles that may create instances) |
| **Operations** | **Backups**, **GitHub access**, **Audit log** | administrators and super admins; GitHub access also to maintainers |
| **Administration** | **Settings**, **Accounts**, **API tokens** | Settings: super admins; Accounts and API tokens: administrators and super admins |
| Bottom | your name and role (opens **My account**), the theme button | everyone |

On a small screen the sidebar opens with the menu button at the top left.

**Server figures** (the four cards at the top). Each card shows the figure now and, inside it, a small line of the
last hour:

| Card | What it shows |
| :--- | :--- |
| Processor | How busy the server's processor is. |
| Memory | Memory in use on the server. |
| Disk | Disk space in use on the server. |
| Running | How many instances are running now. |

**Charts.** Below the cards, four charts show what the cards do not:

| Chart | What it shows |
| :--- | :--- |
| **Requests** | Requests per minute of all instances together over the last hour, with the errors (answers 500 to 599) as a second line. |
| **Instances** | A ring of the instances by state (**Online**, **Working**, **Paused**, **Switched off**), with the total in the middle. |
| **Response time** | How long Odoo takes to start answering, over the last hour: the slowest instance's 95th percentile (95% of its requests were faster) and the average. |
| **By instance** | Bars of the instances that use the most now. Switch between **CPU**, **Memory** and **Disk**. Click a bar to open that instance. |

**The list of instances.** Use **Search** to find an instance by name, and the filters **All**, **Online**,
**Paused** and **Working** (each with its count). Each instance has a card with:

* its name and status ([statuses](#statuses)),
* its Odoo version, edition (Community or Enterprise) and branch,
* the last commit, or, while a job runs, that job with its progress,
* processor, memory and requests per minute,
* **Open**, which opens Odoo in a new tab.

Click the card to open the instance's page.

The page updates by itself: new instances, status changes and job progress appear without reloading. When the
connection to the server is lost for a moment, a small **Reconnecting** notice shows until it is back.

---

## 3. An instance's page

### The header

At the top: the instance's name and status, its Odoo version, edition, branch and link. While a job runs, a line
below the header shows it with its progress; click it to follow the steps.

A warning appears when the instance's branch no longer exists on GitHub, or when its link has a problem.

### Buttons

| Button | What it does |
| :--- | :--- |
| **Open Odoo** | Opens the instance in a new tab. Sign in with the login on the **Access** tab (or ask someone who may see it). Not shown while the instance is paused, switched off or stopped. |
| **Start** | Shown when the instance is paused, switched off or stopped. Starts it now. |
| **Restart** | Shown while it runs. Stops and starts Odoo (about 30 seconds). Useful when Odoo behaves strangely. |
| **Get latest code** | Downloads the newest code of the branch from GitHub, upgrades the modules that changed and restarts. |
| **...** (menu) | The actions below. |

The menu:

| Action | What it does |
| :--- | :--- |
| **Update submodules** | Moves every submodule to the newest commit of its branch and restarts ([section 6](#6-submodules)). |
| **Upgrade modules** | Like **Upgrade** in Odoo's Apps menu. Enter technical names separated by commas, or `all`. |
| **Switch branch** | Moves the instance to another branch of the same repository, upgrades its modules and restarts. The database stays. |
| **Update Odoo and PostgreSQL images** | Downloads the newest build of the instance's Odoo version and PostgreSQL (same versions) and restarts with them. Until then the instance keeps the exact images it was created with. |
| **Pause** | Stops it to free memory now. It starts again on the next visit. |
| **Switch off** | Stops it completely. Visitors see that it is switched off, and it does not start until someone clicks **Start**. |
| **Delete** | Removes Odoo, its database and its files, after a backup. Type the instance's name to confirm. |

**Back up now** and **Restore the latest** are on the **Backups** card of the **Overview** tab
([The Backups card](#the-backups-card)).

**Changed outside the panel.** A red banner with this title means someone changed the instance's containers or
files on the server directly, not through the panel. It lists what differs. Usually the panel puts its own
configuration back by itself within a minute (you see a **Restore the panel's configuration** job in Activity) and
the banner goes; otherwise the banner has a button for it. Tell your administrator either way.

Each button and menu item is shown only to roles that may use it. While a job runs on the instance, the buttons
wait: one job per instance at a time.

### Statuses

| Status | Meaning | What to do |
| :--- | :--- | :--- |
| **Online** | Odoo answers. | Nothing. |
| **Starting** | The container runs but Odoo is not answering yet. | Wait up to a minute. If it stays, open the **Odoo log** tab. |
| **Working** | A job (update, restart, backup...) is running. Other actions wait their turn. | Wait; click the job line to follow it. |
| **Paused** | Stopped to save memory because nobody used it for some hours (6 by default). | Nothing: it starts by itself when someone opens its link, or click **Start**. |
| **Switched off** | Stopped on purpose. It does **not** start when someone opens it. | Someone allowed to do so clicks **Start**. |
| **Stopped** | Odoo stopped unexpectedly, often for lack of memory. | **Start**. If it happens again, check the **Odoo log** and pause other instances. |
| **Checking** | The panel has not measured the instance yet, for example just after the panel started. | Wait a few seconds. |

### Tabs

| Tab | Contents |
| :--- | :--- |
| **Overview** | Four cards with the processor, memory, requests per minute and response time of this instance, each with a small line of the last hour; one live chart with a **CPU / Memory / Requests / Response** switch; the **Backups** card; details such as the database, its size and how long it has been running. |
| **Activity** | Every job on this instance, newest first. Click one to open a panel with its steps, notes, the reason it failed (if it did) and the technical log, which follows live while the job runs. |
| **Code** | The repository and branch, the recent commits, and the submodules, with **Add submodule** and **Remove** ([section 6](#6-submodules)). |
| **Odoo log** | The latest lines Odoo wrote (100 to 3000), with **Refresh**. Lines with `ERROR` or `Traceback` usually explain a problem. |
| **Settings** | The automation switches and the lifetime ([section 5](#5-keeping-the-code-up-to-date)). Changes are saved at once. |
| **Access** | The Odoo sign-in: address, login, password, and the master password (for Odoo's database manager). Click **Show the passwords**; each viewing is recorded in the audit log. |

### The Backups card

The **Backups** card on the **Overview** tab holds the instance's backups.

| Part | What it does |
| :--- | :--- |
| **Back up now** | Saves the database and the files as an Odoo backup now. A running instance keeps running; a paused one stays paused. |
| **Restore the latest** | Puts back the newest backup taken by hand, daily or before a deletion. Greyed out when the instance has none. |
| **Restore another backup…** | Opens a list of every backup on the server, grouped by instance, with its Odoo version and date. Pick one and confirm to put it into this instance, even a backup of another instance. Backups of another Odoo version, or Enterprise backups on a Community instance, are greyed out with the reason. Shown to roles that may both restore and manage backups (administrators and super admins). |
| **Latest backup** | The date and time of that backup, its kind, its size and how long ago it was taken. |
| The list | Every backup of the instance, newest first, with when it was taken, its kind and its size. **Restore** puts back that backup; **Download** (the arrow) saves the zip, for roles that may manage backups. |

The kinds of backup are explained in [section 10](#10-backups-and-audit-log).

**Restoring.** Click **Restore the latest**, or **Restore** on a line of the list. The dialog shows the backup's date,
kind and size, and says that the database and its files go back to how they were then: changes made since are
replaced. Click **Restore** to confirm. The job:

1. saves the current state as a **Before a restore** backup, so the restore can be undone,
2. stops Odoo,
3. replaces the database and the files with those of the backup, and sets the instance's current link in the
   database again,
4. starts Odoo.

It takes about a minute or two. The instance is running afterwards, even if it was paused before.

**A backup of another instance.** With **Restore another backup…** you can put any instance's backup of the same Odoo
version into this one, for example to give a test instance a copy of the live data. The backup's database is loaded
under this instance's database name, and its files go with it. Because the data comes from another instance, the
job then neutralises it, the way Odoo.sh does for copies: outgoing mail servers and scheduled actions are switched
off (Odoo 16 and later use Odoo's own `neutralize` command, which also covers payment providers and other
integrations of installed apps), and the copy gets its own database identity. The job's notes say so. Switch mail
servers and scheduled actions back on in Odoo when you want them. The copied administrator (the first user, usually
`admin`) gets this instance's admin password, so the **Access** tab still works. The other instance's modules come
with its data: if this instance's repository does not have them, Odoo skips them (their screens are missing) until
you add them. A backup of the same instance is put back as it
was, without neutralising.

**Rollback.** After a restore, a banner at the top of the instance's page says when the instance was restored and
offers **Rollback to before the restore** until a given time (24 hours after the restore unless a super admin changed
`ROLLBACK_HOURS`). Click it and confirm to go back to the state just before the restore. The rollback saves the
current state first as a **Before a rollback** backup, kept as long, and never replaces the state it goes back to.
Once you have rolled back, the banner goes; to go back to that state again, restore the **Before a restore**
backup from the Backups card. After that time the **Before a restore** backup is removed and the banner goes. A second restore within that time
replaces it: Rollback always goes back to just before the last restore.

---

## 4. Creating an instance

Click **New instance** in the sidebar (roles that may create instances).

1. **GitHub repository**: paste the repository's address. On GitHub, open the repository, click the green **Code**
   button and copy the address, for example `https://github.com/acme-co/sales`. Leave it empty for a plain Odoo
   without custom modules.
2. The panel checks the repository while you type. The hint under the field says how many branches it found, or
   what is wrong.
3. **Branch**: pick the branch. The instance only ever takes code from this branch. When the branch is named like a
   version (`19.0`), the Odoo version follows it.
4. **Name**: leave it empty to use repository and branch. The hint shows the final name and the database name, for
   example "Will be **sales-main** · database `sales_main`".
5. Below the name, the **access report** shows one line for the repository and one for every submodule, each with
   a mark: green when the server can read it, red with the reason when it cannot. For a private repository, add a
   deploy key under **GitHub access** ([section 7](#7-github-access-private-repositories)); the report is checked
   again when you come back.
6. **Version**: the Odoo versions offered on this server.
7. **Edition**: **Community** (Odoo's free edition) or **Enterprise** (Enterprise apps and interface). Enterprise
   can be chosen only for the versions whose Enterprise add-ons are on the server.
8. **Options**:

   | Option | Effect |
   | :--- | :--- |
   | **Install the repository's modules** | Installs the repository's own modules (not those of submodules) after the database is created. |
   | **Load demo data** | Sample customers, products and orders, useful for presentations. |
   | **Get new code automatically** | New commits on the branch are applied by themselves ([section 5](#5-keeping-the-code-up-to-date)). |
   | **Pause when nobody uses it** | The instance pauses after some hours without visits, to free memory. |
   | **Lifetime** | Deleted that many days after creation (30 by default), with a backup first; or **Keep until deleted by hand**. |

9. **Start from a backup** (optional; administrators and super admins): switch it on and pick a backup from the
   list, grouped by instance. Only backups of the chosen Odoo version (and, for Enterprise backups, an Enterprise
   instance) are listed. The new instance starts with that backup's data and files instead of an empty database,
   loaded under its own database name. A backup of another instance is neutralised: no e-mail goes out and no
   scheduled actions run until you switch them back on in Odoo. **Install the repository's modules** then installs
   only the modules the backup does not have yet; **Load demo data** does not apply. The backup's administrator
   (the first user, usually `admin`) gets the instance's admin password, so the **Access** tab works for it.
10. Click **Create instance**.

If the server has a limit on the number of instances, or a waiting time between two new instances, a warning above
the form says so before you start, and the numbers under the button show how many exist.

The new instance's page opens and shows each step: preparing, downloading the code, downloading Odoo (the first time
for a version takes a few minutes), starting the database, creating the Odoo database, installing modules,
creating the public link, starting Odoo. A new instance usually takes **2 to 4 minutes**. You can leave the page:
the work continues and is listed under **Activity**.

When it is ready, the link is in the header and the login is on the **Access** tab.

If a step fails, the job explains what went wrong in plain words, with the technical log below. Everything created
so far is removed, so you can simply try again.

---

## 5. Keeping the code up to date

**Automatically.** When **Get new code automatically** is on, the panel checks GitHub for new commits on the
instance's branch (every 2 minutes by default, or at once when the server receives GitHub's webhooks). When there
are new commits, it downloads them, upgrades the modules whose files changed and restarts Odoo. The job appears in
**Activity** as "Get latest code", started automatically.

**By hand.** Click **Get latest code**. Use it right after a developer says "I pushed".

**Upgrade modules.** A new field, view or data file needs the module to be upgraded in Odoo. This happens after an
update when **Upgrade changed modules** is on. Otherwise use **Upgrade modules** in the menu, with the technical
names separated by commas, or `all`.

**Switch branch.** Moves the instance to another branch of its repository (menu, **Switch branch**). Use it when the
branch was merged and deleted on GitHub, or to show other work in the same database.

**Settings tab** of an instance:

| Setting | Effect |
| :--- | :--- |
| **Get new code automatically** | Off: the instance only changes when someone clicks **Get latest code**. Use it for an instance that must not change before a presentation. |
| **Upgrade changed modules** | On: after an update, the modules whose files changed are upgraded in Odoo. Off: Odoo only restarts. |
| **Pause when idle** | Off: the instance never pauses by itself (it keeps using memory). |
| **Lifetime** | The number of days after creation when the instance is deleted, after a backup; or **Keep until deleted by hand**. |

Changes on this tab are saved at once.

---

## 6. Submodules

A submodule is another repository included inside the instance's repository, for example OCA's `web` modules in a
folder `oca/web`. See [Git submodules](concepts/GIT_SUBMODULES.md) for how they work.

The **Code** tab lists the submodules with their folder, address and current version.

| Action | Where | What it does |
| :--- | :--- | :--- |
| **Update submodules** | menu at the top | Moves every submodule to the newest commit of its branch and restarts. |
| **Add submodule** | Code tab | Adds a repository as a submodule and saves the change to GitHub. |
| **Remove** | next to a submodule | Removes it from the instance and from GitHub. Uninstall its modules in Odoo first. |

Adding a submodule:

1. Click **Add submodule**.
2. **Repository**, for example `https://github.com/OCA/web`.
3. **Folder** (optional, for example `oca/web`; empty: the repository's name) and **Branch**. For OCA repositories
   use the branch that matches the Odoo version, for example `19.0`.
4. Confirm. The panel first checks that it can read the repository.

Adding and removing change the repository on GitHub, so the server's key for the main repository must be allowed
to write ("Allow write access" ticked on GitHub). If it is not, GitHub refuses, the panel undoes the change on the
server and tells you so: the server and GitHub never disagree.

---

## 7. GitHub access (private repositories)

Public repositories need nothing. Every **private** repository, including every private submodule, needs a
**deploy key**: a key that lets the server read that one repository and nothing else. See
[Deploy keys](concepts/DEPLOY_KEYS.md) for how they work.

You need **admin rights on the repository on GitHub** to add a key. If you do not have them, send the key to
someone who does.

1. In the panel, open **GitHub access** (sidebar, Operations) and click **Add a repository**.
2. Enter the repository (`https://github.com/owner/repository` or `owner/repository`) and click **Create key**.
3. The panel shows the public key. Copy it, then click **Open GitHub** (the repository's **Settings, Deploy keys,
   Add deploy key** page).
4. On GitHub:
   * **Title**: `Sudoo.sh`
   * **Key**: paste.
   * **Allow write access**: leave unticked, unless submodules of this repository will be added or removed from
     the panel.
   * Click **Add key**.
5. Back in the panel, click **Done**. On the **New instance** page the repository's line now has a green mark.

Only the public part of the key leaves the server; the private key is stored encrypted.

The **GitHub access** page lists all keys with their repository and creation date. **Delete** removes the server's
key; also remove it on GitHub (repository Settings, Deploy keys). One key per repository is shared by every
instance that uses that repository.

---

## 8. Accounts and roles

### Roles

Every account has one role. The role decides which pages, buttons and menu items the account sees.

| What | Super admin | Administrator | Maintainer | Developer | Viewer |
| :--- | :---: | :---: | :---: | :---: | :---: |
| See instances, their activity, figures and Odoo log | yes | yes | yes | yes | yes |
| Read the Help pages; change own profile, password and second factors | yes | yes | yes | yes | yes |
| Get latest code, update submodules, add a submodule | yes | yes | yes | yes | no |
| Restart, start | yes | yes | yes | yes | no |
| Create instances | yes | yes | yes | no | no |
| Pause, switch off, upgrade modules, switch branch, back up now, remove a submodule | yes | yes | yes | no | no |
| Restore a backup of an instance (replaces its database and files) | yes | yes | yes | no | no |
| Change an instance's settings tab (automation, lifetime) | yes | yes | yes | no | no |
| See the Odoo passwords (Access tab) | yes | yes | yes | no | no |
| GitHub access (deploy keys) | yes | yes | yes | no | no |
| Delete instances | yes | yes | no | no | no |
| Backups page (download, delete) | yes | yes | no | no | no |
| Accounts, API tokens, audit log | yes | yes | no | no | no |
| Create, change and delete super admins | yes | no | no | no | no |
| Settings, restart the panel | yes | no | no | no | no |

API tokens act with a role too: a **write** token as an Administrator, a **read** token as a Viewer.

When you try something your role does not allow, the panel says which permission is missing. Ask an administrator.

Accounts from an earlier version of the panel were renamed automatically: "administrator" became **Super admin**
and "sync operator" became **Developer**.

### The Accounts page

**Accounts** (sidebar, Administration) lists every account with its name, e-mail address (or user name, when it
has none), role, whether it has a second factor and its last sign-in. Your own account is marked **(you)**, and
**new password pending** shows on accounts that must still choose their own password.

| Action | What happens |
| :--- | :--- |
| **New account** | Enter first name, last name, **e-mail** (required: the person signs in with it, and no other account may use it), phone (optional) and a **role**, then choose the password (below). The user name is made from the e-mail address. |
| **Edit** (row menu) | Change the first and last name, the e-mail address, the phone and the role. |
| **Set a new password** (row menu) | Choose a new password the same way as for a new account. The account's current sessions end. |
| **Remove second factors** (row menu) | For a person who lost their phone or mailbox. They sign in with the password only, and set up a new second factor if one is required. |
| **Delete** (row menu) | The account is removed and signed out at once. |

**The password of a new account**, and **Set a new password**, offer two choices:

| Choice | What happens |
| :--- | :--- |
| **Generate** | The panel makes a random password and shows it **once**. Copy it and give it to the person through a safe channel. At the first sign-in they must choose their own. |
| **Type a password** | Type it twice. It is checked as you type against the [password rules](#password-rules), and a meter of four bars shows its strength: **Acceptable**, **Good**, **Strong**, **Very strong**. **Suggest a strong one** fills in a random password with a copy button. The switch **Ask them to choose their own password when they first sign in** is on by default; turn it off only when the person keeps the password you typed. |

In both cases the password is shown once after you click **Create** or **Set password**.

Rules:

* Only a super admin can create, change or delete a super admin. A super admin can edit other super admins.
* You can edit your own account here: name, e-mail, phone and role. Its menu holds only **Edit**; to change your
  password or second factors use **My account**, and you cannot delete your own account.
* Changing your own role asks for confirmation and signs you out; you sign in again with the new role. When the role
  of another account changes, that account is signed out too.
* There is always at least one super admin: the last one cannot be given another role or be deleted.
* Two accounts cannot share an e-mail address.

Passwords are never stored by the panel, only checked: see
[Passwords and encryption](concepts/PASSWORDS_AND_ENCRYPTION.md).

### API tokens

**API tokens** (sidebar, Administration) let other systems, such as a CI pipeline, create and manage instances
through the panel's API. Click **New token**, give it a name and a scope (**read**, or **write**); copy the token
and the signing secret, shown once, into the other system. The list shows when each token was last used.
**Revoke** stops a token at once. See [Panel API](PANEL_API.md).

---

## 9. My account

Click your name at the bottom of the sidebar.

**Profile.** First name, last name, e-mail and phone. Click **Save**. While your e-mail address receives your
sign-in codes it is locked here; to change it, remove the e-mail code and set it up again with the new address.

**Password.** Enter your current password and the new one twice, then click **Change password**. The new password
is checked as you type against the [password rules](#password-rules), and a meter of four bars shows its strength
(**Acceptable**, **Good**, **Strong**, **Very strong**). Changing your password signs out your other sessions.

**Second factor.** A second factor asks for a 6-digit code after the password, so a stolen password alone is not
enough.

| Factor | Setting it up |
| :--- | :--- |
| **Authenticator app** | Click **Set up**, scan the QR code with an app such as Google Authenticator, Microsoft Authenticator or 1Password, and type the code it shows. |
| **E-mail code** | Click **Set up**, check the address, click **Send a code**, and type the code from the e-mail. Only offered when the server can send e-mail. |

**Remove** turns a factor off; type your password to confirm. Your other sessions end. If your role requires a
second factor, keep at least one.

### Password rules

The same rules apply everywhere a password is chosen: the first run, a new account, **Set a new password** and
**My account**. They follow the NIST guidelines for passwords (SP 800-63B): length counts, forced mixes of
characters do not.

| Rule | Details |
| :--- | :--- |
| Length | 12 to 128 characters. |
| Characters | Any, including spaces. You do not need capitals, digits or symbols. |
| Common passwords | Refused when it contains a common password or word, such as `password`, `qwerty`, `admin`, `odoo`, `sudoo` or `welcome`. |
| Sequences | Refused when it contains five characters in a row of the alphabet, the digits or a keyboard row, in either direction, such as `abcde`, `12345`, `54321`, `qwerty`, `asdfg` or `zxcvb`. |
| Repeats | Refused when one character appears four times in a row, such as `aaaa`. |
| Variety | At least 6 different characters. |
| Personal details | Refused when it contains your first name, last name, user name or the part of your e-mail address before the `@` (each counted when 3 characters or longer). |

Pasting a password and using a password manager both work. A short sentence is the easiest kind of password to
remember and the hardest to guess, for example `green tea at 7 on the balcony`.

---

## 10. Backups and audit log

### Backups

**Backups** (sidebar, Operations) lists every backup: instance, database, **Kind**, when it was taken and its
size. An instance's own backups are also on the **Backups** card of its **Overview** tab
([The Backups card](#the-backups-card)).

| Kind | When it is taken | How long it is kept |
| :--- | :--- | :--- |
| **By hand** | **Back up now** on an instance's page. | Until someone deletes it. |
| **Daily** | Once a day, for each instance that was used since its last daily backup (below). | Only the latest per instance: a new daily backup replaces the previous one. Removed when the instance is deleted. |
| **Before deletion** | Before every deletion, automatic or by hand. If the backup fails, the instance is not deleted. | Until someone deletes it. |
| **Before a restore** | At the start of every restore: the state just before it, offered as **Rollback**. | Only the latest per instance, for 24 hours (`ROLLBACK_HOURS`). Removed when the instance is deleted. |
| **Before a rollback** | At the start of every rollback: the state just before it, so a rollback can be undone by hand. | Only the latest per instance, for 24 hours (`ROLLBACK_HOURS`). Removed when the instance is deleted. |

**Daily backups.** Every day at the time set under **Settings, Backups** (00:00 UTC by default), the panel backs up
each instance that was used since its last daily backup. An instance counts as used when someone opened it through
its link, or when it was started or restarted. An instance nobody used gets no new daily backup, so its last one
stays. A running instance keeps running during the backup, and a paused one stays paused. If the panel was not
running at that time, the backups start as soon as it is back. When an instance is deleted, its daily backup goes
with it: the backup taken before the deletion is newer and is kept.

Backups taken by hand and before deletions are kept until someone deletes them, so look at the list from time to
time; the disk usage is on the Instances page.

What a backup contains: one zip file in Odoo's own backup format, with

| Part | Contents |
| :--- | :--- |
| `dump.sql` | The whole database. |
| `filestore/` | The attachments and images that Odoo keeps outside the database. |
| `manifest.json` | The database name, the Odoo version and (backups of this version of Sudoo.sh on) the edition. |

**Download** saves the zip. **Delete** removes a backup you no longer need.

**Restoring an instance.** To put an instance back to an earlier state, use **Restore the latest** or **Restore**
on its **Backups** card ([Restoring](#the-backups-card)). The current state is saved first as a **Before a
restore** backup, and the instance offers **Rollback** for a while. **Restore another backup…** puts a backup of
another instance of the same Odoo version into it.

**A new instance from a backup.** On the **New instance** page, switch on **Start from a backup** and pick one of
the backups of the chosen Odoo version: the instance starts with that data instead of an empty database
([section 4](#4-creating-an-instance)).

**Restoring into another Odoo.** The zip also works in any Odoo of the same version, for example to make a copy:

1. Open an Odoo of the **same version** (an instance's link, or any other Odoo) at `/web/database/manager`.
2. Click **Restore Database**.
3. Enter the master password (on the instance's **Access** tab), choose the zip file and a database name.
4. Say whether the database was **moved** (it replaces the original) or is a **copy** (a second database next to
   the original), then confirm.

Restoring brings back both the data and the attachments, because both are in the zip.

### Audit log

**Audit log** (sidebar, Operations) lists what happened, newest first: sign-ins (also failed ones), refused actions,
every job on an instance, viewing an instance's passwords, account, key, token and settings changes. Each line shows
when, the account, what happened, the instance and the address it came from. Use **Search** to find entries,
**Refused only** to see only what was not allowed, and **Show older entries** to go further back.

---

## 11. Settings

Super admins only. **Settings** (sidebar, Administration) shows every setting of the panel that can be changed in
the browser, in groups:

| Group | What it holds |
| :--- | :--- |
| **Sign-in and security** | Who must use a second factor (none, administrators, everyone), and how long a session lasts. |
| **E-mail** | The mailbox that sends sign-in codes, with **Send a test**. |
| **Limits** | Requests per minute, how many instances in total and per person, and how often a new one can be created. 0 turns a limit off. |
| **New instances** | What a new instance starts with: pause when idle and after how many hours, automatic updates, upgrades, lifetime, Odoo login. |
| **Backups** | Whether daily backups are taken, at what time (`HH:MM`, 24-hour clock) and in which time zone (for example `Africa/Cairo`; UTC by default). Changes apply at once. |
| **Odoo versions and images** | Which versions are offered and where Odoo and PostgreSQL come from. |
| **Enterprise add-ons** | Where the Enterprise add-ons of each version are. |
| **Code updates and monitoring** | How often GitHub is checked, the webhook secret, how often figures are measured. |
| **Contact and appearance** | Who people are told to contact, and the accent colour of the panel and its e-mails. |
| **Plugins** | Which plugin does each job (mail, second factors, update triggers, Enterprise source, sign-in, rate limits). |
| **Server** | Read only: folders, ports and how the panel is reached. These stay in the server's `.env`. |

How changes apply:

* **At once.** Almost every change applies as soon as you save it. It is kept on top of the server's `.env` file.
* **Use .env** next to a changed setting brings back the value from `.env`.
* **Passwords** (mail password, Odoo admin password, webhook secret) are write-only: the page shows whether one is
  set, never the value. They are stored encrypted.
* **Plugins** apply after **Restart the panel** (in the Plugins group; the button is highlighted when a restart is
  waiting). The restart stops only the panel's backend for a few seconds; instances keep running. It is refused
  while jobs run.
* **Server** settings can only be changed by the server administrator, in `.env` on the server.

**Send a test** (E-mail group) sends a test message with the saved settings to an address you enter. If it fails,
the message says why; for Gmail, the password must be an app password
([Administrator guide: E-mail](ADMIN_GUIDE.md#6-e-mail)).

Every setting is described in [Configuration](CONFIGURATION.md).

---

## 12. Help pages and appearance

**Help** (sidebar) shows this documentation inside the panel: the same pages as in the project's `docs` folder,
with a table of contents and an **On this page** list of the current page's sections. Links between the pages work
as in the repository.

**Theme.** The button at the bottom of the sidebar switches between **System** (follows your computer's setting),
**Light** and **Dark**. The choice is kept in your browser. The accent colour is chosen by a super admin
(**Settings, Contact and appearance**).

---

## 13. When something goes wrong

1. Read the message: the panel explains failures in plain words.
2. Open the job in the instance's **Activity** tab to see which step failed, the reason and the technical log.
3. Try **Restart** if Odoo behaves strangely, and look at the **Odoo log** tab if it does not start.
4. If a button is missing or an action is refused, your role may not include it ([section 8](#8-accounts-and-roles)).
5. If it is still not solved, contact the administrator named on the sign-in page, and say which instance, what you
   did and what the message said.

Common messages are listed in the [Administrator guide's troubleshooting table](ADMIN_GUIDE.md#13-troubleshooting).

---

## 14. Questions and answers

**Do the people I show an instance to need an account?**
No. They only need the instance's link and the Odoo login. Panel accounts are only for people who manage instances.

**Can two instances be open in the same browser at the same time?**
Yes. Each instance has its own link, so each has its own Odoo sign-in.

**The instance shows "Starting up". Is it broken?**
No. It was paused because nobody used it for some hours. The page opens Odoo by itself after 20 to 60 seconds.

**I pushed to GitHub but the instance does not show my change.**
Wait 2 minutes or click **Get latest code**. If the change is a new field or view, the module must be upgraded:
check that **Upgrade changed modules** is on (Settings tab), or use **Upgrade modules**.

**The page says the branch no longer exists on GitHub.**
The branch was deleted on GitHub, usually after its pull request was merged, so there is nothing left to update
from. Use **Switch branch** in the menu and pick the branch the instance should follow now, usually `main`. The
database and its data stay as they are.

**I lost my phone with the authenticator app.**
Ask an administrator to use **Remove second factors** on your account. Then sign in with your password and set up a
new one.

**I forgot my password.**
Ask an administrator to use **Set a new password** on your account. You get a new password once and usually choose
your own at the next sign-in.

**What do I type in the E-mail field when I sign in?**
Your e-mail address. Your user name works too, for example on an older account without an e-mail address.

**Why is my password refused?**
The message says which [password rule](#password-rules) it breaks. Most often it contains a common word, a sequence
such as `12345`, or your name. A short sentence of unrelated words is accepted and easy to remember.

**Does a backup include the attachments?**
Yes. The zip holds the database (`dump.sql`), the filestore with the attachments, and a manifest
([section 10](#10-backups-and-audit-log)).

**When are backups taken?**
Once a day for every instance that was used since its last daily backup (at 00:00 UTC unless a super admin changed
it), before every deletion, at the start of every restore, and whenever someone clicks **Back up now**
([section 10](#10-backups-and-audit-log)).

**How do I restore an instance?**
Open the instance, **Overview** tab, **Backups** card. Click **Restore the latest**, or **Restore** next to an older
backup, and confirm. The current state is saved first as a **Before a restore** backup, so you can go back. It takes
a minute or two ([The Backups card](#the-backups-card)).

**I restored the wrong backup. Can I undo it?**
Yes, for 24 hours (unless your administrator changed it): click **Rollback to before the restore** in the banner at
the top of the instance's page. It puts back the state just before the last restore.

**Can I copy one instance's data into another?**
Yes, if both run the same Odoo version: on the target instance's **Backups** card click **Restore another
backup…**, or start a new instance from the backup on the **New instance** page. The copy is neutralised: it sends
no e-mail and runs no scheduled actions until you switch them back on. Administrators and super admins can do this.

**Can another system send webhooks to an instance, or call its API?**
Yes, through the instance's link. See [API and webhooks](API.md). Remember the link can change after a server
restart.

**Is my data safe in an instance?**
Instances are for showing and testing Odoo. Anyone with the link and the Odoo login can sign in. Do not put real
customer data in them.
