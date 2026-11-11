# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""uvicorn, as docker-entrypoint.sh starts it, takes neither the client address nor the scheme
from X-Forwarded-For/-Proto, not even from loopback, which it trusts by default
(FORWARDED_ALLOW_IPS). The app derives the client address itself from the peers in
TRUSTED_PROXIES, and identity.py tells the gateway by the TCP peer.

The test starts uvicorn with the options of the entrypoint's `exec uvicorn` (host, port and the
worker count replaced) on an app that echoes what uvicorn hands it, with FORWARDED_ALLOW_IPS=*
in its environment, and sends forwarded headers from 127.0.0.1."""

import json
import os
import shlex
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

_ENTRYPOINT = Path(__file__).resolve().parents[1] / "docker-entrypoint.sh"

_ECHO_APP = """
import json


async def app(scope, receive, send):
    body = json.dumps({"client": scope["client"][0], "scheme": scope["scheme"]}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": body})
"""


def _uvicorn_options() -> list[str]:
    """The arguments after `exec uvicorn app.main:app` up to the line without a continuation."""
    lines = _ENTRYPOINT.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("exec uvicorn "))
    command = []
    for line in lines[start:]:
        command.append(line.rstrip("\\").strip())
        if not line.endswith("\\"):
            break
    args = shlex.split(" ".join(command))
    assert args[:3] == ["exec", "uvicorn", "app.main:app"]
    options, rest = [], args[3:]
    while rest:
        option = rest.pop(0)
        if option in ("--host", "--port", "--workers"):
            rest.pop(0)
        else:
            options.append(option)
    return options


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_the_entrypoint_starts_uvicorn_without_proxy_headers():
    options = _uvicorn_options()
    assert "--no-proxy-headers" in options
    assert not any(option.startswith("--forwarded-allow-ips") for option in options)


def test_uvicorn_as_started_ignores_forwarded_headers_even_from_loopback(tmp_path):
    (tmp_path / "echo_app.py").write_text(_ECHO_APP, encoding="utf-8")
    port = _free_port()
    env = {**os.environ, "FORWARDED_ALLOW_IPS": "*"}
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "echo_app:app", "--app-dir", str(tmp_path)]
        + ["--host", "127.0.0.1", "--port", str(port), *_uvicorn_options()],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/",
            headers={"X-Forwarded-For": "203.0.113.7", "X-Forwarded-Proto": "https"},
        )
        deadline = time.monotonic() + 15
        while True:
            try:
                with urllib.request.urlopen(request, timeout=2) as response:
                    seen = json.loads(response.read())
                break
            except OSError:
                assert server.poll() is None, "uvicorn exited before it answered"
                assert time.monotonic() < deadline, "uvicorn did not answer within 15 s"
                time.sleep(0.1)
    finally:
        server.terminate()
        server.wait(timeout=10)

    assert seen == {"client": "127.0.0.1", "scheme": "http"}
