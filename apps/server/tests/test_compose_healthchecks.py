# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every long-running service of docker-compose.yml has a healthcheck, so that `docker compose ps`
and `docker compose up --wait` see whether it answers, not only whether it runs.

victoria asks its own /health. monitoring sends an HTTP GET to /health and the server one to
/api/health: a TCP connect completes from the kernel's listen backlog even while the process
hangs. The server's command runs here against a local HTTP server, a socket that never answers
and a closed port. One test runs the pinned victoria
image with the healthcheck command from the compose file and a counter-check on a port nobody
listens on; it skips when Docker is not at hand or the image can neither be found nor pulled.
"""

import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import yaml

_COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"

# Services without a healthcheck, each with its reason.
_NO_HEALTHCHECK = {
    "scheduler": "opens no port; it only runs jobs against postgres and redis",
    "db-init": "one-shot: sets up the database roles and exits; dependents wait for service_completed_successfully",
    "pg-backup": "opens no port; a loop that dumps once a day and sleeps, nothing depends on it",
}


def _services() -> dict:
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))["services"]


def _test(service: str) -> list[str]:
    return _services()[service]["healthcheck"]["test"]


def test_every_service_but_the_listed_ones_has_a_healthcheck():
    services = _services()
    assert set(_NO_HEALTHCHECK) <= set(services)
    for name, service in services.items():
        if name in _NO_HEALTHCHECK:
            assert "healthcheck" not in service, name
            continue
        assert service.get("healthcheck", {}).get("test"), name


def test_victoria_asks_its_own_health_endpoint():
    assert _test("victoria") == [
        "CMD",
        "wget",
        "-q",
        "-O",
        "/dev/null",
        "http://127.0.0.1:8428/health",
    ]


def test_monitoring_sends_an_http_request_to_health_not_a_tcp_connect():
    test = " ".join(_test("monitoring"))
    assert "http://127.0.0.1:8080/health" in test
    assert "urlopen" in test
    assert "create_connection" not in test


def test_the_server_sends_an_http_request_to_api_health_not_a_tcp_connect():
    test = " ".join(_test("server"))
    assert "http://127.0.0.1:8080/api/health" in test
    assert ".open(" in test and "ProxyHandler({})" in test
    assert "create_connection" not in test


def _server_check(port: int, env: dict[str, str] | None = None) -> int:
    """Runs the server's healthcheck command from the compose file against port."""
    command = _test("server")
    assert command[:3] == ["CMD", "python", "-c"]
    code = command[3].replace("127.0.0.1:8080", f"127.0.0.1:{port}")
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, timeout=30, env=env
    ).returncode


@contextmanager
def _http_server(status: int):
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("status", [200, 403])
def test_the_server_healthcheck_passes_on_an_http_answer(status):
    # 403: what the server answers the check with when ALLOWED_IPS leaves out 127.0.0.1.
    with _http_server(status) as port:
        assert _server_check(port) == 0


def test_the_server_healthcheck_ignores_a_proxy_from_the_environment():
    """Docker puts the proxy of the client config into every container; a loopback check
    sent through an unreachable proxy would never pass."""
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        dead = closed.getsockname()[1]
    proxy = f"http://127.0.0.1:{dead}"
    env = {"PATH": "/usr/bin:/bin", "http_proxy": proxy, "HTTP_PROXY": proxy, "no_proxy": ""}
    with _http_server(200) as port:
        assert _server_check(port, env) == 0


def test_the_server_healthcheck_fails_when_the_process_does_not_answer():
    # A listening socket nobody accepts on: the kernel completes the connect from the
    # backlog, as for a hung uvicorn, but no answer comes.
    with socket.socket() as hung:
        hung.bind(("127.0.0.1", 0))
        hung.listen(1)
        assert _server_check(hung.getsockname()[1]) != 0


def test_the_server_healthcheck_fails_when_nothing_listens():
    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
    assert _server_check(port) != 0


@pytest.fixture
def victoria():
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker is not available")
    image = _services()["victoria"]["image"]
    if subprocess.run([docker, "image", "inspect", image], capture_output=True).returncode:
        pulled = subprocess.run([docker, "pull", "-q", image], capture_output=True, timeout=300)
        if pulled.returncode:
            pytest.skip(f"no docker daemon or {image} can not be pulled")
    name = f"ah-test-victoria-{uuid.uuid4().hex[:12]}"
    subprocess.run(
        [docker, "run", "-d", "--name", name, "--tmpfs", "/victoria-metrics-data", image]
        + ["-storageDataPath=/victoria-metrics-data"],
        check=True,
        capture_output=True,
    )
    try:
        yield docker, name
    finally:
        subprocess.run([docker, "rm", "-f", name], capture_output=True)


def _exec(docker: str, name: str, command: list[str]) -> int:
    return subprocess.run([docker, "exec", name, *command], capture_output=True).returncode


def test_in_the_container_the_victoria_healthcheck_passes_and_fails_on_another_port(victoria):
    docker, name = victoria
    test = _test("victoria")
    assert test[0] == "CMD"
    command = test[1:]
    deadline = time.monotonic() + 30
    while (rc := _exec(docker, name, command)) != 0 and time.monotonic() < deadline:
        time.sleep(1)
    assert rc == 0
    wrong_port = [part.replace(":8428/", ":8429/") for part in command]
    assert wrong_port != command
    assert _exec(docker, name, wrong_port) != 0
