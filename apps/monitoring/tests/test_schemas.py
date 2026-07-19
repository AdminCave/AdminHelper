# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""TemplateCheckDef boundary validation (1.20): a template check must be
validated at the POST/PUT edge exactly like CheckCreate is at the router, not
only fail later at assign/sync time."""

import pytest
from pydantic import ValidationError

from app.schemas import TemplateCheckDef


def _def(**over):
    base = {
        "name": "cpu",
        "check_type": "ping",
        "interval": "5m",
        "severity": "critical",
        # T4: ping configs require a target at the boundary now.
        "config": {"target": "127.0.0.1"},
    }
    return {**base, **over}


def test_accepts_valid_definition():
    d = TemplateCheckDef(**_def())
    assert d.check_type == "ping"


def test_rejects_cron_interval():
    # Cron support was removed (2.113): templates accept only the fixed VALID_INTERVALS,
    # matching the /checks CRUD boundary — a 5-field cron is no longer valid.
    with pytest.raises(ValidationError):
        TemplateCheckDef(**_def(interval="*/5 * * * *"))


def test_rejects_unknown_check_type():
    with pytest.raises(ValidationError):
        TemplateCheckDef(**_def(check_type="pnig"))


def test_rejects_bad_interval():
    with pytest.raises(ValidationError):
        TemplateCheckDef(**_def(interval="10x"))


def test_rejects_bad_severity():
    with pytest.raises(ValidationError):
        TemplateCheckDef(**_def(severity="fatal"))
