# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The server jobs of ci.yml run in shards; the required checks keep their names (R-0950)."""

import json
import subprocess
from pathlib import Path

import pytest
import yaml

_CI = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"
# job with the shards -> job that carries the name the ruleset requires
_SHARDED = {"server": "server-result", "python-lock-server": "python-lock-server-result"}


def _jobs() -> dict:
    return yaml.safe_load(_CI.read_text(encoding="utf-8"))["jobs"]


def _step(job: dict, name: str) -> dict:
    (step,) = (step for step in job["steps"] if step.get("name") == name)
    return step


def _pytest_step(job: dict) -> dict:
    return _step(job, "Run pytest")


def _uses(job: dict, action: str) -> dict:
    (step,) = (step for step in job["steps"] if step.get("uses", "").startswith(f"{action}@"))
    return step


@pytest.mark.parametrize("name", sorted(_SHARDED))
def test_every_shard_from_1_to_n_runs_and_pytest_gets_it(name):
    job = _jobs()[name]
    shards = job["strategy"]["matrix"]["shard"]
    index, count = job["env"]["PYTEST_SHARD"].split("/")
    assert index == "${{ matrix.shard }}"
    assert shards == list(range(1, int(count) + 1)), (shards, count)
    assert '--shard "$PYTEST_SHARD"' in _pytest_step(job)["run"]
    assert "${{ matrix.shard }}" in job["name"]
    # One red shard must not cancel the others: their failures would go unseen.
    assert job["strategy"]["fail-fast"] is False


def test_the_result_jobs_carry_the_names_of_the_legs():
    jobs = _jobs()
    result = jobs["server-result"]
    assert result["name"] == "Server (pytest, py${{ matrix.python-version }})"
    assert (
        result["strategy"]["matrix"]["python-version"]
        == jobs["server"]["strategy"]["matrix"]["python-version"]
    )
    assert jobs["python-lock-server-result"]["name"] == "Server (pytest, image lock)"
    for shards, gate in _SHARDED.items():
        assert jobs[gate]["needs"] == shards
        # Without always() a red shard skips the gate, and a skipped required check passes.
        assert jobs[gate]["if"] == "always()"
        step = _step(jobs[gate], "Every shard passed")
        assert step["env"]["RESULT"] == f"${{{{ needs.{shards}.result }}}}"
    # A red leg must not cancel the other one (R-1020).
    assert result["strategy"]["fail-fast"] is False


@pytest.mark.parametrize(
    ("result", "passes"),
    [("success", True), ("failure", False), ("cancelled", False), ("skipped", False)],
)
def test_a_result_job_is_green_only_when_every_shard_passed(tmp_path, result, passes):
    for gate in _SHARDED.values():
        step = _step(_jobs()[gate], "Every shard passed")
        script = tmp_path / "step.sh"
        script.write_text(step["run"], encoding="utf-8")
        run = subprocess.run(
            ["bash", "-e", str(script)],
            env={"PATH": "/usr/bin:/bin", "RESULT": result},
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert (run.returncode == 0) is passes, (gate, run.stdout, run.stderr)


# shard job -> the artifact name its result job downloads, with the leg's matrix in it
_MANIFEST_NAMES = {
    "server": (
        "shard-manifest-server-py${{ matrix.python-version }}-${{ matrix.shard }}",
        "shard-manifest-server-py${{ matrix.python-version }}-*",
    ),
    "python-lock-server": ("shard-manifest-lock-${{ matrix.shard }}", "shard-manifest-lock-*"),
}


@pytest.mark.parametrize("name", sorted(_SHARDED))
def test_every_shard_uploads_its_manifest_and_its_result_job_compares_them(name):
    jobs = _jobs()
    job, gate = jobs[name], jobs[_SHARDED[name]]
    upload_name, pattern = _MANIFEST_NAMES[name]
    assert '--shard-manifest "$RUNNER_TEMP/shard-manifest.json"' in _pytest_step(job)["run"]
    upload = _uses(job, "actions/upload-artifact")
    # Also after a red pytest: the comparison is what names a shard that collected less.
    assert upload["if"] == "${{ !cancelled() }}"
    assert upload["with"]["name"] == upload_name
    assert upload["with"]["path"] == "${{ runner.temp }}/shard-manifest.json"
    assert upload["with"]["if-no-files-found"] == "error"
    download = _uses(gate, "actions/download-artifact")
    assert download["with"]["pattern"] == pattern
    compare = _step(gate, "The shards collected the same tests")
    assert compare["env"]["MANIFESTS"] == download["with"]["path"]
    assert int(compare["env"]["SHARDS"]) == len(job["strategy"]["matrix"]["shard"])
    names = [step.get("name") or step["uses"].split("@")[0] for step in gate["steps"]]
    assert names.index("actions/download-artifact") < names.index(compare["name"])


def _manifest(shard: str, count: int = 10, sha256: str = "a" * 64) -> dict:
    return {"shard": shard, "count": count, "sha256": sha256}


@pytest.mark.parametrize(
    ("manifests", "passes"),
    [
        ([_manifest("1/2"), _manifest("2/2")], True),
        ([_manifest("1/2"), _manifest("2/2", sha256="b" * 64)], False),
        ([_manifest("1/2"), _manifest("2/2", count=9)], False),
        ([_manifest("1/2")], False),
        ([], False),
        ([_manifest("1/2"), _manifest("1/2")], False),
        ([_manifest("1/2"), _manifest("2/2"), _manifest("2/2")], False),
    ],
    ids=["same", "other-hash", "other-count", "one-missing", "none", "twice-1", "extra"],
)
def test_the_comparison_is_green_only_for_one_equal_manifest_a_shard(tmp_path, manifests, passes):
    root = tmp_path / "manifests"
    for i, manifest in enumerate(manifests):
        # download-artifact puts each artifact in a directory of its name.
        (root / f"shard-manifest-{i}").mkdir(parents=True)
        (root / f"shard-manifest-{i}" / "shard-manifest.json").write_text(json.dumps(manifest))
    root.mkdir(exist_ok=True)
    for gate in _SHARDED.values():
        step = _step(_jobs()[gate], "The shards collected the same tests")
        script = tmp_path / "step.sh"
        script.write_text(step["run"], encoding="utf-8")
        run = subprocess.run(
            ["bash", "-e", str(script)],
            env={"PATH": "/usr/bin:/bin", "MANIFESTS": str(root), "SHARDS": step["env"]["SHARDS"]},
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert (run.returncode == 0) is passes, (gate, run.stdout, run.stderr)
