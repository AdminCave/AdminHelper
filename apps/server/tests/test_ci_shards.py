# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The server jobs of ci.yml run in shards; the required checks keep their names (R-0950)."""

import subprocess
from pathlib import Path

import pytest
import yaml

_CI = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"
# job with the shards -> job that carries the name the ruleset requires
_SHARDED = {"server": "server-result", "python-lock-server": "python-lock-server-result"}


def _jobs() -> dict:
    return yaml.safe_load(_CI.read_text(encoding="utf-8"))["jobs"]


def _pytest_step(job: dict) -> dict:
    (step,) = (step for step in job["steps"] if step.get("name") == "Run pytest")
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
        (step,) = jobs[gate]["steps"]
        assert step["env"]["RESULT"] == f"${{{{ needs.{shards}.result }}}}"


@pytest.mark.parametrize(
    ("result", "passes"),
    [("success", True), ("failure", False), ("cancelled", False), ("skipped", False)],
)
def test_a_result_job_is_green_only_when_every_shard_passed(tmp_path, result, passes):
    for gate in _SHARDED.values():
        (step,) = _jobs()[gate]["steps"]
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
