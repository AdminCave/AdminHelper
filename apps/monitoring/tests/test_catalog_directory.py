# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog modules of the directory and school services (R-1240): the unit finds each one,
its checks bind to it, and each rule fires at its threshold and not just below it."""

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
    "samba-ad-dc": (
        "samba-ad-dc.service",
        {
            "service": _SERVICE,
            "replication": ("app", "samba_drs"),
            "fsmo": ("app", "samba_fsmo"),
            "certificate": ("tls", None),
        },
    ),
    "samba-member": (
        "smbd.service",
        {
            "service": _SERVICE,
            "status": ("app", "samba_member"),
            "domain": ("app", "samba_member"),
            "trust": ("app", "samba_trust"),
        },
    ),
    "linuxmuster": (
        "linuxmuster-webui.service",
        {
            "service": _SERVICE,
            "devices": ("app", "lmn_devices"),
            "linbo": ("app", "lmn_linbo"),
            "certificate": ("certfile", None),
        },
    ),
}


def _block(units=(), state="active", sub="running"):
    return {
        "ts": T0,
        "duration_ms": 900,
        "partial": False,
        "units": [{"name": u, "state": state, "sub": sub} for u in units],
        "sockets": [],
        "containers": [],
        "markers": {},
        "ports": [],
    }


def _check(module_id, key):
    return next(c for c in CATALOG.modules[module_id].checks if c.key == key)


def _status(module_id, key, **values):
    """The status the probe checker gives a result of the module's check with these values."""
    module = CATALOG.modules[module_id]
    unit = MODULES[module_id][0]
    config, why = probe_config(module, _check(module_id, key), unit, {"unit": unit}, [])
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_modules_load_with_their_checks():
    assert CATALOG.errors == ()
    for module_id, (_, checks) in MODULES.items():
        got = {c.key: (c.sensor, c.params.get("view")) for c in CATALOG.modules[module_id].checks}
        assert got == checks, module_id
        assert all(c.credential is None for c in CATALOG.modules[module_id].checks)


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
        if _check(module_id, key).target is not None:
            assert config["target"]["name"] == unit, key


@pytest.mark.parametrize("module_id", sorted(MODULES))
def test_a_stopped_unit_finds_nothing(module_id):
    unit, _ = MODULES[module_id]
    stopped = _block([unit], state="inactive", sub="dead")
    assert not any(m == module_id for m, _ in match_inventory(stopped, CATALOG))


def test_a_linuxmuster_server_is_its_dc_too():
    units = ["linuxmuster-webui.service", "samba-ad-dc.service", "isc-dhcp-server.service"]
    seen = {m for m, _ in match_inventory(_block(units), CATALOG)}
    assert {"linuxmuster", "samba-ad-dc", "isc-dhcp-server"} <= seen


def test_the_fixed_targets():
    ldaps = _check("samba-ad-dc", "certificate")
    assert (ldaps.target.kind, ldaps.target.port_hint) == ("unit", 636)
    cert = _check("linuxmuster", "certificate")
    assert cert.target is None
    assert cert.params == {"path": "/etc/linuxmuster/ssl/server.cert.pem"}


@pytest.mark.parametrize(
    ("module_id", "key", "values", "want"),
    [
        ("samba-ad-dc", "service", {"active_state": "active", "sub_state": "running"}, "ok"),
        ("samba-ad-dc", "service", {"active_state": "failed", "sub_state": "failed"}, "critical"),
        (
            "samba-ad-dc",
            "replication",
            {
                "partners": 2,
                "links": 10,
                "links_failing": 0,
                "outbound_failing": 0,
                "last_success_age_s": 43200,
            },
            "ok",
        ),
        (
            "samba-ad-dc",
            "replication",
            {"links_failing": 1, "outbound_failing": 0, "last_success_age_s": 60},
            "warning",
        ),
        (
            "samba-ad-dc",
            "replication",
            {"links_failing": 0, "outbound_failing": 1, "last_success_age_s": 60},
            "warning",
        ),
        (
            "samba-ad-dc",
            "replication",
            {"links_failing": 0, "outbound_failing": 0, "last_success_age_s": 43201},
            "critical",
        ),
        # A single DC has no inbound link and so no last success.
        (
            "samba-ad-dc",
            "replication",
            {"partners": 0, "links": 0, "links_failing": 0, "outbound_failing": 0},
            "unknown",
        ),
        ("samba-ad-dc", "fsmo", {"roles": 7, "roles_without_owner": 0}, "ok"),
        ("samba-ad-dc", "fsmo", {"roles": 7, "roles_without_owner": 1}, "warning"),
        ("samba-ad-dc", "certificate", {"lifetime_pct": 25, "hours_left": 4200}, "ok"),
        ("samba-ad-dc", "certificate", {"lifetime_pct": 24.9, "hours_left": 4000}, "warning"),
        ("samba-ad-dc", "certificate", {"lifetime_pct": 9.9, "hours_left": 1600}, "critical"),
        ("samba-ad-dc", "certificate", {"lifetime_pct": 50, "hours_left": 11}, "critical"),
        (
            "samba-member",
            "status",
            {"config_ok": True, "sessions": 3, "tcons": 4, "open_files": 9},
            "ok",
        ),
        ("samba-member", "status", {"config_ok": False, "sessions": 0}, "warning"),
        ("samba-member", "domain", {"winbind_ok": True, "dc_ok": True}, "ok"),
        ("samba-member", "domain", {"winbind_ok": True, "dc_ok": False}, "warning"),
        ("samba-member", "domain", {"winbind_ok": False, "dc_ok": False}, "critical"),
        # A file server without winbind: the view leaves both out.
        ("samba-member", "domain", {}, "unknown"),
        ("samba-member", "trust", {"trust_ok": True}, "ok"),
        ("samba-member", "trust", {"trust_ok": False}, "warning"),
        (
            "linuxmuster",
            "devices",
            {
                "import_pending": False,
                "last_import_age_s": 900,
                "import_completed": True,
                "import_errors": 2,
            },
            "ok",
        ),
        ("linuxmuster", "devices", {"import_pending": True}, "warning"),
        ("linuxmuster", "linbo", {"images": 4, "torrents_stale": 0}, "ok"),
        ("linuxmuster", "linbo", {"images": 4, "torrents_stale": 1}, "warning"),
        ("linuxmuster", "certificate", {"days_left": 30}, "ok"),
        ("linuxmuster", "certificate", {"days_left": 29}, "warning"),
        ("linuxmuster", "certificate", {"days_left": 7}, "warning"),
        ("linuxmuster", "certificate", {"days_left": 6}, "critical"),
    ],
)
def test_the_rules_fire_at_their_thresholds(module_id, key, values, want):
    assert _status(module_id, key, **values) == want


def test_the_card_names_fields_of_its_checks():
    for module_id in MODULES:
        module = CATALOG.modules[module_id]
        fields = {c.key: set(c.fields) for c in module.checks}
        assert 1 <= len(module.card) <= 6, module_id
        for item in module.card:
            assert item.field in fields[item.check_key], (module_id, item.check_key, item.field)
