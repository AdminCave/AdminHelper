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


# --- consecutive_oks (alert-quality T3) -------------------------------------


def test_consecutive_oks_defaults_to_two():
    assert TemplateCheckDef(**_def()).consecutive_oks == 2


@pytest.mark.parametrize("value", [0, 101])
def test_rejects_consecutive_oks_out_of_range(value):
    with pytest.raises(ValidationError):
        TemplateCheckDef(**_def(consecutive_oks=value))


@pytest.mark.parametrize("value,error", [(0, "greater_than_equal"), (101, "less_than_equal")])
def test_template_route_rejects_consecutive_oks_out_of_range(client_db, value, error):
    client, _ = client_db
    r = client.post(
        "/templates", json={"name": "t", "check_definitions": [_def(consecutive_oks=value)]}
    )
    assert r.status_code == 422, r.text
    assert {"type": error, "loc": ["body", "check_definitions", 0, "consecutive_oks"]} in [
        {"type": e["type"], "loc": e["loc"]} for e in r.json()["detail"]
    ], r.text


@pytest.mark.parametrize("model", ["CheckCreate", "CheckUpdate", "TemplateCheckDef"])
def test_published_schema_bounds_consecutive_oks(model):
    # Per model, in the schema the API publishes: a bound carried in nested
    # Annotated metadata has been dropped silently before, and the integer lint
    # (test_openapi_integer_bounds.py) is content with IntColumn's own maximum.
    from app.main import app

    prop = app.openapi()["components"]["schemas"][model]["properties"]["consecutive_oks"]
    integers = [s for s in prop.get("anyOf", [prop]) if s.get("type") == "integer"]
    assert [(s["minimum"], s["maximum"]) for s in integers] == [(1, 100)]
