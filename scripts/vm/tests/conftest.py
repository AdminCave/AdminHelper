# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hermetic scaffolding for test_vm.py: recorded replies, a fake clock, no network.

Nothing here invents a Proxmox answer. Every reply either comes from
fixtures/<name>.json (recorded against PVE 9.2.3, see README.md) or is an
explicit `status=`/`body=` a test wrote on purpose to describe a case the
recording could not reach, such as a 500 from a restarting pveproxy.
"""

from __future__ import annotations

import io
import json
import pathlib
import sys
import urllib.error
import urllib.parse

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import vm  # noqa: E402  (the path has to exist before the import)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    with open(FIXTURES / (name + ".json")) as fh:
        return json.load(fh)


def _encode(body) -> bytes:
    return (body if isinstance(body, str) else json.dumps(body)).encode()


class Reply(io.BytesIO):
    """Just enough of an http.client.HTTPResponse for urlopen's callers."""

    def __init__(self, status: int, body):
        super().__init__(_encode(body))
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class Call:
    def __init__(self, req, timeout=None):
        self.timeout = timeout
        self.method = req.get_method()
        self.url = req.full_url
        self.path, _, query = self.url.partition("?")
        self.query = dict(urllib.parse.parse_qsl(query))
        self.headers = {k.lower(): v for k, v in req.headers.items()}
        raw = req.data.decode() if req.data else ""
        self.body = dict(urllib.parse.parse_qsl(raw)) if raw else {}

    def __repr__(self):  # a failed assertion should say what was called
        return "<%s %s q=%r b=%r>" % (self.method, self.path, self.query, self.body)


class FakeHttp:
    """Route (method, substring) -> replies, in the order they were added."""

    def __init__(self):
        self.routes: list[dict] = []
        self.calls: list[Call] = []

    def add(
        self,
        method: str,
        contains: str,
        name: str | None = None,
        status: int | None = None,
        body=None,
        times: int | None = None,
    ):
        reply = fixture(name) if name else {"status": status or 200, "body": body}
        if status is not None:
            reply = dict(reply, status=status)
        if body is not None:
            reply = dict(reply, body=body)
        self.routes.append({"method": method, "contains": contains, "reply": reply, "left": times})
        return self

    def __call__(self, req, timeout=None, context=None):
        call = Call(req, timeout)
        self.calls.append(call)
        for route in self.routes:
            if route["method"] != call.method or route["contains"] not in call.url:
                continue
            if route["left"] is not None:
                if route["left"] <= 0:
                    continue
                route["left"] -= 1
            reply = route["reply"]
            if reply["status"] >= 400:
                raise urllib.error.HTTPError(
                    call.url, reply["status"], "error", {}, io.BytesIO(_encode(reply["body"]))
                )
            return Reply(reply["status"], reply["body"])
        raise AssertionError("no fake route for %r" % (call,))

    def paths(self, method: str | None = None) -> list[str]:
        return [c.path for c in self.calls if method is None or c.method == method]


class FakeClock:
    """Time that only moves when the code under test sleeps."""

    def __init__(self):
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float):
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(vm.time, "monotonic", fake.monotonic)
    monkeypatch.setattr(vm.time, "sleep", fake.sleep)
    return fake


@pytest.fixture
def http(monkeypatch) -> FakeHttp:
    fake = FakeHttp()
    monkeypatch.setattr(vm.urllib.request, "urlopen", fake)
    return fake


@pytest.fixture
def cfg(tmp_path) -> vm.Config:
    ca = tmp_path / "ca.pem"
    ca.write_text("")
    return vm.Config(
        {
            "AH_PVE_URL": "https://pve.example:8006",
            "AH_PVE_NODE": "<node>",
            "AH_PVE_TOKEN": "user@pve!vm=<secret>",
            "AH_PVE_CA": str(ca),
            "AH_PVE_STORAGE": "raid5",
            "AH_PVE_BRIDGE": "vmbr1",
            "AH_PVE_POOL": "adminhelper-ci",
            "AH_PVE_VMID_RANGE": "3000-3999",
            "AH_VM_SSH_KEY": str(tmp_path / "id_ed25519"),
            "AH_VM_MAX": "3",
            "AH_VM_LINKED": "1",
            "AH_VM_REMOTE_DIR": "~/adminhelper",
        }
    )


@pytest.fixture
def api(cfg, monkeypatch) -> vm.Api:
    made = vm.Api(cfg)
    # An empty CA file is not a usable SSL context, and building one would be the
    # only thing in this suite that touches the system trust store.
    monkeypatch.setattr(made, "context", lambda: None)
    return made
