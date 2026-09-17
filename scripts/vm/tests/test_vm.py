# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""vm.py against recorded Proxmox answers — no network, no VM, no hypervisor."""

from __future__ import annotations

import json
import os
import subprocess
import time

import pytest
import vm
from conftest import current_of, fixture, tagged_resources


def parse(*argv):
    """Parse the way main() does — `--` is cut out before argparse sees it,
    because only Python 3.13 drops it on its own and the box runs 3.12."""
    head, command = vm.split_command(list(argv))
    args = vm.build_parser().parse_args(head)
    if command:
        args.cmd = list(getattr(args, "cmd", None) or []) + command
    return args


def verb(name, cfg, api, *argv):
    return getattr(vm, "verb_" + name)(cfg, api, parse(name, *argv))


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
    assert cfg["AH_VM_MAX"] == vm.DEFAULTS["AH_VM_MAX"]  # default, not in the file


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
    # Python 3.13 sets VERIFY_X509_STRICT by default and 3.12 does not, so the
    # equality below is the portable assertion: it pins "the strict flag is off
    # and nothing else was touched" on either. On 3.13 it also catches the
    # clearing being removed, which is the mutation that matters.
    default_flags = real().verify_flags
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
    assert ctx.verify_flags == default_flags & ~vm.ssl.VERIFY_X509_STRICT


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


# ── profiles.json ────────────────────────────────────────────────────────────
def test_every_role_has_a_shape_and_every_profile_a_tag():
    profiles = vm.load_profiles()
    for role, shape in profiles["roles"].items():
        assert shape["memory"] >= 2048 and shape["cores"] >= 1, role
    for name, meta in profiles["profiles"].items():
        assert meta["template_tag"] == "ah-tpl-" + name


def test_the_roles_the_wrappers_use_all_exist():
    # heavy.sh's scenarios and bake name these; a rename here would strand them.
    roles = vm.load_profiles()["roles"]
    for role in (
        "server",
        "desktop",
        "agent",
        "tunnel",
        "visitor",
        "moncheck",
        "rpm",
        "probe",
        "bake",
    ):
        assert role in roles


def test_an_unreadable_profiles_file_is_a_usage_error(tmp_path):
    broken = tmp_path / "profiles.json"
    broken.write_text("{not json")
    with pytest.raises(vm.Usage):
        vm.load_profiles(str(broken))


# ── tags ─────────────────────────────────────────────────────────────────────
def test_tags_are_read_as_a_set():
    entry = next(v for v in fixture("cluster_resources")["body"]["data"] if v["vmid"] == 3001)
    tags = vm.tags_of(entry)
    assert tags == {
        "ah",
        "lane-pilot",
        "role-server",
        "sc-capstone",
        "tpl-linux-full",
        "ttl-1789557020",
    }
    assert vm.tag_value(tags, "role-") == "server"
    assert vm.tag_value(tags, "ttl-") == "1789557020"
    assert vm.tag_value(tags, "nothing-", "fallback") == "fallback"


def test_an_untagged_vm_has_no_tags():
    entry = next(v for v in fixture("cluster_resources")["body"]["data"] if v["vmid"] == 9400)
    assert vm.tags_of(entry) == set()
    assert vm.tags_of({}) == set()
    assert vm.tags_of({"tags": None}) == set()


def test_the_newest_build_of_a_template_wins():
    vms = [
        {"vmid": 3901, "template": 1, "tags": "ah-tpl-linux-full;built-20260101"},
        {"vmid": 3902, "template": 1, "tags": "ah-tpl-linux-full;built-20261231"},
        {"vmid": 3903, "template": 1, "tags": "ah-tpl-linux-server;built-20270101"},
        {"vmid": 3904, "template": 0, "tags": "ah-tpl-linux-full;built-20270202"},
    ]
    assert vm.newest_template(vms, "ah-tpl-linux-full")["vmid"] == 3902  # not the running clone
    assert vm.newest_template(vms, "ah-tpl-base-ubuntu") is None


# ── doctor ───────────────────────────────────────────────────────────────────
def green_doctor(http, resources=None, node=None):
    """Wire every call a green `doctor` makes, in the order it makes them."""
    http.add("GET", "/version", "version")
    http.add("GET", "/access/permissions", "permissions")
    http.add("GET", "/storage/raid5/status", "storage_status")
    reply = (
        resources
        if resources is not None
        else tagged_resources(
            extra_templates=[
                {
                    "vmid": 3900,
                    "name": "ah-tpl-linux-server-20260916",
                    "tags": "ah-tpl-linux-server;built-20260916",
                }
            ]
        )
    )
    http.add("GET", "/cluster/resources", body=reply["body"], status=reply["status"])
    for vmid in (3900, 9400, 9401, 9402):
        http.add("GET", "/qemu/%d/config" % vmid, "template_config")
    http.add("GET", "/nodes/<node>/status", node or "node_status")
    return http


def doctor(cfg, api, *argv):
    return vm.verb_doctor(cfg, api, parse("doctor", *argv))


def test_doctor_is_green_when_everything_is_in_place(cfg, api, http, capsys):
    green_doctor(http)
    assert doctor(cfg, api, "--roles", "probe") == 0
    out = capsys.readouterr().out
    assert "FAIL" not in out
    for check in (
        "api",
        "privileges",
        "storage",
        "templates",
        "template-config",
        "vmids",
        "capacity",
    ):
        assert check + ":" in out


def test_doctor_names_the_missing_privileges(cfg, api, http, capsys):
    stripped = fixture("permissions")
    stripped["body"]["data"]["/pool/adminhelper-ci"]["VM.Clone"] = 0
    del stripped["body"]["data"]["/pool/adminhelper-ci"]["VM.Snapshot.Rollback"]
    http.add("GET", "/version", "version")
    http.add("GET", "/access/permissions", body=stripped["body"])
    green_doctor(http)  # the overrides above were added first and win
    assert doctor(cfg, api, "--roles", "probe") == 74
    out = capsys.readouterr().out
    assert "FAIL privileges" in out
    assert "VM.Clone on /pool/adminhelper-ci" in out
    assert "VM.Snapshot.Rollback on /pool/adminhelper-ci" in out


def test_doctor_reports_a_storage_that_cannot_snapshot(cfg, api, http, capsys):
    plain = fixture("storage_status")
    plain["body"]["data"]["type"] = "lvm"
    http.add("GET", "/version", "version")
    http.add("GET", "/access/permissions", "permissions")
    http.add("GET", "/storage/raid5/status", body=plain["body"])
    green_doctor(http)  # the overrides above were added first and win
    assert doctor(cfg, api, "--roles", "probe") == 74
    assert "FAIL storage: raid5 is lvm, linked=no snapshots=no" in capsys.readouterr().out


def test_doctor_names_the_profiles_without_a_template(cfg, api, http, capsys):
    green_doctor(http, resources=tagged_resources())  # no linux-server template baked yet
    assert doctor(cfg, api, "--roles", "probe") == 74
    out = capsys.readouterr().out
    assert "FAIL templates: no template tagged for linux-server" in out
    assert "linux-full 20260910 (9402)" in out
    assert "base-ubuntu undated (9400)" in out  # the base images carry no build date


def test_doctor_reports_a_template_without_a_guest_agent(cfg, api, http, capsys):
    blind = fixture("template_config")
    del blind["body"]["data"]["agent"]
    http.add("GET", "/version", "version")
    http.add("GET", "/access/permissions", "permissions")
    http.add("GET", "/storage/raid5/status", "storage_status")
    reply = tagged_resources(drop=(3000, 3001, 9400, 9401))
    http.add("GET", "/cluster/resources", body=reply["body"])
    http.add("GET", "/qemu/9402/config", body=blind["body"])
    http.add("GET", "/nodes/<node>/status", "node_status")
    assert doctor(cfg, api, "--roles", "probe") == 74
    assert "linux-full: no guest agent" in capsys.readouterr().out


def test_doctor_reports_a_template_on_the_wrong_bridge(cfg, api, http, capsys):
    stray = fixture("template_config")
    stray["body"]["data"]["net0"] = "virtio=<mac>,bridge=vmbr0"
    http.add("GET", "/version", "version")
    http.add("GET", "/access/permissions", "permissions")
    http.add("GET", "/storage/raid5/status", "storage_status")
    reply = tagged_resources(drop=(3000, 3001, 9400, 9401))
    http.add("GET", "/cluster/resources", body=reply["body"])
    http.add("GET", "/qemu/9402/config", body=stray["body"])
    http.add("GET", "/nodes/<node>/status", "node_status")
    assert doctor(cfg, api, "--roles", "probe") == 74
    assert "linux-full: not on bridge vmbr1" in capsys.readouterr().out


def test_capacity_charges_what_our_vms_have_not_taken_yet(cfg, api, http, capsys):
    # 3000 runs (its RAM is already out of `free`), 3001 is stopped and still owed.
    # 3050 is a crabbox leftover without the `ah` tag: the pool is shared during
    # 2a (spec, trade-off 3) and a VM that is not ours is not ours to budget for.
    crowded = tagged_resources(
        extra_templates=[
            {
                "vmid": 3900,
                "name": "ah-tpl-linux-server-20260916",
                "tags": "ah-tpl-linux-server;built-20260916",
            },
            {
                "vmid": 3050,
                "name": "crabbox-ah-warm-1",
                "tags": "crabbox",
                "template": 0,
                "status": "running",
                "maxmem": 8589934592,
                "mem": 1048576,
            },
        ]
    )
    green_doctor(http, resources=crowded)
    assert doctor(cfg, api, "--roles", "probe") == 0
    detail = capsys.readouterr().out
    # 3001 is stopped: all 2048 MiB still owed. 3000 runs and has touched 28 MiB,
    # so 2020 of its 2048 are owed — charging 0 would be the dangerous reading.
    assert "4068 owed by ours" in detail
    assert "2048 for probe" in detail


def test_capacity_refuses_what_the_node_cannot_carry(cfg, api, http, capsys):
    green_doctor(http)
    assert doctor(cfg, api, "--roles", "desktop,server,desktop") == 74
    out = capsys.readouterr().out
    assert "FAIL capacity" in out
    assert "16384 for desktop,server,desktop" in out
    assert "ours: 3000" in out and "3001" in out


def test_an_unknown_role_is_a_usage_error(cfg, api, http):
    green_doctor(http)
    with pytest.raises(vm.Usage) as caught:
        doctor(cfg, api, "--roles", "datenbank")
    assert "unknown role 'datenbank'" in str(caught.value)


def test_doctor_json_carries_every_line(cfg, api, http, capsys):
    green_doctor(http)
    assert doctor(cfg, api, "--roles", "probe", "--json") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert [line["check"] for line in report["checks"]] == [
        "api",
        "privileges",
        "storage",
        "templates",
        "template-config",
        "vmids",
        "capacity",
    ]
    assert all(line["ok"] for line in report["checks"])


def test_a_dead_api_fails_one_check_and_still_reports_the_rest(cfg, api, http, clock, capsys):
    http.add("GET", "/version", status=500, body='{"message":"pveproxy is down"}')
    http.add("GET", "/access/permissions", "permissions")
    http.add("GET", "/storage/raid5/status", "storage_status")
    reply = tagged_resources()
    http.add("GET", "/cluster/resources", body=reply["body"])
    for vmid in (9400, 9401, 9402):
        http.add("GET", "/qemu/%d/config" % vmid, "template_config")
    http.add("GET", "/nodes/<node>/status", "node_status")
    assert doctor(cfg, api, "--roles", "probe") == 74
    out = capsys.readouterr().out
    assert "FAIL api" in out and "pveproxy is down" in out
    assert "ok   privileges" in out  # the examination did not stop at the first FAIL


def test_a_full_clone_band_is_reported(cfg, api, http, capsys):
    crowded = tagged_resources()
    crowded["body"]["data"] += [
        {
            "vmid": v,
            "name": "ah-probe-main-%04x" % v,
            "tags": "ah;role-probe",
            "template": 0,
            "status": "running",
            "maxmem": 0,
            "pool": "adminhelper-ci",
        }
        for v in range(3000, 3100)
    ]
    green_doctor(http, resources=crowded)
    assert doctor(cfg, api, "--roles", "probe") == 74
    assert "FAIL vmids: no free VMID in 3000-3099" in capsys.readouterr().out


def test_capacity_keeps_the_node_reserve(cfg, api, http, capsys):
    # 12826 free - 4068 owed - 8192 for desktop,agent leaves 566 MiB — enough
    # for the VMs and not enough for the node. Without RESERVE_MB this passes.
    green_doctor(http)
    assert doctor(cfg, api, "--roles", "desktop,agent") == 74
    assert "4096 reserve" in capsys.readouterr().out


def test_a_storage_without_snapshots_only_fails_while_linked_clones_are_on(cfg, api, http, capsys):
    plain = fixture("storage_status")
    plain["body"]["data"]["type"] = "lvm"
    cfg.values["AH_VM_LINKED"] = "0"
    http.add("GET", "/storage/raid5/status", body=plain["body"])
    green_doctor(http)
    assert doctor(cfg, api, "--roles", "probe") == 0
    out = capsys.readouterr().out
    assert "ok   storage: raid5 is lvm, linked=no snapshots=no" in out
    assert "AH_VM_LINKED" not in out


def test_an_unreachable_pool_fails_every_check_that_needs_it(cfg, api, http, clock, capsys):
    http.add("GET", "/version", "version")
    http.add("GET", "/access/permissions", "permissions")
    http.add("GET", "/storage/raid5/status", "storage_status")
    http.add("GET", "/cluster/resources", status=500, body='{"message":"not quorate"}')
    http.add("GET", "/nodes/<node>/status", "node_status")
    assert doctor(cfg, api, "--roles", "probe") == 74
    out = capsys.readouterr().out
    for check in ("templates", "vmids", "capacity"):
        assert "FAIL %s: cluster resources unavailable" % check in out, out
    # Version, permissions, storage and the pool listing (which costs its one
    # 5xx retry) — fetched once despite three checks needing it, and the node
    # status is never asked for because capacity already knows it cannot answer.
    assert len(http.paths("GET")) == 5


def test_a_template_with_the_boolean_agent_shorthand_is_accepted(cfg, api, http, capsys):
    short = fixture("template_config")
    short["body"]["data"]["agent"] = "1"
    http.add("GET", "/qemu/9402/config", body=short["body"])
    green_doctor(http)
    assert doctor(cfg, api, "--roles", "probe") == 0
    assert "FAIL" not in capsys.readouterr().out


def test_a_neighbouring_bridge_name_is_not_a_match(cfg, api, http, capsys):
    stray = fixture("template_config")
    stray["body"]["data"]["net0"] = "virtio=<mac>,bridge=vmbr10"
    http.add("GET", "/qemu/9402/config", body=stray["body"])
    green_doctor(http)
    assert doctor(cfg, api, "--roles", "probe") == 74
    assert "linux-full: not on bridge vmbr1" in capsys.readouterr().out


# ── clone ────────────────────────────────────────────────────────────────────
def clone_ready(http, resources=None, node=None):
    """Every call a successful `clone` makes, in order."""
    reply = resources if resources is not None else tagged_resources()
    http.add("GET", "/cluster/resources", body=reply["body"])
    http.add("GET", "/nodes/<node>/status", node or "node_status")
    http.add("POST", "/qemu/9402/clone", "clone_post")
    http.add("GET", "/tasks/", "task_ok")
    http.add("PUT", "/qemu/3002/config", "config_put")
    http.add("POST", "/qemu/3002/status/start", "status_start")
    return http


def clone(cfg, api, *argv):
    return vm.verb_clone(cfg, api, parse("clone", *argv))


@pytest.fixture
def keyed(cfg, tmp_path):
    (tmp_path / "id_ed25519.pub").write_text("ssh-ed25519 AAAAC3Nz+key/here== kevin@dev\n")
    return cfg


def test_clone_picks_the_lowest_free_vmid_and_tags_the_lease(keyed, api, http, clock, capsys):
    # 3000 and 3001 are taken in the recording, so 3002 is next.
    clone_ready(http)
    assert clone(keyed, api, "--profile", "linux-full", "--role", "probe", "--ttl", "20m") == 0
    assert capsys.readouterr().out.split()[0] == "3002"

    posted = next(c for c in http.calls if c.method == "POST" and "/clone" in c.path)
    assert posted.body["newid"] == "3002"
    assert posted.body["pool"] == "adminhelper-ci"
    assert posted.body["full"] == "0"  # AH_VM_LINKED=1: 2 s instead of 11 minutes
    assert "storage" not in posted.body

    put = next(c for c in http.calls if c.method == "PUT")
    tags = set(put.body["tags"].split(";"))
    assert {"ah", "role-probe", "lane-main", "tpl-linux-full"} <= tags
    ttl = int(vm.tag_value(tags, "ttl-"))
    assert 1190 <= ttl - int(time.time()) <= 1200
    assert not any(t.startswith("sc-") for t in tags)  # no scenario, no tag
    assert put.body["memory"] == "2048" and put.body["cores"] == "2"
    assert put.body["agent"] == "enabled=1" and put.body["ipconfig0"] == "ip=dhcp"
    # Never a ciuser: a lease inherits the template's own guest user, and the
    # fat template's is `crabbox` — whose home holds ~/.cargo and ~/go. Forcing
    # `adminhelper` here would hand every lease a cold, empty home (spec,
    # trade-off 5).
    assert "ciuser" not in put.body


def test_the_public_key_is_sent_url_encoded(keyed, api, http, clock):
    clone_ready(http)
    clone(keyed, api, "--profile", "linux-full", "--role", "probe")
    put = next(c for c in http.calls if c.method == "PUT")
    # PVE decodes once on the way into cloud-init; the recorded clone_config.json
    # shows the stored value still carrying the %20 separators.
    assert put.body["sshkeys"] == "ssh-ed25519%20AAAAC3Nz%2Bkey%2Fhere%3D%3D%20kevin%40dev"


def test_a_missing_public_key_is_a_usage_error_before_anything_is_cloned(cfg, api, http, clock):
    clone_ready(http)
    with pytest.raises(vm.Usage) as caught:
        clone(cfg, api, "--profile", "linux-full", "--role", "probe")
    assert "ssh-keygen" in str(caught.value)
    # Nothing was created, so there is nothing to purge — an unreachable VM is
    # not worth building just to delete it again.
    assert http.calls == []


def test_a_full_clone_names_the_storage(keyed, api, http, clock):
    keyed.values["AH_VM_LINKED"] = "0"
    clone_ready(http)
    clone(keyed, api, "--profile", "linux-full", "--role", "probe")
    posted = next(c for c in http.calls if c.method == "POST" and "/clone" in c.path)
    assert posted.body["full"] == "1" and posted.body["storage"] == "raid5"


def test_role_and_lane_and_scenario_reach_the_name_and_the_tags(keyed, api, http, clock, capsys):
    clone_ready(http)
    clone(
        keyed,
        api,
        "--profile",
        "linux-full",
        "--role",
        "server",
        "--lane",
        "Pilot",
        "--scenario",
        "capstone",
    )
    name = capsys.readouterr().out.split()[1]
    assert name.startswith("ah-server-pilot-")
    put = next(c for c in http.calls if c.method == "PUT")
    tags = set(put.body["tags"].split(";"))
    assert {"role-server", "lane-pilot", "sc-capstone"} <= tags
    assert put.body["memory"] == "4096" and put.body["cores"] == "2"  # the role's shape


def test_explicit_memory_and_cores_and_name_win(keyed, api, http, clock, capsys):
    clone_ready(http)
    clone(
        keyed,
        api,
        "--profile",
        "linux-full",
        "--role",
        "probe",
        "--memory",
        "3072",
        "--cores",
        "3",
        "--name",
        "ah-probe-handmade",
    )
    assert capsys.readouterr().out.strip() == "3002 ah-probe-handmade"
    put = next(c for c in http.calls if c.method == "PUT")
    assert put.body["memory"] == "3072" and put.body["cores"] == "3"


def test_a_failure_after_the_clone_takes_the_vm_with_it(keyed, api, http, clock):
    http.add("GET", "/cluster/resources", body=tagged_resources()["body"])
    http.add("GET", "/nodes/<node>/status", "node_status")
    http.add("POST", "/qemu/9402/clone", "clone_post")
    http.add("GET", "/tasks/", "task_ok")
    http.add("PUT", "/qemu/3002/config", status=500, body='{"message":"tag access denied"}')
    http.add("GET", "/qemu/3002/status/current", "status_current_running")
    http.add("POST", "/qemu/3002/status/stop", "status_stop")
    http.add("DELETE", "/qemu/3002", "destroy")
    with pytest.raises(vm.Infra) as caught:
        clone(keyed, api, "--profile", "linux-full", "--role", "probe")
    assert "tag access denied" in str(caught.value)
    assert "VM 3002 was removed again" in str(caught.value)
    deleted = next(c for c in http.calls if c.method == "DELETE")
    assert deleted.query == {"purge": "1", "destroy-unreferenced-disks": "1"}


def test_a_failed_cleanup_is_reported_next_to_the_original_failure(keyed, api, http, clock):
    http.add("GET", "/cluster/resources", body=tagged_resources()["body"])
    http.add("GET", "/nodes/<node>/status", "node_status")
    http.add("POST", "/qemu/9402/clone", "clone_post")
    http.add("GET", "/tasks/", "task_ok")
    http.add("POST", "/qemu/3002/status/start", status=500, body='{"message":"no boot disk"}')
    http.add("PUT", "/qemu/3002/config", "config_put")
    http.add("GET", "/qemu/3002/status/current", "status_current_stopped")
    http.add("DELETE", "/qemu/3002", status=500, body='{"message":"storage busy"}')
    with pytest.raises(vm.Infra) as caught:
        clone(keyed, api, "--profile", "linux-full", "--role", "probe")
    message = str(caught.value)
    assert "no boot disk" in message and "cleanup of 3002 failed too" in message
    assert "storage busy" in message


def test_capacity_is_checked_before_the_first_clone(keyed, api, http, clock):
    clone_ready(http)
    with pytest.raises(vm.Infra) as caught:
        clone(keyed, api, "--profile", "linux-full", "--role", "desktop")
    assert str(caught.value).startswith("capacity:")
    assert not [c for c in http.calls if c.method == "POST"]


def test_the_default_cap_leaves_room_for_the_capstone():
    # multibox.sh --capstone holds seven leases at once on one lane:
    # server, agent, moncheck, rpm, tunnel, visitor, desktop.
    assert int(vm.DEFAULTS["AH_VM_MAX"]) >= 7


def test_a_cap_that_is_not_a_number_is_a_usage_error(keyed, api, http, clock):
    keyed.values["AH_VM_MAX"] = "viele"
    clone_ready(http)
    with pytest.raises(vm.Usage) as caught:
        clone(keyed, api, "--profile", "linux-full", "--role", "probe")
    assert "AH_VM_MAX must be a number" in str(caught.value)


def test_the_lane_cap_counts_only_its_own_lane(keyed, api, http, clock):
    keyed.values["AH_VM_MAX"] = "1"
    clone_ready(http)  # 3000 is lane-main, 3001 is lane-pilot
    with pytest.raises(vm.Infra) as caught:
        clone(keyed, api, "--profile", "linux-full", "--role", "probe")
    assert "AH_VM_MAX=1 reached on lane main" in str(caught.value)
    assert "3000" in str(caught.value) and "3001" not in str(caught.value)
    clone_ready(http)
    assert clone(keyed, api, "--profile", "linux-full", "--role", "probe", "--lane", "solo") == 0


def test_an_unbaked_profile_is_infrastructure_not_a_crash(keyed, api, http, clock):
    clone_ready(http)
    with pytest.raises(vm.Infra) as caught:
        clone(keyed, api, "--profile", "linux-server", "--role", "probe")
    assert "no template tagged ah-tpl-linux-server" in str(caught.value)


def test_an_unknown_profile_is_a_usage_error(keyed, api, http):
    with pytest.raises(vm.Usage) as caught:
        clone(keyed, api, "--profile", "windows-11", "--role", "probe")
    assert "unknown profile 'windows-11'" in str(caught.value)
    assert http.calls == []


def test_a_full_clone_band_stops_the_clone(keyed, api, http, clock):
    crowded = tagged_resources()
    crowded["body"]["data"] += [
        {
            "vmid": v,
            "name": "ah-probe-main-%04x" % v,
            "tags": "ah;role-probe;lane-other",
            "template": 0,
            "status": "stopped",
            "maxmem": 0,
            "mem": 0,
            "pool": "adminhelper-ci",
        }
        for v in range(3000, 3100)
    ]
    clone_ready(http, resources=crowded)
    with pytest.raises(vm.Infra) as caught:
        clone(keyed, api, "--profile", "linux-full", "--role", "probe")
    assert "no free VMID in 3000-3099" in str(caught.value)


# ── durations, lanes, lookup ─────────────────────────────────────────────────
@pytest.mark.parametrize(
    "text,seconds",
    [("8h", 28800), ("20m", 1200), ("90s", 90), ("2d", 172800), ("45", 45), (" 1h ", 3600)],
)
def test_durations(text, seconds):
    assert vm.parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["", "soon", "8 hours", "-5m", "h"])
def test_bad_durations_are_usage_errors(text):
    with pytest.raises(vm.Usage):
        vm.parse_duration(text)


def test_lane_precedence(state_dir):
    assert vm.current_lane(environ={}) == "main"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "lane").write_text("worktree-a\n")
    assert vm.current_lane(environ={}) == "worktree-a"
    assert vm.current_lane(environ={"AH_LANE": "from-env"}) == "from-env"
    assert vm.current_lane(override="Flag Lane", environ={"AH_LANE": "from-env"}) == "flag-lane"


def test_an_empty_lane_file_still_means_main(state_dir):
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "lane").write_text("\n")
    assert vm.current_lane(environ={}) == "main"


def test_a_vm_is_found_by_id_or_by_name(cfg, api, http):
    http.add("GET", "/cluster/resources", "cluster_resources")
    assert vm.find_vm(cfg, api, "3001")["vmid"] == 3001
    http.add("GET", "/cluster/resources", "cluster_resources")
    assert vm.find_vm(cfg, api, "ah-probe-main-a1b2")["vmid"] == 3000


def test_a_vm_outside_the_pool_is_simply_not_found(cfg, api, http):
    http.add("GET", "/cluster/resources", "cluster_resources")
    with pytest.raises(vm.Usage) as caught:
        vm.find_vm(cfg, api, "100")
    assert "no VM '100' in pool adminhelper-ci" in str(caught.value)


def test_an_ambiguous_name_is_refused(cfg, api, http):
    doubled = fixture("cluster_resources")
    doubled["body"]["data"][1]["name"] = doubled["body"]["data"][0]["name"]
    http.add("GET", "/cluster/resources", body=doubled["body"])
    with pytest.raises(vm.Usage) as caught:
        vm.find_vm(cfg, api, "ah-probe-main-a1b2")
    assert "names 2 VMs" in str(caught.value)


# ── wait ─────────────────────────────────────────────────────────────────────
def wait(cfg, api, *argv):
    return vm.verb_wait(cfg, api, parse("wait", *argv))


def test_wait_returns_the_guests_own_ipv4(cfg, api, http, clock, monkeypatch, capsys):
    http.add("GET", "/cluster/resources", "cluster_resources")
    http.add("POST", "/agent/ping", "agent_ping_not_running", times=1)
    http.add("POST", "/agent/ping", "agent_ping_no_agent", times=1)
    http.add("POST", "/agent/ping", "agent_ping_ok")
    http.add("GET", "/agent/network-get-interfaces", "agent_ifaces")
    http.add("GET", "/qemu/3000/config", "clone_config")
    monkeypatch.setattr(vm, "run_ssh", lambda *a, **k: 0)
    assert wait(cfg, api, "3000") == 0
    # Not 127.0.0.1 from lo, not the fe80:: address on the same interface.
    assert capsys.readouterr().out.strip() == "<ip>"


def test_wait_skips_loopback_and_link_local_and_ipv6():
    interfaces = {
        "result": [
            {
                "name": "lo",
                "ip-addresses": [{"ip-address": "127.0.0.1", "ip-address-type": "ipv4"}],
            },
            {
                "name": "eth0",
                "ip-addresses": [
                    {"ip-address": "fe80::1", "ip-address-type": "ipv6"},
                    {"ip-address": "169.254.3.4", "ip-address-type": "ipv4"},
                    {"ip-address": "192.0.2.17", "ip-address-type": "ipv4"},
                ],
            },
        ]
    }

    class Once:
        def request(self, *a, **k):
            return interfaces

    assert vm.vm_ipv4(Once(), "<node>", 3000) == "192.0.2.17"


def test_an_interface_list_without_an_address_yields_nothing():
    class Empty:
        def request(self, *a, **k):
            return {"result": [{"name": "lo", "ip-addresses": []}]}

    assert vm.vm_ipv4(Empty(), "<node>", 3000) == ""


def test_wait_gives_up_on_a_silent_guest_agent(cfg, api, http, clock):
    http.add("GET", "/cluster/resources", "cluster_resources")
    http.add("POST", "/agent/ping", "agent_ping_no_agent")
    with pytest.raises(vm.Infra) as caught:
        wait(cfg, api, "3000", "--timeout", "30")
    message = str(caught.value)
    assert message.startswith("no ip: guest agent of 3000 silent after 30s")
    assert "QEMU guest agent is not running" in message


def test_wait_gives_up_when_dhcp_never_lands(cfg, api, http, clock):
    http.add("GET", "/cluster/resources", "cluster_resources")
    http.add("POST", "/agent/ping", "agent_ping_ok")
    http.add("GET", "/agent/network-get-interfaces", body={"data": {"result": []}})
    with pytest.raises(vm.Infra) as caught:
        wait(cfg, api, "3000", "--timeout", "30")
    assert "no ip: 3000 has no IPv4 after 30s" in str(caught.value)


def test_wait_gives_up_when_ssh_never_opens(cfg, api, http, clock, monkeypatch):
    http.add("GET", "/cluster/resources", "cluster_resources")
    http.add("POST", "/agent/ping", "agent_ping_ok")
    http.add("GET", "/agent/network-get-interfaces", "agent_ifaces")
    http.add("GET", "/qemu/3000/config", "clone_config")
    monkeypatch.setattr(vm, "run_ssh", lambda *a, **k: 255)
    with pytest.raises(vm.Infra) as caught:
        wait(cfg, api, "3000", "--timeout", "30")
    # The recorded clone carries the template's ciuser, not a configured name.
    assert "no ssh: crabbox@<ip> refused for 30s" in str(caught.value)


def test_the_ssh_command_line_carries_the_key_and_the_batch_flags(cfg, monkeypatch, state_dir):
    seen = {}
    monkeypatch.setattr(
        vm.subprocess,
        "call",
        lambda argv, timeout=None: seen.update(argv=argv, timeout=timeout) or 0,
    )
    assert vm.run_ssh(cfg, "crabbox", "192.0.2.17", ["true"], timeout=60) == 0
    argv = seen["argv"]
    assert argv[0] == "ssh" and argv[-2:] == ["crabbox@192.0.2.17", "true"]
    assert "BatchMode=yes" in argv and "ConnectTimeout=5" in argv
    # No host-key memory: the pool recycles addresses and every bake gives the
    # clones new host keys, so a remembered one is guaranteed to go stale and
    # then nothing reaches the box any more.
    assert "StrictHostKeyChecking=no" in argv
    assert "UserKnownHostsFile=/dev/null" in argv
    assert "LogLevel=ERROR" in argv
    assert not [a for a in argv if "known_hosts" in a]
    assert argv[argv.index("-i") + 1] == cfg.path("AH_VM_SSH_KEY")
    assert seen["timeout"] == 60


def test_an_ssh_that_never_returns_counts_as_unreachable(cfg, monkeypatch, state_dir):
    def hang(argv, timeout=None):
        raise vm.subprocess.TimeoutExpired(argv, timeout)

    monkeypatch.setattr(vm.subprocess, "call", hang)
    assert vm.run_ssh(cfg, "crabbox", "192.0.2.17", ["true"], timeout=1) == 255


# ── the clone must never leave a VM behind ───────────────────────────────────
def half_cloned(http, task_reply):
    """A clone whose task goes wrong — and the purge that has to follow it.

    The task routes are keyed on the UPID's own verb (`qmclone` vs `qmdestroy`),
    so the failing clone task cannot swallow the polls of the cleanup.
    """
    http.add("GET", "/cluster/resources", body=tagged_resources()["body"])
    http.add("GET", "/nodes/<node>/status", "node_status")
    http.add("POST", "/qemu/9402/clone", "clone_post")
    http.add("GET", "qmclone", **task_reply)
    http.add("GET", "/qemu/3002/status/current", "status_current_stopped")
    http.add("DELETE", "/qemu/3002", "destroy")
    http.add("GET", "qmdestroy", "task_ok")
    return http


def test_a_clone_task_that_outruns_us_is_purged_not_orphaned(keyed, api, http, clock):
    # The task keeps running server-side and finishes an UNTAGGED VM — which
    # destroy and reap would refuse to touch forever (spec, Verify-Prinzip).
    half_cloned(http, {"name": "task_running"})
    with pytest.raises(vm.Infra) as caught:
        clone(keyed, api, "--profile", "linux-full", "--role", "probe")
    message = str(caught.value)
    assert "did not finish within 300s" in message
    assert "VM 3002 was removed again" in message
    assert [c.method for c in http.calls if c.method == "DELETE"] == ["DELETE"]


def test_a_clone_task_that_fails_is_purged_too(keyed, api, http, clock):
    half_cloned(
        http,
        {
            "body": {
                "data": {
                    "status": "stopped",
                    "type": "qmclone",
                    "exitstatus": "clone failed: no space left",
                }
            }
        },
    )
    with pytest.raises(vm.Infra) as caught:
        clone(keyed, api, "--profile", "linux-full", "--role", "probe")
    assert "no space left" in str(caught.value)
    assert "VM 3002 was removed again" in str(caught.value)


def test_an_interrupt_before_the_tags_still_purges(keyed, api, http, clock, monkeypatch):
    half_cloned(http, {"body": fixture("task_ok")["body"]})
    real = vm.Api.request

    def interrupted(self, method, path, *a, **k):
        if method == "PUT":
            raise KeyboardInterrupt
        return real(self, method, path, *a, **k)

    monkeypatch.setattr(vm.Api, "request", interrupted)
    with pytest.raises(KeyboardInterrupt):  # stays an interrupt, does not become Infra
        clone(keyed, api, "--profile", "linux-full", "--role", "probe")
    assert [c for c in http.calls if c.method == "DELETE"]


def test_a_rejected_clone_purges_nothing_and_names_the_vmid(keyed, api, http, clock):
    # "config file already exists" WITHOUT a retry means a parallel lane took the
    # same free VMID a moment earlier. Destroying that VM would be destroying
    # theirs. (A 500 is retried once, so this one has to be a 4xx.)
    http.add("GET", "/cluster/resources", body=tagged_resources()["body"])
    http.add("GET", "/nodes/<node>/status", "node_status")
    http.add(
        "POST",
        "/qemu/9402/clone",
        status=400,
        body='{"message":"unable to create VM 3002: config file already exists"}',
    )
    with pytest.raises(vm.Infra) as caught:
        clone(keyed, api, "--profile", "linux-full", "--role", "probe")
    assert "clone of 9402 into 3002 failed" in str(caught.value)
    assert "config file already exists" in str(caught.value)
    assert "removed" not in str(caught.value)
    assert not [c for c in http.calls if c.method == "DELETE"]


def test_a_retried_clone_that_landed_anyway_is_cleaned_up(keyed, api, http, clock):
    # The first submit created the VM and only its answer was lost; the retry
    # is then told the config exists. That VM is ours, carries no tags, and
    # nothing would ever look at it again — so it has to go.
    http.add("GET", "/cluster/resources", body=tagged_resources()["body"])
    http.add("GET", "/nodes/<node>/status", "node_status")
    http.add("POST", "/qemu/9402/clone", status=500, body='{"message":"proxy closed"}', times=1)
    http.add(
        "POST",
        "/qemu/9402/clone",
        status=500,
        body='{"message":"unable to create VM 3002: config file already exists"}',
    )
    http.add("GET", "/qemu/3002/status/current", "status_current_stopped")
    http.add("DELETE", "/qemu/3002", "destroy")
    http.add("GET", "qmdestroy", "task_ok")
    with pytest.raises(vm.Infra) as caught:
        clone(keyed, api, "--profile", "linux-full", "--role", "probe")
    assert "the retry's leftover was removed" in str(caught.value)
    assert [c for c in http.calls if c.method == "DELETE"]


def test_a_purge_stops_a_running_vm_before_deleting_it(cfg, api, http, clock):
    # PVE refuses outright: "VM 3000 is running - destroy failed".
    http.add("GET", "/qemu/3000/status/current", "status_current_running")
    http.add("POST", "/qemu/3000/status/stop", "status_stop")
    http.add("GET", "/tasks/", "task_ok")
    http.add("DELETE", "/qemu/3000", "destroy")
    vm.purge_vm(cfg, api, 3000)
    assert [c.method for c in http.calls] == ["GET", "POST", "GET", "DELETE", "GET"]


def test_a_purge_of_a_vm_that_is_already_gone_is_a_success(cfg, api, http, clock):
    http.add("GET", "/qemu/3000/status/current", "status_current_stopped")
    http.add(
        "DELETE",
        "/qemu/3000",
        status=500,
        body='{"message":"Configuration file \'nodes/n/qemu-server/3000.conf\' does not exist"}',
    )
    vm.purge_vm(cfg, api, 3000)  # the clone rollback runs where it may never have existed


def test_a_purge_that_really_fails_still_raises(cfg, api, http, clock):
    http.add("GET", "/qemu/3000/status/current", "status_current_stopped")
    http.add("DELETE", "/qemu/3000", status=500, body='{"message":"storage busy"}')
    with pytest.raises(vm.Infra):
        vm.purge_vm(cfg, api, 3000)


# ── wait spends one budget, not three ────────────────────────────────────────
def test_the_three_wait_phases_share_one_deadline(cfg, api, http, clock, monkeypatch):
    http.add("GET", "/cluster/resources", "cluster_resources")
    http.add("POST", "/agent/ping", "agent_ping_no_agent", times=4)  # 4 x 5 s = 20 s
    http.add("POST", "/agent/ping", "agent_ping_ok")
    http.add("GET", "/agent/network-get-interfaces", "agent_ifaces")
    http.add("GET", "/qemu/3000/config", "clone_config")
    monkeypatch.setattr(vm, "run_ssh", lambda *a, **k: 255)
    with pytest.raises(vm.Infra) as caught:
        wait(cfg, api, "3000", "--timeout", "30")
    # The agent alone ate 20 s of the 30 s budget, so ssh gets what is left —
    # a per-phase deadline would have given it a fresh 30 s.
    assert "no ssh" in str(caught.value)
    assert clock.now <= 35


def test_the_ssh_attempt_is_bounded_by_what_is_left(cfg, api, http, clock, monkeypatch):
    http.add("GET", "/cluster/resources", "cluster_resources")
    http.add("POST", "/agent/ping", "agent_ping_ok")
    http.add("GET", "/agent/network-get-interfaces", "agent_ifaces")
    http.add("GET", "/qemu/3000/config", "clone_config")
    seen = []
    monkeypatch.setattr(vm, "run_ssh", lambda *a, timeout=None, **k: seen.append(timeout) or 255)
    with pytest.raises(vm.Infra):
        wait(cfg, api, "3000", "--timeout", "30")
    assert seen[0] is not None and seen[0] <= 30
    assert seen == sorted(seen, reverse=True) and seen[-1] < seen[0]  # shrinks, never resets


def test_an_agent_hiccup_between_ping_and_interfaces_is_survivable(
    cfg, api, http, clock, monkeypatch
):
    http.add("GET", "/cluster/resources", "cluster_resources")
    http.add("POST", "/agent/ping", "agent_ping_ok")
    http.add("GET", "/agent/network-get-interfaces", "agent_ping_no_agent", times=2)
    http.add("GET", "/agent/network-get-interfaces", "agent_ifaces")
    http.add("GET", "/qemu/3000/config", "clone_config")
    monkeypatch.setattr(vm, "run_ssh", lambda *a, **k: 0)
    assert wait(cfg, api, "3000", "--timeout", "300") == 0


def test_a_vm_in_another_pool_is_invisible(cfg, api, http):
    # The pool filter, not just "the VMID is absent": a homelab VM that the
    # token happens to see must not be addressable by name or by id.
    foreign = fixture("cluster_resources")
    foreign["body"]["data"].append(
        {
            "vmid": 150,
            "name": "mail-relay",
            "pool": "homelab",
            "template": 0,
            "status": "running",
            "maxmem": 0,
            "mem": 0,
        }
    )
    http.add("GET", "/cluster/resources", body=foreign["body"])
    with pytest.raises(vm.Usage):
        vm.find_vm(cfg, api, "150")
    http.add("GET", "/cluster/resources", body=foreign["body"])
    with pytest.raises(vm.Usage):
        vm.find_vm(cfg, api, "mail-relay")


@pytest.mark.parametrize("raw", ["x;ttl-9999999999", "CAPSTONE", "a b"])
def test_a_scenario_cannot_smuggle_a_second_tag(keyed, api, http, clock, raw):
    clone_ready(http)
    clone(keyed, api, "--profile", "linux-full", "--role", "probe", "--scenario", raw)
    tags = next(c for c in http.calls if c.method == "PUT").body["tags"].split(";")
    assert len([t for t in tags if t.startswith("ttl-")]) == 1
    assert sum(t.startswith("sc-") for t in tags) == 1


def test_a_scenario_of_pure_punctuation_is_refused(keyed, api, http, clock):
    clone_ready(http)
    with pytest.raises(vm.Usage) as caught:
        clone(keyed, api, "--profile", "linux-full", "--role", "probe", "--scenario", ";;;")
    assert "nothing usable" in str(caught.value)


def test_a_missing_storage_is_not_a_missing_vm(cfg, api, http, clock):
    # "does not exist" on its own would read this as "already gone" and let the
    # caller announce a VM as removed while it is still standing.
    http.add("GET", "/qemu/3000/status/current", "status_current_stopped")
    http.add(
        "DELETE",
        "/qemu/3000",
        status=500,
        body='{"message":"could not activate storage \'raid5\': storage does not exist"}',
    )
    with pytest.raises(vm.Infra):
        vm.purge_vm(cfg, api, 3000)


def test_a_locked_template_does_not_lose_the_clone(keyed, api, http, clock):
    # A second lane cloning from the same template holds its config lock. The
    # submit created nothing, so waiting it out is safe — and losing the clone
    # to a lock that clears in seconds is not.
    http.add("GET", "/cluster/resources", body=tagged_resources()["body"])
    http.add("GET", "/nodes/<node>/status", "node_status")
    http.add("POST", "/qemu/9402/clone", "err_vm_locked", times=2)
    http.add("POST", "/qemu/9402/clone", "clone_post")
    http.add("GET", "qmclone", "task_ok")
    http.add("PUT", "/qemu/3002/config", "config_put")
    http.add("POST", "/qemu/3002/status/start", "status_start")
    http.add("GET", "qmstart", "task_ok")
    assert clone(keyed, api, "--profile", "linux-full", "--role", "probe") == 0
    assert len([c for c in http.calls if "/clone" in c.path]) == 3


# ── ssh / sync / run / pull ──────────────────────────────────────────────────
@pytest.fixture
def shell(monkeypatch):
    """Records every ssh/rsync argv and answers with a settable exit code."""

    class Shell:
        def __init__(self):
            self.runs = []
            self.codes = {}
            self.ssh_codes = []  # consumed in order; for runs with several ssh calls

        def __call__(self, argv, timeout=None):
            self.runs.append({"argv": argv, "timeout": timeout})
            if argv[0] == "ssh" and self.ssh_codes:
                return self.ssh_codes.pop(0)
            return self.codes.get(argv[0], 0)

        def of(self, program):
            return [r for r in self.runs if r["argv"][0] == program]

    fake = Shell()
    monkeypatch.setattr(vm.subprocess, "call", fake)
    return fake


@pytest.fixture
def reachable(http):
    """A VM that resolves to an id, an address and a guest user."""
    http.add("GET", "/cluster/resources", "cluster_resources")
    http.add("GET", "/agent/network-get-interfaces", "agent_ifaces")
    http.add("GET", "/qemu/3000/config", "clone_config")
    return http


def test_the_exclude_list_never_hides_tracked_source():
    """The invariant the file itself states, checked against the real index.

    The box builds its evidence hash from what it RECEIVED, so an exclude over
    tracked source would make every artifact describe a tree the box never had —
    green, and about something else. This used to be checked by comparing the
    list against crabbox's; with crabbox gone, check the property directly.
    """
    with open(vm.RSYNC_EXCLUDE) as fh:  # pins the constant at the shipped file too
        ours = [ln.strip() for ln in fh if ln.strip() and not ln.strip().startswith("#")]
    try:
        done = subprocess.run(
            ["git", "-C", vm.ROOT, "ls-files"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        # A tarball checkout has no index to ask. Skipping says that; erroring
        # would claim the property was violated.
        pytest.skip("cannot read the index: %s" % exc)
    tracked = done.stdout.split()
    # The one documented exception: its only tracked entry is an empty .gitkeep,
    # and the directory itself is runtime data the box must not inherit.
    under_data = [t for t in tracked if t.startswith("apps/server/data/")]
    assert under_data == ["apps/server/data/.gitkeep"], under_data
    for entry in ours:
        if entry == "apps/server/data":
            continue
        if "/" in entry:
            # An anchored pattern only matches from the root.
            hits = [t for t in tracked if t == entry or t.startswith(entry + "/")]
        else:
            # rsync matches a slash-less pattern against EVERY path segment, at
            # any depth — `dist` hides apps/agent/dist too. Checking only the
            # prefix would wave exactly that case through.
            hits = [t for t in tracked if entry in t.split("/")]
        assert not hits, "%s excludes tracked source: %s" % (entry, hits[:3])
    # .git stays: run.sh reads head and tree_hash from it, and an artifact
    # without those fields proves nothing about which tree ran.
    assert ".git" not in ours
    # Our own local state never travels — it describes THIS machine's leases.
    assert {".vm", ".ah-out"} <= set(ours)


def test_ssh_without_a_command_opens_a_login_shell(cfg, api, reachable, shell):
    assert verb("ssh", cfg, api, "3000") == 0
    argv = shell.of("ssh")[0]["argv"]
    assert "crabbox@<ip>" in argv
    assert argv[-1].startswith("cd ~/adminhelper")


def test_ssh_with_a_command_hands_back_the_remote_exit_code(cfg, api, reachable, shell):
    shell.codes["ssh"] = 3
    assert verb("ssh", cfg, api, "3000", "--", "false") == 3
    assert shell.of("ssh")[0]["argv"][-1] == "false"


def test_sync_pushes_the_checkout_with_the_exclude_list(cfg, api, reachable, shell):
    assert verb("sync", cfg, api, "3000") == 0
    argv = shell.of("rsync")[0]["argv"]
    assert argv[:3] == ["rsync", "-az", "-e"]
    assert argv[3].startswith("ssh ")  # the same key and host-key policy as ssh itself
    assert "--delete" in argv
    assert argv[argv.index("--exclude-from") + 1].endswith("scripts/vm/rsync-exclude.txt")
    # The checkout, not the current directory: a sync from a subdirectory would
    # push a partial tree and --delete the rest of the box away.
    assert argv[-2:] == [vm.ROOT + "/", "crabbox@<ip>:~/adminhelper/"]


def test_sync_can_keep_what_the_box_already_has(cfg, api, reachable, shell):
    verb("sync", cfg, api, "3000", "--no-delete")
    assert "--delete" not in shell.of("rsync")[0]["argv"]


def test_a_failed_sync_is_infrastructure(cfg, api, reachable, shell):
    shell.codes["rsync"] = 23
    with pytest.raises(vm.Infra) as caught:
        verb("sync", cfg, api, "3000")
    assert "sync failed: rsync exited 23" in str(caught.value)


def test_run_executes_in_the_synced_checkout(cfg, api, reachable, shell):
    assert verb("run", cfg, api, "3000", "--", "bash", "scripts/tests/run.sh", "lint") == 0
    # A login shell: go lives in /etc/profile.d/go.sh and cargo in ~/.cargo/env,
    # and a bare `ssh host cmd` sources neither — run.sh would then dep-gate
    # itself into `go=no cargo=no` and still exit 0.
    assert shell.of("ssh")[0]["argv"][-1] == (
        "bash -lc 'cd ~/adminhelper && bash scripts/tests/run.sh lint'"
    )
    assert not shell.of("rsync")  # --sync was not asked for


def test_run_accepts_the_command_as_one_string(cfg, api, reachable, shell):
    # Both spellings have to mean the same thing: the guest's shell parses it.
    verb("run", cfg, api, "3000", "--", "bash scripts/tests/run.sh lint")
    assert shell.of("ssh")[0]["argv"][-1] == (
        "bash -lc 'cd ~/adminhelper && bash scripts/tests/run.sh lint'"
    )


def test_a_command_with_quotes_in_it_arrives_intact(cfg, api, reachable, shell):
    # The whole inner line is quoted once for the outer shell; a naive f-string
    # would break here and only ever fail on a real box.
    verb("run", cfg, api, "3000", "--", "python3 -c 'print(1)'")
    assert shell.of("ssh")[0]["argv"][-1] == (
        """bash -lc 'cd ~/adminhelper && python3 -c '"'"'print(1)'"'"''"""
    )


def test_a_red_suite_stays_red(cfg, api, reachable, shell):
    shell.codes["ssh"] = 1
    assert verb("run", cfg, api, "3000", "--", "false") == 1


def test_a_broken_connection_is_not_a_test_result(cfg, api, reachable, shell):
    shell.codes["ssh"] = 255
    with pytest.raises(vm.Infra) as caught:
        verb("run", cfg, api, "3000", "--", "bash scripts/tests/run.sh lint")
    assert "ssh to crabbox@<ip> failed (255)" in str(caught.value)


def test_run_syncs_first_when_asked(cfg, api, reachable, shell):
    verb("run", cfg, api, "3000", "--sync", "--", "true")
    assert [r["argv"][0] for r in shell.runs] == ["rsync", "ssh"]


def test_run_pulls_the_output_directory(cfg, api, reachable, shell, tmp_path):
    out = tmp_path / "artifacts"
    verb("run", cfg, api, "3000", "--out", str(out), "--", "true")
    fetch = shell.of("rsync")[-1]["argv"]
    assert fetch[-2:] == ["crabbox@<ip>:~/adminhelper/.ah-out/", str(out) + "/"]
    assert out.is_dir()


def test_the_output_is_fetched_even_when_the_suite_failed(cfg, api, reachable, shell, tmp_path):
    # The artifact of a red run is the one worth having — and collecting it must
    # not overwrite the suite's own verdict.
    shell.ssh_codes = [1, 0]  # the suite failed, the mkdir that follows did not
    assert verb("run", cfg, api, "3000", "--out", str(tmp_path / "o"), "--", "false") == 1
    assert shell.of("rsync")


def test_the_output_directory_is_created_on_the_box_first(cfg, api, reachable, shell, tmp_path):
    # Nothing creates .ah-out until a suite writes into it, and rsync answers a
    # missing source with exit 23 — which would bury the suite's own verdict.
    verb("run", cfg, api, "3000", "--out", str(tmp_path / "o"), "--", "true")
    assert [r["argv"][-1] for r in shell.of("ssh")] == [
        "bash -lc 'cd ~/adminhelper && true'",
        "mkdir -p ~/adminhelper/.ah-out",
    ]


def test_an_output_directory_that_cannot_be_created_is_infrastructure(
    cfg, api, reachable, shell, tmp_path
):
    shell.ssh_codes = [0, 1]  # the suite passed, the mkdir did not (full disk, rights)
    with pytest.raises(vm.Infra) as caught:
        verb("run", cfg, api, "3000", "--out", str(tmp_path / "o"), "--", "true")
    assert "cannot create ~/adminhelper/.ah-out" in str(caught.value)


def test_a_run_that_outlives_its_timeout_says_so(cfg, api, reachable, shell, monkeypatch):
    shell.codes["ssh"] = 255
    ticks = iter([0.0, 1000.0])
    monkeypatch.setattr(vm.time, "monotonic", lambda: next(ticks))
    with pytest.raises(vm.Infra) as caught:
        verb("run", cfg, api, "3000", "--timeout", "900", "--", "bash slow.sh")
    # Not "ssh failed (255)": the weekly triage reads this line.
    assert "timeout: bash slow.sh exceeded 900s" in str(caught.value)


def test_a_non_default_remote_directory_reaches_every_caller(cfg, api, reachable, shell, tmp_path):
    cfg.values["AH_VM_REMOTE_DIR"] = "/srv/ah"
    verb("run", cfg, api, "3000", "--sync", "--out", str(tmp_path / "o"), "--", "true")
    assert shell.of("ssh")[0]["argv"][-1] == "bash -lc 'cd /srv/ah && true'"
    pushed, fetched = shell.of("rsync")
    assert pushed["argv"][-1] == "crabbox@<ip>:/srv/ah/"
    assert fetched["argv"][-2] == "crabbox@<ip>:/srv/ah/.ah-out/"


def test_run_passes_its_timeout_to_ssh(cfg, api, reachable, shell):
    verb("run", cfg, api, "3000", "--timeout", "2700", "--", "true")
    assert shell.of("ssh")[0]["timeout"] == 2700


def test_run_without_a_command_is_a_usage_error(cfg, api, http, shell):
    with pytest.raises(vm.Usage):
        verb("run", cfg, api, "3000")
    assert http.calls == []  # refused before the VM was even looked up


def test_extend_moves_only_the_ttl_tag(cfg, api, reachable, shell, clock):
    # Read fresh before writing the whole tag set back — the listing lags.
    tags, name = POOL_NOW[3000]
    reachable.add(
        "GET", "/qemu/3000/status/current", body=current_of(3000, tags=tags, name=name)["body"]
    )
    reachable.add("PUT", "/qemu/3000/config", "config_put")
    verb("run", cfg, api, "3000", "--extend", "4h", "--", "true")
    tags = next(c for c in reachable.calls if c.method == "PUT").body["tags"].split(";")
    assert {"ah", "lane-main", "role-probe", "sc-none", "tpl-linux-full"} <= set(tags)
    assert len([t for t in tags if t.startswith("ttl-")]) == 1
    assert int(vm.tag_value(set(tags), "ttl-")) - int(time.time()) > 14000


def test_a_vm_that_is_not_ours_keeps_its_lease(cfg, api, http, shell):
    strangers = fixture("cluster_resources")
    for entry in strangers["body"]["data"]:
        if entry["vmid"] == 3000:
            entry["tags"] = "crabbox"
    http.add("GET", "/cluster/resources", body=strangers["body"])
    http.add("GET", "/agent/network-get-interfaces", "agent_ifaces")
    http.add("GET", "/qemu/3000/config", "clone_config")
    http.add("GET", "/qemu/3000/status/current", body=current_of(3000, tags="crabbox")["body"])
    with pytest.raises(vm.Usage) as caught:
        verb("run", cfg, api, "3000", "--extend", "4h", "--", "true")
    assert "is not ours" in str(caught.value)
    assert not [c for c in http.calls if c.method == "PUT"]


def test_pull_copies_a_glob_off_the_box(cfg, api, reachable, shell, tmp_path):
    verb("pull", cfg, api, "3000", "*.log", str(tmp_path / "logs"))
    argv = shell.of("rsync")[0]["argv"]
    assert argv[-2:] == ["crabbox@<ip>:~/adminhelper/*.log", str(tmp_path / "logs") + "/"]


def test_the_address_and_user_are_resolved_once_per_invocation(
    cfg, api, reachable, shell, tmp_path
):
    verb("run", cfg, api, "3000", "--sync", "--out", str(tmp_path / "o"), "--", "true")
    # Four shell calls that all need user@ip, one lookup of each.
    assert len(reachable.paths("GET")) == 3
    assert len(shell.runs) == 4


def test_a_vm_without_an_address_says_what_to_do(cfg, api, http, shell):
    http.add("GET", "/cluster/resources", "cluster_resources")
    http.add("GET", "/agent/network-get-interfaces", body={"data": {"result": []}})
    http.add("GET", "/qemu/3000/config", "clone_config")
    with pytest.raises(vm.Infra) as caught:
        verb("sync", cfg, api, "3000")
    assert "vm.py wait 3000" in str(caught.value)


def test_a_missing_rsync_is_infrastructure(cfg, api, reachable, monkeypatch):
    def missing(argv, timeout=None):
        raise OSError("No such file or directory: 'rsync'")

    monkeypatch.setattr(vm.subprocess, "call", missing)
    with pytest.raises(vm.Infra) as caught:
        verb("sync", cfg, api, "3000")
    assert "cannot run rsync" in str(caught.value)


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["run", "3000", "--sync", "--", "bash", "x"], ("bash x", True, None)),
        (["run", "3000", "--", "bash x"], ("bash x", False, None)),
        (
            ["run", "3000", "--timeout", "60", "--", "bash", "-c", "echo hi"],
            ("bash -c echo hi", False, 60),
        ),
    ],
)
def test_options_after_the_vm_are_options_not_command_words(argv, expected):
    # argparse.REMAINDER would have swallowed --sync/--timeout into the command,
    # which is exactly the syntax the ledger specifies for `run`. The `--` is cut
    # out before argparse sees it, because only 3.13 drops it on its own.
    head, command = vm.split_command(argv)
    args = vm.build_parser().parse_args(head)
    args.cmd = list(args.cmd or []) + command
    assert " ".join(args.cmd) == expected[0]
    assert args.sync is expected[1]
    assert args.timeout == expected[2]


# ── snapshots ────────────────────────────────────────────────────────────────
def test_snap_rollback_and_delsnap_hit_the_right_endpoints(cfg, api, http, clock):
    http.add("GET", "/storage/raid5/status", "storage_status")
    http.add("GET", "/cluster/resources", "cluster_resources")
    http.add("POST", "/qemu/3000/snapshot", "snapshot_post")
    http.add("GET", "qmsnapshot", "task_ok")
    assert verb("snap", cfg, api, "3000", "s1") == 0
    assert http.calls[-2].body == {"snapname": "s1"}

    http.add("POST", "/snapshot/s1/rollback", "rollback_post")
    http.add("GET", "qmrollback", "task_ok")
    assert verb("rollback", cfg, api, "3000", "s1", "--start") == 0
    assert http.calls[-2].body == {"start": "1"}

    http.add("DELETE", "/qemu/3000/snapshot/s1", "delsnap")
    http.add("GET", "qmdelsnapshot", "task_ok")
    assert verb("delsnap", cfg, api, "3000", "s1") == 0


def test_a_ram_snapshot_asks_for_the_vmstate(cfg, api, http, clock):
    http.add("GET", "/storage/raid5/status", "storage_status")
    http.add("GET", "/cluster/resources", "cluster_resources")
    http.add("POST", "/qemu/3000/snapshot", "snapshot_post")
    http.add("GET", "qmsnapshot", "task_ok")
    verb("snap", cfg, api, "3000", "s1", "--ram")
    assert http.calls[-2].body == {"snapname": "s1", "vmstate": "1"}


def test_a_storage_that_cannot_snapshot_says_so_before_trying(cfg, api, http, clock):
    plain = fixture("storage_status")
    plain["body"]["data"]["type"] = "lvm"
    http.add("GET", "/storage/raid5/status", body=plain["body"])
    with pytest.raises(vm.Infra) as caught:
        verb("snap", cfg, api, "3000", "s1")
    assert "storage raid5 is lvm and cannot snapshot" in str(caught.value)
    assert not [c for c in http.calls if c.method == "POST"]


def test_a_rollback_survives_the_lock_the_start_still_holds(cfg, api, http, clock):
    # The recorded case: rollback --start, then the next task ends with
    # "can't lock file" although it was accepted with a UPID.
    http.add("GET", "/storage/raid5/status", "storage_status")
    http.add("GET", "/cluster/resources", "cluster_resources")
    http.add("DELETE", "/qemu/3000/snapshot/s1", "delsnap")
    http.add("GET", "qmdelsnapshot", "task_lock_timeout", times=1)
    http.add("GET", "qmdelsnapshot", "task_ok")
    assert verb("delsnap", cfg, api, "3000", "s1") == 0
    assert len([c for c in http.calls if c.method == "DELETE"]) == 2


@pytest.mark.parametrize("name", ["snap", "rollback", "delsnap"])
def test_no_snapshot_verb_touches_a_vm_that_is_not_ours(cfg, api, http, clock, name):
    http.add("GET", "/storage/raid5/status", "storage_status")
    http.add("GET", "/cluster/resources", "cluster_resources")
    with pytest.raises(vm.Usage) as caught:
        verb(name, cfg, api, "9402", "s1")
    assert "template" in str(caught.value)
    assert not [c for c in http.calls if c.method in ("POST", "DELETE")]


# ── destroy ──────────────────────────────────────────────────────────────────
# The recorded pool, as status/current reports each of its VMs.
POOL_NOW = {
    3000: ("ah;lane-main;role-probe;sc-none;tpl-linux-full;ttl-1789558820", "ah-probe-main-a1b2"),
    3001: (
        "ah;lane-pilot;role-server;sc-capstone;tpl-linux-full;ttl-1789557020",
        "ah-server-pilot-c3d4",
    ),
    9402: ("crabbox", "Copy-of-VM-crabbox-ah-bake-9482bd41"),
}


def purgeable(http, *vmids, now=None):
    """The pool listing, plus the fresh confirmation and purge of each VM."""
    http.add("GET", "/cluster/resources", "cluster_resources")
    for vmid, (tags, name) in (now or POOL_NOW).items():
        reply = current_of(vmid, tags=tags, name=name, template=1 if vmid >= 9400 else 0)
        http.add("GET", "/qemu/%d/status/current" % vmid, body=reply["body"])
    for vmid in vmids:
        http.add("DELETE", "/qemu/%d" % vmid, "destroy")
    http.add("GET", "qmdestroy", "task_ok")
    return http


def test_destroy_takes_named_vms(cfg, api, http, clock, capsys):
    purgeable(http, 3000)
    assert verb("destroy", cfg, api, "3000") == 0
    assert "destroyed 3000" in capsys.readouterr().out
    assert [c.path for c in http.calls if c.method == "DELETE"] == [
        "https://pve.example:8006/api2/json/nodes/<node>/qemu/3000"
    ]


def test_destroy_refuses_a_template_and_destroys_nothing(cfg, api, http, clock):
    purgeable(http, 3000)
    with pytest.raises(vm.Usage) as caught:
        verb("destroy", cfg, api, "3000", "9402")
    assert "9402 is a template" in str(caught.value)
    # Checked before the first destruction: 3000 is still standing.
    assert not [c for c in http.calls if c.method == "DELETE"]


def test_destroy_refuses_a_vm_without_our_tag(cfg, api, http, clock):
    strangers = fixture("cluster_resources")
    for entry in strangers["body"]["data"]:
        if entry["vmid"] == 3000:
            entry["tags"] = "crabbox"
    http.add("GET", "/cluster/resources", body=strangers["body"])
    http.add("GET", "/qemu/3000/status/current", body=current_of(3000, tags="crabbox")["body"])
    with pytest.raises(vm.Usage) as caught:
        verb("destroy", cfg, api, "3000")
    assert "carries no `ah` tag" in str(caught.value)


def test_destroy_selects_by_lane_role_and_scenario(cfg, api, http, clock, capsys):
    purgeable(http, 3001)
    assert verb("destroy", cfg, api, "--lane", "pilot") == 0
    out = capsys.readouterr().out
    assert "destroyed 3001" in out and "3000" not in out

    purgeable(http, 3000)
    verb("destroy", cfg, api, "--role", "probe")
    assert "destroyed 3000" in capsys.readouterr().out

    purgeable(http, 3001)
    verb("destroy", cfg, api, "--scenario", "capstone")
    assert "destroyed 3001" in capsys.readouterr().out


def test_destroy_without_a_selector_is_a_usage_error(cfg, api, http):
    with pytest.raises(vm.Usage):
        verb("destroy", cfg, api)
    assert http.calls == []


def test_destroy_of_a_selector_that_matches_nothing_is_not_an_error(cfg, api, http, clock, capsys):
    purgeable(http)
    assert verb("destroy", cfg, api, "--lane", "nobody") == 0
    assert "nothing to destroy" in capsys.readouterr().out


# ── reap ─────────────────────────────────────────────────────────────────────
def leased(http, *entries):
    """A pool of our own VMs with the given (vmid, lane, ttl-offset, template)."""
    reply = fixture("cluster_resources")
    now = int(time.time())
    data = [v for v in reply["body"]["data"] if v["vmid"] >= 9400]
    for vmid, lane, offset in entries:
        data.append(
            {
                "vmid": vmid,
                "name": "ah-probe-%s-%04x" % (lane, vmid),
                "pool": "adminhelper-ci",
                "template": 0,
                "status": "stopped",
                "maxmem": 0,
                "mem": 0,
                "tags": "ah;role-probe;lane-%s;ttl-%d" % (lane, now + offset),
            }
        )
    reply["body"]["data"] = data
    http.add("GET", "/cluster/resources", body=reply["body"])
    for vmid, lane, offset in entries:
        http.add(
            "GET",
            "/qemu/%d/status/current" % vmid,
            body=current_of(
                vmid,
                tags="ah;role-probe;lane-%s;ttl-%d" % (lane, now + offset),
                name="ah-probe-%s-%04x" % (lane, vmid),
            )["body"],
        )
    return http


def test_reap_takes_the_expired_of_its_own_lane_only(cfg, api, http, clock, capsys):
    leased(http, (3000, "main", -60), (3001, "main", 3600), (3002, "pilot", -60))
    http.add("DELETE", "/qemu/3000", "destroy")
    http.add("GET", "qmdestroy", "task_ok")
    assert verb("reap", cfg, api) == 0
    out = capsys.readouterr().out
    assert "reaped 3000" in out
    assert "3001" not in out and "3002" not in out


def test_reap_all_crosses_lanes(cfg, api, http, clock, capsys):
    leased(http, (3000, "main", -60), (3002, "pilot", -60))
    for vmid in (3000, 3002):
        http.add("DELETE", "/qemu/%d" % vmid, "destroy")
    http.add("GET", "qmdestroy", "task_ok")
    verb("reap", cfg, api, "--all")
    out = capsys.readouterr().out
    assert "reaped 3000" in out and "reaped 3002" in out


def test_a_dry_run_destroys_nothing(cfg, api, http, clock, capsys):
    leased(http, (3000, "main", -60))
    assert verb("reap", cfg, api, "--dry-run") == 0
    assert "would reap 3000" in capsys.readouterr().out
    assert not [c for c in http.calls if c.method == "DELETE"]


def test_the_reaper_never_eats_a_template(cfg, api, http, clock, capsys):
    # A template carries no ttl-, but say it out loud: taking one would take
    # every linked clone's backing store with it.
    tagged = fixture("cluster_resources")
    for entry in tagged["body"]["data"]:
        if entry["vmid"] == 9402:
            entry["tags"] = "ah;ttl-1"
    http.add("GET", "/cluster/resources", body=tagged["body"])
    verb("reap", cfg, api, "--all", "--dry-run")
    assert "9402" not in capsys.readouterr().out


def test_a_vm_without_a_ttl_is_never_reaped(cfg, api, http, clock, capsys):
    forever = fixture("cluster_resources")
    forever["body"]["data"] = [v for v in forever["body"]["data"] if v["vmid"] != 3001]
    for entry in forever["body"]["data"]:
        if entry["vmid"] == 3000:
            entry["tags"] = "ah;role-probe;lane-main"  # ours, leased forever
    http.add("GET", "/cluster/resources", body=forever["body"])
    verb("reap", cfg, api, "--all", "--dry-run")
    assert "nothing expired" in capsys.readouterr().out


# ── list and the leak sweep ──────────────────────────────────────────────────
def test_list_shows_the_lease_of_every_vm_of_ours(cfg, api, http, clock, capsys, state_dir):
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "warm.env").write_text("desktop=3000\n")
    http.add("GET", "/cluster/resources", "cluster_resources")
    http.add("GET", "/agent/network-get-interfaces", "agent_ifaces")
    # 3000 is a warm slot, 3001 belongs to another lane — neither is a leak.
    assert verb("list", cfg, api) == 0
    out = capsys.readouterr().out
    assert "3000  ah-probe-main-a1b2       probe     lane=main" in out
    assert "sc=capstone" in out and "stopped" in out
    assert "<ip>" in out  # running: the address is fetched best effort
    assert "EXPIRED" in out  # both recorded leases are in the past
    assert "2 ours, 3 not ours" in out  # the three templates are not ours


def test_a_vm_nobody_claims_is_a_leak(cfg, api, http, clock, capsys, state_dir):
    http.add("GET", "/cluster/resources", "cluster_resources")
    http.add("GET", "/agent/network-get-interfaces", "agent_ifaces")
    with pytest.raises(vm.Infra) as caught:
        verb("list", cfg, api)
    # 3000 is lane main and in no warm.env; 3001 is lane pilot, not our problem.
    assert "leaked on lane main: 3000" in str(caught.value)


def test_a_warm_box_is_not_a_leak(cfg, api, http, clock, capsys, state_dir):
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "warm.env").write_text("server_ip=10.0.0.9\ndesktop=3000\nserver=3999\n")
    http.add("GET", "/cluster/resources", "cluster_resources")
    http.add("GET", "/agent/network-get-interfaces", "agent_ifaces")
    assert verb("list", cfg, api) == 0


def test_a_vm_of_the_running_scenario_is_not_a_leak(cfg, api, http, clock, monkeypatch, state_dir):
    scened = fixture("cluster_resources")
    for entry in scened["body"]["data"]:
        if entry["vmid"] == 3000:
            entry["tags"] = "ah;role-server;lane-main;sc-capstone;ttl-%d" % (int(time.time()) + 60)
    monkeypatch.setenv("AH_VM_SCENARIO", "capstone")
    http.add("GET", "/cluster/resources", body=scened["body"])
    http.add("GET", "/agent/network-get-interfaces", "agent_ifaces")
    assert verb("list", cfg, api) == 0


def test_a_vm_of_a_different_scenario_is_still_a_leak(
    cfg, api, http, clock, monkeypatch, state_dir
):
    scened = fixture("cluster_resources")
    for entry in scened["body"]["data"]:
        if entry["vmid"] == 3000:
            entry["tags"] = "ah;role-server;lane-main;sc-yesterday;ttl-%d" % (int(time.time()) + 60)
    monkeypatch.setenv("AH_VM_SCENARIO", "capstone")
    http.add("GET", "/cluster/resources", body=scened["body"])
    http.add("GET", "/agent/network-get-interfaces", "agent_ifaces")
    with pytest.raises(vm.Infra):
        verb("list", cfg, api)


def test_list_json_carries_the_rows_and_the_leaks(cfg, api, http, clock, capsys, state_dir):
    http.add("GET", "/cluster/resources", "cluster_resources")
    http.add("GET", "/agent/network-get-interfaces", "agent_ifaces")
    with pytest.raises(vm.Infra):
        verb("list", cfg, api, "--json")
    report = json.loads(capsys.readouterr().out)
    assert report["untagged"] == 3
    assert [r["vmid"] for r in report["vms"]] == [3000, 3001]
    assert report["vms"][1]["ttl"] == "EXPIRED"
    assert report["leaked"] == [3000]


def test_list_can_be_narrowed_to_one_lane(cfg, api, http, clock, capsys, state_dir):
    http.add("GET", "/cluster/resources", "cluster_resources")
    http.add("GET", "/agent/network-get-interfaces", "agent_ifaces")
    # The filter narrows the display, not the sweep: 3000 leaks on our own lane
    # and still says so.
    with pytest.raises(vm.Infra) as caught:
        verb("list", cfg, api, "--lane", "pilot")
    out = capsys.readouterr().out
    assert "3001" in out and "3000" not in out
    assert "leaked on lane main: 3000" in str(caught.value)


def test_an_empty_pool_lists_nothing_and_is_fine(cfg, api, http, clock, capsys, state_dir):
    bare = fixture("cluster_resources")
    bare["body"]["data"] = [v for v in bare["body"]["data"] if v["vmid"] >= 9400]
    http.add("GET", "/cluster/resources", body=bare["body"])
    assert verb("list", cfg, api) == 0
    assert "0 ours, 3 not ours" in capsys.readouterr().out


@pytest.mark.parametrize(
    "offset,shown",
    [(-1, "EXPIRED"), (0, "0m"), (90, "1m"), (3600 + 12 * 60, "1h12m"), (86400, "24h00m")],
)
def test_the_remaining_lease_reads_like_a_clock(offset, shown):
    now = int(time.time())
    assert vm.left_of(str(now + offset), now) == shown
    assert vm.left_of("", now) == "no ttl"
    assert vm.left_of("soon", now) == "no ttl"


# ── auto-reap ────────────────────────────────────────────────────────────────
def wired(monkeypatch, cfg, api, **verbs):
    """main() with a stubbed verb table — the wiring around it is what is tested."""
    monkeypatch.setattr(vm.Config, "load", classmethod(lambda cls, **kw: cfg))
    monkeypatch.setattr(vm, "Api", lambda c: api)
    monkeypatch.setattr(vm, "VERB_TABLE", dict(vm.VERB_TABLE, **verbs))


def test_every_changing_verb_sweeps_its_own_lane_afterwards(cfg, api, http, monkeypatch):
    swept = []
    monkeypatch.setattr(vm, "reap_lane", lambda c, a, lane, dry_run=False: swept.append(lane) or [])
    wired(monkeypatch, cfg, api, sync=lambda c, a, args: 0)
    assert vm.main(["sync", "3000"]) == 0
    assert swept == ["main"]


@pytest.mark.parametrize("verb_name", ["list", "doctor"])
def test_a_report_has_no_side_effects(cfg, api, http, monkeypatch, verb_name):
    swept = []
    monkeypatch.setattr(vm, "reap_lane", lambda *a, **k: swept.append(1) or [])
    wired(monkeypatch, cfg, api, **{verb_name: lambda c, a, args: 0})
    assert vm.main([verb_name]) == 0
    assert swept == []


def test_the_sweep_can_be_switched_off(cfg, api, http, monkeypatch):
    swept = []
    monkeypatch.setenv("AH_VM_NO_AUTOREAP", "1")
    monkeypatch.setattr(vm, "reap_lane", lambda *a, **k: swept.append(1) or [])
    wired(monkeypatch, cfg, api, sync=lambda c, a, args: 0)
    assert vm.main(["sync", "3000"]) == 0
    assert swept == []


def test_a_failed_sweep_does_not_change_the_verbs_answer(cfg, api, http, monkeypatch, capsys):
    def angry(*a, **k):
        raise vm.Infra("cluster filesystem not quorate")

    monkeypatch.setattr(vm, "reap_lane", angry)
    wired(monkeypatch, cfg, api, run=lambda c, a, args: 1)  # a red suite
    assert vm.main(["run", "3000", "--", "false"]) == 1  # still 1, not 74
    assert "the lane sweep did not finish" in capsys.readouterr().err


# ── fail-closed, pinned ──────────────────────────────────────────────────────
def test_the_reaper_never_eats_a_vm_that_is_not_ours(cfg, api, http, clock, capsys):
    # The one path that reaches purge_vm without going through require_ours.
    foreign = fixture("cluster_resources")
    for entry in foreign["body"]["data"]:
        if entry["vmid"] == 3000:
            entry["tags"] = "crabbox;lane-main;ttl-1"  # expired, and not ours
    http.add("GET", "/cluster/resources", body=foreign["body"])
    verb("reap", cfg, api, "--dry-run")
    assert "3000" not in capsys.readouterr().out


def test_destroy_by_the_default_lane_leaves_the_untagged_templates_alone(
    cfg, api, http, clock, capsys
):
    # 9400/9401 carry no tags at all, so their lane reads as `main` — only the
    # `ah` guard keeps --lane main from selecting the three templates.
    purgeable(http, 3000)
    assert verb("destroy", cfg, api, "--lane", "main") == 0
    out = capsys.readouterr().out
    assert "destroyed 3000" in out
    assert "9400" not in out and "9401" not in out and "9402" not in out


def test_a_stranger_on_our_lane_is_neither_destroyed_nor_in_the_way(cfg, api, http, clock, capsys):
    # A crabbox leftover carries no tags at all, so its lane reads as `main`.
    # Without the `ah` filter in the selector it would be picked up and then
    # refused — which would block the destruction of our own VM beside it.
    shared = fixture("cluster_resources")
    shared["body"]["data"].append(
        {
            "vmid": 3050,
            "name": "crabbox-ah-warm-1",
            "pool": "adminhelper-ci",
            "template": 0,
            "status": "running",
            "maxmem": 0,
            "mem": 0,
        }
    )
    http.add("GET", "/cluster/resources", body=shared["body"])
    for vmid, (tags, name) in POOL_NOW.items():
        http.add(
            "GET",
            "/qemu/%d/status/current" % vmid,
            body=current_of(vmid, tags=tags, name=name, template=1 if vmid >= 9400 else 0)["body"],
        )
    http.add("DELETE", "/qemu/3000", "destroy")
    http.add("GET", "qmdestroy", "task_ok")
    assert verb("destroy", cfg, api, "--lane", "main") == 0
    out = capsys.readouterr().out
    assert "destroyed 3000" in out and "3050" not in out


def test_a_selector_is_matched_the_way_the_tag_was_written(cfg, api, http, clock, capsys):
    purgeable(http, 3001)
    assert verb("destroy", cfg, api, "--lane", "Pilot") == 0
    assert "destroyed 3001" in capsys.readouterr().out


def test_a_lease_renewed_a_second_ago_survives_the_sweep(cfg, api, http, clock, capsys):
    # The listing still says expired; status/current says the extend landed.
    # Registered first so it wins over the stale route `leased` adds.
    http.add(
        "GET",
        "/qemu/3000/status/current",
        body=current_of(
            3000,
            tags="ah;role-probe;lane-main;ttl-%d" % (int(time.time()) + 7200),
            name="ah-probe-main-0bb8",
        )["body"],
    )
    leased(http, (3000, "main", -60))
    assert verb("reap", cfg, api) == 0
    assert "nothing expired" in capsys.readouterr().out
    assert not [c for c in http.calls if c.method == "DELETE"]


def test_destroy_confirms_against_fresh_state_not_the_cache(cfg, api, http, clock):
    # The recording's own trap: /cluster/resources served a previous tenant's
    # name for 3001 while its tags were already current.
    http.add("GET", "/cluster/resources", "cluster_resources")
    http.add(
        "GET",
        "/qemu/3001/status/current",
        body=current_of(3001, tags="crabbox", name="somebody-elses-box")["body"],
    )
    # You type the name the listing shows; the VMID behind it is somebody else's.
    with pytest.raises(vm.Usage) as caught:
        verb("destroy", cfg, api, "ah-probe-main-c3d4")
    assert "carries no `ah` tag" in str(caught.value)
    assert not [c for c in http.calls if c.method == "DELETE"]


def test_destroy_finishes_the_rest_of_a_scenario_and_reports_what_failed(
    cfg, api, http, clock, capsys
):
    http.add("GET", "/cluster/resources", "cluster_resources")
    for vmid in (3000, 3001):
        tags, name = POOL_NOW[vmid]
        http.add(
            "GET",
            "/qemu/%d/status/current" % vmid,
            body=current_of(vmid, tags=tags, name=name)["body"],
        )
    http.add("DELETE", "/qemu/3000", status=500, body='{"message":"storage busy"}')
    http.add("DELETE", "/qemu/3001", "destroy")
    http.add("GET", "qmdestroy", "task_ok")
    with pytest.raises(vm.Infra) as caught:
        verb("destroy", cfg, api, "3000", "3001")
    assert "destroyed 3001" in capsys.readouterr().out  # the rest still went
    assert "could not destroy 3000" in str(caught.value)


def test_a_warm_slot_is_read_from_the_role_keys_only(state_dir):
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "warm.env").write_text(
        "desktop=3000\nserver=3001\nserver_ip=10.0.0.9\nserver_sid=3002\nserver_ptok=3003\n"
    )
    # server_sid and server_ptok are session ids that happen to look like VMIDs;
    # counting them as warm would excuse a genuinely leaked VM.
    assert vm.warm_vmids() == {3000, 3001}


def test_the_sweep_runs_after_a_failed_verb_too(cfg, api, http, monkeypatch):
    swept = []
    monkeypatch.setattr(vm, "reap_lane", lambda c, a, lane, dry_run=False: swept.append(lane) or [])

    def refused(c, a, args):
        raise vm.Infra("capacity: 2048 MiB short")

    wired(monkeypatch, cfg, api, clone=refused)
    # The expired VMs eating that capacity are exactly what has to go now.
    assert vm.main(["clone", "--profile", "linux-full", "--role", "probe"]) == 74
    assert swept == ["main"]


def test_a_vm_that_vanished_does_not_stop_the_teardown(cfg, api, http, clock, capsys):
    # Between listing and confirmation another lane's sweep took 3000. The rest
    # of the scenario still has to come down.
    http.add("GET", "/cluster/resources", "cluster_resources")
    http.add(
        "GET",
        "/qemu/3000/status/current",
        status=500,
        body='{"message":"Configuration file \'nodes/n/qemu-server/3000.conf\' does not exist"}',
    )
    tags, name = POOL_NOW[3001]
    http.add(
        "GET", "/qemu/3001/status/current", body=current_of(3001, tags=tags, name=name)["body"]
    )
    http.add("DELETE", "/qemu/3001", "destroy")
    http.add("GET", "qmdestroy", "task_ok")
    assert verb("destroy", cfg, api, "3000", "3001") == 0
    out = capsys.readouterr().out
    assert "already gone 3000" in out and "destroyed 3001" in out


def test_a_vanished_vm_does_not_stop_the_sweep(cfg, api, http, clock, capsys):
    http.add(
        "GET",
        "/qemu/3000/status/current",
        status=500,
        body='{"message":"Configuration file \'nodes/n/qemu-server/3000.conf\' does not exist"}',
    )
    leased(http, (3000, "main", -60), (3001, "main", -60))
    http.add("DELETE", "/qemu/3001", "destroy")
    http.add("GET", "qmdestroy", "task_ok")
    assert verb("reap", cfg, api) == 0
    assert [c.path.rsplit("/", 1)[-1] for c in http.calls if c.method == "DELETE"] == ["3001"]


@pytest.mark.parametrize(
    "tags,template",
    [
        # T7's bake: the clone becomes a template before its lease tags are
        # replaced, while the resource list still shows it as our tagged VM
        # whose ttl ran out during the 45 minutes.
        ("ah;role-bake;lane-main;ttl-1", 1),
        # Or someone re-tagged it out of our care while it sat there expired.
        ("crabbox;lane-main;ttl-1", 0),
    ],
)
def test_the_reaper_re_reads_before_it_takes_anything(cfg, api, http, clock, tags, template):
    http.add(
        "GET",
        "/qemu/3000/status/current",
        body=current_of(3000, tags=tags, name="ah-bake-main-0bb8", template=template)["body"],
    )
    leased(http, (3000, "main", -60))
    assert verb("reap", cfg, api) == 0
    assert not [c for c in http.calls if c.method == "DELETE"]


def test_a_reaped_lane_filter_is_matched_the_way_the_tag_was_written(
    cfg, api, http, clock, capsys, state_dir
):
    http.add("GET", "/cluster/resources", "cluster_resources")
    http.add("GET", "/agent/network-get-interfaces", "agent_ifaces")
    with pytest.raises(vm.Infra):
        verb("list", cfg, api, "--lane", "Pilot")
    assert "3001" in capsys.readouterr().out


def test_ctrl_c_does_not_start_a_sweep(cfg, api, http, monkeypatch):
    swept = []
    monkeypatch.setattr(vm, "reap_lane", lambda *a, **k: swept.append(1) or [])

    def impatient(c, a, args):
        raise KeyboardInterrupt

    wired(monkeypatch, cfg, api, sync=impatient)
    # Someone who pressed Ctrl-C wants out, not another round of API calls.
    assert vm.main(["sync", "3000"]) == 2
    assert swept == []


# ── bake ─────────────────────────────────────────────────────────────────────
def bakeable(http, template_vmid=9400, tag_put=None, lag=0, never_visible=False, final=None):
    """Every call a successful `bake` makes, in the order it makes them."""
    # The first listing picks the source and the free template VMID; every
    # later one has to know about the VM the bake just created.
    http.add("GET", "/cluster/resources", body=tagged_resources()["body"], times=1)
    baking = tagged_resources(
        extra_templates=[
            {
                "vmid": 3900,
                "name": "ah-tpl-linux-full-%s" % time.strftime("%Y%m%d"),
                "template": 0,
                "status": "running",
                "maxmem": 4294967296,
                "mem": 0,
                "tags": "ah;role-bake;lane-main;ttl-%d" % (int(time.time()) + 4 * 3600),
            }
        ]
    )
    http.add("GET", "/cluster/resources", body=baking["body"], times=1)
    http.add("GET", "/nodes/<node>/status", "node_status")
    http.add("POST", "/qemu/%d/clone" % template_vmid, "clone_post")
    http.add("GET", "qmclone", "task_ok")
    if tag_put is None:
        http.add("PUT", "/qemu/3900/config", "config_put")
    else:
        # The first PUT sets the lease, the second replaces it with the
        # template's tags — only the second one is handed the given reply.
        http.add("PUT", "/qemu/3900/config", "config_put", times=1)
        http.add("PUT", "/qemu/3900/config", **tag_put)
    http.add("POST", "/qemu/3900/status/start", "status_start")
    http.add("GET", "qmstart", "task_ok")
    http.add("POST", "/qemu/3900/agent/ping", "agent_ping_ok")
    http.add("GET", "/qemu/3900/agent/network-get-interfaces", "agent_ifaces")
    http.add("GET", "/qemu/3900/config", "clone_config")
    http.add("POST", "/qemu/3900/status/shutdown", "status_stop")
    http.add("GET", "qmstop", "task_ok")
    http.add("POST", "/qemu/3900/template", "status_start")
    http.add("GET", "qmstart", "task_ok")
    # What `bake` sees while it waits for its own template to appear, and then
    # the listing that finally shows it.
    if lag or never_visible:
        http.add(
            "GET",
            "/cluster/resources",
            body=tagged_resources()["body"],
            times=None if never_visible else lag,
        )
    done = tagged_resources(
        extra_templates=[
            {
                "vmid": 3900,
                "name": "ah-tpl-linux-full-%s" % time.strftime("%Y%m%d"),
                "template": 1,
                "status": "stopped",
                "maxmem": 4294967296,
                "mem": 0,
                "tags": "ah-tpl-linux-full;built-%s" % time.strftime("%Y%m%d"),
            }
        ]
    )
    # `final` replaces the listing bake reads while waiting for its own result.
    http.add("GET", "/cluster/resources", **(final or {"body": done["body"]}))
    return http


def bake_cleanup(http):
    http.add("GET", "/qemu/3900/status/current", "status_current_running")
    http.add("POST", "/qemu/3900/status/stop", "status_stop")
    http.add("GET", "qmstop", "task_ok")
    http.add("DELETE", "/qemu/3900", "destroy")
    http.add("GET", "qmdestroy", "task_ok")
    return http


def test_bake_builds_a_template_in_the_template_band(keyed, api, http, clock, shell, capsys):
    bakeable(http)
    assert verb("bake", keyed, api, "--profile", "linux-full") == 0
    day = time.strftime("%Y%m%d")

    posted = next(c for c in http.calls if c.method == "POST" and "/clone" in c.path)
    assert posted.body["newid"] == "3900"  # the upper hundred, not a lease slot
    puts = [c for c in http.calls if c.method == "PUT"]
    lease = puts[0].body
    assert lease["ciuser"] == "adminhelper"  # D20: our own user, not the template's
    assert set(lease["tags"].split(";")) >= {"ah", "role-bake", "lane-main"}
    assert vm.tag_value(set(lease["tags"].split(";")), "ttl-")  # a failed bake is reapable

    # The lease tags come off only once the template exists. The other way
    # round, a failed `template` would leave a running VM with no `ah` tag at
    # all: reap skips it, destroy refuses it, and it is nobody's any more.
    assert puts[-1].body == {"tags": "ah-tpl-linux-full;built-%s" % day}
    shutdown_i = next(i for i, c in enumerate(http.calls) if c.path.endswith("/status/shutdown"))
    template_i = next(i for i, c in enumerate(http.calls) if c.path.endswith("/template"))
    tags_i = [i for i, c in enumerate(http.calls) if c.method == "PUT"][-1]
    assert shutdown_i < template_i < tags_i
    assert capsys.readouterr().out.splitlines()[-1] == (
        "3900 ah-tpl-linux-full-%s ah-tpl-linux-full;built-%s" % (day, day)
    )


def test_bake_runs_bootstrap_then_the_warmup_then_the_clean(keyed, api, http, clock, shell):
    bakeable(http)
    verb("bake", keyed, api, "--profile", "linux-server")
    runs = shell.of("ssh")[1:]  # [0] is wait_for's own reachability probe
    commands = [r["argv"][-1] for r in runs]
    assert "AH_BOOTSTRAP_PROFILE=server bash scripts/vm/bootstrap_linux.sh" in commands[0]
    assert "AH_ALLOW_REAL=1 bash scripts/tests/run.sh unit" in commands[1]
    assert "truncate -s0 /etc/machine-id" in commands[2]
    assert "cloud-init clean" in commands[2]
    # A login shell, or run.sh dep-gates itself into `go=no cargo=no` and warms
    # nothing: the bootstrap puts go on the PATH through /etc/profile.d.
    assert all(c.startswith("bash -lc ") and "cd ~/adminhelper && " in c for c in commands)
    assert [r["timeout"] for r in runs] == [2700, 1800, 600]
    assert shell.of("rsync")  # the checkout is on the box before any of it runs


def test_the_bootstrap_installs_the_guest_agent():
    # Without it a baked template's clones never get an address, and `wait`
    # would hang on every lease off it.
    with open(os.path.join(vm.ROOT, "scripts/vm/bootstrap_linux.sh")) as fh:
        bootstrap = fh.read()
    assert "qemu-guest-agent" in bootstrap
    assert "systemctl enable --now qemu-guest-agent" in bootstrap


@pytest.mark.parametrize("failing", [0, 2])  # bootstrap and clean; the warm-up is not a gate
def test_a_failed_step_takes_the_half_baked_vm_with_it(keyed, api, http, clock, shell, failing):
    bakeable(http)
    bake_cleanup(http)
    shell.ssh_codes = [0] + [0] * failing + [1]  # the probe, then the step that fails
    with pytest.raises(vm.Infra) as caught:
        verb("bake", keyed, api, "--profile", "linux-full")
    assert "VM 3900 was removed again" in str(caught.value)
    assert [c for c in http.calls if c.method == "DELETE"]


def test_a_flaky_unit_test_does_not_throw_away_the_bootstrap(
    keyed, api, http, clock, shell, capsys
):
    # the old bake ran the same step with `|| true`. Half an hour of
    # bootstrap is not worth one red unit test — but it has to be visible.
    bakeable(http)
    shell.ssh_codes = [0, 0, 1]  # probe, bootstrap, warm-up
    assert verb("bake", keyed, api, "--profile", "linux-full") == 0
    out = capsys.readouterr().out
    assert "warm the caches exited 1" in out
    assert "the template is just colder" in out


def test_a_base_image_is_not_something_to_bake(keyed, api, http):
    with pytest.raises(vm.Usage) as caught:
        verb("bake", keyed, api, "--profile", "base-ubuntu")
    assert "is a base image" in str(caught.value)
    assert "linux-full" in str(caught.value) and "linux-server" in str(caught.value)
    assert http.calls == []


def test_an_unknown_profile_is_refused_before_anything_is_cloned(keyed, api, http):
    with pytest.raises(vm.Usage) as caught:
        verb("bake", keyed, api, "--profile", "windows-11")
    assert "unknown profile" in str(caught.value)
    assert http.calls == []


def test_bake_clones_the_base_image_by_default(keyed, api, http, clock, shell):
    bakeable(http, template_vmid=9400)
    verb("bake", keyed, api, "--profile", "linux-full")
    assert [c for c in http.calls if "/clone" in c.path][0].path.endswith("/qemu/9400/clone")


def test_bake_can_be_pointed_at_another_source(keyed, api, http, clock, shell):
    bakeable(http, template_vmid=9401)
    verb("bake", keyed, api, "--profile", "linux-full", "--from", "ah-tpl-base-debian")
    assert [c for c in http.calls if "/clone" in c.path][0].path.endswith("/qemu/9401/clone")


def test_a_missing_source_template_is_infrastructure(keyed, api, http, clock):
    http.add("GET", "/cluster/resources", body=tagged_resources(drop=(9400,))["body"])
    with pytest.raises(vm.Infra) as caught:
        verb("bake", keyed, api, "--profile", "linux-full")
    assert "no template tagged ah-tpl-base-ubuntu" in str(caught.value)


def test_bake_checks_capacity_before_it_clones(keyed, api, http, clock):
    thin = fixture("node_status")
    thin["body"]["data"]["memory"]["free"] = 5 * 1024**3  # 5 GiB: reserve plus a little
    http.add("GET", "/cluster/resources", body=tagged_resources()["body"])
    http.add("GET", "/nodes/<node>/status", body=thin["body"])
    with pytest.raises(vm.Infra) as caught:
        verb("bake", keyed, api, "--profile", "linux-full")
    assert str(caught.value).startswith("capacity:")
    assert not [c for c in http.calls if c.method == "POST"]


def test_a_failed_tag_put_takes_the_fresh_template_with_it(keyed, api, http, clock, shell):
    bakeable(http, tag_put={"status": 500, "body": '{"message":"tag access denied"}'})
    bake_cleanup(http)
    with pytest.raises(vm.Infra) as caught:
        verb("bake", keyed, api, "--profile", "linux-full")
    assert "tag access denied" in str(caught.value)
    assert "VM 3900 was removed again" in str(caught.value)
    assert [c for c in http.calls if c.method == "DELETE"]


def test_the_bake_lease_is_long_enough_to_survive_a_bake(keyed, api, http, clock, shell):
    bakeable(http)
    verb("bake", keyed, api, "--profile", "linux-full")
    tags = set(next(c for c in http.calls if c.method == "PUT").body["tags"].split(";"))
    # A full bake measured ~45 minutes; a lease that expires mid-bake would let
    # another lane's sweep take the VM with it.
    assert int(vm.tag_value(tags, "ttl-")) - int(time.time()) > 3 * 3600


def test_a_running_bake_is_not_reported_as_a_leak(cfg, api, http, clock, capsys, state_dir):
    baking = fixture("cluster_resources")
    for entry in baking["body"]["data"]:
        if entry["vmid"] == 3000:
            entry["tags"] = "ah;role-bake;lane-main;ttl-%d" % (int(time.time()) + 3600)
        if entry["vmid"] == 3001:
            entry["tags"] = "ah;role-probe;lane-pilot;ttl-1"
    http.add("GET", "/cluster/resources", body=baking["body"])
    http.add("GET", "/agent/network-get-interfaces", "agent_ifaces")
    # 45 minutes of bake in one terminal must not make `list` red in another.
    assert verb("list", cfg, api) == 0


def test_the_template_band_never_reaches_below_the_range(cfg):
    cfg.values["AH_PVE_VMID_RANGE"] = "3000-3050"
    assert vm.free_template_vmid(cfg, []) == 3000
    cfg.values["AH_PVE_VMID_RANGE"] = "3000-3999"
    assert vm.free_template_vmid(cfg, []) == 3900


def test_bake_waits_until_its_own_template_is_visible(keyed, api, http, clock, shell, capsys):
    # The resource list is a cache: in the T12 run it still showed the old view
    # when bake returned, and the next `clone --profile linux-server` answered
    # "no template tagged" for a template that existed.
    bakeable(http, lag=3)
    assert verb("bake", keyed, api, "--profile", "linux-full") == 0
    assert "still does not show it" not in capsys.readouterr().out
    assert clock.slept  # it waited rather than returning into a failing clone


def test_bake_says_so_when_the_cache_never_catches_up(keyed, api, http, clock, shell, capsys):
    bakeable(http, never_visible=True)
    assert verb("bake", keyed, api, "--profile", "linux-full") == 0  # the template exists
    out = capsys.readouterr().out
    assert "still does not show it" in out
    assert clock.now >= vm.TEMPLATE_VISIBLE_LIMIT


def test_a_bake_whose_listing_cannot_be_read_still_reports_its_template(
    keyed, api, http, clock, shell, capsys
):
    # The template is built, tagged and ours by then. Failing over a listing
    # that could not be read would throw an hour of work away.
    bakeable(http, final={"status": 500, "body": '{"message":"not quorate"}'})
    assert verb("bake", keyed, api, "--profile", "linux-full") == 0
    out = capsys.readouterr().out
    assert "could not be read" in out
    assert out.splitlines()[-1].startswith("3900 ah-tpl-linux-full-")


def test_a_bake_says_when_another_template_wins_the_tie_break(
    keyed, api, http, clock, shell, capsys
):
    # Same tag, same build date, higher VMID: `clone` would take that one.
    day = time.strftime("%Y%m%d")
    rival = tagged_resources(
        extra_templates=[
            {
                "vmid": 3900,
                "name": "ah-tpl-linux-full-%s" % day,
                "template": 1,
                "status": "stopped",
                "maxmem": 0,
                "mem": 0,
                "tags": "ah-tpl-linux-full;built-%s" % day,
            },
            {
                "vmid": 3950,
                "name": "ah-tpl-linux-full-rival",
                "template": 1,
                "status": "stopped",
                "maxmem": 0,
                "mem": 0,
                "tags": "ah-tpl-linux-full;built-%s" % day,
            },
        ]
    )
    bakeable(http, final={"body": rival["body"]})
    assert verb("bake", keyed, api, "--profile", "linux-full") == 0
    out = capsys.readouterr().out
    assert "3900 is built, but 3950 wins the tie-break for ah-tpl-linux-full" in out


@pytest.mark.parametrize("argv", [["destroy", "3000", "--", "foo"], ["list", "--", "x"]])
def test_a_verb_without_a_command_refuses_one(argv, capsys):
    # `--` is cut out before argparse sees it, so a verb that has no `cmd` has
    # to say so rather than silently dropping what followed.
    with pytest.raises(SystemExit) as caught:
        vm.main(argv)
    assert caught.value.code == 2
    assert "takes no command after" in capsys.readouterr().err


def test_only_the_first_separator_is_eaten():
    head, command = vm.split_command(["run", "3000", "--", "sh", "-c", "--", "x"])
    assert head == ["run", "3000"]
    assert command == ["sh", "-c", "--", "x"]


def test_the_wait_does_not_end_on_the_stale_entry(keyed, api, http, clock, shell, capsys):
    # This is the shape the cache really has during the lag: the VM IS listed,
    # with its old fields — still a running VM, still wearing its lease tags.
    # A bare "is the VMID in the list" test would end the wait on exactly the
    # case it exists for, and then announce a tie-break that is not one.
    stale = tagged_resources(
        extra_templates=[
            {
                "vmid": 3900,
                "name": "ah-tpl-linux-full-%s" % time.strftime("%Y%m%d"),
                "template": 0,
                "status": "running",
                "maxmem": 4294967296,
                "mem": 0,
                "tags": "ah;role-bake;lane-main;ttl-%d" % (int(time.time()) + 4 * 3600),
            }
        ]
    )
    bakeable(http, final={"body": stale["body"]})
    assert verb("bake", keyed, api, "--profile", "linux-full") == 0
    out = capsys.readouterr().out
    assert "wins the tie-break" not in out  # 9402 is older, and 3900 is not visible yet
    assert "still does not show it" in out  # it waited the whole window
    assert clock.now >= vm.TEMPLATE_VISIBLE_LIMIT


def test_a_listing_that_fails_only_later_still_keeps_the_template(
    keyed, api, http, clock, shell, capsys
):
    # The 500 arrives after a round has already been read, so it lands on the
    # second pool_vms() call — the one that used to sit outside the guard.
    bakeable(http, lag=1, final={"status": 500, "body": '{"message":"not quorate"}'})
    assert verb("bake", keyed, api, "--profile", "linux-full") == 0
    out = capsys.readouterr().out
    assert "could not be read" in out
    assert out.splitlines()[-1].startswith("3900 ah-tpl-linux-full-")
