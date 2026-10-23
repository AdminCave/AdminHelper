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

The tunnel edge network frpedge, on which frps sits alone, runs without IP masquerading: frps
only accepts connections, so its published ports keep working, and the packets it sends itself
leave the host with the container's address. The other networks keep Docker's default.

Only the base file is read: docker-compose.test.yml carries `!override`, which `yaml.safe_load`
refuses, and the shipped topology is the base file anyway.
"""

from pathlib import Path

import yaml

_COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"
_NO_NEW_PRIVILEGES = "no-new-privileges:true"
_MASQUERADE = "com.docker.network.bridge.enable_ip_masquerade"


def _compose() -> dict:
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))


def _services() -> dict:
    return _compose()["services"]


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


def test_frpedge_runs_without_ip_masquerading_and_holds_frps_alone():
    compose = _compose()
    frpedge = compose["networks"]["frpedge"] or {}
    on_frpedge = {
        name
        for name, service in compose["services"].items()
        if "frpedge" in service.get("networks", [])
    }

    # The string: compose refuses a YAML bool as a driver option.
    assert (frpedge.get("driver_opts") or {}).get(_MASQUERADE) == "false"
    # Not internal: frps is the public edge and needs its published ports.
    assert frpedge.get("internal", False) is False
    assert on_frpedge == {"frps"}


def test_the_other_networks_keep_ip_masquerading():
    networks = _compose()["networks"]
    options = {name: (networks[name] or {}).get("driver_opts") or {} for name in ("default", "pki")}
    assert {name: opts[_MASQUERADE] for name, opts in options.items() if _MASQUERADE in opts} == {}
