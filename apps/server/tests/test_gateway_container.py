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
"""

import contextlib
import re
import shutil
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


def _compose_gateway() -> dict:
    """The gateway service of docker-compose.yml."""
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))["services"]["gateway"]


def test_compose_gives_the_gateway_only_the_capabilities_nginx_needs():
    gateway = _compose_gateway()
    assert gateway.get("cap_drop") == ["ALL"]
    assert sorted(gateway.get("cap_add", [])) == CAPABILITIES
    assert "no-new-privileges:true" in gateway.get("security_opt", [])
    assert gateway.get("sysctls", {}).get("net.ipv4.ip_unprivileged_port_start") == 0


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
    it, the volume of TLS material and the package repo; removes them again. Skips when Docker
    or the pinned base image is not at hand."""
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
    for path in (setup.repo, setup.repo / "apt"):
        path.chmod(0o755)
    (setup.repo / "apt" / "probe").chmod(0o644)

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
