# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The gateway container keeps only the capabilities its nginx master needs: CHOWN to hand its
temp directories to the image's user nginx, SETUID and SETGID to start its workers as that
user, DAC_OVERRIDE to read gateway.key, which the ca-issuer writes 0600 under its own UID.
Compose drops every other one, sets no-new-privileges and opens the ports of the container's
own network namespace to unprivileged processes (443, 8444 and 8445 without NET_BIND_SERVICE).

Some tests run the gateway image built from apps/gateway with the arguments compose gives
the service, in a Docker network of their own (nginx resolves its upstreams through the
embedded DNS), the TLS material in a volume as the ca-issuer leaves it and a package repo with
one file: nginx serves it on the repo plane, its master holds exactly the capabilities on the
list, its workers run as a user other than root, and it stops within the grace period with exit
code 0. Without any one capability of the list, one of these fails. They skip when Docker or the
pinned base image is not at hand.

The certless planes :8444 and :8445 cap concurrent requests per client address and per plane and
close idle connections after short timeouts; the mTLS plane :443 keeps nginx's defaults. Read
from nginx.conf, and in the container on the repo plane: one address gets 429 beyond its cap
while its other downloads go on, and a connection that sends no request after the handshake is
closed.

The gateway's healthcheck asks a listener of its own on 127.0.0.1 that answers only /healthz
without TLS: from nginx.conf and docker-compose.yml, and in the container, where the compose
command succeeds, a wrong port fails and the listener is out of reach from the network.
"""

import contextlib
import re
import shutil
import socket
import ssl
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

_REPO_ROOT = Path(__file__).resolve().parents[3]
_COMPOSE = _REPO_ROOT / "docker-compose.yml"
_GATEWAY_DIR = _REPO_ROOT / "apps" / "gateway"
_CA_ISSUER_DOCKERFILE = _REPO_ROOT / "apps" / "ca-issuer" / "Dockerfile"

CAPABILITIES = ["CHOWN", "DAC_OVERRIDE", "SETGID", "SETUID"]
# Bit numbers of these capabilities (linux/capability.h).
_CAPABILITY_BITS = {"CHOWN": 0, "DAC_OVERRIDE": 1, "SETGID": 6, "SETUID": 7}
WAIT = 15.0
PROBE = "/apt/probe"
# Far more than the socket buffers between nginx and a client hold, so a download at 1 KiB/s
# stays in progress for the whole test.
LARGE = "/apt/large"
LARGE_SIZE = 32 * 1024 * 1024

CERTLESS_ZONES = [
    ["$binary_remote_addr", "zone=certless_addr:10m"],
    ["$server_port", "zone=certless_plane:1m"],
]
# Per plane: limit_conn per address, then per plane.
CERTLESS_LIMITS = {
    "8444": [["certless_addr", "16"], ["certless_plane", "128"]],
    "8445": [["certless_addr", "64"], ["certless_plane", "256"]],
}
CERTLESS_TIMEOUTS = {
    "client_header_timeout": ["10s"],
    "client_body_timeout": ["10s"],
    "keepalive_timeout": ["15s"],
}
IDLE_LIMIT = 15.0


def _compose_gateway() -> dict:
    """The gateway service of docker-compose.yml."""
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))["services"]["gateway"]


def test_compose_gives_the_gateway_only_the_capabilities_nginx_needs():
    gateway = _compose_gateway()
    assert gateway.get("cap_drop") == ["ALL"]
    assert sorted(gateway.get("cap_add", [])) == CAPABILITIES
    assert "no-new-privileges:true" in gateway.get("security_opt", [])
    assert gateway.get("sysctls", {}).get("net.ipv4.ip_unprivileged_port_start") == 0


@dataclass
class Directive:
    name: str
    args: list[str]
    block: list["Directive"] | None


def _parse(tokens: list[str], start: int = 0) -> tuple[list[Directive], int]:
    """Directives from tokens[start:] up to the closing brace of their block (or the end)."""
    directives: list[Directive] = []
    words: list[str] = []
    index = start
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if token == ";":
            directives.append(Directive(words[0], words[1:], None))
            words = []
        elif token == "{":
            block, index = _parse(tokens, index)
            directives.append(Directive(words[0], words[1:], block))
            words = []
        elif token == "}":
            return directives, index
        else:
            words.append(token)
    return directives, index


def _nginx_http() -> list[Directive]:
    """The directives of the http block of apps/gateway/nginx.conf."""
    text = re.sub(r"#[^\n]*", "", (_GATEWAY_DIR / "nginx.conf").read_text(encoding="utf-8"))
    directives, _ = _parse(re.findall(r'"[^"]*"|[{};]|[^\s{};"]+', text))
    (http,) = [directive.block for directive in directives if directive.name == "http"]
    return http


def _args(block: list[Directive], name: str) -> list[list[str]]:
    return [directive.args for directive in block if directive.name == name]


def _names_within(block: list[Directive]) -> set[str]:
    """Names of all directives in block, nested blocks included."""
    names = set()
    for directive in block:
        names.add(directive.name)
        names |= _names_within(directive.block or [])
    return names


def _servers() -> dict[str, list[Directive]]:
    """The server blocks of the http block by the port they listen on."""
    servers = {}
    for directive in _nginx_http():
        if directive.name == "server":
            (listen,) = _args(directive.block, "listen")
            servers[listen[0]] = directive.block
    return servers


def test_the_certless_planes_cap_concurrent_requests_and_close_idle_connections_early():
    http = _nginx_http()
    assert _args(http, "limit_conn_zone") == CERTLESS_ZONES
    assert _args(http, "limit_conn_status") == [["429"]]

    servers = _servers()
    assert sorted(servers) == ["127.0.0.1:8081", "443", "8444", "8445"]
    for port, limits in CERTLESS_LIMITS.items():
        assert _args(servers[port], "limit_conn") == limits, port
        timeouts = {name: _args(servers[port], name) for name in CERTLESS_TIMEOUTS}
        assert timeouts == {name: [value] for name, value in CERTLESS_TIMEOUTS.items()}, port

    data_plane = {"limit_conn", *CERTLESS_TIMEOUTS} & _names_within(servers["443"])
    assert data_plane == set()


def _run_args(gateway: dict) -> list[str]:
    """docker run arguments for the capabilities, security options, sysctls and the process
    limit compose gives the gateway."""
    args = [arg for cap in gateway["cap_drop"] for arg in ("--cap-drop", cap)]
    args += [arg for cap in gateway["cap_add"] for arg in ("--cap-add", cap)]
    args += [arg for option in gateway["security_opt"] for arg in ("--security-opt", option)]
    sysctls = gateway["sysctls"].items()
    args += [arg for key, value in sysctls for arg in ("--sysctl", f"{key}={value}")]
    args += ["--pids-limit", str(gateway["pids_limit"])]
    return args


def _mask(capabilities: list[str]) -> str:
    """The capabilities as /proc/<pid>/status shows a set of them."""
    return f"{sum(1 << _CAPABILITY_BITS[cap] for cap in capabilities):016x}"


def _issuer_uid() -> int:
    """UID of the ca-issuer's user, as its Dockerfile creates it: the owner of the gateway's TLS
    material."""
    found = re.search(r"\buseradd\b.* -u (\d+) ", _CA_ISSUER_DOCKERFILE.read_text())
    assert found, _CA_ISSUER_DOCKERFILE
    return int(found[1])


def _tls_material(directory: Path) -> None:
    """A throwaway self-signed leaf, its key and the leaf again as the client CA."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "gateway test")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    pem = cert.public_bytes(serialization.Encoding.PEM)
    (directory / "gateway-fullchain.pem").write_bytes(pem)
    (directory / "client-ca.pem").write_bytes(pem)
    (directory / "gateway.key").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )


@dataclass
class Setup:
    docker: str
    prefix: str
    tag: str
    network: str
    client: str
    certs: str
    repo: Path


@pytest.fixture(scope="module")
def gateway_setup(tmp_path_factory):
    """Builds the image from apps/gateway, and for the module a network, a client container in
    it, the volume of TLS material and the package repo (the probe and a large file); removes
    them again. Skips when Docker or the pinned base image is not at hand."""
    dockerfile = (_GATEWAY_DIR / "Dockerfile").read_text()
    base = re.search(r"^FROM (\S+)$", dockerfile, re.M)
    assert base, dockerfile
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker is not available")
    if subprocess.run([docker, "image", "inspect", base[1]], capture_output=True).returncode:
        pytest.skip(f"no docker daemon or {base[1]} not present locally")

    run_id = uuid.uuid4().hex[:12]
    prefix = f"adminhelper-gateway-test-{run_id}"
    setup = Setup(
        docker=docker,
        prefix=prefix,
        tag=f"adminhelper-test/gateway-container:{run_id}",
        network=f"{prefix}-net",
        client=f"{prefix}-client",
        certs=f"{prefix}-certs",
        repo=tmp_path_factory.mktemp("gateway") / "repo",
    )
    pems = setup.repo.parent / "pems"
    pems.mkdir()
    _tls_material(pems)
    (setup.repo / "apt").mkdir(parents=True)
    (setup.repo / "apt" / "probe").write_text("probe\n")
    large = setup.repo / LARGE.lstrip("/")
    with large.open("wb") as sparse:
        sparse.truncate(LARGE_SIZE)
    for path in (setup.repo, setup.repo / "apt"):
        path.chmod(0o755)
    (setup.repo / "apt" / "probe").chmod(0o644)
    large.chmod(0o644)

    uid = _issuer_uid()
    # As the ca-issuer leaves it: the directory and the files its user's, the key 0600.
    fill = (
        f"cp /pems/* /certs/ && chown -R {uid}:{uid} /certs && chmod 0644 /certs/*.pem"
        " && chmod 0600 /certs/gateway.key"
    )
    try:
        build = subprocess.run(
            [docker, "build", "-q", "-t", setup.tag, str(_GATEWAY_DIR)],
            capture_output=True,
            text=True,
        )
        assert build.returncode == 0, build.stderr
        for command in (
            [docker, "network", "create", setup.network],
            [docker, "volume", "create", setup.certs],
            [docker, "run", "--rm", "-v", f"{setup.certs}:/certs", "-v", f"{pems}:/pems:ro"]
            + ["--entrypoint", "sh", setup.tag, "-c", fill],
            [docker, "run", "-d", "--name", setup.client, "--network", setup.network]
            + ["--entrypoint", "sleep", setup.tag, "3600"],
        ):
            result = subprocess.run(command, capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
        yield setup
    finally:
        subprocess.run([docker, "rm", "-f", setup.client], capture_output=True)
        subprocess.run([docker, "volume", "rm", setup.certs], capture_output=True)
        subprocess.run([docker, "network", "rm", setup.network], capture_output=True)
        subprocess.run([docker, "image", "rm", "-f", setup.tag], capture_output=True)


class Gateway:
    """A container of the gateway image in the module's network."""

    def __init__(self, setup: Setup):
        self.setup = setup
        self.docker = setup.docker
        self.name = f"{setup.prefix}-{uuid.uuid4().hex[:8]}"

    def exec(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.docker, "exec", self.name, *args], capture_output=True, text=True
        )

    def logs(self) -> str:
        return subprocess.run(
            [self.docker, "logs", self.name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ).stdout

    def running(self) -> bool:
        inspect = [self.docker, "inspect", "--format", "{{.State.Running}}", self.name]
        return subprocess.run(inspect, capture_output=True, text=True).stdout.strip() == "true"

    def address(self) -> str:
        """The container's address in the module's network."""
        template = f'{{{{(index .NetworkSettings.Networks "{self.setup.network}").IPAddress}}}}'
        inspect = [self.docker, "inspect", "--format", template, self.name]
        result = subprocess.run(inspect, capture_output=True, text=True)
        assert result.returncode == 0 and result.stdout.strip(), result.stderr
        return result.stdout.strip()

    def fetch(self) -> str:
        """HTTP status of the probe on the repo plane as the client container gets it; 000 for
        no answer."""
        url = f"https://{self.name}:8445{PROBE}"
        curl = ["curl", "-sk", "--max-time", "2", "-o", "/dev/null", "-w", "%{http_code}", url]
        result = subprocess.run(
            [self.docker, "exec", self.setup.client, *curl], capture_output=True, text=True
        )
        return result.stdout.strip() or "000"

    def answer(self) -> str:
        """The first 200 for the probe, or the last status while the container ran, up to
        WAIT seconds."""
        deadline = time.monotonic() + WAIT
        while True:
            status = self.fetch()
            if status == "200" or not self.running() or time.monotonic() > deadline:
                return status
            time.sleep(0.3)

    def status(self, pid: int) -> dict[str, str]:
        result = self.exec("cat", f"/proc/{pid}/status")
        assert result.returncode == 0, result.stderr
        fields = dict(line.split(":", 1) for line in result.stdout.splitlines() if ":" in line)
        return {key: " ".join(value.split()) for key, value in fields.items()}

    def workers(self) -> list[int]:
        """UIDs of the nginx master's children."""
        script = r"""for status in /proc/[0-9]*/status; do
    awk '/^(Name|PPid|Uid):/ { printf "%s ", $2 } END { print "" }' "$status" 2>/dev/null
done"""
        result = self.exec("sh", "-c", script)
        assert result.returncode == 0, result.stderr
        uids = []
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) == 3 and fields[:2] == ["nginx", "1"]:
                uids.append(int(fields[2]))
        return uids

    def stop(self) -> str:
        """docker stop within the grace period compose gives the gateway; returns the exit
        code."""
        grace = str(_compose_gateway().get("stop_grace_period", "10s")).removesuffix("s")
        subprocess.run([self.docker, "stop", "-t", grace, self.name], capture_output=True)
        inspect = [self.docker, "inspect", "--format", "{{.State.ExitCode}}", self.name]
        return subprocess.run(inspect, capture_output=True, text=True).stdout.strip()


@contextlib.contextmanager
def _gateway(setup: Setup, gateway: dict):
    """Starts the gateway image with the run arguments of gateway (a compose service), yields
    the container and removes it again."""
    box = Gateway(setup)
    run = [setup.docker, "run", "-d", "--name", box.name, "--network", setup.network]
    run += _run_args(gateway)
    run += ["-e", "MTLS_ENFORCE=false", "-v", f"{setup.certs}:/etc/nginx/certs:ro"]
    run += ["-v", f"{setup.repo}:/usr/share/nginx/repo:ro", setup.tag]
    try:
        result = subprocess.run(run, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        yield box
    finally:
        subprocess.run([setup.docker, "rm", "-f", box.name], capture_output=True)


def test_in_the_gateway_image_nginx_serves_and_stops_with_only_these_capabilities(gateway_setup):
    with _gateway(gateway_setup, _compose_gateway()) as box:
        assert box.answer() == "200", box.logs()

        master = box.status(1)
        assert master["Name"] == "nginx"
        assert master["CapEff"] == master["CapBnd"] == _mask(CAPABILITIES)
        assert master["NoNewPrivs"] == "1"
        workers = box.workers()
        assert workers, box.logs()
        assert [uid for uid in workers if uid == 0] == []

        assert box.stop() == "0", box.logs()


@pytest.mark.parametrize("capability", CAPABILITIES)
def test_without_any_one_of_them_the_gateway_does_not_start_serve_or_stop_cleanly(
    gateway_setup, capability
):
    gateway = _compose_gateway()
    gateway["cap_add"] = [cap for cap in gateway["cap_add"] if cap != capability]
    assert len(gateway["cap_add"]) == len(CAPABILITIES) - 1
    with _gateway(gateway_setup, gateway) as box:
        outcome = (box.answer(), box.stop())
        assert outcome != ("200", "0"), box.logs()


def test_on_the_repo_plane_one_address_gets_429_beyond_its_cap_while_its_downloads_go_on(
    gateway_setup,
):
    downloads = int(CERTLESS_LIMITS["8445"][0][1]) + 1
    with _gateway(gateway_setup, _compose_gateway()) as box:
        assert box.answer() == "200", box.logs()
        # At 1 KiB/s a download of LARGE is still in progress when curl gives up after 8 s
        # (exit code 28): every one that got 200 ran beside the one that got 429.
        curl = (
            "curl -sk --limit-rate 1k --max-time 8 -o /dev/null"
            f" -w '%{{http_code}} %{{exitcode}}\\n' https://{box.name}:8445{LARGE}"
        )
        script = f"for i in $(seq {downloads}); do {curl} & done; wait"
        result = subprocess.run(
            [box.docker, "exec", gateway_setup.client, "sh", "-c", script],
            capture_output=True,
            text=True,
        )
        outcomes = result.stdout.splitlines()
        assert len(outcomes) == downloads, result
        assert "429 0" in outcomes, outcomes
        assert set(outcomes) == {"200 28", "429 0"}, outcomes

        assert box.fetch() == "200", box.logs()


def test_on_the_repo_plane_a_connection_without_a_request_is_closed_within_15_seconds(
    gateway_setup,
):
    with _gateway(gateway_setup, _compose_gateway()) as box:
        assert box.answer() == "200", box.logs()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with socket.create_connection((box.address(), 8445), timeout=WAIT) as raw:
            with context.wrap_socket(raw) as tls:
                opened = time.monotonic()
                tls.settimeout(IDLE_LIMIT + 5)
                try:
                    closed = tls.recv(1) == b""
                except TimeoutError:
                    closed = False
                except (ssl.SSLEOFError, ConnectionResetError):
                    closed = True
                elapsed = time.monotonic() - opened
        assert closed and elapsed <= IDLE_LIMIT, elapsed


def _healthz_listener() -> tuple[str, list[Directive]]:
    """The port and block of the one server that listens on 127.0.0.1 only."""
    local = [
        (listen[0], block)
        for listen_args, block in ((_args(b, "listen"), b) for b in _servers().values())
        for listen in listen_args
        if listen[0].startswith("127.0.0.1:")
    ]
    assert len(local) == 1, local
    ((address, block),) = local
    assert _args(block, "listen") == [[address]], "no ssl, no default_server"
    return address.removeprefix("127.0.0.1:"), block


def _seconds(duration: str) -> int:
    value = re.fullmatch(r"(?:(\d+)m)?(?:(\d+)s)?", str(duration))
    assert value and any(value.groups()), duration
    return int(value[1] or 0) * 60 + int(value[2] or 0)


def test_the_gateway_healthcheck_asks_a_plain_listener_on_localhost_for_healthz():
    port, block = _healthz_listener()
    locations = {tuple(d.args): d.block for d in block if d.name == "location"}
    assert _args(locations[("=", "/healthz")], "return")[0][0] == "200"

    healthcheck = _compose_gateway()["healthcheck"]
    url = f"http://127.0.0.1:{port}/healthz"
    assert healthcheck["test"] == ["CMD", "wget", "-q", "-O", "/dev/null", url]
    # The entrypoint waits up to 120 s for the TLS material before nginx starts.
    assert _seconds(healthcheck["start_period"]) >= 120


def test_in_the_container_the_healthcheck_passes_and_the_listener_stays_local(gateway_setup):
    port, _ = _healthz_listener()
    command = _compose_gateway()["healthcheck"]["test"][1:]
    with _gateway(gateway_setup, _compose_gateway()) as box:
        assert box.answer() == "200", box.logs()
        check = box.exec(*command)
        assert check.returncode == 0, (check, box.logs())

        wrong = [arg.replace(f":{port}/", f":{int(port) + 1}/") for arg in command]
        assert wrong != command
        assert box.exec(*wrong).returncode != 0

        remote = ["wget", "-q", "-T", "3", "-O", "/dev/null", f"http://{box.name}:{port}/healthz"]
        result = subprocess.run(
            [box.docker, "exec", gateway_setup.client, *remote], capture_output=True, text=True
        )
        assert result.returncode != 0, result
