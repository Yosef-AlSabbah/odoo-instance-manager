"""The documentation inside the panel: the repository's README.md and docs/**/*.md, the same files as on GitHub.

The image build copies the Markdown files into the image (settings.docs_dir), so the panel always shows the
documentation of the version that is running. The web app shows them on its Help pages (/help/<path>), with the
HTML rendered here (GET /api/v1/docs/<path>, web/v1/docs.py). Pages are addressed by their path in the repository:

    /help/docs/README.md               the documentation index
    /help/README.md                    the project overview
    /help/docs/concepts/TUNNELING.md   a concept explained with examples

Links between Markdown files are rewritten to /help/ addresses, and the diagrams (docs/images/*.svg, built by
docs/diagrams/build.py) to /docs/ addresses served by the backend, so the same files read correctly on GitHub and in
the panel. Only files found at start-up can be shown: a path is looked up in that list, never opened directly.
"""

from __future__ import annotations

import html
import posixpath
import re
from typing import Any

import markdown
from flask import Blueprint, abort, redirect, send_file
from flask.typing import ResponseReturnValue
from werkzeug.wrappers import Response as WerkzeugResponse

from sudoo.config import settings

blueprint = Blueprint("docs", __name__)

INDEX = "docs/README.md"
SECTIONS = (  # sidebar: (title, path prefixes or exact paths)
    ("Start here", ("README.md", "docs/README.md", "docs/USER_MANUAL.md")),
    ("Guides", ("docs/ADMIN_GUIDE.md", "docs/PLUGINS.md", "docs/PANEL_API.md", "docs/API.md")),
    ("Reference", ("docs/CONFIGURATION.md", "docs/ARCHITECTURE.md", "docs/SECURITY.md", "docs/DESIGN.md")),
    ("Concepts", ("docs/concepts/",)),
)
_LINK = re.compile(r'(href|src|srcset)="(?![a-z]+:|/|#)([^"#]+\.(?:md|svg))(#[^"]*)?"')


def _title(text: str, path: str) -> str:
    if path == "README.md":
        return "Project overview"
    match = re.search(r"^# (.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else path


def _load() -> dict[str, tuple[str, str]]:
    """{path: (title, text)} of every Markdown file shipped with the panel."""
    if not settings.docs_dir.exists():
        return {}
    pages: dict[str, tuple[str, str]] = {}
    for file in sorted(settings.docs_dir.rglob("*.md")):
        path = file.relative_to(settings.docs_dir).as_posix()
        text = file.read_text()
        pages[path] = (_title(text, path), text)
    return pages


PAGES = _load()
IMAGES = (
    {file.relative_to(settings.docs_dir).as_posix() for file in settings.docs_dir.rglob("*.svg")}
    if settings.docs_dir.exists()
    else set()
)


def github_slug(value: str, separator: str = "-") -> str:
    """Heading anchors as GitHub makes them, so `#section` links work in both places."""
    return re.sub(r"[^\w\- ]", "", value.strip().lower()).replace(" ", separator)


def _render(path: str, text: str) -> str:
    body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "sane_lists", "toc"],
        extension_configs={"toc": {"slugify": github_slug}},
    )

    def rewrite(match: re.Match[str]) -> str:
        attribute, relative, anchor = match.groups()
        target = posixpath.normpath(posixpath.join(posixpath.dirname(path), html.unescape(relative)))
        if target in PAGES:
            return f'{attribute}="/help/{target}{anchor or ""}"'
        if target in IMAGES:
            return f'{attribute}="/docs/{target}{anchor or ""}"'
        return match.group(0)

    return _LINK.sub(rewrite, body)


def sections() -> list[dict[str, Any]]:
    """The documentation's table of contents: [{"title", "pages": [{"path", "title"}]}]."""
    found: list[dict[str, Any]] = []
    for title, members in SECTIONS:
        pages = [
            {"path": p, "title": t}
            for p, (t, _) in PAGES.items()
            if any(p == m or (m.endswith("/") and p.startswith(m)) for m in members)
        ]
        if pages:
            found.append({"title": title, "pages": pages})
    return found


_HEADING = re.compile(r'<h([23]) id="([^"]+)">(.*?)</h\1>')


def page_resource(path: str) -> dict[str, Any] | None:
    """A page as the web app shows it: title, HTML, and its headings for the "On this page" list."""
    if path not in PAGES:
        return None
    title, text = PAGES[path]
    body = _render(path, text)
    headings = [
        {"level": int(level), "id": anchor, "text": html.unescape(re.sub(r"<[^>]+>", "", inner))}
        for level, anchor, inner in _HEADING.findall(body)
    ]
    return {"path": path, "title": title, "html": body, "headings": headings}


@blueprint.get("/docs")
def index() -> WerkzeugResponse:
    return redirect(f"/help/{INDEX}")


@blueprint.get("/docs/<path:path>")
def page(path: str) -> ResponseReturnValue:
    """The diagrams; links to pages from earlier versions go to the Help pages."""
    if path in IMAGES:
        return send_file(settings.docs_dir / path, mimetype="image/svg+xml", max_age=3600)
    if path in PAGES:
        return redirect(f"/help/{path}")
    abort(404, "This page of the documentation does not exist.")
