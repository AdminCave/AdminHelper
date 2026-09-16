# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""vm.py against recorded Proxmox answers — no network, no VM, no hypervisor."""

from __future__ import annotations

import json

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
    # Fetched once despite three checks needing it (plus the single 5xx retry).
    assert len(http.paths("GET")) == 6


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
