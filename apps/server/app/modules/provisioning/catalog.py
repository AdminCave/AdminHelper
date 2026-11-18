# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The platform catalog behind GET /api/provisioning/platforms.

What a platform offers comes from the package repo the updater rolled out (``REPO_DIR``,
the same tree the gateway serves on the repo plane), not from configuration: a platform
without packages there has no install command. Commands are structured — a fixed head and
named arguments whose values the desktop fills in and quotes per shell. Nothing here is
quoted text with values in it (R-1595).

Layout read (apps/agent/build-repo.sh, build-pkg.sh):
  apt/dists/stable/InRelease, apt/dists/stable/main/binary-amd64/Packages
  rpm/repodata/repomd.xml, rpm/adminhelper-agent-<ver>-1.x86_64.rpm
  freebsd/<ABI>/meta.conf, freebsd/<ABI>/All/{adminhelper-agent,os-adminhelper}-<ver>.pkg
"""

from __future__ import annotations

import re
from pathlib import Path

INSTALLER_BASE = "https://raw.githubusercontent.com/AdminCave/AdminHelper/main/scripts"
DEFAULT_REPO_PORT = 8445
WINDOWS_EXE = r"& 'C:\Program Files\AdminHelper\adminhelper-agent.exe'"
# A Packages index bigger than this is not ours; the catalog then reports no apt versions.
_MAX_INDEX = 8 << 20
_VERSION = r"[0-9][0-9A-Za-z.+~]*"
# build-repo.sh accepts the release with or without a dist tag (-1.x86_64, -1.el9.x86_64).
_RPM = re.compile(rf"^adminhelper-agent-({_VERSION})-[0-9]+(?:\.[a-z0-9_]+)?\.x86_64\.rpm$")
_PKG = {
    "freebsd": re.compile(rf"^adminhelper-agent-({_VERSION})\.pkg$"),
    "opnsense": re.compile(rf"^os-adminhelper-({_VERSION})\.pkg$"),
}
_ABI = re.compile(r"^FreeBSD:[0-9]+:[a-z0-9_]+$")

# Only what the docs state (agent-deployment.html): package families, not release lists.
LINUX_SYSTEMS = ["Debian/Ubuntu (apt, systemd)", "Rocky/Alma/RHEL (dnf, systemd)"]


def _version_key(v: str) -> list[tuple[int, int | str]]:
    # Numeric runs compare as numbers, the rest as text: 0.47.10 sorts above 0.47.9.
    return [(0, int(p)) if p.isdigit() else (1, p) for p in re.findall(r"\d+|[^\d.]+", v)]


def _sorted(versions: set[str]) -> list[str]:
    return sorted(versions, key=_version_key, reverse=True)


def _apt_versions(repo: Path) -> set[str] | None:
    if not (repo / "apt/dists/stable/InRelease").is_file():
        return None
    index = repo / "apt/dists/stable/main/binary-amd64/Packages"
    try:
        if index.stat().st_size > _MAX_INDEX:
            return set()
        text = index.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    found: set[str] = set()
    for stanza in text.split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in stanza.splitlines() if ": " in line and line[0] != " "
        )
        version = fields.get("Version", "")
        if fields.get("Package") == "adminhelper-agent" and re.fullmatch(_VERSION, version):
            found.add(version)
    return found


def _rpm_versions(repo: Path) -> set[str] | None:
    rpm = repo / "rpm"
    if not (rpm / "repodata/repomd.xml").is_file():
        return None
    try:
        return {m.group(1) for p in rpm.iterdir() if (m := _RPM.match(p.name))}
    except OSError:
        return set()


def _bsd(repo: Path, platform: str) -> tuple[list[str], set[str]]:
    """ABIs that carry the platform's package, and the versions found there."""
    abis: list[str] = []
    versions: set[str] = set()
    root = repo / "freebsd"
    if not root.is_dir():
        return abis, versions
    try:
        abi_dirs = sorted(root.iterdir())
    except OSError:
        return abis, versions
    for abi_dir in abi_dirs:
        if not _ABI.match(abi_dir.name) or not (abi_dir / "meta.conf").is_file():
            continue
        try:
            names = [p.name for p in (abi_dir / "All").iterdir()]
        except OSError:
            continue
        found = {m.group(1) for n in names if (m := _PKG[platform].match(n))}
        if found:
            abis.append(abi_dir.name)
            versions |= found
    return abis, versions


def _arg(flag: str, value: str, *, optional: bool = False, mode: str | None = None) -> dict:
    return {"flag": flag, "value": value, "optional": optional, "mode": mode}


def _register_args() -> list[dict]:
    """The installer's provisioning arguments; without --token it asks hidden on /dev/tty."""
    return [
        _arg("--server", "serverUrl"),
        _arg("--server-id", "serverId"),
        _arg("--ca-fp", "caFp", optional=True),
        _arg("--token", "token", mode="automation"),
    ]


def _repo_port_suffix(repo_port: int) -> str:
    return "" if repo_port == DEFAULT_REPO_PORT else f" --repo-port {int(repo_port)}"


def _ports(enroll_port: int, repo_port: int, frp_port: int) -> list[dict]:
    return [
        {"port": 443, "purpose": "api", "tunnelOnly": False},
        {"port": int(enroll_port), "purpose": "enroll", "tunnelOnly": False},
        {"port": int(repo_port), "purpose": "repo", "tunnelOnly": False},
        {"port": int(frp_port), "purpose": "tunnel", "tunnelOnly": True},
    ]


def _doc(anchor: str) -> dict:
    return {
        "de": f"admin/agent-deployment.html#{anchor}",
        "en": f"en/admin/agent-deployment.html#{anchor}",
    }


def _linux(repo: Path, repo_port: int, ports: list[dict]) -> dict:
    apt, rpm = _apt_versions(repo), _rpm_versions(repo)
    available = apt is not None or rpm is not None
    install = (
        f"curl -fsSL {INSTALLER_BASE}/agent-install.sh | sudo bash -s --"
        f"{_repo_port_suffix(repo_port)}"
    )
    commands = []
    if available:
        # Re-registering runs the installer again: it reads the token hidden and, after the
        # enrollment, pins the internal CA for the repo again. An update does not: the
        # installer without --server-id resets the repo transport to unverified.
        commands = [
            {"action": "install", "shell": "bash", "base": install, "args": _register_args()},
            {
                "action": "update",
                "shell": "bash",
                "base": "if command -v apt-get >/dev/null; then sudo apt-get update && "
                "sudo apt-get install -y --only-upgrade adminhelper-agent; "
                "else sudo dnf upgrade -y adminhelper-agent; fi",
                "args": [],
            },
            {"action": "reregister", "shell": "bash", "base": install, "args": _register_args()},
            {
                "action": "remove",
                "shell": "bash",
                "base": "if command -v apt-get >/dev/null; then sudo apt-get purge -y "
                "adminhelper-agent; else sudo dnf remove -y adminhelper-agent; fi",
                "args": [],
            },
        ]
    return {
        "id": "linux",
        "available": available,
        "reason": None if available else "noRepo",
        "versions": _sorted((apt or set()) | (rpm or set())),
        "arch": ["amd64"],
        "abis": [],
        "prerequisites": {"systems": LINUX_SYSTEMS, "ports": ports},
        "commands": commands,
        "doc": _doc("linux"),
    }


def _bsd_platform(repo: Path, platform: str, repo_port: int, ports: list[dict]) -> dict:
    abis, versions = _bsd(repo, platform)
    available = bool(abis)
    install = (
        f"fetch -o - {INSTALLER_BASE}/agent-install-bsd.sh | sh -s --{_repo_port_suffix(repo_port)}"
    )
    # The repo names the installer writes (scripts/agent-install-bsd.sh). On OPNsense deleting
    # the plugin alone leaves the agent running (agent-deployment.html), so remove drops both.
    if platform == "opnsense":
        update = "pkg upgrade -y -r AdminHelper"
        remove = "pkg delete -y os-adminhelper adminhelper-agent"
        systems = ["OPNsense 26.1 (FreeBSD 14)", "OPNsense 26.7 (FreeBSD 15)"]
    else:
        update = "pkg upgrade -y -r adminhelper adminhelper-agent"
        remove = "pkg delete -y adminhelper-agent"
        systems = ["FreeBSD 14/15"]
    commands = []
    if available:
        commands = [
            {"action": "install", "shell": "sh", "base": install, "args": _register_args()},
            {"action": "update", "shell": "sh", "base": update, "args": []},
            {"action": "reregister", "shell": "sh", "base": install, "args": _register_args()},
            {"action": "remove", "shell": "sh", "base": remove, "args": []},
        ]
    return {
        "id": platform,
        "available": available,
        "reason": None if available else "noRepo",
        "versions": _sorted(versions),
        "arch": ["amd64"],
        "abis": abis,
        "prerequisites": {"systems": systems, "ports": ports},
        "commands": commands,
        "doc": _doc(platform),
    }


def _windows(ports: list[dict]) -> dict:
    # Windows packages come from the GitHub release, not the repo plane. The install
    # one-liner follows with R-1578; until then the catalog offers what works on an
    # installed agent.
    return {
        "id": "windows",
        "available": True,
        "reason": "notYet",
        "versions": [],
        "arch": ["amd64"],
        "abis": [],
        "prerequisites": {
            "systems": ["Windows (amd64)"],
            "ports": [p for p in ports if p["purpose"] != "repo"],
        },
        "commands": [
            {
                "action": "reregister",
                "shell": "powershell",
                "base": f"{WINDOWS_EXE} provision",
                "args": [
                    _arg("--url", "serverUrl"),
                    _arg("--server-id", "serverId"),
                    _arg("--ca-fp", "caFp", optional=True),
                    _arg("--insecure", "insecure", optional=True),
                    _arg("--token-stdin", "flag", mode="interactive"),
                    _arg("--token", "token", mode="automation"),
                ],
            },
            {
                "action": "remove",
                "shell": "powershell",
                "base": f"{WINDOWS_EXE} service uninstall --purge",
                "args": [],
            },
        ],
        "doc": _doc("windows"),
    }


def build_catalog(repo_dir: Path, *, repo_port: int, enroll_port: int, frp_port: int) -> dict:
    ports = _ports(enroll_port, repo_port, frp_port)
    return {
        "platforms": [
            _linux(repo_dir, repo_port, ports),
            _windows(ports),
            _bsd_platform(repo_dir, "freebsd", repo_port, ports),
            _bsd_platform(repo_dir, "opnsense", repo_port, ports),
        ]
    }
