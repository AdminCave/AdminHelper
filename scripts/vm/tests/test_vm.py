# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""vm.py against recorded Proxmox answers — no network, no VM, no hypervisor."""

from __future__ import annotations

import json

import pytest
import vm
from conftest import fixture


# ── configuration ────────────────────────────────────────────────────────────
def test_config_reads_settings_local(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.local.json").write_text(
        json.dumps(
            {"env": {"AH_PVE_URL": "https://pve.example:8006", "AH_PVE_POOL": "adminhelper-ci"}}
        )
    )
    cfg = vm.Config.load(root=str(tmp_path), environ={})
    assert cfg["AH_PVE_URL"] == "https://pve.example:8006"
    assert cfg["AH_VM_MAX"] == "3"  # default, not in the file


def test_environment_wins_over_the_file(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.local.json").write_text(json.dumps({"env": {"AH_PVE_TOKEN": "from-file"}}))
    cfg = vm.Config.load(root=str(tmp_path), environ={"AH_PVE_TOKEN": "from-env"})
    assert cfg["AH_PVE_TOKEN"] == "from-env"


def test_missing_key_is_a_usage_error(tmp_path):
    cfg = vm.Config.load(root=str(tmp_path), environ={})
    with pytest.raises(vm.Usage) as caught:
        cfg["AH_PVE_URL"]
    assert "AH_PVE_URL" in str(caught.value)


@pytest.mark.parametrize("raw", ["3000-3999", " 3000 - 3999 "])
def test_vmid_range_parses(cfg, raw):
    cfg.values["AH_PVE_VMID_RANGE"] = raw
    assert cfg.vmid_range() == (3000, 3999)


@pytest.mark.parametrize("raw", ["3000", "3999-3000", "3000..3999", ""])
def test_bad_vmid_range_is_a_usage_error(cfg, raw):
    cfg.values["AH_PVE_VMID_RANGE"] = raw
    with pytest.raises(vm.Usage):
        cfg.vmid_range()


def test_flag_defaults_and_overrides(cfg):
    assert cfg.flag("AH_VM_LINKED", False) is True
    cfg.values.pop("AH_VM_LINKED")
    assert cfg.flag("AH_VM_LINKED", True) is True


# "False" is what a JSON `false` in settings.local.json becomes on the way
# through str(); reading it as truthy would silently turn linked clones back
# into 11-minute full clones.
@pytest.mark.parametrize("raw", ["0", "false", "False", "FALSE", " no ", "off"])
def test_falsy_flag_spellings(cfg, raw):
    cfg.values["AH_VM_LINKED"] = raw
    assert cfg.flag("AH_VM_LINKED", True) is False


# ── TLS ──────────────────────────────────────────────────────────────────────
def test_the_context_verifies_everything_but_the_strict_flag(cfg, monkeypatch):
    real = vm.ssl.create_default_context
    assert real().verify_flags & vm.ssl.VERIFY_X509_STRICT, "the flag we clear is on by default"
    seen = {}

    def fake(cafile=None):
        seen["cafile"] = cafile
        return real()  # a real context; the fixture's CA file is empty on purpose

    monkeypatch.setattr(vm.ssl, "create_default_context", fake)
    ctx = vm.Api(cfg).context()
    assert seen["cafile"] == cfg.path("AH_PVE_CA")
    assert ctx.check_hostname is True
    assert ctx.verify_mode == vm.ssl.CERT_REQUIRED
    # Equality, not a bit test: "everything but the strict flag" has to mean
    # that nothing else was cleared on the way past.
    assert ctx.verify_flags == real().verify_flags & ~vm.ssl.VERIFY_X509_STRICT


def test_the_context_is_built_once(cfg, monkeypatch):
    calls = []
    real = vm.ssl.create_default_context
    monkeypatch.setattr(
        vm.ssl, "create_default_context", lambda cafile=None: calls.append(cafile) or real()
    )
    api = vm.Api(cfg)
    assert api.context() is api.context()
    assert len(calls) == 1


def test_a_missing_ca_file_is_a_usage_error(cfg):
    cfg.values["AH_PVE_CA"] = "/nonexistent/pve-root-ca.pem"
    with pytest.raises(vm.Usage) as caught:
        vm.Api(cfg).context()
    assert "AH_PVE_CA" in str(caught.value)


# ── HTTP ─────────────────────────────────────────────────────────────────────
def test_token_header_and_unwrapped_data(api, http):
    http.add("GET", "/version", "version")
    assert api.request("GET", "/version")["version"] == "9.2.3"
    assert http.calls[0].headers["authorization"] == "PVEAPIToken=user@pve!vm=<secret>"
    # An unbounded call is how a stuck hypervisor becomes a stuck test run.
    assert http.calls[0].timeout == vm.HTTP_TIMEOUT


def test_delete_parameters_go_into_the_query(api, http):
    # PVE answers a DELETE that carries a body with 501 (err_delete_body.json).
    http.add("DELETE", "/qemu/3000", "destroy")
    api.request(
        "DELETE", "/nodes/<node>/qemu/3000", body={"purge": 1, "destroy-unreferenced-disks": 1}
    )
    call = http.calls[0]
    assert call.body == {}
    assert call.query == {"purge": "1", "destroy-unreferenced-disks": "1"}


def test_five_hundred_is_retried_exactly_once(api, http, clock):
    http.add("GET", "/version", status=500, body='{"message":"pveproxy restarting"}', times=1)
    http.add("GET", "/version", "version")
    assert api.request("GET", "/version")["version"] == "9.2.3"
    assert len(http.calls) == 2


def test_a_second_five_hundred_gives_up(api, http, clock):
    http.add("GET", "/version", status=500, body='{"message":"still down"}')
    with pytest.raises(vm.Infra) as caught:
        api.request("GET", "/version")
    assert len(http.calls) == 2
    assert "still down" in str(caught.value)


def test_connection_errors_are_retried_once(api, http, clock, monkeypatch):
    attempts = []

    def boom(req, timeout=None, context=None):
        attempts.append(req.full_url)
        raise OSError("connection refused")

    monkeypatch.setattr(vm.urllib.request, "urlopen", boom)
    with pytest.raises(vm.Infra):
        api.request("GET", "/version")
    assert len(attempts) == 2


def test_forbidden_names_the_missing_privilege(api, http):
    http.add("GET", "/qemu/100/config", "err_403_foreign")
    with pytest.raises(vm.Infra) as caught:
        api.request("GET", "/nodes/<node>/qemu/100/config")
    message = str(caught.value)
    assert "VM.Audit" in message and "/vms/100" in message
    assert caught.value.code == 74


def test_a_forbidden_call_is_not_retried(api, http):
    http.add("GET", "/qemu/100/config", "err_403_foreign")
    with pytest.raises(vm.Infra):
        api.request("GET", "/nodes/<node>/qemu/100/config")
    assert len(http.calls) == 1


def test_a_non_json_error_body_survives(api, http):
    reply = fixture("err_delete_body")
    assert reply["status"] == 501
    http.add("DELETE", "/qemu/3000", "err_delete_body")
    with pytest.raises(vm.Infra) as caught:
        api.request("DELETE", "/nodes/<node>/qemu/3000")
    assert "Unexpected content" in str(caught.value)


def test_the_url_query_is_kept_out_of_error_messages(api, http):
    http.add("PUT", "/qemu/3000/config", status=500, body='{"message":"nope"}')
    with pytest.raises(vm.Infra) as caught:
        api.request("PUT", "/nodes/<node>/qemu/3000/config", params={"sshkeys": "ssh-ed25519 AAAA"})
    assert "ssh-ed25519" not in str(caught.value)


# ── tasks ────────────────────────────────────────────────────────────────────
def test_wait_task_polls_until_stopped(api, http, clock):
    http.add("GET", "/tasks/", "task_running", times=2)
    http.add("GET", "/tasks/", "task_ok")
    status = api.wait_task("UPID:<node>:x:qmclone:9402:", limit=60)
    assert status["exitstatus"] == "OK"
    assert clock.slept == [1.0, 2.0]  # backoff 1 -> 2 -> ... capped at 5


def test_wait_task_backoff_is_capped(api, http, clock):
    http.add("GET", "/tasks/", "task_running", times=6)
    http.add("GET", "/tasks/", "task_ok")
    api.wait_task("UPID:x", limit=600)
    assert clock.slept == [1.0, 2.0, 4.0, 5.0, 5.0, 5.0]


def test_wait_task_times_out(api, http, clock):
    http.add("GET", "/tasks/", "task_running")
    with pytest.raises(vm.Infra) as caught:
        api.wait_task("UPID:x", limit=30)
    assert "did not finish within 30s" in str(caught.value)


def test_a_failed_task_is_infrastructure(api, http, clock):
    http.add("GET", "/tasks/", "task_lock_timeout")
    with pytest.raises(vm.Infra) as caught:
        api.wait_task("UPID:x", limit=60)
    assert "can't lock file" in str(caught.value)
    assert caught.value.code == 74


def test_the_upid_is_url_quoted(api, http, clock):
    http.add("GET", "/tasks/", "task_ok")
    api.wait_task("UPID:<node>:0029D8B9:qmclone:9402:user@pve!vm:")
    assert "UPID%3A%3Cnode%3E" in http.calls[0].url


# ── lock retry ───────────────────────────────────────────────────────────────
def test_a_task_that_lost_the_lock_is_resubmitted(api, http, clock):
    # The shape that looks like success: UPID + 200, then `can't lock file`.
    http.add("DELETE", "/snapshot/s1", "delsnap")
    http.add("GET", "/tasks/", "task_lock_timeout", times=1)
    http.add("GET", "/tasks/", "task_ok")
    status = api.task("DELETE", "/nodes/<node>/qemu/3001/snapshot/s1")
    assert status["exitstatus"] == "OK"
    assert (
        http.paths("DELETE")
        == ["https://pve.example:8006/api2/json/nodes/<node>/qemu/3001/snapshot/s1"] * 2
    )


def test_an_http_lock_error_is_retried_on_a_plain_call(api, http, clock):
    # The other shape, on the call it was actually recorded on: `PUT config`
    # produces no task at all ({"data": null}), so only request(lock_retry=True)
    # can survive the 500 "VM is locked (rollback)" that T4/T5 will meet.
    http.add("PUT", "/config", "err_vm_locked", times=1)
    http.add("PUT", "/config", "config_put")
    assert (
        api.request(
            "PUT", "/nodes/<node>/qemu/3000/config", body={"tags": "ah;role-probe"}, lock_retry=True
        )
        is None
    )
    assert len(http.calls) == 2


def test_a_plain_call_does_not_wait_for_a_lock_by_default(api, http, clock):
    http.add("PUT", "/config", "err_vm_locked")
    with pytest.raises(vm.Infra) as caught:
        api.request("PUT", "/nodes/<node>/qemu/3000/config", body={"tags": "ah"})
    assert "VM is locked" in str(caught.value)
    assert len(http.calls) == 1  # a lock is not a 5xx worth retrying blindly


def test_lock_retry_gives_up_after_the_window(api, http, clock):
    http.add("DELETE", "/snapshot/s1", "delsnap")
    http.add("GET", "/tasks/", "task_lock_timeout")
    with pytest.raises(vm.Infra) as caught:
        api.task("DELETE", "/nodes/<node>/qemu/3001/snapshot/s1")
    assert "can't lock file" in str(caught.value)
    assert clock.now >= vm.LOCK_RETRY_LIMIT


def test_a_real_failure_is_not_mistaken_for_a_lock(api, http, clock):
    http.add("POST", "/clone", "err_vmid_taken")
    with pytest.raises(vm.Infra) as caught:
        api.task("POST", "/nodes/<node>/qemu/9402/clone", body={"newid": 3000})
    assert "config file already exists" in str(caught.value)
    # 500 plus one retry, and no lock loop on top of it.
    assert len(http.calls) == 2


# ── exit codes ───────────────────────────────────────────────────────────────
def test_usage_is_two_and_infra_is_seventy_four():
    assert vm.Usage("x").code == 2
    assert vm.Infra("x").code == 74
    assert vm.VmError("x").code == 1


def test_no_verb_prints_help_and_exits_two(capsys):
    assert vm.main([]) == 2
    assert "doctor" in capsys.readouterr().out


# The smallest invocation each verb accepts — this pins the required options
# (a `clone` without --profile must stay an error), not just the verb names.
MINIMAL = {
    "doctor": [],
    "clone": ["--profile", "linux-full", "--role", "probe"],
    "wait": ["3000"],
    "ssh": ["3000"],
    "sync": ["3000"],
    "run": ["3000"],
    "pull": ["3000", "*.log", "out"],
    "snap": ["3000", "s1"],
    "rollback": ["3000", "s1"],
    "delsnap": ["3000", "s1"],
    "destroy": [],
    "reap": [],
    "list": [],
    "bake": ["--profile", "linux-full"],
}


def test_every_verb_parses_and_none_is_missing():
    assert set(MINIMAL) == set(vm.VERBS) == set(vm.VERB_TABLE)
    parser = vm.build_parser()
    for verb, extra in MINIMAL.items():
        assert parser.parse_args([verb] + extra).verb == verb


@pytest.mark.parametrize("argv", [["clone", "--role", "probe"], ["bake"], ["snap", "3000"]])
def test_a_missing_required_option_is_a_parser_error(argv):
    with pytest.raises(SystemExit):
        vm.build_parser().parse_args(argv)


def test_a_verb_error_becomes_its_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(
        vm,
        "VERB_TABLE",
        dict(
            vm.VERB_TABLE,
            list=lambda cfg, api, args: (_ for _ in ()).throw(vm.Infra("capacity: 2 GB short")),
        ),
    )
    monkeypatch.setattr(
        vm.Config,
        "load",
        classmethod(
            lambda cls, **kw: vm.Config(
                {"AH_PVE_URL": "https://pve.example:8006", "AH_PVE_NODE": "n"}
            )
        ),
    )
    assert vm.main(["list"]) == 74
    assert "capacity: 2 GB short" in capsys.readouterr().err
