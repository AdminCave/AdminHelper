# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog modules of the mail services (R-1239): the unit finds each one, Mailcow is found
by its compose project and its checks bind to its services, and each rule fires at its threshold
and not just below it."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
# Far from the test machine's clock, so only the report's own time makes a result fresh.
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"

_SERVICE = ("unit", None)

# module id -> (the unit, {check key: (sensor, view)})
MODULES = {
    "postfix": (
        "postfix.service",
        {
            "service": _SERVICE,
            "smtp": ("proto", None),
            "queue": ("app", "postfix_queue"),
            "queue_age": ("app", "postfix_queue_age"),
        },
    ),
    "dovecot": ("dovecot.service", {"service": _SERVICE, "status": ("app", "dovecot_status")}),
    "mailpiler": ("piler.service", {"service": _SERVICE, "archive": ("app", "piler_status")}),
    "clamav": (
        "clamav-daemon.service",
        {"service": _SERVICE, "signatures": ("app", "clamav_db")},
    ),
    "rspamd": ("rspamd.service", {"service": _SERVICE, "ping": ("http", None)}),
    "spamassassin": ("spamd.service", {"service": _SERVICE, "ping": ("app", "spamd_ping")}),
    "opendkim": ("opendkim.service", {"service": _SERVICE, "keys": ("app", "opendkim_keys")}),
}

MAILCOW_SERVICES = {
    "postfix-mailcow": "ghcr.io/mailcow/postfix:3.7.11",
    "dovecot-mailcow": "ghcr.io/mailcow/dovecot:2.3.21.1",
    "rspamd-mailcow": "ghcr.io/mailcow/rspamd:2.2",
    "mysql-mailcow": "mariadb:10.11",
    "redis-mailcow": "redis:7.4.12-alpine",
    "nginx-mailcow": "ghcr.io/mailcow/nginx:1.03",
    "watchdog-mailcow": "ghcr.io/mailcow/watchdog:2.08",
}


def _block(units=(), containers=(), state="active", sub="running"):
    return {
        "ts": T0,
        "duration_ms": 900,
        "partial": False,
        "units": [{"name": u, "state": state, "sub": sub} for u in units],
        "sockets": [],
        "containers": list(containers),
        "markers": {},
        "ports": [],
    }


def _mailcow(project="mailcowdockerized", images=MAILCOW_SERVICES):
    return [
        {
            "id": "id-" + service,
            "name": f"{project}-{service}-1",
            "image": image,
            "compose_project": project,
            "compose_service": service,
            "state": "running",
            "health": "none",
            "ports": [],
            "mounts": [],
        }
        for service, image in images.items()
    ]


def _check(module_id, key):
    return next(c for c in CATALOG.modules[module_id].checks if c.key == key)


def _status(module_id, key, **values):
    """The status the probe checker gives a result of the module's check with these values."""
    module = CATALOG.modules[module_id]
    if module_id == "mailcow":
        block = _block(containers=_mailcow())
        instance = "mailcowdockerized"
        summary = match_inventory(block, CATALOG)[("mailcow", instance)]
    else:
        block = _block()
        instance = MODULES[module_id][0]
        summary = {"unit": instance}
    config, why = probe_config(
        module, _check(module_id, key), instance, summary, block["containers"]
    )
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_modules_load_with_their_checks():
    assert CATALOG.errors == ()
    for module_id, (_, checks) in MODULES.items():
        got = {c.key: (c.sensor, c.params.get("view")) for c in CATALOG.modules[module_id].checks}
        assert got == checks, module_id
    assert all(
        c.credential is None for m in [*MODULES, "mailcow"] for c in CATALOG.modules[m].checks
    )


@pytest.mark.parametrize("module_id", sorted(MODULES))
def test_the_unit_makes_one_instance_and_its_checks_bind_to_it(module_id):
    unit, checks = MODULES[module_id]
    seen = match_inventory(_block([unit, "ssh.service"]), CATALOG)
    ours = {k: v for k, v in seen.items() if k[0] == module_id}
    assert ours == {(module_id, unit): {"unit": unit}}
    module = CATALOG.modules[module_id]
    for key in checks:
        config, why = probe_config(
            module, _check(module_id, key), unit, ours[(module_id, unit)], []
        )
        assert why is None, (key, why)
        if config["target"]["kind"] == "unit":
            assert config["target"]["name"] == unit


@pytest.mark.parametrize("module_id", sorted(MODULES))
def test_a_stopped_unit_finds_nothing(module_id):
    unit, _ = MODULES[module_id]
    stopped = _block([unit], state="inactive", sub="dead")
    assert not any(m == module_id for m, _ in match_inventory(stopped, CATALOG))


def test_spamd_is_also_found_by_its_older_unit():
    seen = match_inventory(_block(["spamassassin.service"]), CATALOG)
    assert ("spamassassin", "spamassassin.service") in seen


def test_the_rspamd_ping_asks_only_the_public_path():
    check = _check("rspamd", "ping")
    assert check.params == {"path": "/ping", "method": "GET", "expect": "pong"}
    assert (check.target.kind, check.target.port_hint, check.target.scheme) == (
        "unit",
        11334,
        "http",
    )


@pytest.mark.parametrize("image", ["ghcr.io/mailcow/postfix:3.7.11", "mailcow/postfix:1.80"])
def test_mailcow_is_found_by_its_compose_project(image):
    containers = _mailcow(images={**MAILCOW_SERVICES, "postfix-mailcow": image})
    seen = match_inventory(_block(containers=containers), CATALOG)
    assert ("mailcow", "mailcowdockerized") in seen
    # A Postfix of the host is another module; it does not make Mailcow.
    alone = match_inventory(_block(["postfix.service"]), CATALOG)
    assert not any(m == "mailcow" for m, _ in alone)


def test_the_checks_of_mailcow_bind_to_their_services():
    block = _block(containers=_mailcow())
    summary = match_inventory(block, CATALOG)[("mailcow", "mailcowdockerized")]
    module = CATALOG.modules["mailcow"]
    want = {
        "postfix": "postfix-mailcow",
        "dovecot": "dovecot-mailcow",
        "rspamd": "rspamd-mailcow",
        "mysql": "mysql-mailcow",
        "redis": "redis-mailcow",
        "nginx": "nginx-mailcow",
        "queue": "postfix-mailcow",
        "watchdog": "redis-mailcow",
    }
    got = {}
    for check in module.checks:
        config, why = probe_config(module, check, "mailcowdockerized", summary, block["containers"])
        assert why is None, (check.key, why)
        got[check.key] = config["target"]["name"]
    assert got == {k: f"mailcowdockerized-{s}-1" for k, s in want.items()}
    assert {k: c.params.get("view") for k, c in ((c.key, c) for c in module.checks)} == {
        **{k: None for k in want},
        "queue": "mailcow_queue",
        "watchdog": "mailcow_watchdog",
    }


@pytest.mark.parametrize(
    ("module_id", "key", "values", "want"),
    [
        ("postfix", "service", {"active_state": "active", "sub_state": "exited"}, "ok"),
        ("postfix", "service", {"active_state": "failed", "sub_state": "failed"}, "critical"),
        # Debian's postfix.service stays active (exited) when the master dies: the greeting fails.
        ("postfix", "smtp", {"ok": True, "detail": "smtp", "duration_ms": 3}, "ok"),
        ("postfix", "smtp", {"ok": False, "detail": "refused", "duration_ms": 1}, "critical"),
        (
            "postfix",
            "queue",
            {
                "active": 1,
                "capped": False,
                "deferred": 100,
                "hold": 3,
                "incoming": 0,
                "total": 104,
            },
            "ok",
        ),
        ("postfix", "queue", {"capped": False, "deferred": 101}, "warning"),
        ("postfix", "queue", {"capped": True, "deferred": 0}, "warning"),
        ("postfix", "queue_age", {"age_read": True, "oldest_age_s": 86400}, "ok"),
        ("postfix", "queue_age", {"age_read": True, "oldest_age_s": 86401}, "warning"),
        ("postfix", "queue_age", {"age_read": True, "oldest_age_s": 345600}, "warning"),
        ("postfix", "queue_age", {"age_read": True, "oldest_age_s": 345601}, "critical"),
        ("postfix", "queue_age", {"age_read": False}, "warning"),
        (
            "dovecot",
            "status",
            {"errors_1h": 0, "services": 12, "services_at_limit": 0, "warnings_1h": 5},
            "ok",
        ),
        ("dovecot", "status", {"errors_1h": 0, "services_at_limit": 1}, "warning"),
        ("dovecot", "status", {"errors_1h": 1, "services_at_limit": 0}, "warning"),
        ("mailcow", "queue", {"capped": False, "deferred": 100, "total": 100}, "ok"),
        ("mailcow", "queue", {"capped": False, "deferred": 101}, "warning"),
        (
            "mailcow",
            "watchdog",
            {"last_age_s": 30, "logged": True, "services": 20, "services_failing": 0},
            "ok",
        ),
        ("mailcow", "watchdog", {"logged": False, "services": 0, "services_failing": 0}, "ok"),
        ("mailcow", "watchdog", {"services": 20, "services_failing": 1}, "warning"),
        ("mailcow", "postfix", {"state": "running", "health": "healthy"}, "ok"),
        ("mailcow", "postfix", {"state": "exited", "health": "none"}, "critical"),
        ("mailpiler", "archive", {"archived": True, "last_age_s": 172800}, "ok"),
        ("mailpiler", "archive", {"archived": True, "last_age_s": 172801}, "warning"),
        ("mailpiler", "archive", {"archived": False}, "unknown"),
        ("clamav", "signatures", {"age_s": 172800, "version": 27800}, "ok"),
        ("clamav", "signatures", {"age_s": 172801, "version": 27800}, "warning"),
        ("clamav", "signatures", {"age_s": 432000, "version": 27800}, "warning"),
        ("clamav", "signatures", {"age_s": 432001, "version": 27800}, "critical"),
        ("rspamd", "ping", {"status_code": 200, "body_match": True}, "ok"),
        ("rspamd", "ping", {"status_code": 200, "body_match": False}, "critical"),
        ("rspamd", "ping", {"status_code": 403, "body_match": False}, "critical"),
        ("spamassassin", "ping", {"reachable": True}, "ok"),
        ("spamassassin", "ping", {"reachable": False}, "critical"),
        ("opendkim", "keys", {"keys": 2, "keys_failed": 0}, "ok"),
        ("opendkim", "keys", {"keys": 2, "keys_failed": 1}, "warning"),
    ],
)
def test_the_rules_fire_at_their_thresholds(module_id, key, values, want):
    assert _status(module_id, key, **values) == want


def test_the_card_names_fields_of_its_checks():
    for module_id in [*MODULES, "mailcow"]:
        module = CATALOG.modules[module_id]
        fields = {c.key: set(c.fields) for c in module.checks}
        assert 1 <= len(module.card) <= 6, module_id
        for item in module.card:
            assert item.field in fields[item.check_key], (module_id, item.check_key, item.field)
