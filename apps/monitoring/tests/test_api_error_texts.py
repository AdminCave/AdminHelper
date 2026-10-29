# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""HTTP error texts of the monitoring service are English (R-0488). The desktop
passes a refused call on as "HTTP <code>: <body>", so a German text showed up in
the English interface as well. One case per text the API can reach, through the
real app, with `detail` compared exactly; status codes are pinned alongside."""

import httpx
import pytest
from sqlalchemy.exc import IntegrityError

from app.check_types import VALID_CHECK_TYPES
from app.models import (
    MonitorAgentKey,
    MonitorAlertRule,
    MonitorCheck,
    MonitorTemplate,
    MonitorTemplateAssignment,
)
from app.schemas import VALID_CHANNELS, VALID_INTERVALS, VALID_SEVERITIES

_CONFIG_ERROR = "Invalid config for agent_resources: cpu_warn: Input should be a valid number"
_ASSIGN = {"server_id": "srv-1", "hostname": "h", "server_name": "n"}
_CHECK = {"name": "c", "check_type": "agent_ping"}
_STRING_THRESHOLD = {"name": "c", "check_type": "agent_resources", "config": {"cpu_warn": "85"}}


def _allowed(values) -> str:
    return ", ".join(sorted(values))


def _seed(factory):
    with factory() as db:
        db.add(
            MonitorCheck(
                id="c1",
                server_id="srv-1",
                name="c",
                check_type="agent_resources",
                config='{"cpu_warn": 85}',
                enabled=True,
            )
        )
        db.add(MonitorAlertRule(id="r1", name="r", channel="webhook", channel_config="{}"))
        db.add(
            MonitorTemplate(id="tpl-1", name="T", check_definitions="[]", alert_definitions="[]")
        )
        db.add(
            MonitorTemplateAssignment(
                id="a1",
                template_id="tpl-1",
                server_id="srv-1",
                server_hostname="h",
                server_name="n",
            )
        )
        db.commit()


def _detail(response) -> str:
    """The text the client sees: an HTTPException's detail, or the message of the
    single error pydantic reports for a schema validator."""
    detail = response.json()["detail"]
    if isinstance(detail, list):
        assert len(detail) == 1, detail
        return detail[0]["msg"]
    return detail


def _not_found(resource: str, text: str, routes):
    return [
        pytest.param(method, path, body, 404, text, id=f"{resource}-404-{method}-{path}")
        for method, path, body in routes
    ]


_CASES = [
    # /checks: the router checks type, interval and severity by hand (400).
    pytest.param(
        "post",
        "/checks",
        {**_CHECK, "check_type": "bogus"},
        400,
        f"Invalid check_type. Allowed: {_allowed(VALID_CHECK_TYPES)}",
        id="check-create-type",
    ),
    pytest.param(
        "post",
        "/checks",
        {**_CHECK, "interval": "7m"},
        400,
        f"Invalid interval. Allowed: {_allowed(VALID_INTERVALS)}",
        id="check-create-interval",
    ),
    pytest.param(
        "post",
        "/checks",
        {**_CHECK, "severity": "apocalyptic"},
        400,
        f"Invalid severity. Allowed: {_allowed(VALID_SEVERITIES)}",
        id="check-create-severity",
    ),
    pytest.param(
        "post",
        "/checks",
        _STRING_THRESHOLD,
        422,
        f"Value error, {_CONFIG_ERROR}",
        id="check-create-config",
    ),
    pytest.param(
        "put",
        "/checks/c1",
        {"check_type": "bogus"},
        400,
        "Invalid check_type",
        id="check-update-type",
    ),
    pytest.param(
        "put", "/checks/c1", {"interval": "7m"}, 400, "Invalid interval", id="check-update-interval"
    ),
    pytest.param(
        "put",
        "/checks/c1",
        {"severity": "apocalyptic"},
        400,
        "Invalid severity",
        id="check-update-severity",
    ),
    pytest.param(
        "put",
        "/checks/c1",
        {"config": {"cpu_warn": "85"}},
        422,
        _CONFIG_ERROR,
        id="check-update-config",
    ),
    *_not_found(
        "check",
        "Check not found",
        [
            ("get", "/checks/missing", None),
            ("put", "/checks/missing", {}),
            ("delete", "/checks/missing", None),
            ("post", "/checks/missing/toggle", None),
            ("post", "/checks/missing/run", None),
            ("get", "/checks/missing/metrics", None),
        ],
    ),
    # /alerts
    pytest.param(
        "post",
        "/alerts",
        {"name": "r", "channel": "sms"},
        400,
        f"Invalid channel. Allowed: {_allowed(VALID_CHANNELS)}",
        id="alert-create-channel",
    ),
    pytest.param(
        "post",
        "/alerts",
        {"name": "r", "channel": "webhook", "match_severity": "apocalyptic"},
        400,
        "Invalid severity",
        id="alert-create-severity",
    ),
    pytest.param(
        "put", "/alerts/r1", {"channel": "sms"}, 400, "Invalid channel", id="alert-update-channel"
    ),
    pytest.param(
        "put",
        "/alerts/r1",
        {"match_severity": "apocalyptic"},
        400,
        "Invalid severity",
        id="alert-update-severity",
    ),
    *_not_found(
        "alert",
        "Alert rule not found",
        [
            ("get", "/alerts/missing", None),
            ("put", "/alerts/missing", {}),
            ("delete", "/alerts/missing", None),
            ("post", "/alerts/missing/toggle", None),
        ],
    ),
    # /templates: the definitions are checked by the schema (422 from pydantic).
    pytest.param(
        "post",
        "/templates",
        {"name": "T", "check_definitions": [{**_CHECK, "check_type": "bogus"}]},
        422,
        "Value error, Invalid check_type: bogus",
        id="template-def-type",
    ),
    pytest.param(
        "post",
        "/templates",
        {"name": "T", "check_definitions": [{**_CHECK, "interval": "7m"}]},
        422,
        "Value error, Invalid interval: 7m",
        id="template-def-interval",
    ),
    pytest.param(
        "post",
        "/templates",
        {"name": "T", "check_definitions": [{**_CHECK, "severity": "apocalyptic"}]},
        422,
        "Value error, Invalid severity: apocalyptic",
        id="template-def-severity",
    ),
    pytest.param(
        "post",
        "/templates",
        {"name": "T", "alert_definitions": [{"name": "a", "channel": "sms"}]},
        422,
        "Value error, Invalid channel: sms",
        id="template-def-channel",
    ),
    pytest.param(
        "post",
        "/templates",
        {"name": "T", "check_definitions": [_STRING_THRESHOLD]},
        422,
        f"Value error, {_CONFIG_ERROR}",
        id="template-def-config",
    ),
    *_not_found(
        "template",
        "Template not found",
        [
            ("get", "/templates/missing", None),
            ("put", "/templates/missing", {}),
            ("delete", "/templates/missing", None),
            ("post", "/templates/missing/assign", _ASSIGN),
            ("post", "/templates/missing/assign-tag", {"tag": "web"}),
        ],
    ),
    pytest.param(
        "post",
        "/templates/tpl-1/assign",
        _ASSIGN,
        409,
        "Template already assigned to this server",
        id="template-assigned",
    ),
    pytest.param(
        "delete",
        "/templates/tpl-1/assign/srv-9",
        None,
        404,
        "Assignment not found",
        id="assignment-404",
    ),
]


@pytest.mark.parametrize(("method", "path", "body", "status", "text"), _CASES)
def test_error_text_is_english(client_db, method, path, body, status, text):
    client, factory = client_db
    _seed(factory)
    r = client.request(method.upper(), path, json=body)
    assert r.status_code == status
    assert _detail(r) == text


def test_assign_race_has_the_same_text(client_db, monkeypatch):
    # The losing side of a concurrent assign ends in the unique constraint, not in
    # the read-then-insert check; the client must not tell the two apart.
    client, factory = client_db
    with factory() as db:
        db.add(
            MonitorTemplate(id="tpl-2", name="T", check_definitions="[]", alert_definitions="[]")
        )
        db.commit()

    def _lose_the_race(*a, **k):
        raise IntegrityError("stmt", {}, Exception("unique constraint"))

    monkeypatch.setattr("app.routers.templates.apply_template", _lose_the_race)
    r = client.post("/templates/tpl-2/assign", json=_ASSIGN)
    assert r.status_code == 409
    assert _detail(r) == "Template already assigned to this server"


def test_metrics_with_the_store_down_have_the_text(client_db, monkeypatch):
    from app.core import victoria as victoria_mod

    client, factory = client_db
    _seed(factory)

    def _refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    transport_client = httpx.Client(transport=httpx.MockTransport(_refuse))
    monkeypatch.setattr(victoria_mod.victoria, "_client", transport_client)
    try:
        r = client.get("/checks/c1/metrics")
    finally:
        transport_client.close()
    assert r.status_code == 502
    assert _detail(r) == "Metrics store unavailable"


@pytest.fixture()
def real_auth(client_db, monkeypatch):
    """client_db with the real require_internal and require_agent."""
    from app.core import auth
    from app.main import app

    app.dependency_overrides.pop(auth.require_internal)
    app.dependency_overrides.pop(auth.require_agent)
    monkeypatch.setattr(auth, "INTERNAL_API_KEY", "internal-secret")
    client, factory = client_db
    with factory() as db:
        db.add(
            MonitorAgentKey(
                id="k1", server_id="srv-1", hashed_key=MonitorAgentKey.hash_key("agent-key-1")
            )
        )
        db.commit()
    return client


@pytest.mark.parametrize(
    ("method", "path", "headers", "status", "text"),
    [
        pytest.param("get", "/checks", {}, 401, "Invalid internal API key", id="internal-none"),
        pytest.param(
            "get",
            "/checks",
            {"X-Internal-Key": "wrong"},
            401,
            "Invalid internal API key",
            id="internal-wrong",
        ),
        pytest.param("post", "/agent/srv-1/report", {}, 401, "Missing API key", id="agent-none"),
        pytest.param(
            "post",
            "/agent/srv-1/report",
            {"X-API-Key": "not-the-key"},
            401,
            "Invalid API key",
            id="agent-wrong",
        ),
        pytest.param(
            "post",
            "/agent/srv-2/report",
            {"X-API-Key": "agent-key-1"},
            403,
            "API key does not belong to this server",
            id="agent-foreign-server",
        ),
    ],
)
def test_auth_error_text_is_english(real_auth, method, path, headers, status, text):
    body = {} if method == "post" else None
    r = real_auth.request(method.upper(), path, json=body, headers=headers)
    assert r.status_code == status
    assert _detail(r) == text
