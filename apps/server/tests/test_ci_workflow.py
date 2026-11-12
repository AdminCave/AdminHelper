# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Which events run which jobs of ci.yml (R-1339, R-1342).

The from-outside stack runs on pull requests as on main: no job of ci.yml skips itself by the
event that started the run. A merge queue starts the workflow with merge_group: its run, like a
push to main, is never cancelled or pushed out, and the public repo guard reads the commits the
group brings on top of main.
"""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

_CI = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"


def _workflow() -> dict:
    return yaml.safe_load(_CI.read_text(encoding="utf-8"))


def _triggers() -> dict:
    # YAML 1.1 reads the bare key on as true.
    return _workflow()[True]


def test_the_stack_job_runs_on_pull_requests():
    assert "pull_request" in _triggers()
    job = _workflow()["jobs"]["integration-stack"]
    assert "if" not in job
    assert job["steps"][-1]["run"] == "bash scripts/tests/integration_stack_test.sh"


def test_no_job_skips_itself_by_event():
    for name, job in _workflow()["jobs"].items():
        assert "github.event_name" not in str(job.get("if", "")), name


def test_a_merge_queue_starts_the_workflow():
    assert _triggers()["merge_group"] == {"types": ["checks_requested"]}


def _evaluate(value: str, **github: str):
    """Evaluates an expression of the concurrency block: ==, &&, || and format().

    && and || return one of their operands, as Python's and and or do.
    """
    assert value.startswith("${{ ") and value.endswith(" }}"), value
    expression = value[4:-3]
    assert "!" not in expression.replace("!=", ""), expression
    python = expression.replace("&&", " and ").replace("||", " or ")
    names = {"github": SimpleNamespace(**github), "format": lambda text, *args: text.format(*args)}
    return eval(python, {"__builtins__": {}}, names)


_SHA = "c0ffee" * 6 + "c0ff"


@pytest.mark.parametrize(
    ("event", "ref", "group", "cancels"),
    [
        ("pull_request", "refs/pull/7/merge", "ci-refs/pull/7/merge", True),
        ("push", "refs/heads/main", f"ci-push-{_SHA}", False),
        ("merge_group", "refs/heads/gh-readonly-queue/main/pr-7", f"ci-merge_group-{_SHA}", False),
        ("workflow_dispatch", "refs/heads/feature/x", "ci-refs/heads/feature/x", False),
    ],
)
def test_only_a_pull_request_cancels_and_a_merge_group_has_a_group_of_its_own(
    event, ref, group, cancels
):
    concurrency = _workflow()["concurrency"]
    github = {"event_name": event, "ref": ref, "sha": _SHA}
    assert _evaluate(concurrency["group"], **github) == group
    assert _evaluate(concurrency["cancel-in-progress"], **github) is cancels


def _git(repo: Path, *args: str) -> str:
    run = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        env={"PATH": "/usr/bin:/bin", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"},
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return run.stdout.strip()


# Stands in for review.sh in both trees: the guard wants --range in the base's copy, and the
# log names the copy and what it was asked.
_STUB = """#!/bin/bash
# reads --range
echo "$0 $*" >> "$GUARD_LOG"
echo "sec: clean"
"""


@pytest.fixture
def guard_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts" / "dev").mkdir(parents=True)
    (repo / "scripts" / "dev" / "review.sh").write_text(_STUB)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    (repo / "change.txt").write_text("queued\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "the group")
    return repo


def _guard_step() -> str:
    job = _workflow()["jobs"]["public-repo-guard"]
    (step,) = (s for s in job["steps"] if s.get("name", "").startswith("review.sh sec over"))
    assert step["env"]["EVENT"] == "${{ github.event_name }}"
    return step["run"]


@pytest.mark.parametrize(
    ("event", "base_ref", "before", "base", "span"),
    [
        ("merge_group", "", "", "origin/main", "origin/main...{sha}"),
        ("pull_request", "main", "", "origin/main", "origin/main...{sha}"),
        ("push", "", "{main}", "{main}", "{main}..{sha}"),
        ("workflow_dispatch", "", "", "origin/main", "origin/main...{sha}"),
    ],
)
def test_the_guard_reads_what_the_event_brings_on_top_of_its_base(
    tmp_path, guard_repo, event, base_ref, before, base, span
):
    sha, main = _git(guard_repo, "rev-parse", "HEAD"), _git(guard_repo, "rev-parse", "origin/main")
    script, log, runner_temp = tmp_path / "step.sh", tmp_path / "guard.log", tmp_path / "runner"
    script.write_text(_guard_step(), encoding="utf-8")
    runner_temp.mkdir()
    run = subprocess.run(
        ["bash", "-e", str(script)],
        cwd=guard_repo,
        env={
            "PATH": "/usr/bin:/bin",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "EVENT": event,
            "BASE_REF": base_ref,
            "BEFORE": before.format(main=main),
            "SHA": sha,
            "RUNNER_TEMP": str(runner_temp),
            "GUARD_LOG": str(log),
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, (run.stdout, run.stderr)
    want = f"sec --range {span.format(sha=sha, main=main)}"
    assert log.read_text().splitlines() == [
        f"{runner_temp}/base/scripts/dev/review.sh {want}",
        f"scripts/dev/review.sh {want}",
    ]
    assert _git(runner_temp / "base", "rev-parse", "HEAD") == _git(
        guard_repo, "rev-parse", base.format(main=main)
    )


def test_the_guard_fails_closed_on_a_push_without_before(tmp_path, guard_repo):
    script = tmp_path / "step.sh"
    script.write_text(_guard_step(), encoding="utf-8")
    run = subprocess.run(
        ["bash", "-e", str(script)],
        cwd=guard_repo,
        env={
            "PATH": "/usr/bin:/bin",
            "EVENT": "push",
            "BEFORE": "0" * 40,
            "SHA": _git(guard_repo, "rev-parse", "HEAD"),
            "RUNNER_TEMP": str(tmp_path),
            "GUARD_LOG": str(tmp_path / "guard.log"),
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 1, (run.stdout, run.stderr)
    assert "push without a usable 'before'" in run.stdout
    assert not (tmp_path / "guard.log").exists()
