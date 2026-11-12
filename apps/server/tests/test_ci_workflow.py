# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Which events run which jobs of ci.yml (R-1339, R-1340, R-1342).

The from-outside stack runs on pull requests as on main: no job of ci.yml skips itself by the
event that started the run. A merge queue starts the workflow with merge_group: its run, like a
push to main, is never cancelled or pushed out, and the public repo guard reads the commits the
group brings on top of main. Which suites a pull request runs, the job changes decides from its
paths (test_ci_changes.py); here the expressions that read its outputs.
"""

import json
import re
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


def _namespace(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{k.replace("-", "_"): _namespace(v) for k, v in value.items()})
    return value


def _evaluate(value: str, cancelled: bool = False, **context):
    """Evaluates an expression of ci.yml: ==, !=, &&, ||, !cancelled(), contains, fromJSON, format.

    && and || return one of their operands, as Python's and and or do. A hyphen inside a name
    (needs.changes.outputs.server-legs) becomes an underscore, outside the quoted strings.
    """
    assert value.startswith("${{ ") and value.endswith(" }}"), value
    expression = value[4:-3]
    # Python's not binds looser than a comparison, the expressions' ! tighter: only in front of
    # cancelled(), followed by &&, do both read the same.
    assert "!" not in expression.replace("!=", "").replace("!cancelled() &&", ""), expression
    parts = re.split(r"('[^']*')", expression)
    for i in range(0, len(parts), 2):
        part = parts[i].replace("&&", " and ").replace("||", " or ")
        part = part.replace("!cancelled()", "not cancelled()")
        parts[i] = re.sub(r"(?<=\w)-(?=[A-Za-z_])", "_", part)
    names = {name: _namespace(item) for name, item in context.items()}
    names |= {
        "cancelled": lambda: cancelled,
        "contains": lambda search, item: item in search,
        "fromJSON": json.loads,
        "format": lambda text, *args: text.format(*args),
    }
    return eval("".join(parts), {"__builtins__": {}}, names)


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
    assert _evaluate(concurrency["group"], github=github) == group
    assert _evaluate(concurrency["cancel-in-progress"], github=github) is cancels


def _needs(**outputs: str) -> dict:
    return {"changes": {"outputs": {name.replace("_", "-"): v for name, v in outputs.items()}}}


@pytest.mark.parametrize(
    ("legs", "run"),
    [
        ('["3.14"]', ["3.14"]),
        ('["3.14","3.15"]', ["3.14", "3.15"]),
        # The job changes failed and left its outputs empty: both legs, as before R-1340.
        ("", ["3.14", "3.15"]),
    ],
)
def test_the_server_matrix_runs_the_legs_the_changes_name(legs, run):
    matrix = _workflow()["jobs"]["server"]["strategy"]["matrix"]["python-version"]
    assert _evaluate(matrix, needs=_needs(server_legs=legs)) == run


@pytest.mark.parametrize(
    ("server", "legs", "want"),
    [
        ("true", '["3.14"]', {"3.14": True, "3.15": False}),
        ("true", '["3.14","3.15"]', {"3.14": True, "3.15": True}),
        ("false", '["3.14"]', {"3.14": False, "3.15": False}),
        ("", "", {"3.14": True, "3.15": True}),
    ],
)
def test_server_result_checks_a_leg_only_when_the_server_job_ran_it(server, legs, want):
    result = _workflow()["jobs"]["server-result"]
    needs = _needs(server=server, server_legs=legs)
    for leg in result["strategy"]["matrix"]["python-version"]:
        context = {"needs": needs, "matrix": {"python-version": leg}}
        assert _evaluate(result["env"]["WANT"], **context) is want[leg], leg


@pytest.mark.parametrize(("lock", "want"), [("true", True), ("false", False), ("", True)])
def test_the_image_lock_gate_checks_its_shards_unless_the_changes_turned_them_off(lock, want):
    gate = _workflow()["jobs"]["python-lock-server-result"]
    assert _evaluate(gate["env"]["WANT"], needs=_needs(lock_server=lock)) is want


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


# nightly.yml (R-1343): the deep checks the pull request CI leaves out.
_NIGHTLY = _CI.with_name("nightly.yml")


def _nightly() -> dict:
    return yaml.safe_load(_NIGHTLY.read_text(encoding="utf-8"))


def test_the_nightly_runs_once_a_day_by_hand_and_on_a_pull_request_that_changes_it():
    triggers = _nightly()[True]
    assert set(triggers) == {"schedule", "workflow_dispatch", "pull_request"}
    (schedule,) = triggers["schedule"]
    assert re.fullmatch(r"\d+ \d+ \* \* \*", schedule["cron"]), schedule
    assert triggers["pull_request"] == {"paths": [".github/workflows/nightly.yml"]}


def test_the_nightly_reads_the_tree_and_no_secret():
    assert _nightly()["permissions"] == {"contents": "read"}
    assert "secrets." not in _NIGHTLY.read_text(encoding="utf-8")


def test_nothing_in_the_nightly_skips_itself_or_turns_a_failure_green():
    for name, job in _nightly()["jobs"].items():
        assert "if" not in job and "continue-on-error" not in job, name
        for step in job["steps"]:
            assert "if" not in step and "continue-on-error" not in step, (name, step)


def test_the_deep_fuzzing_is_the_ci_job_with_100_examples():
    ci = _workflow()["jobs"]["schemathesis"]
    deep = _nightly()["jobs"]["schemathesis"]
    assert ci["env"]["AH_SCHEMATHESIS_EXAMPLES"] == "0"
    assert deep["env"] == ci["env"] | {"AH_SCHEMATHESIS_EXAMPLES": "100"}
    assert deep["services"] == ci["services"]
    assert deep["runs-on"] == ci["runs-on"]
    (summary,) = (s for s in deep["steps"] if s.get("name") == "Name the commit and the budget")
    assert [s for s in deep["steps"] if s is not summary] == ci["steps"]
    assert deep["steps"].index(summary) < len(deep["steps"]) - 1


def test_the_deep_fuzzing_names_the_commit_and_the_budget_before_it_starts(tmp_path):
    (step,) = (
        s
        for s in _nightly()["jobs"]["schemathesis"]["steps"]
        if s.get("name") == "Name the commit and the budget"
    )
    summary = tmp_path / "summary.md"
    run = subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        env={
            "PATH": "/usr/bin:/bin",
            "GITHUB_SHA": _SHA,
            "AH_SCHEMATHESIS_EXAMPLES": "100",
            "GITHUB_STEP_SUMMARY": str(summary),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 0, run.stderr
    text = summary.read_text()
    assert f"Commit `{_SHA}`, AH_SCHEMATHESIS_EXAMPLES=100" in text


def test_the_nightly_restore_runs_the_round_trip_where_a_skip_is_red():
    job = _nightly()["jobs"]["backup-restore"]
    # The step's exit is the job's: the script's 75 (a missing precondition) is red here.
    assert job["steps"][-1] == {
        "name": "Backup, total loss, restore",
        "run": "bash scripts/tests/backup_restore_test.sh",
    }
