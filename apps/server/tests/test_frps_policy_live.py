# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""frps admits a proxy only as the policy file the server writes allows it (frp/policy.py and
the plugin frps-policy, apps/agent/internal/frpspolicy): a real frpc of the frp version the
stack pins registers against the frps image as compose runs it, with the policy and the
frpc.toml of the server's generators.

A host's own stcp and https proxy, as the generator writes them, come up. Refused are a proxy
without a key or with a wrong one, the tunnel of another host under the own user, the user of
another host with the own key, a domain the tunnel does not have, a tcp proxy with a remotePort
and a group the tunnel does not have; without the policy file no proxy comes up. Each refusal
is the plugin's, for its reason.

frpc runs in the network namespace of the frps container, which has no other network, and
reaches frps on 127.0.0.1. The tests skip when Docker, a pinned base image of frps or the frpc
image is not at hand."""

import contextlib
import re
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from ipaddress import IPv4Address
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID

from app.modules.frp import docker_manager, policy
from app.modules.frp._helpers import frpc_sync_inputs
from app.modules.frp.config_generator import (
    _AGENT_IDENTITY_DIR,
    generate_frpc_toml,
    generate_frps_toml,
)
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.frp.proxy_key import PROXY_KEY_META, proxy_key
from app.modules.servers.models import Server

from .test_frps_supervisor import (
    STARTED_SUCCESSFULLY,
    TOKEN,
    WAIT,
    Container,
    _bases,
    _built_frps_image,
    _container,
    _key,
    _key_pem,
)

# The frpc of the frp version the frps image builds on (test_frpc_is_the_version_of_frps). On
# one line: the CI job of the server pulls it from here.
FRPC_IMAGE = "snowdreamtech/frpc:0.72.0-alpine@sha256:ade64d3a367d68634131515dd7de88e125a9ae78f4f6af7641589a46f7f913b9"
SERVER_A = "3c9d0f1e-2a4b-4c5d-8e6f-7a8b9c0d1e2f"
SERVER_B = "9e8d7c6b-5a49-4382-9170-6f5e4d3c2b1a"
CONFIG = {
    "id": "cfg-1",
    "name": "Default",
    "server_addr": "127.0.0.1",
    "bind_port": 7000,
    "auth_token": TOKEN,
    "vhost_https_port": 8443,
}
# The reason the plugin gives for a proxy it admits: none.
ADMITTED = ""


def test_frpc_is_the_version_of_frps():
    version = re.compile(r"^snowdreamtech/(frp[sc]):(\d+\.\d+\.\d+)-alpine@sha256:[0-9a-f]{64}$")
    frps = version.match(_bases()[-1])
    frpc = version.match(FRPC_IMAGE)
    assert frps and frpc
    assert (frps[1], frpc[1], frpc[2]) == ("frps", "frpc", frps[2])


def _cert(key, name: str, issuer_key, issuer: str, *, ca: bool, ip: str | None = None) -> bytes:
    now = datetime.now(timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer)]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    if ip is not None:
        # frpc checks the certificate of frps against serverAddr.
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(IPv4Address(ip))]), critical=False
        )
    return builder.sign(issuer_key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM)


@pytest.fixture(scope="module")
def pki() -> dict[str, bytes]:
    """One CA for frps and the agents, as the CA issuer has it."""
    ca_key, frps_key, agent_key = _key(), _key(), _key()
    ca = _cert(ca_key, "test ca", ca_key, "test ca", ca=True)
    return {
        "ca.crt": ca,
        "frps.crt": _cert(frps_key, "frps", ca_key, "test ca", ca=False, ip="127.0.0.1"),
        "frps.key": _key_pem(frps_key),
        "agent.crt": _cert(agent_key, "agent", ca_key, "test ca", ca=False),
        "agent.key": _key_pem(agent_key),
    }


@pytest.fixture(scope="module")
def frps_image():
    yield from _built_frps_image()


@pytest.fixture(scope="module")
def docker(frps_image) -> str:
    docker, _ = frps_image
    if subprocess.run([docker, "image", "inspect", FRPC_IMAGE], capture_output=True).returncode:
        pytest.skip(f"{FRPC_IMAGE} not present locally")
    return docker


@pytest.fixture(scope="module")
def frps(tmp_path_factory, frps_image, docker, pki):
    """frps from the image, on the generator's frps.toml, until the end of the module."""
    toml = generate_frps_toml(FrpServerConfig(**CONFIG))
    root = tmp_path_factory.mktemp("frps")
    with _container(frps_image, root, pki, toml) as box:
        box.wait_until(
            lambda: STARTED_SUCCESSFULLY in box.logs() and box.read().state == "running",
            "frps up",
        )
        yield box


def _tunnel(tunnel_id: str, server_id: str, tunnel_type: str, **over) -> FrpTunnel:
    fields = {
        "id": tunnel_id,
        "server_id": server_id,
        "frp_config_id": CONFIG["id"],
        "name": tunnel_id,
        "tunnel_type": tunnel_type,
        "protocol": "ssh" if tunnel_type == "stcp" else "web",
        "local_port": 22 if tunnel_type == "stcp" else 443,
        "secret_key": "stcp-secret-placeholder" if tunnel_type == "stcp" else None,
        "enabled": True,
    }
    fields.update(over)
    return FrpTunnel(**fields)


@pytest.fixture()
def frpc_toml(db_session, frps, monkeypatch) -> str:
    """Host A's frpc.toml as the sync hands it out; the policy for A and B is in place."""
    db_session.add(FrpServerConfig(**CONFIG))
    db_session.add_all([Server(id=SERVER_A, name="server-a"), Server(id=SERVER_B, name="server-b")])
    db_session.flush()
    db_session.add_all(
        [
            _tunnel("t-ssh", SERVER_A, "stcp"),
            _tunnel("t-web", SERVER_A, "https", custom_domains="web.example"),
            _tunnel("t-db", SERVER_B, "stcp"),
        ]
    )
    db_session.commit()
    monkeypatch.setattr(docker_manager, "FRP_CONFIG_DIR", frps.frp)
    policy.sync_policy(db_session)
    assert (frps.frp / docker_manager.POLICY_FILE).is_file()
    config, tunnels, allow_users = frpc_sync_inputs(db_session, SERVER_A)
    return generate_frpc_toml(config, tunnels, SERVER_A, allow_users)


class Frpc:
    def __init__(self, docker: str, name: str):
        self.docker, self.name = docker, name

    def logs(self) -> str:
        return subprocess.run(
            [self.docker, "logs", self.name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ).stdout


@contextlib.contextmanager
def _frpc(docker: str, frps: Container, root: Path, pki: dict[str, bytes], toml: str):
    """frpc on toml with the agent's identity where the generator points it, in the network
    namespace of frps."""
    name = f"frpc-policy-test-{uuid.uuid4().hex[:12]}"
    conf, identity = root / "conf", root / "identity"
    for directory in (conf, identity):
        directory.mkdir()
    (conf / "frpc.toml").write_text(toml, encoding="utf-8")
    for file in ("ca.crt", "agent.crt", "agent.key"):
        (identity / file).write_bytes(pki[file])
    run = [docker, "run", "-d", "--name", name, "--network", f"container:{frps.name}"]
    run += ["--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
    run += ["-v", f"{conf}:/etc/frp:ro", "-v", f"{identity}:{_AGENT_IDENTITY_DIR}:ro"]
    run += ["--entrypoint", "frpc", FRPC_IMAGE, "-c", "/etc/frp/frpc.toml"]
    try:
        subprocess.run(run, check=True, capture_output=True)
        yield Frpc(docker, name)
    finally:
        subprocess.run([docker, "rm", "-f", name], capture_output=True)


# The plugin's decision on a proxy, as it logs it (frpspolicy/handler.go).
_DECISION = re.compile(
    r'msg="proxy (?:admitted|refused)" user=(?P<user>\S+) proxy=(?P<proxy>\S+)'
    r'(?: reason=(?:"(?P<quoted>[^"]*)"|(?P<word>\S+)))?'
)
# frpc's word on the answer of frps, per proxy (client/control.go).
_STARTED = "] [{}] start proxy success"
_START_ERROR = "] [{}] start error: "


def _register(docker, frps, root, pki, toml: str) -> dict[str, str]:
    """Runs frpc on toml until frps answered on each of its proxies; returns the plugin's
    reason by proxy name, ADMITTED for a proxy it let through, and checks that frpc got the
    same answer."""
    names = re.findall(r'^name = "([^"]+)"$', toml, re.M)
    user = re.search(r'^user = "([^"]+)"$', toml, re.M)[1]
    seen = len(frps.logs())
    decisions: dict[str, str] = {}
    with _frpc(docker, frps, root, pki, toml) as frpc:

        def answered() -> bool:
            for match in _DECISION.finditer(frps.logs()[seen:]):
                if match["user"] == user and match["proxy"].startswith(f"{user}."):
                    reason = match["quoted"] or match["word"] or ADMITTED
                    decisions[match["proxy"].removeprefix(f"{user}.")] = reason
            log = frpc.logs()
            return set(decisions) == set(names) and all(
                _STARTED.format(name) in log or _START_ERROR.format(name) in log for name in names
            )

        deadline = time.monotonic() + WAIT * 3
        while not answered():
            assert time.monotonic() < deadline, (
                f"no answer to each of {names}:\n{frps.logs()[seen:]}\n{frpc.logs()}"
            )
            time.sleep(0.2)
        log = frpc.logs()
    for name, reason in decisions.items():
        started = _STARTED.format(name) in log
        refused = _START_ERROR.format(name) in log
        assert (started, refused) == (reason == ADMITTED, reason != ADMITTED), (name, log)
    return decisions


def _edit(toml: str, old: str, new: str, count: int = 1) -> str:
    assert toml.count(old) == count, old
    return toml.replace(old, new)


def test_the_own_stcp_and_https_proxy_of_a_host_come_up(docker, frps, tmp_path, pki, frpc_toml):
    decisions = _register(docker, frps, tmp_path, pki, frpc_toml)
    assert decisions == {"t-ssh": ADMITTED, "t-web": ADMITTED}


KEY_LINE = f'metadatas.{PROXY_KEY_META} = "{{}}"\n'
STCP = 'type = "stcp"'
SECRET = 'secretKey = "stcp-secret-placeholder"\n'
ALLOW = 'allowUsers = ["ops-admin"]\n'
DOMAINS = 'customDomains = ["web.example"]\n'


def _no_key(toml):
    return _edit(toml, KEY_LINE.format(proxy_key(SERVER_A)), "", count=2)


def _wrong_key(toml):
    return _edit(toml, proxy_key(SERVER_A), proxy_key(str(uuid.uuid4())), count=2)


def _tunnel_of_another_host(toml):
    return _edit(toml, 'name = "t-ssh"', 'name = "t-db"')


def _user_of_another_host(toml):
    toml = _edit(toml, f'user = "{SERVER_A}"', f'user = "{SERVER_B}"')
    return _tunnel_of_another_host(toml)


def _domain_not_assigned(toml):
    return _edit(toml, DOMAINS, 'customDomains = ["other.example"]\n')


def _tcp_with_remote_port(toml):
    toml = _edit(_edit(_edit(toml, SECRET, ""), ALLOW, ""), STCP, 'type = "tcp"')
    return _edit(toml, "localPort = 22\n", "localPort = 22\nremotePort = 2222\n")


def _group(toml):
    return _edit(toml, DOMAINS, DOMAINS + 'loadBalancer.group = "web"\n')


REFUSED = {
    "no key": (_no_key, {"t-ssh": "no key", "t-web": "no key"}),
    "wrong key": (_wrong_key, {"t-ssh": "wrong key", "t-web": "wrong key"}),
    "tunnel of another host": (
        _tunnel_of_another_host,
        {"t-db": "no tunnel of this user", "t-web": ADMITTED},
    ),
    "user of another host": (_user_of_another_host, {"t-db": "wrong key", "t-web": "wrong key"}),
    "domain not assigned": (
        _domain_not_assigned,
        {"t-ssh": ADMITTED, "t-web": "other custom domains"},
    ),
    "tcp with remotePort": (_tcp_with_remote_port, {"t-ssh": "other type", "t-web": ADMITTED}),
    "group": (_group, {"t-ssh": ADMITTED, "t-web": "other group"}),
}


@pytest.mark.parametrize("case", list(REFUSED))
def test_a_proxy_the_policy_does_not_hold_is_refused(docker, frps, tmp_path, pki, frpc_toml, case):
    edit, expected = REFUSED[case]
    assert _register(docker, frps, tmp_path, pki, edit(frpc_toml)) == expected


def test_without_the_policy_file_no_proxy_comes_up(docker, frps, tmp_path, pki, frpc_toml):
    (frps.frp / docker_manager.POLICY_FILE).unlink()
    decisions = _register(docker, frps, tmp_path, pki, frpc_toml)
    assert decisions == {"t-ssh": "no policy", "t-web": "no policy"}
