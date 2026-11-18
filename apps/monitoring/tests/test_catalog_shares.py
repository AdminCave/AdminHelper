# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module net_share (R-1267): every network share the agent finds mounted is a
finding of its own, named after its mount point; its check asks the agent's view of the share,
and each rule fires at its threshold and not without it."""

import copy
from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.catalog.modules.net_share import MODULE
from app.checkers.probe import ProbeChecker
from app.discovery import MAX_SHARES, clean_inventory, match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
FINE = {"mounted": True, "hung": False, "used_percent": 40.0, "free_gb": 600.0}


def _inventory(shares=(), **parts):
    return clean_inventory(
        {
            "ts": T0,
            "duration_ms": 900,
            "partial": False,
            "units": [],
            "sockets": [],
            "containers": [],
            "markers": {},
            "ports": [],
            "vhosts": [],
            "shares": list(shares),
            **parts,
        }
    )


def _instances(inv):
    return sorted(k for m, k in match_inventory(inv, CATALOG) if m == "net_share")


def _config(mountpoint="/mnt/pve/backup"):
    module = CATALOG.modules["net_share"]
    summary = {"share": mountpoint, "fstype": "nfs4"}
    key = mountpoint[1:].replace("/", ":")
    config, why = probe_config(module, module.checks[0], key, summary, [])
    assert why is None, why
    return {**config, "_check_id": "chk"}


def _status(**values):
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate(_config(), report)[0]


def test_the_module_loads_through_the_loader():
    assert CATALOG.errors == ()
    module = CATALOG.modules["net_share"]
    assert (module.instance, module.detect.net_shares) == ("share", True)


def test_each_mounted_share_is_an_instance_named_after_its_mount_point():
    inv = _inventory(
        [
            {"mountpoint": "/mnt/pve/backup", "fstype": "nfs4"},
            {"mountpoint": "/srv/smb", "fstype": "cifs"},
            {"mountpoint": "/data", "fstype": "nfs"},
        ]
    )
    assert _instances(inv) == ["data", "mnt:pve:backup", "srv:smb"]


def test_the_inventory_keeps_only_mount_point_and_type_of_a_share():
    share = {"mountpoint": "/mnt/nas", "fstype": "smb3", "source": "//nas/share", "opts": "rw"}
    assert _inventory([share])["shares"] == [{"mountpoint": "/mnt/nas", "fstype": "smb3"}]


@pytest.mark.parametrize(
    "share",
    [
        # Not a network type, or none.
        {"mountpoint": "/mnt/disk", "fstype": "ext4"},
        {"mountpoint": "/mnt/nas"},
        # Mount points the agent's share target refuses (probe validMountpoint).
        {"mountpoint": "/", "fstype": "nfs"},
        {"mountpoint": "mnt/nas", "fstype": "nfs"},
        {"mountpoint": "/mnt/nas/", "fstype": "nfs"},
        {"mountpoint": "/mnt//nas", "fstype": "nfs"},
        {"mountpoint": "/mnt/../etc", "fstype": "nfs"},
        {"mountpoint": "/mnt/.hidden", "fstype": "nfs"},
        {"mountpoint": "/mnt/na:s", "fstype": "nfs"},
        {"mountpoint": "/mnt/nas\n", "fstype": "nfs"},
        {"mountpoint": "/" + "a" * 255, "fstype": "nfs"},
        {"mountpoint": 5, "fstype": "nfs"},
        "/mnt/nas",
    ],
)
def test_a_share_outside_the_contract_is_left_out(share):
    assert _inventory([share])["shares"] == []


def test_a_mount_point_the_key_cannot_hold_is_kept_but_makes_no_instance():
    # A blank, "," or "+" is a valid mount point, but no instance key.
    inv = _inventory([{"mountpoint": "/mnt/my share", "fstype": "cifs"}])
    assert inv["shares"] == [{"mountpoint": "/mnt/my share", "fstype": "cifs"}]
    assert _instances(inv) == []


def test_a_point_mounted_twice_is_one_share():
    twice = [{"mountpoint": "/mnt/nas", "fstype": t} for t in ("nfs", "nfs4")]
    assert _inventory(twice)["shares"] == [{"mountpoint": "/mnt/nas", "fstype": "nfs"}]


def test_shares_beyond_the_bound_are_cut_and_make_only_their_section_partial():
    many = [{"mountpoint": f"/mnt/s{i}", "fstype": "nfs"} for i in range(MAX_SHARES + 1)]
    inv = _inventory(many)
    assert len(inv["shares"]) == MAX_SHARES
    assert inv["partial"] is True
    assert inv["complete"]["shares"] is False
    assert inv["complete"]["units"] is True


def test_an_inventory_without_shares_finds_none():
    inv = _inventory()
    del inv["shares"]
    assert _instances(inv) == []


def test_the_check_asks_the_agent_for_the_share_at_its_mount_point():
    config = _config()
    assert config["target"] == {
        "kind": "share",
        "name": "/mnt/pve/backup",
        "port_hint": None,
        "scheme": None,
    }
    assert config["params"] == {"view": "net_share_usage"}
    assert config["interval_s"] == 300
    # Above the agent's 10 s for statfs, so a share that hangs reads as hung.
    assert config["timeout_s"] > 10


def test_a_share_that_is_mounted_and_answers_is_ok():
    assert _status(**FINE) == "ok"


@pytest.mark.parametrize(
    ("change", "want"),
    [
        ({"mounted": False, "hung": False, "used_percent": None, "free_gb": None}, "critical"),
        ({"hung": True, "used_percent": None, "free_gb": None}, "critical"),
        ({"used_percent": 84.9}, "ok"),
        ({"used_percent": 85.0}, "warning"),
        ({"used_percent": 94.9}, "warning"),
        ({"used_percent": 95.0}, "critical"),
    ],
)
def test_each_rule_fires_at_its_threshold(change, want):
    values = {k: v for k, v in {**FINE, **change}.items() if v is not None}
    assert _status(**values) == want


def _variant(instance="share", **detect):
    module = copy.deepcopy(MODULE)
    module["instance"], module["detect"] = instance, detect
    return ("net_share", module)


@pytest.mark.parametrize(
    ("instance", "detect", "error"),
    [
        pytest.param("share", {"net_shares": True}, None, id="as-shipped"),
        pytest.param("share", {}, "detects by net_shares only", id="nothing"),
        pytest.param(
            "share",
            {"net_shares": True, "units": ["nfs-client.target"]},
            "detects by net_shares only",
            id="and-a-unit",
        ),
        pytest.param(
            "share",
            {"net_shares": True, "vhost_tls": True},
            "detects by net_shares only",
            id="and-vhosts",
        ),
        pytest.param(
            "unit",
            {"net_shares": True, "units": ["nfs-client.target"]},
            "net_shares needs instance 'share'",
            id="other-instance",
        ),
        pytest.param(
            "unit",
            {"units": ["nfs-client.target"]},
            "target 'share' needs instance 'share'",
            id="share-target-on-a-unit",
        ),
    ],
)
def test_a_share_module_detects_by_its_shares_alone(instance, detect, error):
    catalog = load_catalog([_variant(instance, **detect)])
    if error is None:
        assert catalog.errors == ()
    else:
        assert len(catalog.errors) == 1 and error in str(catalog.errors[0])
