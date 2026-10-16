# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Compose runs frps from its own image (apps/frps) under the supervisor.

frps mounts its input read-only: frp-config with nocopy, so that it holds what the server
writes and nothing else, and frps-certs. It writes two volumes of its own: frps-state, which
the server and the scheduler mount read-only to read the status file, and frps-active, which
holds the checked copy with token and key and which no other service mounts.

frps keeps a single capability: the supervisor runs as root and reads frps.toml and frps.key,
which the server and the ca-issuer write 0600 under their own UID. Port 443 inside needs none,
since Docker opens every port to unprivileged processes in a container's own network namespace
(net.ipv4.ip_unprivileged_port_start=0). The server and the scheduler run as the app user of
their image, so they read the status through the bits the supervisor grants everyone.

A TERM while the supervisor stops frps waits for frps a second time, so the grace period
outlasts two stops. The health check runs the supervisor's health subcommand, nothing else.

Only docker-compose.test.yml needs a loader of its own: it carries `!override`, which
`yaml.safe_load` refuses. One test runs the frps image with the settings compose gives it; it
skips when Docker or the pinned base image is not at hand.
"""

import contextlib
import os
import re
import shutil
import signal
import stat
import subprocess
import time
import uuid
from pathlib import Path

import pytest
import yaml

from app.modules.frp.config_generator import generate_frps_toml
from app.modules.frp.supervisor_status import read_supervisor_status

from .test_frps_supervisor import (
    PEMS,
    SCRIPT,
    STARTED_SUCCESSFULLY,
    TOKEN,
    WAIT,
    _cert_pem,
    _cfg,
    _image,
    _key,
    _key_pem,
)

_ROOT = Path(__file__).resolve().parents[3]
_COMPOSE = _ROOT / "docker-compose.yml"
_COMPOSE_TEST = _ROOT / "docker-compose.test.yml"
_ENV_EXAMPLE = _ROOT / ".env.example"
_FRPS_IMAGE = "${FRPS_IMAGE:-ghcr.io/admincave/adminhelper/frps:latest}"
_BIND_PORT = "${FRP_BIND_PORT:-7000}"
# Where the server and the scheduler find the status file.
_STATE_MOUNT = "/app/frps-state"


class _TestLoader(yaml.SafeLoader):
    """Reads compose's `!override` as the plain node it marks."""


def _plain(loader: yaml.SafeLoader, node: yaml.Node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return loader.construct_scalar(node)


_TestLoader.add_constructor("!override", _plain)


def _compose() -> dict:
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))


def _services() -> dict:
    return _compose()["services"]


def _mounts(service: dict) -> dict[str, tuple[str, bool, bool]]:
    """Mount target -> (source, read-only, nocopy), from the short and the long syntax."""
    out = {}
    for entry in service.get("volumes", []):
        if isinstance(entry, str):
            source, target, *mode = entry.split(":")
            flags = set(mode[0].split(",")) if mode else set()
            out[target] = (source, "ro" in flags, "nocopy" in flags)
        else:
            nocopy = entry.get("volume", {}).get("nocopy", False)
            out[entry["target"]] = (entry["source"], entry.get("read_only", False), nocopy)
    return out


def _environment(service: dict) -> dict[str, str]:
    return dict(entry.split("=", 1) for entry in service.get("environment", []))


def _script_default(name: str) -> str:
    """The default the supervisor gives one of its settings."""
    found = re.search(rf'^{name}="\$\{{{name}:-(.+)\}}"$', SCRIPT.read_text(), re.M)
    assert found, name
    return found[1]


def _seconds(duration: str) -> int:
    found = re.fullmatch(r"(\d+)s", duration)
    assert found, duration
    return int(found[1])


def test_frps_runs_from_its_own_image():
    assert _services()["frps"]["image"] == _FRPS_IMAGE


def test_frps_reads_its_input_read_only_and_writes_two_volumes_of_its_own():
    frps = _services()["frps"]
    config_dir = str(Path(_script_default("FRPS_CONFIG")).parent)

    assert _mounts(frps) == {
        config_dir: ("frp-config", True, True),
        _script_default("FRPS_PKI_DIR"): ("frps-certs", True, False),
        _script_default("FRPS_STATE_DIR"): ("frps-state", False, False),
        _script_default("FRPS_ACTIVE_DIR"): ("frps-active", False, False),
    }
    long_form = [entry for entry in frps["volumes"] if isinstance(entry, dict)]
    assert [entry["type"] for entry in long_form] == ["volume"] * len(long_form)
    assert {"frps-state", "frps-active"} <= set(_compose()["volumes"])


def test_only_frps_mounts_its_working_copy():
    holders = {
        name
        for name, service in _services().items()
        for source, _, _ in _mounts(service).values()
        if source == "frps-active"
    }
    assert holders == {"frps"}


def test_server_and_scheduler_read_the_status_and_know_the_published_port():
    services = _services()
    readers = {
        name: (target, read_only)
        for name, service in services.items()
        if name != "frps"
        for target, (source, read_only, _) in _mounts(service).items()
        if source == "frps-state"
    }

    assert readers == {"server": (_STATE_MOUNT, True), "scheduler": (_STATE_MOUNT, True)}
    for name in ("server", "scheduler"):
        env = _environment(services[name])
        assert env["FRPS_STATE_DIR"] == _STATE_MOUNT, name
        assert env["FRP_BIND_PORT"] == _BIND_PORT, name
    assert _environment(services["frps"])["FRP_BIND_PORT"] == _BIND_PORT
    assert f"{_BIND_PORT}:{_BIND_PORT}" in services["frps"]["ports"]


def test_frps_keeps_only_the_capability_to_read_its_input():
    frps = _services()["frps"]
    assert frps["cap_drop"] == ["ALL"]
    assert frps["cap_add"] == ["DAC_OVERRIDE"]


def test_the_grace_period_outlasts_a_term_while_frps_is_being_stopped():
    stop = int(_script_default("FRPS_STOP_SECONDS"))
    # Twice FRPS_STOP_SECONDS, and the one-second steps the supervisor waits in, with room.
    assert _seconds(_services()["frps"]["stop_grace_period"]) >= 2 * stop + 5


def test_the_health_check_runs_the_supervisor_and_nothing_else():
    _, _, entrypoint = _image()
    test = _services()["frps"]["healthcheck"]["test"]
    assert test == ["CMD", *entrypoint, "health"]


def test_the_supervisor_runs_as_root_and_server_and_scheduler_as_their_app_user():
    """The premise of the status file's modes: it belongs to root and its group, and its
    readers are neither."""
    services = _services()
    assert "user" not in services["frps"]
    assert not re.search(r"^USER\b", (_ROOT / "apps/frps/Dockerfile").read_text(), re.M)

    dockerfile = (_ROOT / "Dockerfile").read_text()
    entrypoint = (_ROOT / "apps/server/docker-entrypoint.sh").read_text()
    user = re.search(r"useradd -r -g (\w+) -u (\d+) -d \S+ (\w+)", dockerfile)
    assert user, dockerfile
    group, uid, name = user.groups()
    assert int(uid) != 0 and f"groupadd -r {group}" in dockerfile
    assert f"exec gosu {name}:{group} " in entrypoint
    for reader in ("server", "scheduler"):
        assert "user" not in services[reader]
        assert services[reader]["image"] == services["server"]["image"]


def test_everyone_may_read_the_status_file_the_supervisor_writes(tmp_path):
    state = tmp_path / "state"
    # A mode the supervisor has to widen.
    state.mkdir(mode=0o700)
    state.chmod(0o700)
    env = {
        "PATH": os.environ["PATH"],
        "FRPS_CONFIG": str(tmp_path / "frp" / "frps.toml"),
        "FRPS_PKI_DIR": str(tmp_path / "pki"),
        "FRPS_ACTIVE_DIR": str(tmp_path / "active"),
        "FRPS_STATE_DIR": str(state),
        "FRPS_BIN": "false",
        "FRPS_POLL_SECONDS": "3600",
    }
    supervisor = subprocess.Popen(
        ["/bin/sh", str(SCRIPT)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + WAIT
        while not (state / "status.json").exists():
            assert supervisor.poll() is None, f"supervisor exited ({supervisor.returncode})"
            assert time.monotonic() < deadline, f"no status within {WAIT}s"
            time.sleep(0.05)
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(supervisor.pid, signal.SIGTERM)
        supervisor.wait(timeout=WAIT)

    assert read_supervisor_status(state / "status.json").state == "waiting"
    assert stat.S_IMODE(state.stat().st_mode) & stat.S_IXOTH
    assert stat.S_IMODE((state / "status.json").stat().st_mode) & stat.S_IROTH


def test_the_test_overlay_builds_frps_from_this_checkout():
    overlay = yaml.load(_COMPOSE_TEST.read_text(encoding="utf-8"), Loader=_TestLoader)
    frps = overlay["services"]["frps"]
    assert frps["image"] == "adminhelper-test/frps:latest"
    assert frps["build"] == {"context": "apps/frps"}
    assert (_ROOT / frps["build"]["context"] / "Dockerfile").is_file()


def test_env_example_names_the_frps_image():
    default = _FRPS_IMAGE.removeprefix("${FRPS_IMAGE:-").removesuffix("}")
    lines = _ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    assert f"FRPS_IMAGE={default}" in lines


@pytest.fixture(scope="module")
def pems() -> dict[str, bytes]:
    ca_key, leaf_key = _key(), _key()
    return {
        "ca.crt": _cert_pem(ca_key, "test ca", ca_key, "test ca", days=(-1, 30), ca=True),
        "frps.crt": _cert_pem(leaf_key, "frps", ca_key, "test ca", days=(-1, 30), ca=False),
        "frps.key": _key_pem(leaf_key),
    }


def _at_default(value: str) -> str:
    """A compose value with every `${NAME:-default}` taken at its default."""
    return re.sub(r"\$\{\w+:-([^}]*)\}", r"\1", value)


def _uid(dockerfile: Path) -> str:
    found = re.search(r"useradd .*-u (\d+)", dockerfile.read_text())
    assert found, dockerfile
    return found[1]


def test_in_the_frps_image_under_the_compose_settings_frps_runs_and_the_server_reads_the_status(
    tmp_path, pems
):
    base, target, entrypoint = _image()
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker is not available")
    if subprocess.run([docker, "image", "inspect", base], capture_output=True).returncode != 0:
        pytest.skip(f"no docker daemon or {base} not present locally")
    services = _services()
    frps = services["frps"]
    server_uid = _uid(_ROOT / "Dockerfile")
    issuer_uid = _uid(_ROOT / "apps/ca-issuer/Dockerfile")
    run_id = f"frps-compose-test-{uuid.uuid4().hex[:12]}"
    volumes = {source: f"{run_id}-{source}" for source, _, _ in _mounts(frps).values()}
    source = tmp_path / "in"
    source.mkdir()
    # Port 443 inside, as compose publishes it: frps binds it without a capability.
    (source / "frps.toml").write_text(generate_frps_toml(_cfg(vhost_https_port=443)))
    for name in PEMS:
        (source / name).write_bytes(pems[name])

    def docker_run(*args: str, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run([docker, "run", "--network", "none", *args], **kwargs)

    def logs() -> str:
        result = subprocess.run([docker, "logs", run_id], capture_output=True, text=True)
        return result.stdout + result.stderr

    try:
        for volume in volumes.values():
            subprocess.run([docker, "volume", "create", volume], check=True, capture_output=True)
        # As the server and the ca-issuer leave the files: their UID, the token and the key 0600.
        fill = (
            "cp /in/frps.toml /cfg/ && cp /in/frps.crt /in/frps.key /in/ca.crt /certs/"
            " && chmod 0600 /cfg/frps.toml /certs/frps.key && chmod 0644 /certs/*.crt"
            f" && chown -R {server_uid} /cfg && chown -R {issuer_uid} /certs"
        )
        docker_run(
            "--rm",
            "-v",
            f"{source}:/in:ro",
            "-v",
            f"{volumes['frp-config']}:/cfg",
            "-v",
            f"{volumes['frps-certs']}:/certs",
            "--entrypoint",
            "/bin/sh",
            base,
            "-c",
            fill,
            check=True,
            capture_output=True,
        )

        run = ["-d", "--name", run_id]
        run += [arg for cap in frps["cap_drop"] for arg in ("--cap-drop", cap)]
        run += [arg for cap in frps["cap_add"] for arg in ("--cap-add", cap)]
        for key, value in _environment(frps).items():
            run += ["-e", f"{key}={_at_default(value)}"]
        for mount, (volume, read_only, nocopy) in _mounts(frps).items():
            spec = f"type=volume,src={volumes[volume]},dst={mount}"
            if read_only:
                spec += ",readonly"
            if nocopy:
                spec += ",volume-nocopy"
            run += ["--mount", spec]
        run += ["-v", f"{SCRIPT}:{target}:ro", "--entrypoint", entrypoint[0], base, *entrypoint[1:]]
        docker_run(*run, check=True, capture_output=True)

        # The server's view: its UID, a group other than root's, the volume read-only where
        # compose mounts it.
        server_env = _environment(services["server"])
        read = ["--rm", "--user", f"{server_uid}:{server_uid}", "--cap-drop", "ALL"]
        read += ["--mount", f"type=volume,src={volumes['frps-state']},dst={_STATE_MOUNT},readonly"]
        read += ["--entrypoint", "cat", base, f"{server_env['FRPS_STATE_DIR']}/status.json"]
        copy = tmp_path / "status.json"
        deadline = time.monotonic() + WAIT * 3
        while True:
            result = docker_run(*read, capture_output=True)
            if result.returncode == 0:
                copy.write_bytes(result.stdout)
                if (
                    read_supervisor_status(copy).state == "running"
                    and STARTED_SUCCESSFULLY in logs()
                ):
                    break
            assert time.monotonic() < deadline, f"not running:\n{result.stderr!r}\n{logs()}"
            time.sleep(0.2)

        status = read_supervisor_status(copy)
        assert (status.state, status.reason, status.stale) == ("running", "none", False)
        whoami = subprocess.run(
            [docker, "exec", run_id, "id", "-u"], capture_output=True, text=True
        )
        assert whoami.stdout.strip() == "0"
        health = subprocess.run(
            [docker, "exec", run_id, *frps["healthcheck"]["test"][1:]], capture_output=True
        )
        assert health.returncode == 0, logs()

        grace = str(_seconds(frps["stop_grace_period"]))
        subprocess.run([docker, "stop", "-t", grace, run_id], check=True, capture_output=True)
        inspect = [docker, "inspect", "--format", "{{.State.ExitCode}}", run_id]
        assert subprocess.run(inspect, capture_output=True, text=True).stdout.strip() == "0"
        assert TOKEN not in logs()
    finally:
        subprocess.run([docker, "rm", "-f", run_id], capture_output=True)
        for volume in volumes.values():
            subprocess.run([docker, "volume", "rm", volume], capture_output=True)
