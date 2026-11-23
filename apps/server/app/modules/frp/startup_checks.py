# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the server checks and writes of the FRP server config at startup (R-0690: moved
out of app/main.py): the stored rows against what the frps supervisor starts frps with,
then frps.toml from the DB."""

import json
import logging

from app.core.config import FRP_BIND_PORT
from app.modules.frp.config_generator import frps_fields
from app.modules.frp.extra_config import STRING_FIELDS, rejected_keys, value_allowed
from app.modules.frp.models import FrpServerConfig
from app.modules.frp.schemas import dashboard_port_refused
from app.modules.notifications.models import Notification
from app.modules.notifications.schemas import IncomingEvent
from app.modules.notifications.service import notify_users
from app.modules.users.models import User

logger = logging.getLogger(__name__)


# The fields _report_rejected_fields names, as the web interface labels them.
_FRPS_FIELD_LABELS = {
    "subdomain_host": "Subdomain Host",
    "dashboard_user": "Dashboard User",
    "dashboard_password": "Dashboard Passwort",
    "auth_token": "Auth Token",
    "dashboard_port": "Dashboard Port",
}
# The rules of check_config (apps/frps/frps-supervisor.sh) _report_rejected_fields names.
_FRPS_RULE_CHARACTERS = "ohne Anführungszeichen, Backslash, geschweifte Klammern und Steuerzeichen"
_FRPS_RULE_TOKEN = "mindestens 16 Zeichen"
_FRPS_RULE_DASHBOARD_PORT = "weder 443 noch der Bind Port noch FRP_BIND_PORT"


def _tell_admins(db, event_type, title, body, source_id):
    admins = db.query(User).filter(User.is_admin.is_(True)).order_by(User.id).all()
    notify_users(
        db,
        admins,
        IncomingEvent(
            event_type=event_type,
            severity="warning",
            category="tunnel",
            title=title,
            body=body,
            source_type="frp_config",
            source_id=source_id,
        ),
    )


def _remove_rejected_extra_config(db, config):
    """Remove the extra_config entries frps is not started with. Logs the keys, never the
    values, and tells the admins; a second start finds nothing left to remove."""
    extra = json.loads(config.extra_config or "null") or {}
    removed = rejected_keys(extra)
    if not removed:
        return
    kept = {key: value for key, value in extra.items() if key not in removed}
    config.extra_config = json.dumps(kept) if kept else None
    logger.warning(
        "FRP server config %s: extra_config keys removed, frps is not started with them: %s",
        config.id,
        removed,
    )
    _tell_admins(
        db,
        "lifecycle.frp.config.extra_config_removed",
        "Zusätzliche FRP-Einstellungen entfernt",
        "Der FRP-Server übernimmt diese zusätzlichen Einstellungen (extra_config) nicht; sie "
        "wurden beim Start aus der FRP-Server-Konfiguration entfernt: " + ", ".join(removed) + ".",
        config.id,
    )


def _report_rejected_fields(db, config):
    """Name the fields frps.toml carries with a value frps is not started with: a string
    field with a character check_config refuses, an auth token under 16 bytes and a
    dashboard port that is 443, the bind port or FRP_BIND_PORT. A token or password has no
    sensible replacement and a port no obvious one, so the row stays as it is: the field
    names (never the values) are logged at every start, and the admins are told once, each
    field with its rule, for as long as the same fields stay so."""
    written = frps_fields(config)
    rules = {
        field: _FRPS_RULE_CHARACTERS
        for key, field in STRING_FIELDS.items()
        if key in written and not value_allowed(getattr(config, field))
    }
    # check_config runs under LC_ALL=C, so it counts the token in bytes.
    if "auth_token" not in rules and len(config.auth_token.encode()) < 16:
        rules["auth_token"] = _FRPS_RULE_TOKEN
    if "webServer.port" in written and dashboard_port_refused(
        written["webServer.port"], written["bindPort"], FRP_BIND_PORT
    ):
        rules["dashboard_port"] = _FRPS_RULE_DASHBOARD_PORT
    fields = list(rules)
    if not fields:
        return
    logger.warning(
        "FRP server config %s: frps is not started with the values of these fields, they "
        "need to be set anew: %s",
        config.id,
        fields,
    )
    source_id = f"{config.id}:{','.join(fields)}"
    told = (
        db.query(Notification.id)
        .filter(Notification.source_type == "frp_config", Notification.source_id == source_id)
        .first()
    )
    if told:
        return
    _tell_admins(
        db,
        "lifecycle.frp.config.field_rejected",
        "FRP-Server-Konfiguration: Felder neu setzen",
        "Der FRP-Server übernimmt die Konfiguration so nicht. Bitte neu setzen: "
        + ", ".join(f"{_FRPS_FIELD_LABELS[field]} ({rule})" for field, rule in rules.items())
        + ".",
        source_id,
    )


def check_frps_server_configs(db):
    """Bring the stored FRP server configs in line with what the frps supervisor starts frps
    with (frp/extra_config.py, R-0411): a row stored before those checks would otherwise
    leave frps without a config after an update. Best effort, like ensure_frps_config, and
    each check on its own: a failed one is logged with the type of the error only (a
    database error quotes the connection, password included)."""
    try:
        ids = [config_id for (config_id,) in db.query(FrpServerConfig.id).all()]
    except Exception as exc:
        db.rollback()
        logger.warning("FRP server configs not checked (%s)", type(exc).__name__)
        return
    for config_id in ids:
        for check in (_remove_rejected_extra_config, _report_rejected_fields):
            try:
                # Every uvicorn worker runs this at its start: the lock, held until the
                # check commits, lets one of them act on the row and tell the admins, and
                # the others then find it done.
                config = (
                    db.query(FrpServerConfig)
                    .filter(FrpServerConfig.id == config_id)
                    .with_for_update()
                    .populate_existing()
                    .one()
                )
                check(db, config)
                db.commit()
            except Exception as exc:
                db.rollback()
                logger.warning(
                    "FRP server config %s: %s failed (%s)",
                    config_id,
                    check.__name__,
                    type(exc).__name__,
                )


def ensure_frps_config(db):
    """Reconcile frps.toml with the DB on startup, in both directions: the DB
    config is written, and without one a frps.toml still in the shared volume is
    removed (the DB is the source of truth; a removal after a delete is only best
    effort). The frps TLS material now comes from the ca-issuer under the tunnel
    intermediate (A7) — the server no longer runs its own FRP CA (D6/F3): no CA
    generation, no cert minting, no publish. Only the non-secret frps.toml
    (ports, auth token, TLS file paths pointing at /etc/frp-pki) is regenerated
    here. First go the temp files a killed write left behind, with or without a config."""
    from app.modules.frp._helpers import get_frp_config
    from app.modules.frp.docker_manager import (
        remove_frps_config,
        remove_stale_temp_files,
        write_frps_config,
    )

    remove_stale_temp_files()
    try:
        config = get_frp_config(db)
        if not config:
            remove_frps_config()
            return
        write_frps_config(config)
        logger.info("frps.toml neu geschrieben")
    except Exception as exc:
        logger.warning("frps.toml not written at startup (%s)", type(exc).__name__)
