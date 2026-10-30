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

Every service also has a memory limit (mem_limit), far above what it needs idle, so that a leak or
a runaway query uses up its own container's memory and not the host's.

The monitoring checks run `ping` as the image's app user. Under no-new-privileges a setuid or
file-capability `ping` gains nothing and falls back to ICMP datagram sockets, which the kernel
grants only to the groups in net.ipv4.ping_group_range; compose sets the range itself, whatever
the engine defaults to.

The tunnel edge network frpedge, on which frps sits alone, runs without IP masquerading: frps
only accepts connections, so its published ports keep working, and the packets it sends itself
leave the host with the container's address. The other networks keep Docker's default.

The CA root passphrase reaches the ca-issuer as a compose secret, a file under /run/secrets, and
not as an environment variable: no service's environment carries it, so it stays out of
`docker inspect` and /proc/<pid>/environ. Compose takes the secret from CA_ROOT_PASSPHRASE in
the project's .env; without that line `docker compose up` aborts, so .env.example keeps it
active (update.sh adds missing active lines to an existing .env). Compose leaves a secret's
content out of the configuration hash it compares on `up`, so the ca-issuer carries a label that
only says whether a value is set: emptying the value changes the label, `up -d` recreates the
container, and the old passphrase file goes with it.

The server always trusts the gateway service, by its name, to forward the client address:
compose puts `gateway` in front of whatever TRUSTED_PROXIES the .env adds, so the per-address
rate limits, ALLOWED_IPS and the audit log see the client rather than the gateway. The
scheduler runs the same image but takes no HTTP requests and trusts no proxy.

Only the base file is read: docker-compose.test.yml carries `!override`, which `yaml.safe_load`
refuses, and the shipped topology is the base file anyway.
"""

import re
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_COMPOSE = _ROOT / "docker-compose.yml"
_ENV_EXAMPLE = _ROOT / ".env.example"
_NO_NEW_PRIVILEGES = "no-new-privileges:true"
_MASQUERADE = "com.docker.network.bridge.enable_ip_masquerade"
_PASSPHRASE_SECRET = "ca_root_passphrase"
_PASSPHRASE_LABEL = "com.admincave.adminhelper.ca-root-passphrase-present"
# ${VAR:+word}: `word` when the value is set and not empty, else nothing. Unset or empty, the
# server trusts the gateway alone; set, the gateway and the entries of the .env.
_SERVER_TRUSTED_PROXIES = "gateway${TRUSTED_PROXIES:+,${TRUSTED_PROXIES}}"
# Compose reads the units of a byte value as powers of 1024: 8g is 8 GiB.
_BYTE_UNITS = {"k": 1024, "m": 1024**2, "g": 1024**3}


def _compose() -> dict:
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))


def _services() -> dict:
    return _compose()["services"]


def _entries(service: dict, key: str) -> dict[str, str]:
    """A service's `environment:` or `labels:`, list form (`- KEY=value`) or mapping form."""
    entries = service.get(key) or {}
    if isinstance(entries, dict):
        return {name: "" if value is None else str(value) for name, value in entries.items()}
    return dict(entry.split("=", 1) if "=" in entry else (entry, "") for entry in entries)


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


def test_every_service_has_a_memory_limit_of_at_least_128m():
    limits = {name: service.get("mem_limit") for name, service in _services().items()}

    malformed = {
        name: limit
        for name, limit in limits.items()
        if not (isinstance(limit, str) and re.fullmatch(r"[1-9][0-9]*[kmg]", limit))
    }
    assert malformed == {}
    sizes = {name: int(limit[:-1]) * _BYTE_UNITS[limit[-1]] for name, limit in limits.items()}
    assert {name: limit for name, limit in limits.items() if sizes[name] < 128 * 1024**2} == {}


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


def test_no_service_carries_the_ca_root_passphrase_in_its_environment():
    carriers = {
        name
        for name, service in _services().items()
        if "CA_ROOT_PASSPHRASE" in _entries(service, "environment")
    }
    assert carriers == set()


def test_the_ca_issuer_reads_the_passphrase_from_a_secret_taken_from_the_env_file():
    compose = _compose()
    ca_issuer = compose["services"]["ca-issuer"]

    assert (
        _entries(ca_issuer, "environment").get("CA_ROOT_PASSPHRASE_FILE")
        == f"/run/secrets/{_PASSPHRASE_SECRET}"
    )
    # The short form: compose mounts it as /run/secrets/<name>, the path above.
    assert _PASSPHRASE_SECRET in ca_issuer.get("secrets", [])
    assert (compose.get("secrets") or {}).get(_PASSPHRASE_SECRET) == {
        "environment": "CA_ROOT_PASSPHRASE"
    }


def test_emptying_the_passphrase_changes_a_label_of_the_ca_issuer():
    label = _entries(_services()["ca-issuer"], "labels").get(_PASSPHRASE_LABEL, "")

    # ${VAR:+word}: `word` when the value is set and not empty, else the empty string. The
    # word must not be the value itself, or the passphrase would land in the labels.
    assert re.fullmatch(r"\$\{CA_ROOT_PASSPHRASE:\+[^${}]+\}", label), (
        f"{_PASSPHRASE_LABEL}: {label!r}"
    )


def test_env_example_keeps_the_passphrase_line_active_and_empty():
    lines = _ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    assert [line for line in lines if line.startswith("CA_ROOT_PASSPHRASE=")] == [
        "CA_ROOT_PASSPHRASE="
    ]


def test_the_server_always_trusts_the_gateway_and_takes_further_proxies_from_the_env_file():
    environment = _entries(_services()["server"], "environment")
    assert environment.get("TRUSTED_PROXIES") == _SERVER_TRUSTED_PROXIES


def test_the_scheduler_trusts_no_proxy():
    assert "TRUSTED_PROXIES" not in _entries(_services()["scheduler"], "environment")


def _commented_service(name: str) -> dict:
    """A service the compose file ships commented out (`# name:` plus its `#   key: value`
    lines up to the blank line): yaml.safe_load drops comments, so the tests above never see
    it, and whoever uncomments it takes it over exactly as written."""
    block: list[str] = []
    for line in _COMPOSE.read_text(encoding="utf-8").splitlines():
        if line == f"  # {name}:":
            block = [f"  {name}:"]
        elif block and line.startswith("  #   "):
            block.append("  " + line[4:])
        elif block:
            break
    assert block, f"no commented-out service {name} in {_COMPOSE.name}"
    return yaml.safe_load("services:\n" + "\n".join(block))["services"][name]


def test_the_commented_out_pg_backup_carries_the_hardening_of_the_active_services():
    service = _commented_service("pg-backup")

    assert _NO_NEW_PRIVILEGES in service.get("security_opt", [])
    limit = service.get("pids_limit")
    assert type(limit) is int and limit >= 128
    memory = service.get("mem_limit")
    assert isinstance(memory, str) and re.fullmatch(r"[1-9][0-9]*[kmg]", memory)
    assert int(memory[:-1]) * _BYTE_UNITS[memory[-1]] >= 128 * 1024**2
