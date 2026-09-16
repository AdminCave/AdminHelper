# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""vm.py against recorded Proxmox answers — no network, no VM, no hypervisor."""

from __future__ import annotations

import json
import time

import pytest
import vm
from conftest import fixture, tagged_resources


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
    return vm.verb_doctor(cfg, api, vm.build_parser().parse_args(["doctor", *argv]))


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
    return vm.verb_clone(cfg, api, vm.build_parser().parse_args(["clone", *argv]))


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
    # crabbox_multibox.sh --capstone holds seven leases at once on one lane:
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
    return vm.verb_wait(cfg, api, vm.build_parser().parse_args(["wait", *argv]))


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
    assert "StrictHostKeyChecking=accept-new" in argv
    assert "UserKnownHostsFile=" + str(state_dir / "known_hosts") in argv
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
    # "config file already exists" can mean a parallel lane took the same free
    # VMID a moment earlier. Destroying that VM would be destroying theirs.
    http.add("GET", "/cluster/resources", body=tagged_resources()["body"])
    http.add("GET", "/nodes/<node>/status", "node_status")
    http.add("POST", "/qemu/9402/clone", "err_vmid_taken")
    with pytest.raises(vm.Infra) as caught:
        clone(keyed, api, "--profile", "linux-full", "--role", "probe")
    assert "clone of 9402 into 3002 failed" in str(caught.value)
    assert "config file already exists" in str(caught.value)
    assert not [c for c in http.calls if c.method == "DELETE"]


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
