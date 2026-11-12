# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The boundary of central checks (R-1224): config schema, the router's interval floor
and partner rule, and the refusal in templates."""

import json

import pytest
from pydantic import ValidationError

from app.check_configs import CentralConfig, validate_check_config
from app.models import MonitorCheck
from app.schemas import TemplateCheckDef


def _config(**over):
    c = {"sensor": "tls", "host": "www.example.test"}
    c.update(over)
    return c


# --- the config ---


@pytest.mark.parametrize(
    "config",
    [
        _config(),
        _config(port=8443),
        _config(port=1),
        _config(port=65535),
        _config(host="xn--bcher-kva.example"),
        _config(host="192.0.2.10"),
        _config(host="2001:db8::10"),
        _config(host="localhost"),  # a name; the rule public/internal decides at run time
        _config(pair_check_id="p1"),
        _config(params={}),
        _config(sensor="dns"),
        _config(sensor="dns", params={"expected": ["192.0.2.10", "2001:db8::10"]}),
        _config(sensor="dns", params={"expected": None}),
        _config(sensor="rdap"),
        _config(sensor="rdap", host="example.test"),
        _config(sensor="rdap", params={"warn_days": 60, "crit_days": 14}),
        _config(sensor="rdap", params={"warn_days": 1, "crit_days": 0}),
        _config(sensor="smtp"),
        _config(sensor="smtp", port=465),
        _config(sensor="smtp", port=587),
        _config(sensor="smtp", host="192.0.2.10"),
        _config(sensor="imap"),
        _config(sensor="imap", port=143),
        _config(sensor="imap", port=995),
        _config(sensor="mail_dns"),
        _config(sensor="mail_dns", host="example.test"),
        _config(sensor="dnsbl", host="example.test"),
        _config(sensor="dnsbl", params={"lists": None}),
        _config(sensor="dnsbl", params={"lists": ["psbl"]}),
        _config(
            sensor="dnsbl", params={"lists": ["psbl", "spamcop", "uceprotect1", "spamhaus_zen"]}
        ),
    ],
)
def test_valid_configs_pass(config):
    validate_check_config("central", config)


@pytest.mark.parametrize(
    ("config", "fragment"),
    [
        (_config(port=22), "ports 22 and 3306"),
        (_config(port=3306), "ports 22 and 3306"),
        (_config(port=0), "port"),
        (_config(port=65536), "port"),
        (_config(port="443"), "port"),  # strict: no string coercion
        (_config(port=True), "port"),
        (_config(port=443.0), "port"),
        (_config(sensor="ftp"), "unknown sensor"),
        (_config(sensor=["tls"]), "sensor"),
        (_config(host=""), "host"),
        (_config(host="www.example.test."), "host"),  # trailing dot
        (_config(host="fe80::1%eth0"), "host"),  # zone index
        (_config(host="-bad.example.test"), "host"),
        (_config(host="bad_.example.test"), "host"),
        (_config(host="münchen.example"), "host"),  # IDN only in xn-- form
        (_config(host="1.2.3"), "host"),
        (_config(host="999.1.1.1"), "host"),
        (_config(host="a" * 64 + ".example"), "host"),
        (_config(host="www.example.test/path"), "host"),
        (_config(pair_check_id=""), "pair_check_id"),
        (_config(pair_check_id="p" * 65), "pair_check_id"),
        (_config(params={"x": 1}), "params"),
        (_config(extra=1), "extra"),
        ({"host": "www.example.test"}, "sensor"),
        (_config(sensor="dns", port=53), "the sensor dns takes no port"),
        (_config(sensor="dns", host="192.0.2.10"), "the sensor dns needs a host name"),
        (_config(sensor="dns", host="2001:db8::10"), "the sensor dns needs a host name"),
        (_config(sensor="dns", params={"expected": []}), "params.expected"),
        (_config(sensor="dns", params={"expected": "192.0.2.10"}), "params.expected"),
        (_config(sensor="dns", params={"expected": ["www.example.test"]}), "not an IP address"),
        (_config(sensor="dns", params={"expected": ["fe80::1%eth0"]}), "zone index"),
        (_config(sensor="dns", params={"expected": ["192.0.2.10"] * 33}), "params.expected"),
        (_config(sensor="dns", params={"expected": [10]}), "params.expected"),
        (_config(sensor="dns", params={"other": 1}), "params"),
        (_config(params={"expected": ["192.0.2.10"]}), "params"),  # tls takes none
        (_config(sensor="rdap", port=443), "the sensor rdap takes no port"),
        (_config(sensor="rdap", host="192.0.2.10"), "the sensor rdap needs a host name"),
        (_config(sensor="rdap", params={"warn_days": 7, "crit_days": 7}), "below warn_days"),
        (_config(sensor="rdap", params={"warn_days": 0}), "params.warn_days"),
        (_config(sensor="rdap", params={"warn_days": 366}), "params.warn_days"),
        (_config(sensor="rdap", params={"crit_days": -1}), "params.crit_days"),
        (_config(sensor="rdap", params={"warn_days": "30"}), "params.warn_days"),
        (_config(sensor="rdap", params={"warn_days": True}), "params.warn_days"),
        (_config(sensor="rdap", params={"days": 30}), "params"),
        (_config(sensor="smtp", port=443), "the sensor smtp takes port 25, 465 or 587"),
        (_config(sensor="smtp", port=2525), "the sensor smtp takes port 25, 465 or 587"),
        (_config(sensor="imap", port=110), "the sensor imap takes port 143, 993 or 995"),
        (_config(sensor="imap", port=25), "the sensor imap takes port 143, 993 or 995"),
        (_config(sensor="smtp", port=22), "ports 22 and 3306"),
        (_config(sensor="smtp", params={"ehlo": "mx.example.test"}), "params"),
        (_config(sensor="imap", params={"x": 1}), "params"),
        (_config(sensor="mail_dns", port=25), "the sensor mail_dns takes no port"),
        (_config(sensor="mail_dns", host="192.0.2.10"), "the sensor mail_dns needs a host name"),
        (_config(sensor="mail_dns", params={"x": 1}), "params"),
        (_config(sensor="dnsbl", port=25), "the sensor dnsbl takes no port"),
        (_config(sensor="dnsbl", host="192.0.2.10"), "the sensor dnsbl needs a host name"),
        (_config(sensor="dnsbl", params={"lists": []}), "params.lists"),
        (_config(sensor="dnsbl", params={"lists": ["spamhaus"]}), "params.lists"),
        (_config(sensor="dnsbl", params={"lists": "psbl"}), "params.lists"),
        (_config(sensor="dnsbl", params={"lists": ["psbl", "psbl"]}), "each list at most once"),
        (_config(sensor="dnsbl", params={"zones": ["psbl"]}), "params"),
    ],
)
def test_invalid_configs_are_refused(config, fragment):
    with pytest.raises(ValueError, match=fragment):
        validate_check_config("central", config)


def test_a_zone_index_is_refused_even_where_the_ip_parser_takes_it():
    with pytest.raises(ValidationError, match="zone index"):
        CentralConfig.model_validate(_config(host="fe80::1%25"))


# --- the template boundary ---


def test_a_template_cannot_carry_a_central_check():
    with pytest.raises(ValidationError, match="created by the admin, not from a template"):
        TemplateCheckDef.model_validate(
            {"name": "t", "check_type": "central", "interval": "1h", "config": _config()}
        )


# --- the router ---


def _payload(**over):
    p = {
        "name": "c",
        "server_id": "srv-1",
        "check_type": "central",
        "severity": "critical",
        "config": _config(),
    }
    p.update(over)
    return p


def _add(factory, check_id, *, check_type="probe", server_id="srv-1", config=None, interval="5m"):
    with factory() as db:
        db.add(
            MonitorCheck(
                id=check_id,
                server_id=server_id,
                name=check_id,
                check_type=check_type,
                config=config if isinstance(config, str) else json.dumps(config or {}),
                enabled=True,
                interval=interval,
                severity="critical",
            )
        )
        db.commit()


def test_create_without_interval_takes_the_sensor_default(client_db):
    client, factory = client_db

    r = client.post("/checks", json=_payload())

    assert r.status_code == 201, r.text
    with factory() as db:
        assert db.get(MonitorCheck, r.json()["id"]).interval == "1h"


@pytest.mark.parametrize(
    ("interval", "code"), [("1m", 400), ("5m", 400), ("15m", 201), ("6h", 201)]
)
def test_create_refuses_an_interval_below_the_sensor_floor(client_db, interval, code):
    client, _ = client_db

    r = client.post("/checks", json=_payload(interval=interval))

    assert r.status_code == code, r.text
    if code == 400:
        assert r.json()["detail"] == "Interval too short for sensor tls: at least 15m"


@pytest.mark.parametrize(("interval", "code"), [("1m", 400), ("5m", 201)])
def test_the_dns_sensor_has_its_own_floor_and_default(client_db, interval, code):
    client, factory = client_db
    config = _config(sensor="dns")

    r = client.post("/checks", json=_payload(config=config, interval=interval))
    default = client.post("/checks", json=_payload(config=config))

    assert r.status_code == code, r.text
    if code == 400:
        assert r.json()["detail"] == "Interval too short for sensor dns: at least 5m"
    assert default.status_code == 201, default.text
    with factory() as db:
        assert db.get(MonitorCheck, default.json()["id"]).interval == "15m"


@pytest.mark.parametrize("sensor", ["smtp", "imap"])
@pytest.mark.parametrize(("interval", "code"), [("5m", 400), ("15m", 201)])
def test_the_mail_sensors_run_at_most_every_15_minutes(client_db, sensor, interval, code):
    client, factory = client_db
    config = _config(sensor=sensor)

    r = client.post("/checks", json=_payload(config=config, interval=interval))
    default = client.post("/checks", json=_payload(config=config))

    assert r.status_code == code, r.text
    if code == 400:
        assert r.json()["detail"] == f"Interval too short for sensor {sensor}: at least 15m"
    assert default.status_code == 201, default.text
    with factory() as db:
        assert db.get(MonitorCheck, default.json()["id"]).interval == "15m"


@pytest.mark.parametrize(("interval", "code"), [("12h", 400), ("24h", 201)])
def test_the_rdap_sensor_runs_at_most_daily(client_db, interval, code):
    client, factory = client_db
    config = _config(sensor="rdap")

    r = client.post("/checks", json=_payload(config=config, interval=interval))
    default = client.post("/checks", json=_payload(config=config))

    assert r.status_code == code, r.text
    if code == 400:
        assert r.json()["detail"] == "Interval too short for sensor rdap: at least 24h"
    assert default.status_code == 201, default.text
    with factory() as db:
        assert db.get(MonitorCheck, default.json()["id"]).interval == "24h"


@pytest.mark.parametrize(("interval", "code"), [("30m", 400), ("1h", 201)])
def test_the_mail_dns_sensor_runs_at_most_hourly(client_db, interval, code):
    client, factory = client_db
    config = _config(sensor="mail_dns", host="example.test")

    r = client.post("/checks", json=_payload(config=config, interval=interval))
    default = client.post("/checks", json=_payload(config=config))

    assert r.status_code == code, r.text
    if code == 400:
        assert r.json()["detail"] == "Interval too short for sensor mail_dns: at least 1h"
    assert default.status_code == 201, default.text
    with factory() as db:
        assert db.get(MonitorCheck, default.json()["id"]).interval == "1h"


@pytest.mark.parametrize(("interval", "code"), [("12h", 400), ("24h", 201)])
def test_the_dnsbl_sensor_runs_at_most_daily(client_db, interval, code):
    client, factory = client_db
    config = _config(sensor="dnsbl", host="example.test")

    r = client.post("/checks", json=_payload(config=config, interval=interval))
    default = client.post("/checks", json=_payload(config=config))

    assert r.status_code == code, r.text
    if code == 400:
        assert r.json()["detail"] == "Interval too short for sensor dnsbl: at least 24h"
    assert default.status_code == 201, default.text
    with factory() as db:
        assert db.get(MonitorCheck, default.json()["id"]).interval == "24h"


def test_create_refuses_a_forbidden_port_at_the_schema(client_db):
    client, _ = client_db

    r = client.post("/checks", json=_payload(config=_config(port=22)))

    assert r.status_code == 422


@pytest.mark.parametrize("sensor", ["tls", "certfile", "http"])
def test_create_accepts_a_probe_partner_of_the_same_server(client_db, sensor):
    client, factory = client_db
    _add(factory, "p1", config={"module": "web", "sensor": sensor})

    r = client.post("/checks", json=_payload(config=_config(pair_check_id="p1")))

    assert r.status_code == 201, r.text


@pytest.mark.parametrize(
    ("partner", "server_id"),
    [
        ({"check_type": "ping", "config": {"target": "192.0.2.10"}}, "srv-1"),
        ({"config": {"sensor": "tls"}, "server_id": "srv-2"}, "srv-1"),
        ({"config": {"sensor": "tls"}}, None),  # a central check without a server has no partner
        (None, "srv-1"),  # no such check
    ],
)
def test_create_refuses_a_partner_that_is_no_probe_of_the_same_server(
    client_db, partner, server_id
):
    client, factory = client_db
    if partner is not None:
        _add(factory, "p1", **partner)

    r = client.post(
        "/checks", json=_payload(server_id=server_id, config=_config(pair_check_id="p1"))
    )

    assert r.status_code == 400
    assert r.json()["detail"] == "pair_check_id must name a probe check of the same server"


@pytest.mark.parametrize(
    "stored",
    [
        {"sensor": "process"},
        {"sensor": ["tls"]},  # unhashable: must not raise in the set lookup
        {"sensor": {"tls": 1}},
        {},
        ["tls"],
        "not json",
    ],
)
def test_create_refuses_a_probe_partner_with_another_sensor(client_db, stored):
    client, factory = client_db
    _add(factory, "p1", config=stored)

    r = client.post("/checks", json=_payload(config=_config(pair_check_id="p1")))

    assert r.status_code == 400
    assert r.json()["detail"].startswith("pair_check_id must name a probe check with sensor")


def test_update_re_checks_the_interval_floor(client_db):
    client, factory = client_db
    _add(factory, "c1", check_type="central", config=_config(), interval="1h")

    assert client.put("/checks/c1", json={"interval": "5m"}).status_code == 400
    assert client.put("/checks/c1", json={"interval": "15m"}).status_code == 200


def test_update_re_checks_the_partner_when_the_server_changes(client_db):
    client, factory = client_db
    _add(factory, "p1", config={"sensor": "tls"})
    _add(factory, "c1", check_type="central", config=_config(pair_check_id="p1"), interval="1h")

    r = client.put("/checks/c1", json={"server_id": "srv-2"})

    assert r.status_code == 400
    assert r.json()["detail"] == "pair_check_id must name a probe check of the same server"


def test_update_of_other_fields_leaves_a_stored_check_editable(client_db):
    # A check stored before the floor (or written directly) stays editable in name
    # and severity; the floor applies when interval, config, type or server change.
    client, factory = client_db
    _add(factory, "c1", check_type="central", config=_config(), interval="5m")

    assert client.put("/checks/c1", json={"name": "renamed"}).status_code == 200


def test_update_to_type_central_checks_the_floor(client_db):
    client, factory = client_db
    _add(factory, "c1", check_type="tcp", config={"host": "192.0.2.10", "port": 443})

    r = client.put("/checks/c1", json={"check_type": "central", "config": _config()})

    assert r.status_code == 400
    assert r.json()["detail"] == "Interval too short for sensor tls: at least 15m"
