# Contributing to Sudoo.sh

Thank you for taking the time to help. This guide explains how to report problems, suggest changes and send code so that your work can be reviewed and merged quickly.

## Before you start

- Read the [README](README.md) and the [Architecture](docs/ARCHITECTURE.md) document: they explain what the panel does and why it is built the way it is.
- Read the [licence terms for contributions](#licence-of-contributions) below. Pull requests can only be merged when you agree to them.
- Security problems are **never** reported in a public issue. Follow [SECURITY.md](SECURITY.md) instead.
- Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

| You want to | Do this |
|---|---|
| Report a bug | Open an issue with the **Bug report** form. |
| Suggest a feature or a change of behaviour | Open an issue with the **Feature request** form first, and wait for a reply before writing code. |
| Ask a question | See [SUPPORT.md](SUPPORT.md). |
| Fix a typo or a small documentation mistake | Open a pull request directly. |
| Fix a bug or build a feature | Comment on the issue so nobody else starts the same work, then open a pull request. |

Large changes that were not discussed in an issue first may be declined, even when they are well written, if they do not fit the project's direction.

## Development setup

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) (it also installs the right Python),
[Node.js](https://nodejs.org/) 22.22 or later for the web app and, to run the panel itself, a Linux machine with
Docker. A disposable virtual machine or a spare server is the safest
place to run it: the panel manages Docker containers on the host.

```bash
git clone https://github.com/Sudoo-sh/sudoo.sh.git
cd sudoo.sh
uv sync                        # creates .venv with the project, its dependencies and the development tools
uv run pre-commit install      # runs the checks below on every commit
uv run pytest                  # the tests
cd web && npm ci               # the web app's packages
npm run dev                    # the web app with live reload on :5173, using a backend on 127.0.0.1:9002
```

The web app needs a running backend: on a server through an SSH tunnel
(`ssh -L 9002:127.0.0.1:9002 -L 9001:127.0.0.1:9001 <server>`), or locally with `uv run sudoo.sh serve` and the
settings of your choice. How the interface is built and how to change its look: [docs/DESIGN.md](docs/DESIGN.md).

To try a change on a server, build and start the two images from your working copy (README, "From source"):
`sudo docker compose build && sudo docker compose up -d manager web`. Only `sudoo-panel` and `sudoo-web` are
replaced; instances, accounts, keys and settings are kept. Settings are described in
[docs/CONFIGURATION.md](docs/CONFIGURATION.md) and the template [.env.example](.env.example).

### Checks to run before you push

Every commit runs them through pre-commit, and every pull request runs them again in
[CI](.github/workflows/ci.yml), together with a Docker image build. A pull request cannot be merged while they fail.

```bash
uv run pre-commit run --all-files   # black, ruff, mypy, shellcheck, uv.lock, whitespace, private keys
uv run pytest                       # tests
cd web && npm run build             # web app: TypeScript check and production build
```

| Tool | What it checks | Settings |
| :--- | :--- | :--- |
| [black](https://black.readthedocs.io/) | Formatting (line length 120) | `pyproject.toml` |
| [ruff](https://docs.astral.sh/ruff/) | Lint and import order | `pyproject.toml` |
| [mypy](https://mypy.readthedocs.io/) | Type hints: every function is annotated | `pyproject.toml` |
| [pytest](https://docs.pytest.org/) | Behaviour | `tests/` |
| [TypeScript](https://www.typescriptlang.org/) (strict) and [Vite](https://vite.dev/) | The web app's types and build | `web/tsconfig.json`, `web/vite.config.ts` |
| [pre-commit](https://pre-commit.com/) | Runs all of the above on every commit | `.pre-commit-config.yaml` |

Dependencies are managed with uv: `uv add <package>` (or `uv add --dev <package>`) updates `pyproject.toml` and
`uv.lock` together. Commit both.

Then test the behaviour you changed on a real server through the public links, the way users reach the panel. The
[Testing](README.md#testing) section lists what is normally checked.

## Rules of the code

These rules keep the panel small, safe and easy to review. Pull requests that break them will be asked to change.

1. **One module per responsibility.** Each module starts with a docstring that says what it owns. Put new behaviour in the module that owns it, or in a new module with a clear name.
2. **`web/` only receives requests, checks them and calls other modules.** The real work (operations, git, Docker) lives outside `web/`.
3. **No shell.** Every external command is a list of arguments run through `core/shell.py` or `core/jobs.py`. Never use `shell=True`, `os.system` or string-built commands.
4. **Every value from outside goes through `web/validation.py`.** Add an allow-list rule there for any new input.
5. **One way to do each thing, no fallbacks.** When something fails there must be one path to look at.
6. **The web app only uses `/api/v1`**, takes its look only from the design tokens, and follows the motion rules in [docs/DESIGN.md](docs/DESIGN.md); no inline scripts, so the strict Content-Security-Policy keeps working.
7. **Nothing forced on every server.** Behaviour that can differ between servers is a setting in `config.py` or a plugin (see [docs/PLUGINS.md](docs/PLUGINS.md)), never a fixed choice. New dependencies are discussed in an issue first and added with `uv add` or `npm install` (commit the lock file).
8. **Secrets stay encrypted.** Anything the panel must read back goes through `core/vault.py`; passwords are only ever hashed.
9. **Explain failures in plain language.** When you add an error, add a hint for it in `core/hints.py`.
10. **Check a permission, never a role.** New endpoints and actions name the permission they need (`roles.py`, `@require(...)`).
11. **Document what you change.** Update the relevant file under `docs/` in the same pull request, since the same documents are shown inside the panel.

Style: black formats the code and ruff checks it; add type hints to every function (mypy checks them). Use clear names, and comments that explain *why*, not *what*.

## Commits and pull requests

1. Fork the repository and create a branch from `main` with a short descriptive name, for example `fix/backup-filestore-size` or `feat/instance-labels`.
2. Keep each pull request focused on one change. Several small pull requests are reviewed faster than one large one.
3. Write commit messages in the imperative mood, with a short first line (about 72 characters at most), for example `Retry the tunnel when Cloudflare returns 1033`. Add a body explaining the reason when it is not obvious.
4. Sign off every commit (`git commit -s`). The sign-off line certifies the [Developer Certificate of Origin](https://developercertificate.org/): that you wrote the change or otherwise have the right to submit it.
5. Open the pull request against `main` and fill in the template. Link the issue it closes (`Closes #123`).
6. Make sure the automatic checks pass. A maintainer will review; please answer review comments by pushing new commits to the same branch.
7. Pull requests are merged by a maintainer, usually with a squash merge.

Add a line under **Unreleased** in [CHANGELOG.md](CHANGELOG.md) for any change users or administrators will notice.

## Licence of contributions

This project is published under the [PolyForm Noncommercial License 1.0.0](LICENSE.md), and the author also offers separate commercial licences. To keep both possible, every contribution has to be licensed in a way that allows it.

By opening a pull request you confirm that:

1. You have the right to submit the contribution (it is your own work, or you have permission to submit it), as certified by your `Signed-off-by` line.
2. You license your contribution to the public under the PolyForm Noncommercial License 1.0.0, the same licence as the project.
3. You also grant Yousef M. Y. Al Sabbah, the project's author, a perpetual, worldwide, non-exclusive, royalty-free, irrevocable licence to use, copy, modify, distribute and sublicense your contribution as part of the project under any licence terms, including commercial licences.
4. You keep the copyright in your contribution.

If you cannot agree to these terms, please open an issue to describe the change instead of sending code.

## Never commit

- `.env` files, passwords, deploy keys, the vault key or any other secret.
- Odoo Enterprise code. This repository contains none and must stay that way; see the README.
- Database dumps, backups or files taken from a real instance.

If you commit a secret by mistake, tell the maintainer privately at once (see [SECURITY.md](SECURITY.md)): removing it from a later commit is not enough.
