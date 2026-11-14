"""The panel's settings (permission settings.manage).

    GET    /api/v1/settings              every setting: value, .env value, changed here or not, when it applies
    PATCH  /api/v1/settings              change settings: {"idle_hours": 4, "smtp_password": "..."}; null resets
    DELETE /api/v1/settings/<key>        bring back the .env value -> 204
    POST   /api/v1/settings/test-email   send the test e-mail to {"to"} with the current mail settings

"applies" says when a change takes effect: "now", "restart" (it chooses a plugin; restart the panel with
POST /api/v1/server/restart) or "env" (only in .env: folders, ports, exposure, storage). Changes are kept on top of
.env (config.py, LiveSettings); secrets are stored encrypted and never shown, only whether they are set.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, abort
from pydantic import ValidationError

from sudoo import accounts, config
from sudoo.config import Settings, live, settings
from sudoo.core import events

from .. import validation as check
from ..security import log, require
from .responses import no_content, ok

blueprint = Blueprint("settings", __name__)

_FIXED = {
    "pause_check_interval_seconds",
    "expiry_check_interval_seconds",
    "integrity_check_interval_seconds",
    "history_samples",
}
_HIDDEN = {"docs_dir", "memory_dir"}


def _type(annotation: Any) -> str:
    return {bool: "boolean", int: "integer", float: "number"}.get(annotation, "string")


def _shown(key: str, value: Any) -> Any:
    if key in config.SECRET:
        return bool(value)  # set or not
    return str(value) if not isinstance(value, bool | int | float | str) else value


def resource() -> list[dict[str, Any]]:
    overrides = live.overrides()
    result = []
    for key, field in Settings.model_fields.items():
        if key in _FIXED or key in _HIDDEN:
            continue
        minimum = next((getattr(m, "ge", None) for m in field.metadata if getattr(m, "ge", None) is not None), None)
        result.append(
            {
                "key": key,
                "env": key.upper(),
                "value": _shown(key, getattr(settings, key)),
                "env_value": _shown(key, getattr(live.env, key)),
                "changed_in_panel": key in overrides,
                "editable": key in config.EDITABLE or key in config.RESTART,
                "applies": "now" if key in config.EDITABLE else "restart" if key in config.RESTART else "env",
                "pending_restart": live.pending_restart(key),
                "secret": key in config.SECRET,
                "type": _type(field.annotation),
                "minimum": minimum,
                "description": field.description,
            }
        )
    return result


@blueprint.get("/settings")
@require("settings.manage")
def read() -> Response:
    return ok(resource())


def _change(values: dict[str, Any]) -> None:
    try:
        live.change(values)
    except ValidationError as error:
        first = error.errors()[0]
        abort(400, f"{str(first['loc'][0]).upper()}: {first['msg']}.")
    except ValueError as error:
        abort(400, str(error))
    log("settings changed", detail=", ".join(f"{k.upper()}={'(env)' if v is None else v}" for k, v in values.items()))


@blueprint.patch("/settings")
@require("settings.manage")
def change() -> Response:
    values = check.body()
    if not values:
        abort(400, 'Send the settings to change, for example {"idle_hours": 4}.')
    _change(values)
    return ok(resource())


@blueprint.delete("/settings/<key>")
@require("settings.manage")
def reset(key: str) -> Response:
    if key not in config.EDITABLE and key not in config.RESTART:
        abort(404, "No setting with this name can be changed in the panel.")
    _change({key: None})
    return no_content()


@blueprint.post("/settings/test-email")
@require("settings.manage")
def test_email() -> Response:
    from sudoo.mail import MailError, mailer, send_template

    to = check.text(check.body(), "to", max_length=254)
    if not accounts.EMAIL_RE.match(to):
        abort(400, "Enter the e-mail address to send the test to.")
    if not mailer().ready:
        abort(400, "E-mail is not set up yet: fill in the mail server (SMTP) settings first.")
    server = f"{settings.smtp_host}:{settings.smtp_port} ({settings.smtp_security})"
    try:
        send_template(to, "test", "Sudoo.sh e-mail works", preheader="Your mail settings work.",
                      kicker="E-mail settings", title="It works", server=server)  # fmt: skip
    except MailError as error:
        abort(502, f"{error} For Gmail, the password must be an app password.")
    log("test e-mail sent", detail=to)
    return ok({"sent_to": to})


def publish_changes(changed: dict[str, Any]) -> None:
    """Live event "settings" after every change (registered in web/v1/__init__.py)."""
    events.publish("settings", ",".join(sorted(changed)), {"changed": sorted(changed)})
