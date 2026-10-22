# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Limits compose sets on every service of the shipped stack.

No process in any container gains privileges on exec (no-new-privileges): setuid bits and file
capabilities stay without effect. The entrypoints that drop to an unprivileged user (gosu,
su-exec, nginx's workers) do so from root through system calls and are not affected.

Every service has a process limit (pids_limit), generous by the structure of the service, so
that a runaway process (a hook script that forks without end, say) exhausts its own container
and not the host. The server's must leave room for one thread pool per uvicorn worker and the
hook processes on top.

The monitoring checks run `ping` as the image's app user. Under no-new-privileges a setuid or
file-capability `ping` gains nothing and falls back to ICMP datagram sockets, which the kernel
grants only to the groups in net.ipv4.ping_group_range; compose sets the range itself, whatever
the engine defaults to.

Only the base file is read: docker-compose.test.yml carries `!override`, which `yaml.safe_load`
refuses, and the shipped topology is the base file anyway.
"""

from pathlib import Path

import yaml

_COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"
_NO_NEW_PRIVILEGES = "no-new-privileges:true"


def _services() -> dict:
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))["services"]


def test_no_process_in_any_service_gains_privileges_on_exec():
    services = _services()
    hardened = {
        name
        for name, service in services.items()
        if _NO_NEW_PRIVILEGES in service.get("security_opt", [])
    }
    assert hardened == set(services)


def test_every_service_has_a_process_limit_and_the_server_room_for_its_workers():
    limits = {name: service.get("pids_limit") for name, service in _services().items()}

    # type() rather than isinstance(): a YAML `true` is a bool, which isinstance counts as int.
    assert {name: limit for name, limit in limits.items() if type(limit) is not int} == {}
    assert {name: limit for name, limit in limits.items() if limit < 128} == {}
    assert limits["server"] >= 2048


def test_the_monitoring_app_user_may_open_icmp_datagram_sockets():
    sysctls = _services()["monitoring"].get("sysctls", {})
    assert sysctls.get("net.ipv4.ping_group_range") == "0 2147483647"
