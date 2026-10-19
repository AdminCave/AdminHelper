# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The pipeline builds, publishes and awaits every image the stack pulls from ghcr, frps among
them.

ci.yml builds each image on every pull request (job docker-build), docker.yml publishes the same
matrix, and release.yml offers a draft release only once every published image of the tag is on
ghcr, since install.sh and update.sh pin them by version. docker-compose.yml pulls exactly those
images from ghcr.

The frps image builds on the frps image of the FRP release that ci.yml and release.yml pin as
FRP_VERSION; the lockstep job frp-consistency compares that base with the other pins. The server
job of ci.yml pulls that base, so the tests that run the frps image run there instead of
skipping. The ops-scripts job shellchecks the supervisor as the POSIX sh the image runs it with.

The steps are run, where they can be, as Actions runs a step without a shell of its own
(`bash -e`), on copies of the files they read or with a stub for docker.
"""

import os
import re
import shlex
import subprocess
from pathlib import Path

import yaml

from .test_frps_supervisor import _image

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOWS = _ROOT / ".github" / "workflows"
_FRPS_DOCKERFILE = "apps/frps/Dockerfile"
_SUPERVISOR = "apps/frps/frps-supervisor.sh"
_GHCR = re.compile(r"ghcr\.io/admincave/adminhelper/([a-z-]+):")
_FRPS_BASE = re.compile(r"^FROM (snowdreamtech/frps:(\d+\.\d+\.\d+)@sha256:[0-9a-f]{64})$", re.M)
# What the lockstep step of frp-consistency reads.
_PINNED = (
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    _FRPS_DOCKERFILE,
    "scripts/vm/bootstrap_linux.sh",
)
_PULL_STEP = "Pull the base of the frps image"


def _workflow(name: str) -> dict:
    return yaml.safe_load((_WORKFLOWS / name).read_text(encoding="utf-8"))


def _step(workflow: str, job: str, name: str) -> dict:
    steps = [step for step in _workflow(workflow)["jobs"][job]["steps"] if step.get("name") == name]
    assert len(steps) == 1, (workflow, job, name)
    return steps[0]


def _matrix(workflow: str, job: str) -> list[dict]:
    return _workflow(workflow)["jobs"][job]["strategy"]["matrix"]["include"]


def _published() -> set[str]:
    return {entry["image"] for entry in _matrix("docker.yml", "build")}


def _frps_base() -> re.Match:
    base = _FRPS_BASE.search((_ROOT / _FRPS_DOCKERFILE).read_text(encoding="utf-8"))
    assert base, f"{_FRPS_DOCKERFILE}: FROM snowdreamtech/frps:<version>@sha256:<digest>"
    return base


def _run_step(step: dict, tmp_path: Path, cwd: Path, path: str) -> subprocess.CompletedProcess:
    script = tmp_path / "step.sh"
    script.write_text(step["run"], encoding="utf-8")
    return subprocess.run(
        ["bash", "-e", str(script)],
        cwd=cwd,
        env={"PATH": path},
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_ci_builds_every_image_docker_yml_publishes_frps_among_them():
    built = _matrix("ci.yml", "docker-build")
    assert built == _matrix("docker.yml", "build")
    assert {"image": "frps", "context": "apps/frps", "dockerfile": _FRPS_DOCKERFILE} in built


def test_the_release_waits_for_every_published_image():
    run = _step("release.yml", "release", "Assert the tag images exist on ghcr")["run"]
    loop = re.search(r"^\s*for img in ([a-z -]+); do$", run, re.M)
    assert loop, run
    awaited = loop[1].split()
    assert len(awaited) == len(set(awaited)), awaited
    assert set(awaited) == _published()


def test_compose_pulls_from_ghcr_exactly_the_published_images():
    compose = yaml.safe_load((_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    images = [service.get("image", "") for service in compose["services"].values()]
    assert {found[1] for image in images if (found := _GHCR.search(image))} == _published()


def test_the_frps_image_builds_on_the_frp_version_the_workflows_pin():
    version = _frps_base()[2]
    assert _workflow("ci.yml")["env"]["FRP_VERSION"] == version
    assert _workflow("release.yml")["env"]["FRP_VERSION"] == version


def _lockstep(tmp_path: Path, dockerfile: str | None = None) -> subprocess.CompletedProcess:
    """The pin comparison of frp-consistency on a copy of the files it reads, nothing else; the
    copy of the Dockerfile replaced by dockerfile if given."""
    tree = tmp_path / "tree"
    for name in _PINNED:
        target = tree / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((_ROOT / name).read_bytes())
    if dockerfile is not None:
        (tree / _FRPS_DOCKERFILE).write_text(dockerfile, encoding="utf-8")
    step = _step("ci.yml", "frp-consistency", "Compare the four FRP_VERSION pins")
    return _run_step(step, tmp_path, tree, os.environ["PATH"])


def test_the_lockstep_job_reads_the_frp_version_of_the_frps_image(tmp_path):
    result = _lockstep(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"{_FRPS_DOCKERFILE}={_frps_base()[2]}" in result.stdout.split(), result.stdout


def test_the_lockstep_job_fails_when_the_frps_image_moves_alone(tmp_path):
    base = _frps_base()
    dockerfile = (_ROOT / _FRPS_DOCKERFILE).read_text(encoding="utf-8")
    moved = dockerfile.replace(base[1], base[1].replace(f":{base[2]}@", ":0.0.1@"))
    assert moved != dockerfile

    result = _lockstep(tmp_path, moved)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "FRP_VERSION drift" in result.stdout, result.stdout + result.stderr


def test_the_server_job_pulls_the_base_of_the_frps_image_before_its_tests(tmp_path):
    steps = [step.get("name") for step in _workflow("ci.yml")["jobs"]["server"]["steps"]]
    assert steps.index(_PULL_STEP) < steps.index("Run pytest"), steps
    # docker as a stub that prints what it was asked to do.
    stub = tmp_path / "bin" / "docker"
    stub.parent.mkdir()
    stub.write_text('#!/bin/sh\necho "$@"\n', encoding="utf-8")
    stub.chmod(0o755)

    path = f"{stub.parent}:{os.environ['PATH']}"
    pull = _run_step(_step("ci.yml", "server", _PULL_STEP), tmp_path, _ROOT, path)
    assert pull.returncode == 0, pull.stdout + pull.stderr
    # The reference the image tests look up before they build the image.
    base, _, _ = _image()
    assert pull.stdout.split() == ["pull", base]


def test_ci_shellchecks_the_frps_supervisor_as_posix_sh():
    run = _step("ci.yml", "ops-scripts", "shellcheck")["run"]
    calls = [
        shlex.split(line) for line in run.splitlines() if line.lstrip().startswith("shellcheck")
    ]
    supervisor = [call for call in calls if _SUPERVISOR in call]
    assert len(supervisor) == 1, run
    call = supervisor[0]
    assert "-s" in call and call[call.index("-s") + 1] == "sh", call
