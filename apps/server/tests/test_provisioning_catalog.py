# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""GET /api/provisioning/platforms: what the package repo carries decides which platform
has commands, and the commands stay structured (no values inside server text, R-1595)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import config
from app.core.auth import create_access_token
from app.core.identity import SCOPE_AGENT
from app.modules.provisioning.catalog import build_catalog
from tests.test_mtls_scope import _gateway_headers
from tests.token_claims import claims_for

PORTS = {"repo_port": 8445, "enroll_port": 8444, "frp_port": 7000}


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _apt(repo: Path, *versions: str) -> None:
    _write(repo / "apt/dists/stable/InRelease", "signed")
    stanzas = [f"Package: adminhelper-agent\nVersion: {v}\nArchitecture: amd64" for v in versions]
    stanzas.append("Package: something-else\nVersion: 9.9.9")
    _write(repo / "apt/dists/stable/main/binary-amd64/Packages", "\n\n".join(stanzas) + "\n")


def _rpm(repo: Path, *versions: str) -> None:
    _write(repo / "rpm/repodata/repomd.xml", "<repomd/>")
    for v in versions:
        _write(repo / f"rpm/adminhelper-agent-{v}-1.x86_64.rpm")


def _bsd(repo: Path, abi: str, *names: str) -> None:
    _write(repo / f"freebsd/{abi}/meta.conf", "version = 2;")
    for n in names:
        _write(repo / f"freebsd/{abi}/All/{n}")


def _by_id(catalog: dict) -> dict[str, dict]:
    return {p["id"]: p for p in catalog["platforms"]}


def test_without_a_repo_only_windows_is_offered(tmp_path):
    platforms = _by_id(build_catalog(tmp_path / "missing", **PORTS))
    assert list(platforms) == ["linux", "windows", "freebsd", "opnsense"]
    for pid in ("linux", "freebsd", "opnsense"):
        assert platforms[pid]["available"] is False
        assert platforms[pid]["reason"] == "noRepo"
        assert platforms[pid]["commands"] == []
        assert platforms[pid]["versions"] == []
    win = platforms["windows"]
    assert win["available"] is True and win["reason"] == "notYet"
    assert [c["action"] for c in win["commands"]] == ["reregister", "remove"]


def test_apt_and_rpm_versions_merge_newest_first(tmp_path):
    _apt(tmp_path, "0.47.9", "0.47.10")
    _rpm(tmp_path, "0.47.10", "0.46.0")
    _write(tmp_path / "rpm/adminhelper-agent-0.47.11-1.el9.x86_64.rpm")
    linux = _by_id(build_catalog(tmp_path, **PORTS))["linux"]
    assert linux["available"] is True and linux["reason"] is None
    assert linux["versions"] == ["0.47.11", "0.47.10", "0.47.9", "0.46.0"]
    assert [c["action"] for c in linux["commands"]] == ["install", "update", "reregister", "remove"]


def test_apt_without_signed_release_is_not_a_repo(tmp_path):
    _write(tmp_path / "apt/dists/stable/main/binary-amd64/Packages", "Package: adminhelper-agent\n")
    assert _by_id(build_catalog(tmp_path, **PORTS))["linux"]["available"] is False


def test_a_hostile_version_field_is_dropped(tmp_path):
    _write(tmp_path / "apt/dists/stable/InRelease", "signed")
    _write(
        tmp_path / "apt/dists/stable/main/binary-amd64/Packages",
        "Package: adminhelper-agent\nVersion: 1.0; rm -rf /\n\n"
        "Package: adminhelper-agent\nVersion: 0.47.0\n",
    )
    assert _by_id(build_catalog(tmp_path, **PORTS))["linux"]["versions"] == ["0.47.0"]


def test_an_unreadable_repo_part_reads_as_empty(tmp_path, monkeypatch):
    _rpm(tmp_path, "0.47.0")
    _bsd(tmp_path, "FreeBSD:15:amd64", "adminhelper-agent-0.47.0.pkg")

    def _refuse(self):
        raise PermissionError(self)

    monkeypatch.setattr(Path, "iterdir", _refuse)
    platforms = _by_id(build_catalog(tmp_path, **PORTS))
    assert platforms["linux"]["available"] is True and platforms["linux"]["versions"] == []
    assert platforms["freebsd"]["available"] is False


def test_an_unreadable_abi_package_folder_drops_only_that_abi(tmp_path, monkeypatch):
    _bsd(tmp_path, "FreeBSD:14:amd64", "adminhelper-agent-0.46.0.pkg")
    _bsd(tmp_path, "FreeBSD:15:amd64", "adminhelper-agent-0.47.0.pkg")
    iterdir = Path.iterdir

    def _refuse_one(self):
        if self == tmp_path / "freebsd/FreeBSD:14:amd64/All":
            raise PermissionError(self)
        return iterdir(self)

    monkeypatch.setattr(Path, "iterdir", _refuse_one)
    freebsd = _by_id(build_catalog(tmp_path, **PORTS))["freebsd"]
    assert freebsd["abis"] == ["FreeBSD:15:amd64"]
    assert freebsd["versions"] == ["0.47.0"]


def test_freebsd_and_opnsense_come_from_their_own_packages(tmp_path):
    _bsd(tmp_path, "FreeBSD:14:amd64", "adminhelper-agent-0.47.0.pkg")
    _bsd(tmp_path, "FreeBSD:15:amd64", "adminhelper-agent-0.47.0.pkg", "os-adminhelper-0.47.0.pkg")
    _bsd(tmp_path, "not-an-abi", "os-adminhelper-9.9.9.pkg")
    platforms = _by_id(build_catalog(tmp_path, **PORTS))
    assert platforms["freebsd"]["abis"] == ["FreeBSD:14:amd64", "FreeBSD:15:amd64"]
    assert platforms["opnsense"]["abis"] == ["FreeBSD:15:amd64"]
    assert platforms["opnsense"]["versions"] == ["0.47.0"]
    assert platforms["linux"]["available"] is False


def test_install_args_are_named_values_never_text(tmp_path):
    _apt(tmp_path, "0.47.0")
    _bsd(tmp_path, "FreeBSD:15:amd64", "adminhelper-agent-0.47.0.pkg", "os-adminhelper-0.47.0.pkg")
    for platform in build_catalog(tmp_path, **PORTS)["platforms"]:
        for cmd in platform["commands"]:
            for arg in cmd["args"]:
                assert arg["value"] in {
                    "serverUrl",
                    "serverId",
                    "caFp",
                    "token",
                    "tokenStdin",
                    "flag",
                    "insecure",
                }
            # The token is only ever a parameter in automation mode; otherwise it is read hidden.
            token_args = [a for a in cmd["args"] if a["value"] in ("token", "tokenStdin")]
            assert all(a["mode"] == "automation" for a in token_args)
    linux = _by_id(build_catalog(tmp_path, **PORTS))["linux"]
    install = next(c for c in linux["commands"] if c["action"] == "install")
    assert install["shell"] == "bash"
    assert install["base"].endswith("agent-install.sh | sudo bash -s --")
    assert [a["flag"] for a in install["args"]] == ["--server", "--server-id", "--ca-fp", "--token"]


def test_a_non_default_repo_port_reaches_the_installers(tmp_path):
    _apt(tmp_path, "0.47.0")
    _bsd(tmp_path, "FreeBSD:15:amd64", "adminhelper-agent-0.47.0.pkg")
    catalog = _by_id(build_catalog(tmp_path, repo_port=9445, enroll_port=9444, frp_port=7700))
    for pid in ("linux", "freebsd"):
        install = next(c for c in catalog[pid]["commands"] if c["action"] == "install")
        assert install["base"].endswith(" -s -- --repo-port 9445")
    ports = {p["purpose"]: p for p in catalog["linux"]["prerequisites"]["ports"]}
    assert ports["enroll"]["port"] == 9444 and ports["repo"]["port"] == 9445
    assert ports["tunnel"] == {"port": 7700, "purpose": "tunnel", "tunnelOnly": True}
    assert "repo" not in {p["purpose"] for p in catalog["windows"]["prerequisites"]["ports"]}


def test_windows_reregister_reads_the_token_hidden_unless_automated(tmp_path):
    win = _by_id(build_catalog(tmp_path, **PORTS))["windows"]
    rereg = next(c for c in win["commands"] if c["action"] == "reregister")
    assert rereg["shell"] == "powershell"
    token = [(a["flag"], a["value"], a["mode"]) for a in rereg["args"] if "token" in a["flag"]]
    # Automated too, the token goes to the agent on stdin: as --token it would sit in the
    # process list while the provisioning runs.
    assert token == [
        ("--token-stdin", "flag", "interactive"),
        ("--token-stdin", "tokenStdin", "automation"),
    ]
    assert win["doc"] == {
        "de": "admin/agent-deployment.html#windows",
        "en": "en/admin/agent-deployment.html#windows",
    }


def test_windows_commands_call_the_agent_in_its_own_program_folder(tmp_path):
    # "AdminHelper" under Program Files is the desktop app's MSI folder; the agent
    # installs itself into "AdminHelper Agent" (service_windows.go, programDirName).
    win = _by_id(build_catalog(tmp_path, **PORTS))["windows"]
    exe = r"& 'C:\Program Files\AdminHelper Agent\adminhelper-agent.exe'"
    bases = {c["action"]: c["base"] for c in win["commands"]}
    assert bases["reregister"] == f"{exe} provision"
    assert bases["remove"] == f"{exe} service uninstall --purge"


# --- route ----------------------------------------------------------------------


def _bearer(username: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(claims_for(username))}"}


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    _apt(tmp_path, "0.47.0")
    monkeypatch.setattr(config, "REPO_DIR", tmp_path)
    return tmp_path


def test_route_serves_the_catalog_to_an_admin(test_client, admin_user, repo):
    resp = test_client.get("/api/provisioning/platforms", headers=_bearer("admin"))
    assert resp.status_code == 200, resp.text
    platforms = _by_id(resp.json())
    assert platforms["linux"]["versions"] == ["0.47.0"]
    assert platforms["freebsd"]["reason"] == "noRepo"


def test_route_refuses_without_login(test_client, repo):
    assert test_client.get("/api/provisioning/platforms").status_code == 401


def test_route_refuses_a_non_admin(test_client, normal_user, repo):
    resp = test_client.get("/api/provisioning/platforms", headers=_bearer("viewer"))
    assert resp.status_code == 403, resp.text


def test_route_refuses_an_agent_certificate(test_client, admin_user, repo, monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    resp = test_client.get(
        "/api/provisioning/platforms",
        headers={**_bearer("admin"), **_gateway_headers(cn="admin", ou=SCOPE_AGENT)},
    )
    assert resp.status_code == 403, resp.text
