# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The error contract: a CodedHTTPException answers {detail, code}, every other error keeps its body."""

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.errors import CodedHTTPException, coded_http_exception_handler, install_coded_errors


def _probe_app() -> FastAPI:
    app = FastAPI()
    install_coded_errors(app)

    @app.get("/coded")
    def coded():
        raise CodedHTTPException(403, "ERR_PROBE: prose", "ERR_PROBE", headers={"X-Probe": "1"})

    @app.get("/plain")
    def plain():
        raise HTTPException(404, "missing")

    @app.get("/number/{n}")
    def number(n: int):
        return {"n": n}

    return app


def test_coded_exception_answers_detail_and_code_with_its_headers():
    resp = TestClient(_probe_app()).get("/coded")
    assert resp.status_code == 403
    assert resp.json() == {"detail": "ERR_PROBE: prose", "code": "ERR_PROBE"}
    assert resp.headers["X-Probe"] == "1"


def test_plain_http_exception_keeps_its_body_without_code():
    resp = TestClient(_probe_app()).get("/plain")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "missing"}


def test_validation_error_carries_no_code():
    resp = TestClient(_probe_app()).get("/number/not-a-number")
    assert resp.status_code == 422
    assert "code" not in resp.json()


def test_server_app_registers_the_coded_handler():
    from app.main import app

    assert app.exception_handlers[CodedHTTPException] is coded_http_exception_handler
