# Security Policy

The panel manages Docker on its server and stores deploy keys and Odoo master passwords, so security problems are taken seriously. Thank you for reporting them responsibly.

## Supported versions

Only the latest release receives security fixes. `sudo sudoo-install update` updates a server to it. How the release
images and files are signed, and how to check them: [docs/SECURITY.md](docs/SECURITY.md#12-releases-and-signatures).

## Reporting a vulnerability

**Do not open a public issue, discussion or pull request for a security problem.**

Report it privately through GitHub:

1. Go to the repository's **Security** tab.
2. Choose **Report a vulnerability**.
3. Describe the problem, the steps to reproduce it, what an attacker could do with it, and the commit you tested.

Please do not include real passwords, keys or links to instances that hold other people's data. If you need to share a proof of concept, use an instance you created yourself.

## What happens next

| When | What |
|---|---|
| Within 3 working days | Your report is acknowledged. |
| Within 10 working days | You receive an assessment: accepted, needs more information, or not a vulnerability. |
| When a fix is ready | It is published, the advisory is made public, and you are credited unless you prefer not to be. |

Please give a reasonable time to fix the problem before you talk about it publicly.

## Scope

In scope: the panel, its gateway, the release images and the installer (`sudoo-install.sh`), and the way they store secrets and run commands.

Out of scope, because they are documented on purpose in [docs/SECURITY.md](docs/SECURITY.md) and the README's *Known Limitations*:

- Odoo instances open with the login `admin` / `admin`; they are for demonstrations, not real data.
- Cloudflare quick-tunnel links are public to anyone who has them and change on restart.
- The vault key is on the same server as the secrets it protects.
- Problems in Odoo itself, Docker, PostgreSQL or Cloudflare. Please report those to their own projects.

The full description of how the panel is protected, and what is deliberately not protected, is in [docs/SECURITY.md](docs/SECURITY.md).
