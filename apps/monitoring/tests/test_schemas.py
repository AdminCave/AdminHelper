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
    base = {"name": "cpu", "check_type": "ping", "interval": "5m", "severity": "critical"}
    return {**base, **over}


def test_accepts_valid_definition():
    d = TemplateCheckDef(**_def())
    assert d.check_type == "ping"


def test_accepts_cron_interval():
    # Templates additionally allow a 5-field cron expression.
    d = TemplateCheckDef(**_def(interval="*/5 * * * *"))
    assert d.interval == "*/5 * * * *"


def test_rejects_unknown_check_type():
    with pytest.raises(ValidationError):
        TemplateCheckDef(**_def(check_type="pnig"))


def test_rejects_bad_interval():
    with pytest.raises(ValidationError):
        TemplateCheckDef(**_def(interval="10x"))


def test_rejects_bad_severity():
    with pytest.raises(ValidationError):
        TemplateCheckDef(**_def(severity="fatal"))
