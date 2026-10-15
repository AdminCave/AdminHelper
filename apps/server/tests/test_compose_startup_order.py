# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The ca-issuer starts only after the server's migration (R-0288).

The ca-issuer works on tables the server's Alembic migration creates (enrollment tokens,
the certificate register). The server turns healthy only after `alembic upgrade head`
(docker-entrypoint.sh runs it before uvicorn binds the port its healthcheck probes), so
the edge ca-issuer -> server with `service_healthy` is what keeps /enroll and /renew from
answering 500 on a schema without those tables. Before it, only the gateway's own wait on
the healthy server closed that window; a partial start with the gateway already running
could leave it open.

Only the base file is read: docker-compose.test.yml carries `!override`, which
`yaml.safe_load` refuses, and the shipped topology is the base file anyway.
"""

from pathlib import Path

import yaml

_COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"


def test_ca_issuer_waits_for_the_healthy_server():
    services = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))["services"]
    depends_on = services["ca-issuer"].get("depends_on", {})
    assert depends_on.get("server") == {"condition": "service_healthy"}, depends_on
