# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Rules every module of the shipped catalog keeps (arch-monitoring-apps-1).

A request that looks like reading can make a service act (monitoring concept §3.6): no
HTTP check asks a known trap, and a path that makes the service do real work is marked
as a test object. No HTTP check asks the loopback address, where a web server answers
with its default site rather than the app's. No module detects itself by a name every
other stack runs too, or it would claim their containers and units. Each rule is shown
to catch a module that breaks it.
"""

import re

import pytest

from app.catalog.loader import load_catalog
from app.catalog.model import Module
from app.discovery import image_repo

SHIPPED = load_catalog()

# Paths with side effects: Jicofo moves participants, Moodle and WordPress start their cron,
# Uptime Kuma records a heartbeat, OnlyOffice shuts down on a write there, Mattermost's deep
# ping writes a file, admin and login routes lock out or alert on a wrong guess.
TRAPS = (
    "move-endpoints",
    "/admin",
    "cron.php",
    "wp-cron.php",
    "/api/push/",
    "/internal/cluster/inactive",
    "get_server_status",
    "/login",
)
# Paths that make the service do real work: OnlyOffice writes a test object, BookStack
# opens a session.
TEST_OBJECT_PATHS = frozenset({"/healthcheck", "/status"})
# Names every other stack runs too; the php-fpm units carry their version.
GENERIC_NAMES = frozenset(
    {
        "nginx",
        "apache2",
        "httpd",
        "php-fpm",
        "postgres",
        "redis",
        "mariadb",
        "node",
        "python3",
        "java",
    }
)
_PHP_FPM = re.compile(r"^php[0-9.]*-fpm$")


def _http_paths(module: Module):
    for check in module.checks:
        if check.sensor == "http":
            yield check, check.params["path"]
        elif check.sensor == "unixsocket" and check.params["protocol"] == "http":
            yield check, check.params["http_path"]


def _traps(module: Module) -> list[str]:
    return [
        f"{check.key}: {path}"
        for check, path in _http_paths(module)
        if any(trap in path.lower() for trap in TRAPS)
    ]


def _unmarked_test_objects(module: Module) -> list[str]:
    return [
        f"{check.key}: {path}"
        for check, path in _http_paths(module)
        if path.split("?", 1)[0] in TEST_OBJECT_PATHS and not check.test_object
    ]


def _loopback_http(module: Module) -> list[str]:
    return [
        check.key
        for check in module.checks
        if check.sensor == "http" and check.target is not None and check.target.kind == "loopback"
    ]


def _generic(name: str) -> bool:
    return name in GENERIC_NAMES or bool(_PHP_FPM.fullmatch(name))


def _generic_detect(module: Module) -> list[str]:
    d = module.detect
    return (
        [f"image:{i}" for i in d.container_images if _generic(image_repo(i))]
        + [f"unit:{u}" for u in d.units if _generic(u.removesuffix(".service"))]
        + [f"process:{p}" for p in d.processes if _generic(p)]
    )


RULES = {
    "trap": _traps,
    "test_object": _unmarked_test_objects,
    "loopback": _loopback_http,
    "generic_detect": _generic_detect,
}


def test_the_shipped_catalog_loads():
    assert SHIPPED.errors == ()


@pytest.mark.parametrize("rule", sorted(RULES))
def test_no_shipped_module_breaks_the_rule(rule):
    broken = {mid: found for mid, m in SHIPPED.modules.items() if (found := RULES[rule](m))}
    assert broken == {}


def _module(detect=None, **check):
    raw_check = {
        "key": "web",
        "name": "Web",
        "sensor": "http",
        "target": {"kind": "container"},
        "interval": 900,
        "fields": ["status_code"],
    }
    raw_check.update(check)
    raw = {
        "id": "app",
        "name": "App",
        "version": 1,
        "detect": detect or {"container_images": ["example/app"]},
        "instance": "container",
        "checks": [raw_check],
    }
    catalog = load_catalog([("app", raw)])
    assert catalog.errors == ()
    return catalog.modules["app"]


@pytest.mark.parametrize(
    ("rule", "module"),
    [
        ("trap", {"params": {"path": "/colibri/../move-endpoints/x"}}),
        ("trap", {"params": {"path": "/admin/"}}),
        ("trap", {"params": {"path": "/Admin/cron.php"}}),
        ("trap", {"params": {"path": "/wp-cron.php?doing_wp_cron"}}),
        ("trap", {"params": {"path": "/api/push/abc"}}),
        ("trap", {"params": {"path": "/internal/cluster/inactive"}}),
        ("trap", {"params": {"path": "/api/v4/system/ping?get_server_status=true"}}),
        ("trap", {"params": {"path": "/api/login"}}),
        (
            "trap",
            {
                "sensor": "unixsocket",
                "target": None,
                "params": {"path": "/run/app.sock", "protocol": "http", "http_path": "/admin"},
            },
        ),
        ("test_object", {"params": {"path": "/healthcheck"}}),
        ("test_object", {"params": {"path": "/status?x=1"}}),
        ("loopback", {"target": {"kind": "loopback", "port_hint": 80}}),
        ("generic_detect", {"detect": {"container_images": ["docker.io/library/postgres:16"]}}),
        ("generic_detect", {"detect": {"container_images": ["redis"]}}),
        ("generic_detect", {"detect": {"units": ["nginx.service"]}}),
        ("generic_detect", {"detect": {"units": ["php8.2-fpm"]}}),
        ("generic_detect", {"detect": {"processes": ["java"]}}),
    ],
)
def test_each_rule_catches_a_module_that_breaks_it(rule, module):
    detect = module.pop("detect", None)
    assert RULES[rule](_module(detect, **module))


def test_a_module_that_keeps_the_rules_passes_them():
    module = _module(
        {"container_images": ["ghcr.io/example/app"], "units": ["app-web.service"]},
        params={"path": "/healthcheck"},
        test_object=True,
    )
    assert {rule: check(module) for rule, check in RULES.items()} == dict.fromkeys(RULES, [])
