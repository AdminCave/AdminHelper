# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The pipeline builds, publishes and awaits every image the stack pulls from ghcr, frps among
them.

ci.yml builds each image on every pull request (job docker-build), docker.yml publishes the same
matrix, and release.yml offers a draft release only once every published image of the tag is on
ghcr, since install.sh and update.sh pin them by version. docker-compose.yml pulls exactly those
images from ghcr. The draft is a pre-release, and "latest" of every image moves only when the
release turns stable and is the latest release: then docker.yml points it at the image the tag
push built, once the signature that push made checks out.

The frps image builds on the frps image of the FRP release that ci.yml and release.yml pin as
FRP_VERSION; the lockstep job frp-consistency compares that base with the other pins. The server
job of ci.yml pulls that base, so the tests that run the frps image run there instead of
skipping. The ops-scripts job shellchecks the supervisor as the POSIX sh the image runs it with.

The steps are run, where they can be, as Actions runs a step without a shell of its own
(`bash -e`), on copies of the files they read or with stubs for docker, cosign and gh.
"""

import hashlib
import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest
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
_LATEST_STEP = "Point latest at the signed images of the release"
_REPO = "ghcr.io/admincave/adminhelper"
_ISSUER = "https://token.actions.githubusercontent.com"
_GH_LATEST = "gh api repos/AdminCave/AdminHelper/releases/latest --jq .tag_name"
# docker answers `buildx imagetools inspect` from a registry of files, one per reference holding
# its digest; `buildx imagetools create` gives the new reference the digest of its source (a
# carbon copy) or, with STUB_REWRAP set, another one, and fails for the image STUB_CREATE_FAIL.
# cosign verifies a signature only for the identity STUB_SIGNER and the issuer of GitHub
# Actions, and finds none on the image STUB_UNSIGNED. gh answers that STUB_LATEST is the latest
# release. Every stub logs every call.
_DOCKER_STUB = """#!/bin/sh
echo "docker $*" >> "$STUB_LOG"
ref_file() { echo "$STUB_REGISTRY/$(echo "$1" | tr /:@ ___)"; }
[ "$1 $2" = "buildx imagetools" ] || exit 2
case "$3" in
  inspect)
    [ -f "$(ref_file "$4")" ] || { echo "ERROR: $4: not found" >&2; exit 1; }
    printf '{"digest": "%s"}\\n' "$(cat "$(ref_file "$4")")" ;;
  create)
    [ "$4" = --tag ] || exit 2
    [ "${6%@*}" != "${STUB_CREATE_FAIL:-}" ] || { echo "ERROR: $5: push failed" >&2; exit 1; }
    digest="${6#*@}"
    [ -z "${STUB_REWRAP:-}" ] || digest="sha256:rewrapped"
    echo "$digest" > "$(ref_file "$5")" ;;
  *) exit 2 ;;
esac
"""
_COSIGN_STUB = """#!/bin/sh
echo "cosign $*" >> "$STUB_LOG"
[ "$1" = verify ] || exit 2
shift
while [ $# -gt 0 ]; do
  case "$1" in
    --certificate-identity) identity="$2"; shift 2 ;;
    --certificate-oidc-issuer) issuer="$2"; shift 2 ;;
    -*) exit 2 ;;
    *) ref="$1"; shift ;;
  esac
done
[ "${identity:-}" = "$STUB_SIGNER" ] && [ "${issuer:-}" = "$STUB_ISSUER" ] \\
  && [ "${ref%@*}" != "${STUB_UNSIGNED:-}" ] \\
  || { echo "Error: no matching signatures" >&2; exit 1; }
echo '[{"critical": {}}]'
"""
_GH_STUB = '#!/bin/sh\necho "gh $*" >> "$STUB_LOG"\necho "$STUB_LATEST"\n'


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


def _run_step(
    step: dict, tmp_path: Path, cwd: Path, path: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    script = tmp_path / "step.sh"
    script.write_text(step["run"], encoding="utf-8")
    return subprocess.run(
        ["bash", "-e", str(script)],
        cwd=cwd,
        env={"PATH": path, **(env or {})},
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


def test_only_a_stable_release_moves_latest():
    docker = _workflow("docker.yml")
    # YAML 1.1 reads the key `on` as true.
    assert docker[True]["release"] == {"types": ["released"]}
    assert docker["jobs"]["build"]["if"] == "${{ github.event_name != 'release' }}"
    assert docker["jobs"]["latest"]["if"] == "${{ github.event_name == 'release' }}"
    meta = [step for step in docker["jobs"]["build"]["steps"] if step.get("id") == "meta"]
    assert len(meta) == 1 and meta[0]["with"]["flavor"].split() == ["latest=false"], meta
    draft = _step("release.yml", "release", "Create draft release")["with"]
    assert draft["draft"] is True and draft["prerelease"] is True, draft


def _ref_file(registry: Path, ref: str) -> Path:
    return registry / ref.translate(str.maketrans("/:@", "___"))


def _digest(image: str) -> str:
    return "sha256:" + hashlib.sha256(image.encode()).hexdigest()


def _signer(tag: str) -> str:
    """The identity job build of docker.yml signs with on the push of tag: Fulcio puts the
    job_workflow_ref of the GitHub token into the certificate."""
    return f"https://github.com/AdminCave/AdminHelper/.github/workflows/docker.yml@refs/tags/{tag}"


def _latest(
    tmp_path: Path, present: set[str], tag: str = "v1.2.3", **env: str
) -> tuple[subprocess.CompletedProcess, Path, list[str]]:
    """The latest step of docker.yml for the release of tag, the latest release, with the
    images present of its version on the stub registry, signed by the push of tag; the run,
    the registry and the logged calls."""
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for name, body in (("docker", _DOCKER_STUB), ("cosign", _COSIGN_STUB), ("gh", _GH_STUB)):
        (stubs / name).write_text(body, encoding="utf-8")
        (stubs / name).chmod(0o755)
    registry = tmp_path / "registry"
    registry.mkdir()
    for image in present:
        ref = f"{_REPO}/{image}:{tag.removeprefix('v')}"
        _ref_file(registry, ref).write_text(_digest(image) + "\n")
    log = tmp_path / "calls.log"
    log.touch()
    context = {
        "GITHUB_REF_NAME": tag,
        "GITHUB_REPOSITORY": "AdminCave/AdminHelper",
        "OWNER": "AdminCave",
        "STUB_ISSUER": _ISSUER,
        "STUB_LATEST": tag,
        "STUB_LOG": str(log),
        "STUB_REGISTRY": str(registry),
        "STUB_SIGNER": _signer(tag),
    }
    step = _step("docker.yml", "latest", _LATEST_STEP)
    path = f"{stubs}:{os.environ['PATH']}"
    result = _run_step(step, tmp_path, tmp_path, path, {**context, **env})
    return result, registry, log.read_text(encoding="utf-8").splitlines()


def _creates(calls: list[str]) -> list[str]:
    return [call for call in calls if call.startswith("docker buildx imagetools create ")]


def _moved(registry: Path) -> list[str]:
    return sorted(file.name for file in registry.iterdir() if file.name.endswith("_latest"))


def test_latest_points_every_published_image_at_the_signed_image_of_the_release(tmp_path):
    result, registry, calls = _latest(tmp_path, _published())
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls[0] == _GH_LATEST, calls

    verify = f"cosign verify --certificate-identity {_signer('v1.2.3')} --certificate-oidc-issuer"
    for image in _published():
        latest, source = f"{_REPO}/{image}:latest", f"{_REPO}/{image}@{_digest(image)}"
        assert _ref_file(registry, latest).read_text().strip() == _digest(image)
        assert f"{verify} {_ISSUER} {source}" in calls, calls
        assert f"docker buildx imagetools create --tag {latest} {source}" in calls, calls
    assert len(_moved(registry)) == len(_published()), _moved(registry)
    # The signature of the tag push hangs on the digest; this run signs nothing.
    assert [call for call in calls if call.startswith("cosign ")] == [
        call for call in calls if call.startswith("cosign verify ")
    ], calls

    # Every signature checked before the first create, every create before the first look at
    # where latest points.
    def at(found: list[str]) -> list[int]:
        return [calls.index(call) for call in found]

    verified = at([call for call in calls if call.startswith("cosign verify ")])
    rechecked = at([call for call in calls if " inspect " in call and ":latest " in call])
    assert len(rechecked) == len(_published()), calls
    assert max(verified) < min(at(_creates(calls))), calls
    assert max(at(_creates(calls))) < min(rechecked), calls


# Each image in turn: the last one the step resolves proves that it resolves all before it
# moves any.
@pytest.mark.parametrize("missing", sorted(_published()))
def test_latest_moves_nothing_while_an_image_of_the_release_is_missing(tmp_path, missing):
    result, registry, calls = _latest(tmp_path, _published() - {missing})
    assert result.returncode != 0, result.stdout + result.stderr
    assert f"{missing}:1.2.3 not found on ghcr" in result.stdout, result.stdout

    assert not _creates(calls), calls
    assert not _moved(registry)


@pytest.mark.parametrize("unsigned", sorted(_published()))
def test_latest_moves_nothing_while_an_image_lacks_the_signature_of_the_tag_push(
    tmp_path, unsigned
):
    result, registry, calls = _latest(tmp_path, _published(), STUB_UNSIGNED=f"{_REPO}/{unsigned}")
    assert result.returncode != 0, result.stdout + result.stderr
    expected = f"{unsigned}:1.2.3 ({_digest(unsigned)}) has no valid signature of"
    assert expected in result.stdout, result.stdout

    assert not _creates(calls), calls
    assert not _moved(registry)


def test_latest_stays_when_an_older_release_turns_stable(tmp_path):
    result, registry, calls = _latest(tmp_path, _published(), STUB_LATEST="v1.2.4")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "the latest release is v1.2.4, not v1.2.3" in result.stdout, result.stdout

    assert calls == [_GH_LATEST], calls
    assert not _moved(registry)


# Present, signed by the push of the tag and the latest release: only the version stops it.
@pytest.mark.parametrize("tag", ["v1.2.3-beta.1", "v1.2", "v1.2.3.4"])
def test_latest_moves_nothing_for_a_tag_that_is_not_a_plain_version(tmp_path, tag):
    result, registry, calls = _latest(tmp_path, _published(), tag=tag)
    assert result.returncode != 0, result.stdout + result.stderr
    assert f"tag {tag} is not vX.Y.Z" in result.stdout, result.stdout

    assert not _creates(calls), calls
    assert not _moved(registry)


def test_latest_says_rerun_when_a_retag_fails_midway(tmp_path):
    result, _, _ = _latest(tmp_path, _published(), STUB_CREATE_FAIL=f"{_REPO}/gateway")
    assert result.returncode != 0, result.stdout + result.stderr
    assert "gateway:latest not moved" in result.stdout, result.stdout
    assert "rerun the job" in result.stdout, result.stdout


def test_latest_says_rerun_when_the_retag_changes_the_digest(tmp_path):
    result, _, calls = _latest(tmp_path, _published(), STUB_REWRAP="1")
    assert result.returncode != 0, result.stdout + result.stderr
    assert "latest is sha256:rewrapped" in result.stdout, result.stdout
    assert "rerun the job" in result.stdout, result.stdout
    assert len(_creates(calls)) == len(_published()), calls


def test_the_latest_job_verifies_with_no_oidc_token():
    docker = _workflow("docker.yml")
    assert docker["jobs"]["latest"]["permissions"] == {"contents": "read", "packages": "write"}
    step = _step("docker.yml", "latest", _LATEST_STEP)
    assert step["env"]["GH_TOKEN"] == "${{ github.token }}", step["env"]
    # Where the identity of _signer comes from: job build signs on the push of a tag v*.
    assert docker[True]["push"]["tags"] == ["v*"]
    build = docker["jobs"]["build"]["steps"]
    assert [signs for signs in build if "cosign sign" in signs.get("run", "")], build


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
