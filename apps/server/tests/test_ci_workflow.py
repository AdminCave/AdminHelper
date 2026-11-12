# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Which events run which jobs of ci.yml (R-1339).

The from-outside stack runs on pull requests as on main: no job of ci.yml skips itself by the
event that started the run.
"""

from pathlib import Path

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
