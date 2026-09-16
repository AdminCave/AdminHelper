#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""vm.py — ephemeral Proxmox VMs for AdminHelper's heavy test tiers.

    python3 scripts/vm/vm.py <verb> [options]

Verbs: doctor clone wait ssh sync run pull snap rollback delsnap destroy reap
list bake. Python 3 standard library only — no proxmoxer, no pvesh, no qm: the
REST API is the whole surface, and a dependency for ~25 endpoints buys nothing a
hermetic test could not give us (spec: docs/features/harness-stufe-2.md).

Configuration comes from .claude/settings.local.json -> "env" (gitignored, the
only place the token lives); a real environment variable of the same name wins,
so a runner can inject its own without a file. Keys:

    AH_PVE_URL NODE TOKEN CA STORAGE BRIDGE POOL VMID_RANGE
    AH_VM_SSH_KEY MAX LINKED REMOTE_DIR

State lives on the hypervisor, as tags: every VM this tool creates carries
`ah` plus `role-…`, `lane-…`, `sc-…`, `ttl-<epoch>`, `tpl-…`. A VM without the
`ah` tag is none of our business — every destructive verb refuses it (exit 2),
which is what keeps a wrong VMID from eating a homelab VM.

Exit codes: 0 ok · 1 the thing you ran failed (a remote command's own exit) ·
2 usage, or a refusal to touch something that is not ours · 74 infrastructure
(API, capacity, no IP, missing privilege) — the class heavy.sh sorts away as
`infra` instead of reporting a red test.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Everything this tool caches locally. Gitignored, and small on purpose: the
# hypervisor's tags are the state, this is only what ssh and the wrappers need.
VM_STATE_DIR = os.path.join(ROOT, ".vm")

# Time bounds. Every one of them exists because something hung once: an
# unbounded HTTP call, a UPID poll that never ended, a lock that never cleared.
HTTP_TIMEOUT = 30  # seconds per request
TASK_POLL_MIN = 1.0  # UPID poll backoff 1 s -> 5 s
TASK_POLL_MAX = 5.0
TASK_LIMIT = 300  # clone/snapshot/destroy tasks; a bake's `run` has its own
LOCK_RETRY_LIMIT = 60  # window for "can't lock file"; measured collisions clear in ~12 s
CLONE_LIMIT_LINKED = 300  # measured: 2 s
CLONE_LIMIT_FULL = 1800  # measured: ~11 min on the thin pool
WAIT_TIMEOUT = 900  # agent ping -> IP -> ssh
AGENT_POLL = 5
SSH_CONNECT_TIMEOUT = 5

# A locked config is not an error worth failing on: PVE holds the lock for a few
# seconds after `rollback --start`, and it surfaces in TWO shapes — as HTTP 500
# ("VM is locked (rollback)") and, more treacherously, as a task that was
# accepted with a UPID and 200 and then ended with `exitstatus: can't lock file`.
# Retrying only on the HTTP shape would miss the one that looks like success
# (see scripts/vm/tests/README.md).
LOCK_MARKERS = ("can't lock file", "VM is locked")

DEFAULTS = {
    "AH_PVE_VMID_RANGE": "3000-3999",
    "AH_VM_SSH_KEY": "~/.config/adminhelper/vm_ed25519",
    # The capstone holds seven leases at once, so a cap below that would break
    # the very run it is meant to protect. It is a runaway guard, not a budget.
    "AH_VM_MAX": "8",
    "AH_VM_LINKED": "1",
    "AH_VM_REMOTE_DIR": "~/adminhelper",
}
# Keys that only ever come from the file or the environment, so they need no
# default. Presence is not checked here — Config.__getitem__ raises on access,
# which is what keeps `vm.py list` from demanding a bake profile.
ENV_KEYS = (
    "AH_PVE_URL",
    "AH_PVE_NODE",
    "AH_PVE_TOKEN",
    "AH_PVE_CA",
    "AH_PVE_STORAGE",
    "AH_PVE_BRIDGE",
    "AH_PVE_POOL",
)


class VmError(Exception):
    """Base for everything main() turns into an exit code."""

    code = 1


class Usage(VmError):
    """Bad arguments, or a refusal to touch a VM that is not ours."""

    code = 2


class Infra(VmError):
    """The hypervisor, the network or the capacity said no."""

    code = 74


# ── configuration ────────────────────────────────────────────────────────────
class Config:
    def __init__(self, values: dict):
        self.values = values

    @classmethod
    def load(cls, root: str = ROOT, environ=None) -> "Config":
        environ = os.environ if environ is None else environ
        values = dict(DEFAULTS)
        path = os.path.join(root, ".claude", "settings.local.json")
        try:
            with open(path) as fh:
                values.update(json.load(fh).get("env", {}))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError, TypeError) as exc:
            # AttributeError/TypeError cover a settings file whose top level is
            # not an object — a broken config must not surface as a traceback.
            raise Usage("cannot read %s: %s" % (path, exc)) from exc
        # The environment wins over the file so `ah-runner` (stage 4) can hand a
        # job its own token without writing one to disk.
        for key in list(values) + list(ENV_KEYS):
            if environ.get(key):
                values[key] = environ[key]
        return cls({k: str(v) for k, v in values.items()})

    def __getitem__(self, key: str) -> str:
        value = self.values.get(key, "")
        if not value:
            raise Usage("%s is not configured (.claude/settings.local.json -> env)" % key)
        return value

    def get(self, key: str, default: str = "") -> str:
        return self.values.get(key) or default

    def flag(self, key: str, default: bool) -> bool:
        raw = self.values.get(key)
        if raw in (None, ""):
            return default
        # A JSON `false` in settings.local.json arrives here as "False" — casing
        # is not the author's mistake to pay for.
        return raw.strip().lower() not in ("0", "false", "no", "off")

    def path(self, key: str) -> str:
        return os.path.expanduser(self[key])

    def vmid_range(self) -> tuple[int, int]:
        raw = self["AH_PVE_VMID_RANGE"]
        match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", raw)
        if not match:
            raise Usage("AH_PVE_VMID_RANGE must read '<low>-<high>', got %r" % raw)
        low, high = int(match.group(1)), int(match.group(2))
        if low >= high:
            raise Usage("AH_PVE_VMID_RANGE is empty or inverted: %r" % raw)
        return low, high


# ── HTTP ─────────────────────────────────────────────────────────────────────
class Api:
    """The Proxmox REST surface: one request method, one task waiter."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.node = cfg["AH_PVE_NODE"]
        self.base = cfg["AH_PVE_URL"].rstrip("/") + "/api2/json"
        self._ctx = None

    def context(self) -> ssl.SSLContext:
        if self._ctx is None:
            ca = self.cfg.path("AH_PVE_CA")
            if not os.path.exists(ca):
                raise Usage("AH_PVE_CA does not exist: %s" % ca)
            ctx = ssl.create_default_context(cafile=ca)
            # The homelab root CA carries no keyUsage extension, which Python
            # 3.13 rejects under VERIFY_X509_STRICT. Dropping that one flag keeps
            # full chain + hostname verification (so AH_PVE_URL must use a name
            # from the certificate's SAN); the alternative on offer elsewhere,
            # verify_mode = CERT_NONE, would not.
            ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
            self._ctx = ctx
        return self._ctx

    def request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        body: dict | None = None,
        lock_retry: bool = False,
    ):
        """One call, exactly one retry. Returns the unwrapped `data` value.

        `lock_retry` is for the calls that produce no task and can still lose
        the race against a config lock — `PUT config` above all, which is how a
        fresh clone gets its tags and how `run --extend` renews a lease. Without
        it those would surface the recorded HTTP 500 "VM is locked (rollback)"
        as a hard exit 74 (fixtures/err_vm_locked.json).
        """
        if lock_retry:
            return self._while_locked(lambda: self._send(method, path, params, body))
        return self._send(method, path, params, body)

    def _send(self, method: str, path: str, params: dict | None, body: dict | None):
        url = self.base + path
        # PVE answers DELETE-with-a-body with 501 "Unexpected content for method
        # 'DELETE'" — so a DELETE's parameters go into the query string, always.
        if method == "DELETE" and body:
            params = dict(params or {}, **body)
            body = None
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = urllib.parse.urlencode(body).encode() if body else None

        for attempt in (0, 1):
            try:
                return self._once(method, url, data)
            except Infra as exc:
                # One retry covers a restarting pveproxy and a dropped
                # connection. It is safe even for `clone`, whose only
                # non-idempotent effect is pinned to an explicit `newid`: the
                # second attempt would hit "config file already exists" rather
                # than build a second VM.
                if attempt == 0 and getattr(exc, "retryable", False):
                    time.sleep(1)
                    continue
                raise

    def _once(self, method: str, url: str, data: bytes | None):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "PVEAPIToken=" + self.cfg["AH_PVE_TOKEN"])
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT, context=self.context()) as resp:
                return _unwrap(resp.read().decode())
        except urllib.error.HTTPError as exc:
            raise _http_error(exc, method, url) from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            err = Infra("%s %s: %s" % (method, _redact(url), exc))
            err.retryable = True
            raise err from exc

    # ── tasks ────────────────────────────────────────────────────────────────
    def wait_task(self, upid: str, limit: int = TASK_LIMIT) -> dict:
        """Poll a UPID to `stopped`. Raises Infra unless it ended OK."""
        deadline = time.monotonic() + limit
        delay = TASK_POLL_MIN
        quoted = urllib.parse.quote(upid, safe="")
        while True:
            status = self._send(
                "GET", "/nodes/%s/tasks/%s/status" % (self.node, quoted), None, None
            )
            if status.get("status") == "stopped":
                exitstatus = status.get("exitstatus") or ""
                if exitstatus != "OK":
                    raise Infra("task %s failed: %s" % (status.get("type", "?"), exitstatus))
                return status
            if time.monotonic() >= deadline:
                raise Infra("task %s did not finish within %ds" % (status.get("type", "?"), limit))
            time.sleep(delay)
            delay = min(delay * 2, TASK_POLL_MAX)

    def task(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        body: dict | None = None,
        limit: int = TASK_LIMIT,
    ) -> dict:
        """Submit a task-producing call and wait for it, retrying while locked."""

        def submit():
            upid = self._send(method, path, params, body)
            return self.wait_task(upid, limit)

        return self._while_locked(submit)

    def _while_locked(self, call):
        """Repeat `call` while the config lock is the only thing in the way."""
        deadline = time.monotonic() + LOCK_RETRY_LIMIT
        while True:
            try:
                return call()
            except Infra as exc:
                if not (_is_lock(str(exc)) and time.monotonic() < deadline):
                    raise
                time.sleep(2)


def _unwrap(text: str):
    try:
        return json.loads(text).get("data")
    except ValueError:
        # Some error paths answer in plain text (the DELETE-with-body 501 does).
        return text


def _http_error(exc: urllib.error.HTTPError, method: str, url: str) -> VmError:
    raw = ""
    try:
        raw = exc.read().decode(errors="replace")
    except Exception:  # noqa: BLE001 - a body we cannot read must not mask the status
        pass
    message = raw
    try:
        message = json.loads(raw).get("message") or raw
    except ValueError:
        pass
    message = message.strip()
    if exc.code == 403:
        # "Permission check failed (/vms/100, VM.Audit)" — name the missing
        # privilege, because that is the one thing an operator must act on.
        match = re.search(r"\(([^,]+),\s*([^)]+)\)", message)
        if match:
            return Infra("privilege: %s missing on %s" % (match.group(2), match.group(1)))
        return Infra("privilege: %s" % message)
    err = Infra("%s %s: HTTP %d %s" % (method, _redact(url), exc.code, message))
    err.retryable = exc.code >= 500 and not _is_lock(message)
    return err


def _is_lock(message: str) -> bool:
    return any(marker in message for marker in LOCK_MARKERS)


def _redact(url: str) -> str:
    """Paths are fine in a log; a query string may carry an ssh key."""
    return url.split("?", 1)[0]


# ── the pool's own vocabulary ────────────────────────────────────────────────
PROFILES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles.json")
OURS = "ah"  # the tag that separates our VMs from the homelab's
RESERVE_MB = 4096  # RAM the node keeps for itself, whatever we plan
# Storage types that can hold a linked clone and a snapshot. File-based stores
# manage both only with qcow2 images, which the status endpoint does not reveal —
# they are reported as capable and the first clone would say otherwise.
SNAPSHOT_STORAGE = {"lvmthin", "zfspool", "rbd", "btrfs", "dir", "nfs", "cifs"}
# Privileges each verb needs, by the path the ACL hangs on.
NEEDED_PRIVILEGES = {
    "pool": (
        "VM.Allocate",
        "VM.Audit",
        "VM.Clone",
        "VM.Config.CPU",
        "VM.Config.Cloudinit",
        "VM.Config.Disk",
        "VM.Config.Memory",
        "VM.Config.Network",
        "VM.Config.Options",
        "VM.GuestAgent.Audit",
        "VM.PowerMgmt",
        "VM.Snapshot",
        "VM.Snapshot.Rollback",
    ),
    "storage": ("Datastore.AllocateSpace", "Datastore.Audit"),
    "node": ("Sys.Audit", "VM.Audit"),
}


def load_profiles(path: str = PROFILES_FILE) -> dict:
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise Usage("cannot read %s: %s" % (path, exc)) from exc


def tags_of(vm_entry: dict) -> set:
    """Tags are a SET: PVE hands them back sorted alphabetically, never as given."""
    return {t for t in (vm_entry.get("tags") or "").split(";") if t}


def tag_value(tags: set, prefix: str, default: str = "") -> str:
    for tag in tags:
        if tag.startswith(prefix):
            return tag[len(prefix) :]
    return default


def pool_vms(cfg: Config, api: Api) -> list:
    """Every VM the token can see in our pool, tags included.

    /pools/<pool> would read more naturally, but it answers without tags — and
    tags are the only state this tool has (see scripts/vm/tests/README.md).
    """
    pool = cfg["AH_PVE_POOL"]
    entries = api.request("GET", "/cluster/resources", params={"type": "vm"}) or []
    return [v for v in entries if v.get("pool") == pool]


def newest_template(vms: list, template_tag: str) -> dict | None:
    """The template carrying `template_tag`, newest `built-<yyyymmdd>` first."""
    candidates = [v for v in vms if v.get("template") and template_tag in tags_of(v)]
    if not candidates:
        return None
    return max(candidates, key=lambda v: (tag_value(tags_of(v), "built-"), v["vmid"]))


def role_shape(profiles: dict, role: str) -> dict:
    shape = profiles["roles"].get(role)
    if not shape:
        raise Usage("unknown role %r — known: %s" % (role, ", ".join(sorted(profiles["roles"]))))
    return shape


# ── verbs ────────────────────────────────────────────────────────────────────
VERBS = (
    "doctor",
    "clone",
    "wait",
    "ssh",
    "sync",
    "run",
    "pull",
    "snap",
    "rollback",
    "delsnap",
    "destroy",
    "reap",
    "list",
    "bake",
)


def parse_duration(text: str) -> int:
    """`8h`, `20m`, `90s`, `2d` -> seconds. A bare number is seconds."""
    match = re.fullmatch(r"\s*(\d+)\s*([smhd]?)\s*", text or "")
    if not match:
        raise Usage("cannot read a duration from %r (try 8h, 20m, 90s)" % text)
    return int(match.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]


def tag_safe(value: str) -> str:
    """Tags are a `;`-separated set of lowercase words. Anything that goes into
    one — or is matched against one — passes through here, so that `--lane Main`
    finds lane `main` and a stray `;` cannot smuggle in a second tag."""
    return re.sub(r"[^a-z0-9-]", "-", (value or "").lower()).strip("-")


def current_lane(override: str | None = None, environ=None) -> str:
    """--lane, else AH_LANE, else .vm/lane, else `main` (the shared checkout)."""
    environ = os.environ if environ is None else environ
    lane = override or environ.get("AH_LANE") or ""
    if not lane:
        try:
            with open(os.path.join(VM_STATE_DIR, "lane")) as fh:
                lane = fh.read().strip()
        except OSError:
            lane = ""
    return tag_safe(lane) or "main"


def capacity_report(cfg: Config, api: Api, vms: list, need_mb: int, label: str):
    """(spare_mb, detail) — shared by `doctor` and by every verb that clones."""
    node = api.request("GET", "/nodes/%s/status" % cfg["AH_PVE_NODE"])
    free_mb = (node.get("memory", {}).get("free") or 0) // 1024**2
    # What our VMs may still take, not what they were configured for: a running
    # VM's touched RAM is already out of `free`, so charging its full maxmem
    # again would refuse clones the node can carry — while charging nothing
    # would hand out the 5 GB a freshly booted 6 GB box has not claimed yet. For
    # a stopped VM `mem` is 0 and the term is its maxmem. `mem` rides the same
    # lagging resource list as the tags do: a guard rail, not a promise.
    ours = [v for v in vms if OURS in tags_of(v) and not v.get("template")]
    owed = [(v, max(0, (v.get("maxmem") or 0) - (v.get("mem") or 0)) // 1024**2) for v in ours]
    owed_mb = sum(mb for _, mb in owed)
    spare = free_mb - RESERVE_MB - owed_mb - need_mb
    detail = "%d MiB free - %d reserve - %d owed by ours - %d for %s = %d MiB" % (
        free_mb,
        RESERVE_MB,
        owed_mb,
        need_mb,
        label,
        spare,
    )
    if spare < 0 and owed_mb:
        detail += " (ours: %s)" % ", ".join(
            "%d %s %d MiB" % (v["vmid"], v.get("name", "?"), mb) for v, mb in owed if mb
        )
    return spare, detail


def free_vmid(cfg: Config, vms: list) -> int:
    """The smallest free VMID in the clone band — the lower hundred of the range.

    Templates live in the upper hundred so a bake never collides with a lease.
    """
    low, high = cfg.vmid_range()
    taken = {v["vmid"] for v in vms}
    for vmid in range(low, low + 100):
        if vmid not in taken:
            return vmid
    raise Infra("no free VMID in %d-%d — the clone band is full" % (low, low + 99))


def find_vm(cfg: Config, api: Api, ref: str, vms: list | None = None) -> dict:
    """A VMID or a name, resolved inside our pool — and nowhere else."""
    vms = pool_vms(cfg, api) if vms is None else vms
    if str(ref).isdigit():
        matches = [v for v in vms if v["vmid"] == int(ref)]
    else:
        matches = [v for v in vms if v.get("name") == ref]
    if not matches:
        raise Usage("no VM %r in pool %s" % (ref, cfg["AH_PVE_POOL"]))
    if len(matches) > 1:
        raise Usage("%r names %d VMs: %s" % (ref, len(matches), [v["vmid"] for v in matches]))
    return matches[0]


def guest_user(cfg: Config, api: Api, vmid: int) -> str:
    """The cloud-init user, inherited from the template — not a config value.

    The fat template still says `crabbox`; the first rebake (T7) says
    `adminhelper`. Reading it off the VM makes that a template swap, not a sweep.
    """
    config = api.request("GET", "/nodes/%s/qemu/%d/config" % (cfg["AH_PVE_NODE"], vmid))
    user = config.get("ciuser")
    if not user:
        raise Infra("VM %d has no ciuser — the template is not cloud-init ready" % vmid)
    return str(user)


def fresh_entry(cfg: Config, api: Api, vmid: int) -> dict | None:
    """status/current, shaped like a /cluster/resources entry.

    The resource list lags (scripts/vm/tests/README.md: it served a previous
    tenant's name for a recycled VMID while the tags were already current).
    Deciding to destroy something from a cache is how the wrong VM dies, and how
    a lease renewed a second ago gets reaped anyway. `None` means the VM is
    already gone.
    """
    try:
        current = api.request(
            "GET", "/nodes/%s/qemu/%d/status/current" % (cfg["AH_PVE_NODE"], vmid)
        )
    except VmError as exc:
        # Already gone — another lane's sweep, an expired lease, a `qm destroy`
        # by hand. Not an error, and above all not a reason to abandon the rest
        # of a teardown: `purge_vm` reads the same wording the same way.
        if "qemu-server/%d.conf" % vmid in str(exc):
            return None
        raise
    current = current or {}
    return {
        "vmid": vmid,
        "name": current.get("name", ""),
        "tags": current.get("tags", ""),
        "status": current.get("status", "?"),
        "template": current.get("template", 0),
        "_current": current,
    }


def purge_vm(cfg: Config, api: Api, vmid: int, current: dict | None = None):
    """Stop if need be, then delete with the disks. PVE refuses to delete a
    running VM ("VM 3000 is running - destroy failed"), so the stop is not
    optional. A VM that is already gone is a success, not an error — the clone
    rollback runs on paths where it may never have been created."""
    node = cfg["AH_PVE_NODE"]
    try:
        if current is None:
            current = api.request("GET", "/nodes/%s/qemu/%d/status/current" % (node, vmid))
        if (current or {}).get("status") != "stopped":
            api.task("POST", "/nodes/%s/qemu/%d/status/stop" % (node, vmid))
    except VmError:
        pass  # a VM that cannot be read or stopped may still be deletable
    try:
        api.task(
            "DELETE",
            "/nodes/%s/qemu/%d" % (node, vmid),
            params={"purge": 1, "destroy-unreferenced-disks": 1},
        )
    except VmError as exc:
        # Exactly PVE's own wording for this VM's config file. A looser test
        # such as "does not exist" also matches "storage 'raid5' does not
        # exist", and would report a VM as removed while it is still standing.
        if "qemu-server/%d.conf" % vmid not in str(exc):
            raise


# ── doctor ───────────────────────────────────────────────────────────────────
class Checks:
    """Collects `ok|FAIL <name>: <detail>` lines; one FAIL decides the exit code."""

    def __init__(self):
        self.lines: list[dict] = []

    def add(self, ok: bool, name: str, detail: str):
        self.lines.append({"check": name, "ok": bool(ok), "detail": detail})
        return ok

    def run(self, name: str, probe):
        """A check that raises is a FAIL, not the end of the examination — the
        whole point of `doctor` is to say everything that is wrong in one pass."""
        try:
            ok, detail = probe()
        except VmError as exc:
            return self.add(False, name, str(exc))
        return self.add(ok, name, detail)

    @property
    def failed(self) -> bool:
        return any(not line["ok"] for line in self.lines)


def verb_doctor(cfg: Config, api: Api, args) -> int:
    profiles = load_profiles()
    roles = [r.strip() for r in (args.roles or "").split(",") if r.strip()]
    checks = Checks()
    state: dict = {}

    def api_check():
        version = api.request("GET", "/version")
        return True, "PVE %s on node %s" % (version.get("version", "?"), cfg["AH_PVE_NODE"])

    def privilege_check():
        granted = api.request("GET", "/access/permissions") or {}
        paths = {
            "pool": "/pool/" + cfg["AH_PVE_POOL"],
            "storage": "/storage/" + cfg["AH_PVE_STORAGE"],
            "node": "/nodes/" + cfg["AH_PVE_NODE"],
        }
        missing = []
        for kind, path in paths.items():
            have = {name for name, on in (granted.get(path) or {}).items() if on}
            missing += ["%s on %s" % (n, path) for n in NEEDED_PRIVILEGES[kind] if n not in have]
        if missing:
            return False, "missing " + ", ".join(missing)
        return True, "all privileges on %s" % ", ".join(sorted(paths.values()))

    def storage_check():
        storage = cfg["AH_PVE_STORAGE"]
        status = api.request("GET", "/nodes/%s/storage/%s/status" % (cfg["AH_PVE_NODE"], storage))
        kind = status.get("type", "?")
        capable = kind in SNAPSHOT_STORAGE
        free_gb = (status.get("avail") or 0) / 1024**3
        yes_no = "yes" if capable else "no"
        detail = "%s is %s, linked=%s snapshots=%s, %.0f GiB free" % (
            storage,
            kind,
            yes_no,
            yes_no,
            free_gb,
        )
        # A store that cannot do either is a supported way to run (full clones,
        # no snapshots) — it is only wrong while AH_VM_LINKED asks for the
        # opposite. T6 refuses the individual snapshot verbs at the time.
        if not capable and cfg.flag("AH_VM_LINKED", True):
            return False, detail + " — set AH_VM_LINKED=0 for full clones"
        return True, detail

    def vms():
        """The pool, fetched once. A failure is cached too — three checks need
        this list, and each must say it is missing rather than read `ok` off an
        empty default."""
        if "vms" not in state:
            try:
                state["vms"] = pool_vms(cfg, api)
            except VmError as exc:
                state["vms"] = None
                state["vms_error"] = str(exc)
        if state["vms"] is None:
            raise Infra("cluster resources unavailable: %s" % state["vms_error"])
        return state["vms"]

    def template_check():
        found, missing = [], []
        for profile, meta in sorted(profiles["profiles"].items()):
            template = newest_template(vms(), meta["template_tag"])
            if template is None:
                missing.append(profile)
                continue
            state.setdefault("templates", {})[profile] = template
            built = tag_value(tags_of(template), "built-") or "undated"
            found.append("%s %s (%d)" % (profile, built, template["vmid"]))
        if missing:
            return False, "no template tagged for %s; have %s" % (
                ", ".join(missing),
                ", ".join(found) or "none",
            )
        return True, ", ".join(found)

    def template_config_check():
        templates = state.get("templates") or {}
        if not templates:
            return False, "no template to inspect"
        complaints = []
        for profile, template in sorted(templates.items()):
            config = api.request(
                "GET", "/nodes/%s/qemu/%d/config" % (cfg["AH_PVE_NODE"], template["vmid"])
            )
            # PVE stores the property string "enabled=1" or the bare boolean "1".
            agent = str(config.get("agent") or "")
            if "enabled=1" not in agent and agent.strip() != "1":
                complaints.append("%s: no guest agent" % profile)
            bridge = cfg["AH_PVE_BRIDGE"]
            nets = [str(v) for k, v in config.items() if k.startswith("net")]
            # Exact, comma-separated: a substring test lets vmbr1 match vmbr10.
            if not any("bridge=" + bridge in n.split(",") for n in nets):
                complaints.append("%s: not on bridge %s" % (profile, bridge))
        if complaints:
            return False, "; ".join(complaints)
        return True, "guest agent on, bridge %s, %d template(s)" % (
            cfg["AH_PVE_BRIDGE"],
            len(templates),
        )

    def vmid_check():
        low, high = cfg.vmid_range()
        taken = {v["vmid"] for v in vms() if low <= v["vmid"] <= high}
        free = next((i for i in range(low, low + 100) if i not in taken), None)
        if free is None:
            return False, "no free VMID in %d-%d (clone band full)" % (low, low + 99)
        return True, "%d-%d: %d taken, next clone %d, templates %d-%d" % (
            low,
            high,
            len(taken),
            free,
            high - 99,
            high,
        )

    def capacity_check():
        need_mb = sum(role_shape(profiles, r)["memory"] for r in roles)
        spare, detail = capacity_report(cfg, api, vms(), need_mb, ",".join(roles) or "nothing")
        return spare >= 0, detail

    for role in roles:
        role_shape(profiles, role)  # a typo in --roles is a usage error, not a FAIL line

    checks.run("api", api_check)
    checks.run("privileges", privilege_check)
    checks.run("storage", storage_check)
    checks.run("templates", template_check)
    checks.run("template-config", template_config_check)
    checks.run("vmids", vmid_check)
    checks.run("capacity", capacity_check)

    if args.as_json:
        print(json.dumps({"ok": not checks.failed, "checks": checks.lines}, indent=2))
    else:
        for line in checks.lines:
            print("%-4s %s: %s" % ("ok" if line["ok"] else "FAIL", line["check"], line["detail"]))
    return 74 if checks.failed else 0


# ── clone / wait ─────────────────────────────────────────────────────────────
def verb_clone(cfg: Config, api: Api, args) -> int:
    profiles = load_profiles()
    meta = profiles["profiles"].get(args.profile)
    if not meta:
        raise Usage(
            "unknown profile %r — known: %s"
            % (args.profile, ", ".join(sorted(profiles["profiles"])))
        )
    shape = role_shape(profiles, args.role)
    memory = args.memory or shape["memory"]
    cores = args.cores or shape["cores"]
    lane = current_lane(override=args.lane)
    ttl_seconds = parse_duration(args.ttl)
    # Read before anything is created: a VM whose key never made it in is
    # unreachable, and finding that out after the clone means a purge for
    # nothing. Everything argparse cannot check is checked here.
    key = public_key(cfg)
    # A tag list is separated by ';' — an unfiltered scenario could smuggle a
    # second ttl- into it, and tags are read as a SET, so which one wins would
    # be luck. The lane is cleaned the same way one function up.
    scenario = tag_safe(args.scenario)
    if args.scenario and not scenario:
        raise Usage("--scenario %r has nothing usable in it" % args.scenario)

    vms = pool_vms(cfg, api)
    ours_here = [
        v
        for v in vms
        if OURS in tags_of(v)
        and not v.get("template")
        and tag_value(tags_of(v), "lane-", "main") == lane
    ]
    raw_cap = cfg.get("AH_VM_MAX", "0") or "0"
    if not str(raw_cap).strip().isdigit():
        raise Usage("AH_VM_MAX must be a number, got %r" % raw_cap)
    cap = int(raw_cap)
    if cap and len(ours_here) >= cap:
        raise Infra(
            "AH_VM_MAX=%d reached on lane %s: %s"
            % (cap, lane, ", ".join("%d %s" % (v["vmid"], v.get("name", "?")) for v in ours_here))
        )
    spare, detail = capacity_report(cfg, api, vms, memory, args.role)
    if spare < 0:
        raise Infra("capacity: " + detail)

    template = newest_template(vms, meta["template_tag"])
    if template is None:
        raise Infra(
            "no template tagged %s in pool %s — bake one"
            % (meta["template_tag"], cfg["AH_PVE_POOL"])
        )
    newid = free_vmid(cfg, vms)
    name = args.name or "ah-%s-%s-%04x" % (args.role, lane, os.getpid() & 0xFFFF)
    node = cfg["AH_PVE_NODE"]
    linked = cfg.flag("AH_VM_LINKED", True)

    body = {"newid": newid, "name": name, "full": 0 if linked else 1, "pool": cfg["AH_PVE_POOL"]}
    if not linked:
        body["storage"] = cfg["AH_PVE_STORAGE"]
    # Submit and wait are split on purpose. A rejected submit created nothing —
    # and "config file already exists" may well mean a parallel lane grabbed the
    # same free VMID a moment earlier, so purging on that would destroy someone
    # else's VM. Once the UPID is out, the VM is ours whatever happens next: a
    # clone task that outruns our patience keeps running on the server and
    # finishes an UNTAGGED VM, which `destroy` and `reap` would then refuse to
    # touch forever. That one belongs in the purge.
    try:
        # lock_retry, because the source template can be locked by a second
        # lane cloning from it (or by T8 tagging it) — and by the argument
        # above, a submit that is refused has created nothing to clean up.
        upid = api.request(
            "POST",
            "/nodes/%s/qemu/%d/clone" % (node, template["vmid"]),
            body=body,
            lock_retry=True,
        )
    except VmError as exc:
        raise Infra("clone of %d into %d failed: %s" % (template["vmid"], newid, exc)) from exc

    try:
        api.wait_task(upid, limit=CLONE_LIMIT_LINKED if linked else CLONE_LIMIT_FULL)
        tags = [
            "ah",
            "role-" + args.role,
            "lane-" + lane,
            "tpl-" + args.profile,
            "ttl-%d" % (int(time.time()) + ttl_seconds),
        ]
        if scenario:
            tags.append("sc-" + scenario)
        config = {
            "tags": ";".join(tags),
            "agent": "enabled=1",
            "memory": memory,
            "cores": cores,
            "ipconfig0": "ip=dhcp",
        }
        # PVE stores this value url-encoded and decodes it once on the way into
        # cloud-init; urlencode's own escaping is the second layer.
        config["sshkeys"] = urllib.parse.quote(key, safe="")
        api.request("PUT", "/nodes/%s/qemu/%d/config" % (node, newid), body=config, lock_retry=True)
        api.task("POST", "/nodes/%s/qemu/%d/status/start" % (node, newid))
    except BaseException as exc:
        # BaseException, not VmError: a Ctrl-C between the clone and the tags
        # leaves exactly the same untagged leftover, and so would a bug in the
        # tag building. The interrupt is re-raised as itself afterwards.
        try:
            purge_vm(cfg, api, newid)
        except VmError as cleanup:
            raise Infra("%s; and the cleanup of %d failed too: %s" % (exc, newid, cleanup)) from exc
        if isinstance(exc, VmError):
            raise Infra("%s (VM %d was removed again)" % (exc, newid)) from exc
        raise

    print("%d %s" % (newid, name))
    return 0


def public_key(cfg: Config) -> str:
    path = cfg.path("AH_VM_SSH_KEY") + ".pub"
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError as exc:
        raise Usage(
            "no public key at %s — create the pair with "
            "`ssh-keygen -t ed25519 -f %s -N ''`" % (path, cfg.path("AH_VM_SSH_KEY"))
        ) from exc


def vm_ipv4(api: Api, node: str, vmid: int) -> str:
    """The guest's own IPv4, loopback and link-local and IPv6 filtered out."""
    interfaces = api.request("GET", "/nodes/%s/qemu/%d/agent/network-get-interfaces" % (node, vmid))
    for iface in (interfaces or {}).get("result", []):
        if iface.get("name") == "lo":
            continue
        for address in iface.get("ip-addresses", []):
            ip = address.get("ip-address", "")
            if address.get("ip-address-type") != "ipv4":
                continue
            if ip.startswith("127.") or ip.startswith("169.254."):
                continue
            return ip
    return ""


def verb_wait(cfg: Config, api: Api, args) -> int:
    entry = find_vm(cfg, api, args.vm)
    vmid = entry["vmid"]
    node = cfg["AH_PVE_NODE"]
    deadline = time.monotonic() + args.timeout

    last = "no answer yet"
    while True:
        try:
            api.request("POST", "/nodes/%s/qemu/%d/agent/ping" % (node, vmid))
            break
        except VmError as exc:
            # "VM is not running" right after start, "QEMU guest agent is not
            # running" while it boots — both are HTTP 500 and both are normal.
            last = str(exc)
        if time.monotonic() >= deadline:
            raise Infra(
                "no ip: guest agent of %d silent after %ds (%s)" % (vmid, args.timeout, last)
            )
        time.sleep(AGENT_POLL)

    ip = ""
    while True:
        try:
            ip = vm_ipv4(api, node, vmid)
        except VmError as exc:
            # The agent answered the ping a moment ago; a 500 here is the same
            # kind of hiccup and deserves the same patience, not a hard stop.
            last = str(exc)
        if ip:
            break
        if time.monotonic() >= deadline:
            raise Infra("no ip: %d has no IPv4 after %ds (%s)" % (vmid, args.timeout, last))
        time.sleep(AGENT_POLL)

    user = guest_user(cfg, api, vmid)
    while True:
        # Bounded by what is left of our own timeout: ConnectTimeout covers the
        # TCP handshake, not a host that accepts and then stalls in the key
        # exchange — and an unbounded ssh would outlive the deadline it is
        # supposed to honour.
        left = max(1, int(deadline - time.monotonic()))
        if run_ssh(cfg, user, ip, ["true"], timeout=left) == 0:
            break
        if time.monotonic() >= deadline:
            raise Infra("no ssh: %s@%s refused for %ds" % (user, ip, args.timeout))
        time.sleep(AGENT_POLL)

    print(ip)
    return 0


def ssh_options(cfg: Config) -> list:
    known_hosts = os.path.join(VM_STATE_DIR, "known_hosts")
    os.makedirs(os.path.dirname(known_hosts), exist_ok=True)
    return [
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=%d" % SSH_CONNECT_TIMEOUT,
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "UserKnownHostsFile=" + known_hosts,
        "-i",
        cfg.path("AH_VM_SSH_KEY"),
    ]


def run_ssh(cfg: Config, user: str, ip: str, command: list, timeout: int | None = None) -> int:
    argv = ["ssh", *ssh_options(cfg), "%s@%s" % (user, ip), *command]
    try:
        return subprocess.call(argv, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 255
    except OSError as exc:
        raise Infra("cannot run ssh: %s" % exc) from exc


# ── ssh / sync / run / pull ──────────────────────────────────────────────────
RSYNC_EXCLUDE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rsync-exclude.txt")


class Target:
    """A VM resolved once per invocation: id, guest user, address.

    Each of those is an API round trip, and `run --sync --out` needs all three
    three times over.
    """

    def __init__(self, cfg: Config, api: Api, ref: str):
        self.cfg, self.api = cfg, api
        entry = find_vm(cfg, api, ref)
        self.vmid = entry["vmid"]
        self.tags = tags_of(entry)
        self._ip = ""
        self._user = ""

    @property
    def ip(self) -> str:
        if not self._ip:
            self._ip = vm_ipv4(self.api, self.cfg["AH_PVE_NODE"], self.vmid)
            if not self._ip:
                raise Infra(
                    "no ip: %d has no IPv4 — is it running? try `vm.py wait %d`"
                    % (self.vmid, self.vmid)
                )
        return self._ip

    @property
    def user(self) -> str:
        if not self._user:
            self._user = guest_user(self.cfg, self.api, self.vmid)
        return self._user

    @property
    def at(self) -> str:
        # Address first: "no ip, run wait" is the more useful of the two
        # failures, and asking for the guest user of an unreachable VM is noise.
        ip = self.ip
        return "%s@%s" % (self.user, ip)


def remote_dir(cfg: Config) -> str:
    """The checkout's path on the guest. Expanded by the guest's own shell, so
    a `~` works and a path with spaces does not — which is why it is a config
    value with a sane default and not something a caller passes per run."""
    return cfg.get("AH_VM_REMOTE_DIR", "~/adminhelper").rstrip("/")


def rsync(cfg: Config, args: list, what: str) -> None:
    ssh_cmd = " ".join(shlex.quote(part) for part in ["ssh", *ssh_options(cfg)])
    argv = ["rsync", "-az", "-e", ssh_cmd, *args]
    try:
        code = subprocess.call(argv)
    except OSError as exc:
        raise Infra("cannot run rsync: %s" % exc) from exc
    if code != 0:
        raise Infra("%s failed: rsync exited %d" % (what, code))


def verb_ssh(cfg: Config, api: Api, args) -> int:
    target = Target(cfg, api, args.vm)
    command = list(args.cmd or [])
    if not command:
        # No command: hand the terminal over, and hand back whatever the shell
        # exits with. An interactive session has no timeout worth guessing.
        return run_ssh(
            cfg, target.user, target.ip, ["-t", "cd %s || true; exec $SHELL -l" % remote_dir(cfg)]
        )
    return run_ssh(cfg, target.user, target.ip, command)


def verb_sync(cfg: Config, api: Api, args) -> int:
    target = Target(cfg, api, args.vm)
    _sync(cfg, target, delete=not args.no_delete)
    return 0


def _sync(cfg: Config, target: "Target", delete: bool) -> None:
    argv = ["--exclude-from", RSYNC_EXCLUDE]
    if delete:
        argv.append("--delete")
    # ROOT, not "./": from a subdirectory this would push a partial tree and
    # --delete the rest away, and every anchored exclude (apps/server/data,
    # apps/web/test-results) would silently stop matching.
    argv += [ROOT + "/", "%s:%s/" % (target.at, remote_dir(cfg))]
    rsync(cfg, argv, "sync")


def verb_run(cfg: Config, api: Api, args) -> int:
    command = list(args.cmd or [])
    if not command:
        raise Usage("run needs a command: vm.py run <vm> -- <command>")
    target = Target(cfg, api, args.vm)
    if args.extend:
        extend_lease(cfg, api, target, args.extend)
    if args.sync:
        _sync(cfg, target, delete=True)

    # Joined with spaces, exactly as ssh itself would: the guest's shell parses
    # the result, so `-- 'bash scripts/tests/run.sh lint'` and
    # `-- bash scripts/tests/run.sh lint` mean the same thing.
    remote = "cd %s && %s" % (remote_dir(cfg), " ".join(command))
    started = time.monotonic()
    code = run_ssh(cfg, target.user, target.ip, [remote], timeout=args.timeout)
    if code == 255:
        # ssh's own failure code, which run_ssh also uses for a timeout. Passing
        # either through would report infrastructure as a test result — and the
        # weekly triage reads these lines, so they must say which it was.
        if args.timeout and time.monotonic() - started >= args.timeout:
            raise Infra(
                "timeout: %s exceeded %ds on %s" % (" ".join(command), args.timeout, target.at)
            )
        raise Infra("ssh to %s failed (255) while running: %s" % (target.at, " ".join(command)))
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        # Nothing creates .ah-out until a suite writes into it, and rsync
        # answers a missing source with exit 23 — which would turn "the suite
        # produced no artifacts" into an infrastructure failure and bury the
        # remote exit code we are about to return.
        made = run_ssh(
            cfg, target.user, target.ip, ["mkdir -p %s/.ah-out" % remote_dir(cfg)], timeout=60
        )
        if made != 0:
            raise Infra("cannot create %s/.ah-out on %s" % (remote_dir(cfg), target.at))
        rsync(
            cfg,
            ["%s:%s/.ah-out/" % (target.at, remote_dir(cfg)), args.out.rstrip("/") + "/"],
            "out",
        )
    # The remote exit code IS the answer: a red suite must stay red here.
    return code


def verb_pull(cfg: Config, api: Api, args) -> int:
    target = Target(cfg, api, args.vm)
    os.makedirs(args.dir, exist_ok=True)
    rsync(
        cfg,
        ["%s:%s/%s" % (target.at, remote_dir(cfg), args.glob), args.dir.rstrip("/") + "/"],
        "pull",
    )
    return 0


def extend_lease(cfg: Config, api: Api, target: "Target", duration: str) -> None:
    """Move the ttl- tag, keeping every other tag as it was."""
    if OURS not in target.tags:
        raise Usage(
            "%d is not ours (no `%s` tag) — refusing to touch its lease" % (target.vmid, OURS)
        )
    kept = sorted(t for t in target.tags if not t.startswith("ttl-"))
    kept.append("ttl-%d" % (int(time.time()) + parse_duration(duration)))
    api.request(
        "PUT",
        "/nodes/%s/qemu/%d/config" % (cfg["AH_PVE_NODE"], target.vmid),
        body={"tags": ";".join(kept)},
        lock_retry=True,
    )


# ── snapshots, destruction, the reaper ───────────────────────────────────────
def require_ours(entry: dict) -> dict:
    """Fail closed. A VMID is four digits, a typo is one keystroke, and the pool
    holds homelab VMs and templates this tool did not build."""
    vmid = entry["vmid"]
    if entry.get("template"):
        raise Usage("%d is a template — those are Kevin's to delete, not ours" % vmid)
    if OURS not in tags_of(entry):
        raise Usage(
            "%d (%s) carries no `%s` tag — it is not ours, refusing"
            % (vmid, entry.get("name", "?"), OURS)
        )
    return entry


def snapshots_possible(cfg: Config, api: Api) -> tuple[bool, str]:
    status = api.request(
        "GET", "/nodes/%s/storage/%s/status" % (cfg["AH_PVE_NODE"], cfg["AH_PVE_STORAGE"])
    )
    kind = status.get("type", "?")
    return kind in SNAPSHOT_STORAGE, kind


def require_snapshots(cfg: Config, api: Api) -> None:
    possible, kind = snapshots_possible(cfg, api)
    if not possible:
        raise Infra(
            "storage %s is %s and cannot snapshot — `vm.py doctor` says so too"
            % (cfg["AH_PVE_STORAGE"], kind)
        )


def _snapshot_target(cfg: Config, api: Api, ref: str) -> int:
    require_snapshots(cfg, api)
    return require_ours(find_vm(cfg, api, ref))["vmid"]


def verb_snap(cfg: Config, api: Api, args) -> int:
    vmid = _snapshot_target(cfg, api, args.vm)
    body = {"snapname": args.name}
    if args.ram:
        body["vmstate"] = 1
    api.task("POST", "/nodes/%s/qemu/%d/snapshot" % (cfg["AH_PVE_NODE"], vmid), body=body)
    return 0


def verb_rollback(cfg: Config, api: Api, args) -> int:
    vmid = _snapshot_target(cfg, api, args.vm)
    body = {"start": 1} if args.start else None
    api.task(
        "POST",
        "/nodes/%s/qemu/%d/snapshot/%s/rollback" % (cfg["AH_PVE_NODE"], vmid, args.name),
        body=body,
    )
    return 0


def verb_delsnap(cfg: Config, api: Api, args) -> int:
    vmid = _snapshot_target(cfg, api, args.vm)
    api.task("DELETE", "/nodes/%s/qemu/%d/snapshot/%s" % (cfg["AH_PVE_NODE"], vmid, args.name))
    return 0


def select_vms(cfg: Config, vms: list, args) -> list:
    """The VMs a `destroy` names, by id/name or by tag."""
    chosen: dict = {}
    for ref in args.vm or []:
        entry = find_vm(cfg, None, ref, vms=vms)
        chosen[entry["vmid"]] = entry
    filters = [
        ("sc-", tag_safe(args.scenario) if args.scenario else None),
        ("lane-", tag_safe(args.lane) if args.lane else None),
        ("role-", tag_safe(args.role) if args.role else None),
    ]
    if any(value for _, value in filters):
        for entry in vms:
            tags = tags_of(entry)
            if OURS not in tags or entry.get("template"):
                continue
            if all(
                value is None
                or tag_value(tags, prefix, "main" if prefix == "lane-" else "") == value
                for prefix, value in filters
            ):
                chosen[entry["vmid"]] = entry
    return [chosen[vmid] for vmid in sorted(chosen)]


def verb_destroy(cfg: Config, api: Api, args) -> int:
    if not (args.vm or args.scenario or args.lane or args.role):
        raise Usage("destroy needs VMs, or one of --scenario/--lane/--role")
    vms = pool_vms(cfg, api)
    chosen = select_vms(cfg, vms, args)
    # Everything is checked BEFORE the first destruction, and checked against
    # FRESH state rather than the resource cache that picked it: a refusal
    # halfway through would leave a scenario partly torn down, and a stale name
    # would kill the wrong VM.
    confirmed = []
    for entry in chosen:
        current = fresh_entry(cfg, api, entry["vmid"])
        if current is None:
            print("already gone %d %s" % (entry["vmid"], entry.get("name", "")))
            continue
        require_ours(current)
        confirmed.append(current)
    failures = []
    for entry in confirmed:
        try:
            purge_vm(cfg, api, entry["vmid"], current=entry["_current"])
        except VmError as exc:
            # Keep going: stopping here would leave the rest of a scenario
            # standing, which is the state this verb exists to avoid.
            failures.append("%d: %s" % (entry["vmid"], exc))
            continue
        print("destroyed %d %s" % (entry["vmid"], entry["name"]))
    if not confirmed:
        print("nothing to destroy")
    if failures:
        raise Infra("could not destroy " + "; ".join(failures))
    return 0


def expired(entry: dict, now: int) -> bool:
    ttl = tag_value(tags_of(entry), "ttl-")
    return bool(ttl) and ttl.isdigit() and int(ttl) < now


def reap_lane(cfg: Config, api: Api, lane: str | None, dry_run: bool = False) -> list:
    """Destroy our expired VMs. `lane=None` means every lane."""
    now = int(time.time())
    doomed = []
    for entry in pool_vms(cfg, api):
        tags = tags_of(entry)
        # Templates never carry `ah`, but say it out loud: a reaper that eats a
        # template takes every linked clone's backing store with it.
        if OURS not in tags or entry.get("template"):
            continue
        if lane is not None and tag_value(tags, "lane-", "main") != lane:
            continue
        if expired(entry, now):
            doomed.append(entry)
    if dry_run:
        return doomed
    taken = []
    for entry in doomed:
        # Re-read: the listing is a cache, and `run --extend` may have renewed
        # this very lease a second ago — for exactly the reason it was expiring.
        current = fresh_entry(cfg, api, entry["vmid"])
        if current is None:
            continue  # someone else got there first; the sweep goes on
        tags = tags_of(current)
        # `ah` and `template` again, not only the ttl: during a bake the fresh
        # clone becomes a template while the resource list still shows it as a
        # tagged VM whose lease ran out mid-bake. This line is what keeps the
        # reaper off a brand new template.
        if OURS not in tags or current["template"] or not expired(current, int(time.time())):
            continue
        purge_vm(cfg, api, entry["vmid"], current=current["_current"])
        taken.append(entry)
    return taken


def verb_reap(cfg: Config, api: Api, args) -> int:
    lane = None if args.every_lane else current_lane()
    doomed = reap_lane(cfg, api, lane, dry_run=args.dry_run)
    for entry in doomed:
        print(
            "%s %d %s (lane %s)"
            % (
                "would reap" if args.dry_run else "reaped",
                entry["vmid"],
                entry.get("name", ""),
                tag_value(tags_of(entry), "lane-", "main"),
            )
        )
    if not doomed:
        print("nothing expired%s" % ("" if lane is None else " on lane " + lane))
    elif args.dry_run:
        print("(from the listing, without the fresh re-read the real sweep does)")
    return 0


def warm_vmids(path: str | None = None) -> set:
    """The VMIDs .vm/warm.env claims as long-lived. Written by the wrappers."""
    path = path or os.path.join(VM_STATE_DIR, "warm.env")
    kept = set()
    try:
        with open(path) as fh:
            for line in fh:
                key, _, value = line.partition("=")
                # Only the bare role slots hold a VMID. The file also carries
                # server_sid, server_ptok and friends, and a four-digit one of
                # those would quietly excuse a genuinely leaked VM.
                if "_" in key.strip():
                    continue
                value = value.strip()
                if value.isdigit():
                    kept.add(int(value))
    except OSError:
        pass
    return kept


def left_of(ttl: str, now: int) -> str:
    if not ttl or not ttl.isdigit():
        return "no ttl"
    seconds = int(ttl) - now
    if seconds < 0:
        return "EXPIRED"
    hours, rest = divmod(seconds, 3600)
    return "%dh%02dm" % (hours, rest // 60) if hours else "%dm" % (rest // 60)


def verb_list(cfg: Config, api: Api, args) -> int:
    now = int(time.time())
    lane_filter = tag_safe(args.lane) if args.lane else ""
    mine = current_lane()
    scenario = os.environ.get("AH_VM_SCENARIO", "")
    warm = warm_vmids()

    rows, strangers, leaks = [], 0, []
    for entry in sorted(pool_vms(cfg, api), key=lambda v: v["vmid"]):
        tags = tags_of(entry)
        if OURS not in tags or entry.get("template"):
            strangers += 1
            continue
        lane = tag_value(tags, "lane-", "main")
        row = {
            "vmid": entry["vmid"],
            "name": entry.get("name", ""),
            "role": tag_value(tags, "role-"),
            "lane": lane,
            "scenario": tag_value(tags, "sc-"),
            "status": entry.get("status", "?"),
            "ttl": left_of(tag_value(tags, "ttl-"), now),
            "ip": "",
        }
        if entry.get("status") == "running":
            try:
                row["ip"] = vm_ipv4(api, cfg["AH_PVE_NODE"], entry["vmid"])
            except VmError:
                pass  # best effort: a booting guest has no agent yet
        # A VM of our own lane that no warm slot and no running scenario claims
        # is a leak — the one thing this listing exists to catch. Checked before
        # --lane narrows the display: a filter is for reading, not for looking
        # away.
        claimed = entry["vmid"] in warm or (scenario and row["scenario"] == scenario)
        if lane == mine and not claimed:
            leaks.append(row)
        if lane_filter and lane != lane_filter:
            continue
        rows.append(row)

    if args.as_json:
        print(
            json.dumps(
                {"vms": rows, "untagged": strangers, "leaked": [r["vmid"] for r in leaks]}, indent=2
            )
        )
    else:
        for row in rows:
            print(
                "%(vmid)-5d %(name)-24s %(role)-9s lane=%(lane)-8s sc=%(scenario)-10s "
                "%(status)-8s %(ttl)-8s %(ip)s" % row
            )
        print("%d ours, %d not ours" % (len(rows), strangers))
    if leaks:
        raise Infra(
            "leaked on lane %s: %s — neither warm nor part of scenario %r"
            % (mine, ", ".join(str(r["vmid"]) for r in leaks), scenario)
        )
    return 0


def _stub(name):
    def verb(cfg, api, args):
        raise Usage("%s is not implemented yet" % name)

    return verb


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vm.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="verb", metavar="<verb>")

    doctor = sub.add_parser("doctor", help="check config, rights, templates and capacity")
    doctor.add_argument(
        "--roles", default="probe", help="comma-separated roles the capacity check must fit"
    )
    doctor.add_argument("--json", action="store_true", dest="as_json")

    clone = sub.add_parser("clone", help="clone a template into a tagged, running VM")
    clone.add_argument("--profile", required=True)
    clone.add_argument("--role", required=True)
    clone.add_argument("--lane")
    clone.add_argument("--scenario")
    clone.add_argument("--ttl", default="8h")
    clone.add_argument("--memory", type=int)
    clone.add_argument("--cores", type=int)
    clone.add_argument("--name")

    wait = sub.add_parser("wait", help="wait for guest agent, IP and ssh")
    wait.add_argument("vm")
    wait.add_argument("--timeout", type=int, default=WAIT_TIMEOUT)

    shell = sub.add_parser("ssh", help="ssh into a VM (interactive without a command)")
    shell.add_argument("vm")
    shell.add_argument("cmd", nargs="*")

    sync = sub.add_parser("sync", help="rsync the checkout onto a VM")
    sync.add_argument("vm")
    sync.add_argument("--no-delete", action="store_true")

    run = sub.add_parser("run", help="run a command in the synced checkout")
    run.add_argument("vm")
    run.add_argument("--sync", action="store_true")
    run.add_argument("--timeout", type=int)
    run.add_argument("--out")
    run.add_argument("--extend")
    run.add_argument("cmd", nargs="*")

    pull = sub.add_parser("pull", help="copy files off a VM")
    pull.add_argument("vm")
    pull.add_argument("glob")
    pull.add_argument("dir")

    snap = sub.add_parser("snap", help="take a snapshot")
    snap.add_argument("vm")
    snap.add_argument("name")
    snap.add_argument("--ram", action="store_true")

    rollback = sub.add_parser("rollback", help="roll a VM back to a snapshot")
    rollback.add_argument("vm")
    rollback.add_argument("name")
    rollback.add_argument("--start", action="store_true")

    delsnap = sub.add_parser("delsnap", help="delete a snapshot")
    delsnap.add_argument("vm")
    delsnap.add_argument("name")

    destroy = sub.add_parser("destroy", help="stop and purge VMs we own")
    destroy.add_argument("vm", nargs="*")
    destroy.add_argument("--scenario")
    destroy.add_argument("--lane")
    destroy.add_argument("--role")

    reap = sub.add_parser("reap", help="destroy expired VMs")
    reap.add_argument("--all", action="store_true", dest="every_lane")
    reap.add_argument("--dry-run", action="store_true")

    listing = sub.add_parser("list", help="show our VMs and their leases")
    listing.add_argument("--json", action="store_true", dest="as_json")
    listing.add_argument("--lane")

    bake = sub.add_parser("bake", help="build a template from the base image")
    bake.add_argument("--profile", required=True)
    bake.add_argument("--from", dest="from_tag")

    return parser


VERB_TABLE = {name: _stub(name) for name in VERBS}
VERB_TABLE["doctor"] = verb_doctor
VERB_TABLE["clone"] = verb_clone
VERB_TABLE["wait"] = verb_wait
VERB_TABLE["ssh"] = verb_ssh
VERB_TABLE["sync"] = verb_sync
VERB_TABLE["run"] = verb_run
VERB_TABLE["pull"] = verb_pull
VERB_TABLE["snap"] = verb_snap
VERB_TABLE["rollback"] = verb_rollback
VERB_TABLE["delsnap"] = verb_delsnap
VERB_TABLE["destroy"] = verb_destroy
VERB_TABLE["reap"] = verb_reap
VERB_TABLE["list"] = verb_list


def auto_reap(cfg: Config, api: Api, verb: str) -> None:
    """Every verb that changes something sweeps its own lane afterwards.

    This is the whole reaper: no timer, no cron on the hypervisor, nothing that
    runs without someone asking for it — and still no expired VM survives a
    working day. `list` and `doctor` are exempt because a report must not have
    side effects. A sweep that fails is reported and swallowed: it is not the
    caller's result.
    """
    if verb in ("list", "doctor") or os.environ.get("AH_VM_NO_AUTOREAP") == "1":
        return
    try:
        for entry in reap_lane(cfg, api, current_lane()):
            sys.stderr.write(
                "vm.py: reaped expired %d %s\n" % (entry["vmid"], entry.get("name", ""))
            )
    except VmError as exc:
        sys.stderr.write("vm.py: the lane sweep did not finish: %s\n" % exc)


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.verb:
        parser.print_help()
        return 2
    try:
        cfg = Config.load()
        api = Api(cfg)
        interrupted = False
        try:
            return VERB_TABLE[args.verb](cfg, api, args) or 0
        except KeyboardInterrupt:
            interrupted = True
            raise
        finally:
            # Also after a failure: a `clone` refused for capacity is exactly
            # the moment the expired VMs eating that capacity must go, or the
            # next attempt fails the same way.
            if not interrupted:
                auto_reap(cfg, api, args.verb)
    except VmError as exc:
        sys.stderr.write("vm.py: %s\n" % exc)
        return exc.code
    except KeyboardInterrupt:
        sys.stderr.write("vm.py: interrupted\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
