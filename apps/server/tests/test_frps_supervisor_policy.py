# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The frps supervisor (apps/frps/frps-supervisor.sh) and its plugin frps-policy: before every
start of frps it sees to it that the plugin serves on 127.0.0.1, at FRPS_POLICY_PORT or the next
port up that bindPort, vhostHTTPSPort and webServer.port of the copy leave free, started as a
user of its own (FRPS_POLICY_USER: no root, neither the UID of frps nor that of the requests to
the dashboard, outside the group of frps) and given FRPS_READ_SECONDS to answer on /healthz;
frps starts either way. Its copy of frps.toml ends in a fixed [[httpPlugins]] block for that
port (op NewProxy), which an input must not carry itself and a copy from an earlier run must
carry as it does. Every poll asks /healthz again; a plugin that does not answer is KILLed and
started anew, with a log line. The plugin runs until the supervisor ends, through restarts of
frps; it moves along when a new copy takes its port.

The tests run the script as test_frps_supervisor.py does (Box, a stub frps, the stub plugin at a
port of the test's own). Those on the frps image run the real plugin there; the real frps
verify passing a copy with the block is in test_frps_supervisor.py
(test_in_the_frps_image_frps_starts_only_from_a_checked_copy)."""

import contextlib
import os
import pwd
import re
import shutil
import signal
import socket
import subprocess
import time
import uuid

import pytest

from app.modules.frp.config_generator import generate_frps_toml

from . import test_frps_supervisor as _supervisor
from .test_frps_supervisor import (
    ACTIVE_DIR,
    FRPS_DIR,
    SCRIPT,
    STARTED_SUCCESSFULLY,
    SU_EXEC,
    WAIT,
    Box,
    _alive,
    _as_user,
    _built_frps_image,
    _cfg,
    _compose_frps,
    _container,
    _plugin_block,
    _polling,
    _security_args,
    _session,
    _toml,
    _wait_gone,
)

# pytest takes the fixtures of a module from its names; bound by assignment, the parameters of
# the same name do not shadow an import.
box = _supervisor.box
pems = _supervisor.pems


def _plugin_started(box: Box) -> int:
    """How often the log says the plugin was started."""
    return box._log().count("frps-policy started on ")


def _wait_plugins(box: Box, count: int) -> list[int]:
    box.wait_until(lambda: len(box.policy_pids()) >= count, f"{count} plugins up")
    return box.policy_pids()


def _listen(port: int, box: Box) -> str:
    """The arguments of a start of the plugin at port, as the stub records them."""
    return f"-listen 127.0.0.1:{port} -path /handler -policy {box.config.parent}/frps-policy.json"


def _free_ports(count: int) -> int:
    """The first of count ports in a row on 127.0.0.1 that nothing listens at just now."""
    for _ in range(50):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            first = probe.getsockname()[1]
        if first + count - 1 > 65535:
            continue
        with contextlib.ExitStack() as stack:
            try:
                for port in range(first, first + count):
                    stack.enter_context(socket.socket()).bind(("127.0.0.1", port))
            except OSError:
                continue
            return first
    pytest.fail(f"no {count} free ports in a row")


def test_the_plugin_serves_before_frps_starts_and_the_copy_points_frps_at_it(box):
    box.write_input()

    box.run(frps=True)

    assert (box.read().state, box.read().reason) == ("running", "none")
    expected = box.copy_of(box.config.read_text())
    assert (box.current / "frps.toml").read_text() == expected
    assert (box.stub / "verified.toml").read_text() == expected
    # At the port of the test and with the policy next to frps.toml, once.
    assert box.policy_calls() == [_listen(box.policy_port, box)]
    log = box._log()
    started = log.index(f"frps-policy started on 127.0.0.1:{box.policy_port} (pid ")
    assert started < log.index("frps started from ")
    assert "does not answer" not in log
    assert [p.name for p in box.active.iterdir()] == ["current"]


def test_the_plugin_reads_the_policy_it_is_given(box):
    policy = box.root / "elsewhere" / "policy.json"
    box.env["FRPS_POLICY"] = str(policy)
    box.write_input()

    box.run(frps=True)

    (call,) = box.policy_calls()
    assert call.endswith(f" -policy {policy}")


def test_without_a_valid_input_no_plugin_starts(box):
    box.run(frps=False)

    assert (box.read().state, box.read().reason) == ("waiting", "config_missing")
    assert box.policy_calls() == []
    assert "frps-policy" not in box._log()


# Ports of the input, as offsets from FRPS_POLICY_PORT, and where the plugin serves then.
PORTS = {
    "bindPort": ({"bind_port": 0}, 1),
    "vhostHTTPSPort": ({"vhost_https_port": 0}, 1),
    "webServer.port": ({"dashboard_port": 0}, 1),
    "all three in a row": ({"bind_port": 0, "vhost_https_port": 1, "dashboard_port": 2}, 3),
    "all three in another order": (
        {"dashboard_port": 0, "bind_port": 1, "vhost_https_port": 2},
        3,
    ),
    "with a gap": ({"bind_port": 0, "dashboard_port": 2}, 1),
    "ports above alone": ({"bind_port": 1, "vhost_https_port": 2}, 0),
}


@pytest.mark.parametrize("case", list(PORTS))
def test_the_plugin_gives_way_to_the_ports_of_the_copy(box, case):
    offsets, shift = PORTS[case]
    # The port the plugin ends up at is one nothing listens at.
    port = _free_ports(1)
    base = port - shift
    box.env["FRPS_POLICY_PORT"] = str(base)
    box.policy_port = port
    box.write_input(_toml(box.pki, **{key: base + off for key, off in offsets.items()}))

    box.run(frps=True)

    assert (box.current / "frps.toml").read_text() == box.copy_of(box.config.read_text())
    assert box.policy_calls() == [_listen(port, box)]
    assert "does not answer" not in box._log()


def test_the_plugin_gives_way_to_a_port_as_frps_reads_the_number(box):
    port = _free_ports(2)
    box.env["FRPS_POLICY_PORT"] = str(port)
    box.policy_port = port + 1
    # +P.0 is P to frps, and the layout lets it through as long as it is no port it refuses.
    toml = _toml(box.pki, dashboard_port=port).replace(
        f"webServer.port = {port}", f"webServer.port = +{port}.0"
    )
    box.write_input(toml)

    box.run(frps=True)

    assert (box.current / "frps.toml").read_text() == box.copy_of(toml)
    assert box.policy_calls() == [_listen(port + 1, box)]


def test_the_plugin_goes_up_to_65535_from_the_highest_port_allowed(box):
    box.env["FRPS_POLICY_PORT"] = "65532"
    box.policy_port = 65535
    box.write_input(_toml(box.pki, bind_port=65532, vhost_https_port=65533, dashboard_port=65534))

    box.run(frps=True)

    # Whether the stub gets the port or not: frps starts, its copy names the plugin there.
    assert (box.current / "frps.toml").read_text() == box.copy_of(box.config.read_text())
    assert "frps-policy started on 127.0.0.1:65535 (pid " in box._log()


# A [[httpPlugins]] block the input brings along, for the port of the plugin: one of its own,
# the very one the supervisor appends and that one with ops beyond NewProxy.
INBOUND = {
    "foreign": lambda port: (
        f'\n[[httpPlugins]]\nname = "own"\naddr = "127.0.0.1:{port}"\npath = "/h"\n'
        'ops = ["Login"]\n'
    ),
    "as the supervisor appends it": _plugin_block,
    "with more ops": lambda port: _plugin_block(port).replace(
        'ops = ["NewProxy"]', 'ops = ["NewProxy", "Login"]'
    ),
}


@pytest.mark.parametrize("case", list(INBOUND))
def test_an_input_with_a_plugin_block_of_its_own_starts_nothing(box, case):
    box.write_input()
    box.config.write_text(box.config.read_text() + INBOUND[case](box.policy_port))

    box.run(frps=False)

    status = box.read()
    assert (status.state, status.reason, status.events) == ("waiting", "verify_failed", ())
    assert box.calls() == []
    assert box.policy_calls() == []


def _strip_block(box: Box):
    copy = box.current / "frps.toml"
    text = copy.read_text()
    block = _plugin_block(box.policy_port)
    assert text.endswith(block)
    copy.write_text(text.removesuffix(block))


def _block_elsewhere(box: Box):
    copy = box.current / "frps.toml"
    text = copy.read_text()
    copy.write_text(
        text.replace(
            f'addr = "127.0.0.1:{box.policy_port}"', f'addr = "127.0.0.1:{box.policy_port + 1}"'
        )
    )


def _block_twice(box: Box):
    copy = box.current / "frps.toml"
    copy.write_text(copy.read_text() + _plugin_block(box.policy_port))


def _no_ops(box: Box):
    copy = box.current / "frps.toml"
    copy.write_text(copy.read_text().replace('ops = ["NewProxy"]\n', ""))


# Copies an earlier run left: one from before the plugin, one whose block names another port
# (FRPS_POLICY_PORT changed since), one with the block twice, one with the block cut short.
OLD_COPIES = {
    "without the block": _strip_block,
    "the block at another port": _block_elsewhere,
    "the block twice": _block_twice,
    "the block without ops": _no_ops,
}


@pytest.mark.parametrize("case", list(OLD_COPIES))
def test_a_copy_from_an_earlier_run_without_the_block_as_appended_goes(box, case):
    box.write_input()
    box.run(frps=True)
    box.stop()
    OLD_COPIES[case](box)
    # An invalid input: the copy alone could start frps.
    box.write_input(pems={"frps.crt": box.pems["expired.crt"]})
    (box.stub / "policy-calls").unlink()

    box.run(frps=False)

    status = box.read()
    assert (status.state, status.reason, status.events) == ("waiting", "cert_expired", ())
    assert box.runs() == 0
    assert list(box.active.iterdir()) == []
    assert "fails the check and goes" in box._log()
    assert box.policy_calls() == []


def test_a_copy_from_an_earlier_run_with_the_block_starts_frps_again(box):
    box.write_input()
    box.run(frps=True)
    box.stop()
    box.write_input(pems={"frps.crt": box.pems["expired.crt"]})

    box.run(frps=True)

    assert (box.read().state, box.read().reason) == ("degraded", "cert_expired")
    assert len(box.policy_calls()) == 2


def test_frps_that_exits_starts_again_and_the_plugin_runs_on(box):
    _polling(box)
    (plugin,) = _wait_plugins(box, 1)
    box.wait_until(box.pids, "frps up")

    os.kill(box.pids()[0], signal.SIGKILL)

    box.wait_until(lambda: len(box.pids()) == 2, "frps up again")
    assert box.policy_pids() == [plugin] and _alive(plugin)
    assert _plugin_started(box) == 1
    assert "did not answer" not in box._log()


def test_a_removed_input_stops_frps_and_the_plugin_runs_on(box):
    _polling(box)
    (plugin,) = _wait_plugins(box, 1)

    box.config.unlink()
    box.wait_state("stopped")
    box.write_input()
    box.wait_until(lambda: box.runs() == 2, "frps up again")

    assert box.policy_pids() == [plugin] and _alive(plugin)
    assert _plugin_started(box) == 1


def test_a_new_copy_that_takes_the_port_of_the_plugin_moves_it(box):
    port = _free_ports(2)
    box.env["FRPS_POLICY_PORT"] = str(port)
    box.policy_port = port
    _polling(box)
    (plugin,) = _wait_plugins(box, 1)

    box.write_input(_toml(box.pki, dashboard_port=port))
    box.wait_until(lambda: box.runs() == 2, "frps up from the new copy")

    box.policy_port = port + 1
    assert (box.current / "frps.toml").read_text() == box.copy_of(box.config.read_text())
    assert box.policy_calls() == [_listen(port, box), _listen(port + 1, box)]
    assert not _alive(plugin)
    # Moved, not found dead.
    assert "did not answer" not in box._log()


def test_a_plugin_that_ended_is_started_anew_at_the_next_poll(box):
    _polling(box)
    (plugin,) = _wait_plugins(box, 1)

    os.kill(plugin, signal.SIGKILL)

    (_, again) = _wait_plugins(box, 2)
    assert not _alive(plugin) and _alive(again)
    assert "frps-policy did not answer, restarting it" in box._log()
    assert box.policy_calls() == [_listen(box.policy_port, box)] * 2
    # frps is left alone.
    assert box.runs() == 1 and len(box.pids()) == 1


def test_a_plugin_that_hangs_is_killed_and_started_anew(box):
    _polling(box, FRPS_READ_SECONDS="1")
    (plugin,) = _wait_plugins(box, 1)

    (box.stub / "policy-hangs").write_text(f"{plugin}\n")

    (_, again) = _wait_plugins(box, 2)
    box.wait_until(lambda: not _alive(plugin), "the hanging plugin gone")
    assert _alive(again)
    assert "frps-policy did not answer, restarting it" in box._log()
    assert box.runs() == 1 and len(box.pids()) == 1


# Stands in for frps-policy: ends at once, so it never answers.
DEAD_PLUGIN = """#!/bin/sh
exit 1
"""


def test_frps_starts_while_the_plugin_does_not_answer_and_each_poll_tries_again(box):
    dead = box.root / "dead-policy"
    dead.write_text(DEAD_PLUGIN)
    dead.chmod(0o755)
    box.env["FRPS_POLICY_BIN"] = str(dead)

    _polling(box, FRPS_READ_SECONDS="1")
    box.wait_until(lambda: box._log().count("did not answer, restarting it") >= 2, "two tries")

    # frps registers no proxy then; it runs, so that it can once the plugin answers.
    assert (box.read().state, box.read().reason) == ("running", "none")
    assert box.runs() == 1
    assert f"frps-policy does not answer on 127.0.0.1:{box.policy_port}" in box._log()


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT], ids=["TERM", "INT"])
def test_the_plugin_ends_with_the_supervisor(box, sig):
    box.write_input()
    box.run(frps=True)
    (plugin,) = _wait_plugins(box, 1)

    box.supervisor.send_signal(sig)

    assert box.supervisor.wait(timeout=WAIT) == 0
    _wait_gone(box.supervisor.pid)
    assert not _alive(plugin)


def test_a_signal_while_the_plugin_hangs_ends_the_check_at_once(box):
    _polling(box, FRPS_READ_SECONDS="30")
    (plugin,) = _wait_plugins(box, 1)
    (box.stub / "policy-hangs").write_text(f"{plugin}\n")
    # A poll under way, its check held by the plugin: past the pause of a second between polls,
    # the request is still there.
    time.sleep(2.5)
    assert any("(curl)" in line for line in _session(box.supervisor.pid)), box._log()

    box.supervisor.send_signal(signal.SIGTERM)

    assert box.supervisor.wait(timeout=WAIT) == 0
    _wait_gone(box.supervisor.pid)


@pytest.mark.parametrize("value", ["0", "07480", "-1", "x", "7480x", "65533", "100000"])
def test_a_plugin_port_that_is_no_port_up_to_65532_stops_the_supervisor(box, value):
    box.write_input()
    box.env["FRPS_POLICY_PORT"] = value

    result = box.once()

    assert result.returncode == 1, result.stderr
    assert "FRPS_POLICY_PORT must be a port number up to 65532" in result.stderr
    assert box.calls() == [] and not box.status_file.exists()


def test_a_plugin_port_of_65532_passes_the_start_check(box):
    box.env["FRPS_POLICY_PORT"] = "65532"

    box.run(frps=False)

    assert box.read().state == "waiting"


# Stands in for id: knows one user more, policy-test, with the UID and the groups the test gives
# it (none: id -G fails), and leaves every other question to the real id.
ID = """#!/bin/sh
case "$*" in
"-u policy-test") echo {uid} ;;
"-G policy-test") [ -n "{groups}" ] && echo "{groups}" ;;
*) exec {real} "$@" ;;
esac
"""


def _policy_user(box: Box, uid: int, groups: str):
    real = shutil.which("id")
    assert real, "id"
    stub = box.root / "bin" / "id"
    stub.write_text(ID.format(uid=uid, groups=groups, real=real))
    stub.chmod(0o755)
    box.env["FRPS_POLICY_USER"] = "policy-test"


def _own_user() -> str:
    return pwd.getpwuid(os.getuid()).pw_name


@pytest.mark.parametrize(
    ("case", "error"),
    [
        ("root", "must not be root"),
        ("no user", "no-such-user-for-the-plugin is no user"),
        ("the user of frps", "must not share the UID of FRPS_USER"),
        ("the user of the requests", "must not share the UID of FRPS_FETCH_USER"),
        ("in the primary group of frps", "must not be in the group of FRPS_USER"),
        ("in a supplementary group of frps", "must not be in the group of FRPS_USER"),
        ("in no group", "policy-test has no group"),
    ],
)
def test_a_plugin_user_that_could_reach_frps_or_the_dashboard_stops_the_supervisor(
    box, case, error
):
    gid = pwd.getpwuid(os.getuid()).pw_gid
    if case == "root":
        box.env["FRPS_POLICY_USER"] = "root"
    elif case == "no user":
        box.env["FRPS_POLICY_USER"] = "no-such-user-for-the-plugin"
    elif case == "the user of frps":
        _as_user(box)
        box.env["FRPS_POLICY_USER"] = _own_user()
    elif case == "the user of the requests":
        box.env["FRPS_FETCH_USER"] = _own_user()
        box.env["FRPS_POLICY_USER"] = _own_user()
    else:
        _as_user(box)
        groups = {
            "in the primary group of frps": f"{gid}",
            "in a supplementary group of frps": f"{gid + 1} {gid}",
            "in no group": "",
        }[case]
        _policy_user(box, os.getuid() + 2, groups)
    box.write_input()

    result = box.once()

    assert result.returncode == 1, result.stderr
    assert f"FRPS_POLICY_USER {error}" in result.stderr
    assert box.calls() == [] and not box.status_file.exists()


# Stands in for su-exec as SU_EXEC does, and runs the plugin, too.
SU_EXEC_POLICY = SU_EXEC.replace("frps | curl)", "frps | curl | frps-policy)")


def test_the_plugin_runs_as_its_user_through_su_exec(box):
    assert SU_EXEC_POLICY != SU_EXEC
    _as_user(box)
    (box.root / "bin" / "su-exec").write_text(SU_EXEC_POLICY)
    gid = pwd.getpwuid(os.getuid()).pw_gid
    # Groups whose numbers hold that of the group of frps, none of them that group.
    _policy_user(box, os.getuid() + 2, f"{gid}0 1{gid} {gid + 1}")
    box.write_input()

    box.run(frps=True)

    record = (box.stub / "su-exec").read_text().splitlines()
    assert f"policy-test frps-policy {_listen(box.policy_port, box)}" in record
    assert box.policy_calls() == [_listen(box.policy_port, box)]


def _default_policy_user() -> tuple[str, int]:
    """Name and UID of the user the plugin runs as by default, as the image creates it."""
    default = re.search(
        r'^FRPS_POLICY_USER="\$\{FRPS_POLICY_USER-(\S+)\}"$', SCRIPT.read_text(), re.M
    )
    assert default, "no default for FRPS_POLICY_USER"
    dockerfile = (FRPS_DIR / "Dockerfile").read_text()
    name = re.escape(default[1])
    found = re.search(rf"\badduser\b.* -u (\d+) -G {name} {name}(?: |$)", dockerfile, re.M)
    assert found, dockerfile
    return default[1], int(found[1])


@pytest.fixture(scope="module")
def frps_image():
    yield from _built_frps_image()


def test_in_the_frps_image_the_plugin_runs_as_its_user_before_frps_starts(
    tmp_path, pems, frps_image
):
    _, uid = _default_policy_user()
    toml = generate_frps_toml(_cfg())
    with _container(frps_image, tmp_path, pems, toml) as box:
        box.wait_until(lambda: STARTED_SUCCESSFULLY in box.logs(), "frps started")
        logs = box.logs()
        assert (box.read().state, box.read().reason) == ("running", "none"), logs
        assert [name for name, _, _ in box.processes(uid)] == ["frps-policy"], logs
        started = logs.index("frps-policy started on 127.0.0.1:7480 (pid ")
        assert started < logs.index("frps started from ")
        assert "does not answer" not in logs
        copy = box.exec("cat", f"{ACTIVE_DIR}/current/frps.toml")
        assert copy.stdout.endswith(
            'addr = "127.0.0.1:7480"\npath = "/handler"\nops = ["NewProxy"]\n'
        )


def test_in_the_frps_image_the_supervisor_does_not_run_the_plugin_as_root(frps_image):
    docker, tag = frps_image
    name = f"frps-supervisor-test-{uuid.uuid4().hex[:12]}"
    run = [docker, "run", "--name", name, "--network", "none", *_security_args(_compose_frps())]
    run += ["-e", "FRPS_POLICY_USER=", tag]
    try:
        result = subprocess.run(run, capture_output=True, text=True, timeout=WAIT * 3)
    finally:
        subprocess.run([docker, "rm", "-f", name], capture_output=True)

    assert result.returncode == 1 and "FRPS_POLICY_USER" in result.stderr, result.stderr
