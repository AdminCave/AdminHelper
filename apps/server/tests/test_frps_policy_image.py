# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The frps image carries the plugin frps-policy, built in a stage of its own from the Go module
of the agent (apps/frps/Dockerfile).

The image builds from the repository root, and apps/frps/Dockerfile.dockerignore, which takes
precedence over the .dockerignore of the root, lets in the supervisor and the Go sources of the
plugin alone: no tests, no test data, nothing else of the checkout. The Go stage pins its image
by digest, at a Go no older than the toolchain of the agent, and builds without a download.

In the image the program is root's and for anyone else to execute only (0711), as frps and curl
are. It runs as frps-policy, a user of its own, outside the group frps, whose UID no other user
of the image or service of the stack has. It serves on a loopback address only.

The test of the build context builds a scratch image of the context alone. The tests on the
image build it as compose does; they skip when Docker or a pinned base image is not at hand."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from .test_frps_supervisor import _built_frps_image, _fetch_user, _frps_user

_ROOT = Path(__file__).resolve().parents[3]
_DOCKERFILE = _ROOT / "apps/frps/Dockerfile"
_IGNORE = _ROOT / "apps/frps/Dockerfile.dockerignore"
_AGENT = _ROOT / "apps/agent"
_PLUGIN_SOURCES = ("cmd/frps-policy", "internal/frpspolicy")
# The UIDs the other images of the stack run their services as.
_SERVICE_DOCKERFILES = ("Dockerfile", "apps/ca-issuer/Dockerfile", "apps/monitoring/Dockerfile")


def _docker() -> str:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker is not available")
    if subprocess.run([docker, "info"], capture_output=True).returncode != 0:
        pytest.skip("no docker daemon")
    return docker


def _plugin() -> tuple[str, str]:
    """Name of the plugin's user and the plugin's place in the image, as in the Dockerfile."""
    dockerfile = _DOCKERFILE.read_text()
    target = re.search(r"^COPY --from=plugin \S+ \S+ /out/frps-policy (\S+)$", dockerfile, re.M)
    user = re.search(r"\badduser\b.* -G (frps-policy) (frps-policy)$", dockerfile, re.M)
    assert target and user, dockerfile
    return user[2], target[1]


def _expected_context() -> set[str]:
    sources = {
        source.relative_to(_ROOT).as_posix()
        for directory in _PLUGIN_SOURCES
        for source in (_AGENT / directory).glob("*.go")
        if not source.name.endswith("_test.go")
    }
    return sources | {"apps/frps/frps-supervisor.sh", "apps/agent/go.mod", "apps/agent/go.sum"}


def test_the_build_context_holds_the_supervisor_and_the_plugin_sources_alone(tmp_path):
    docker = _docker()
    # A Dockerfile of its own with the same ignore rules next to it, from the same root: the
    # image of COPY . is the context as the build of the frps image sees it.
    probe = tmp_path / "probe.Dockerfile"
    probe.write_text("FROM scratch\nCOPY . /ctx\n")
    shutil.copyfile(_IGNORE, tmp_path / "probe.Dockerfile.dockerignore")
    out = tmp_path / "out"
    build = subprocess.run(
        [docker, "build", "-q", "-f", str(probe), "-o", f"type=local,dest={out}", str(_ROOT)],
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    context = out / "ctx"
    files = {path.relative_to(context).as_posix() for path in context.rglob("*") if path.is_file()}
    assert files == _expected_context()
    # The sources of the plugin are there, its tests are not.
    assert "apps/agent/cmd/frps-policy/main.go" in files
    assert (_AGENT / "cmd/frps-policy/main_test.go").is_file()


def test_the_plugin_builds_with_a_pinned_go_no_older_than_the_toolchain_of_the_agent():
    stage = re.search(
        r"^FROM golang:(\d+)\.(\d+)\.(\d+)-alpine@sha256:[0-9a-f]{64} AS plugin$",
        _DOCKERFILE.read_text(),
        re.M,
    )
    toolchain = re.search(
        r"^toolchain go(\d+)\.(\d+)\.(\d+)$", (_AGENT / "go.mod").read_text(), re.M
    )
    assert stage and toolchain
    assert tuple(map(int, stage.groups())) >= tuple(map(int, toolchain.groups()))


@pytest.fixture(scope="module")
def frps_image():
    yield from _built_frps_image()


def _run(frps_image, *args: str, user: str | None = None) -> subprocess.CompletedProcess:
    docker, image = frps_image
    as_user = ["--user", user] if user else []
    entrypoint, *rest = args
    return subprocess.run(
        [
            docker,
            "run",
            "--rm",
            "--network",
            "none",
            *as_user,
            "--entrypoint",
            entrypoint,
            image,
            *rest,
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_in_the_frps_image_the_plugin_is_roots_and_for_others_to_execute_only(frps_image):
    _, program = _plugin()
    stat = _run(frps_image, "stat", "-c", "%a %U %G", program)
    assert (stat.returncode, stat.stdout) == (0, "711 root root\n"), stat.stderr


def test_in_the_frps_image_the_plugin_has_a_user_of_its_own_outside_the_group_frps(frps_image):
    user, _ = _plugin()
    frps, frps_uid = _frps_user()
    _, fetch_uid = _fetch_user()
    found = _run(frps_image, "sh", "-c", f"id -u {user}; id -G {user}; getent group {frps}")
    assert found.returncode == 0, found.stderr
    uid, groups, frps_group = found.stdout.splitlines()
    frps_gid = frps_group.split(":")[2]
    services = {
        int(uid)
        for dockerfile in _SERVICE_DOCKERFILES
        for uid in re.findall(r"\buseradd\b.* -u (\d+)", (_ROOT / dockerfile).read_text())
    }
    assert services, _SERVICE_DOCKERFILES
    assert int(uid) not in {0, frps_uid, fetch_uid, *services}
    # One group, its own: not frps, whose members read the copy with token and key.
    assert len(groups.split()) == 1
    assert frps_gid not in groups.split()


def test_in_the_frps_image_the_plugin_runs_as_its_user_and_serves_on_loopback_only(frps_image):
    user, program = _plugin()
    # Its user executes the program and cannot read it.
    read = _run(frps_image, "cat", program, user=user)
    assert read.returncode != 0 and "Permission denied" in read.stderr, read.stderr
    refused = _run(frps_image, program, "-listen", "0.0.0.0:7480", user=user)
    assert refused.returncode != 0
    # slog quotes the address within the quoted error.
    assert '\\"0.0.0.0:7480\\" is no loopback IP' in refused.stderr, refused.stderr
