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
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Time bounds. Every one of them exists because something hung once: an
# unbounded HTTP call, a UPID poll that never ended, a lock that never cleared.
HTTP_TIMEOUT = 30  # seconds per request
TASK_POLL_MIN = 1.0  # UPID poll backoff 1 s -> 5 s
TASK_POLL_MAX = 5.0
TASK_LIMIT = 300  # clone/snapshot/destroy tasks; a bake's `run` has its own
LOCK_RETRY_LIMIT = 60  # window for "can't lock file"; measured collisions clear in ~12 s
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
    "AH_VM_MAX": "3",
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
        node = api.request("GET", "/nodes/%s/status" % cfg["AH_PVE_NODE"])
        free_mb = (node.get("memory", {}).get("free") or 0) // 1024**2
        # What our VMs may still take, not what they were configured for: a
        # running VM's touched RAM is already out of `free`, so charging its full
        # maxmem again would refuse clones the node can carry — while charging
        # nothing would hand out the 5 GB a freshly booted 6 GB box has not
        # claimed yet. For a stopped VM `mem` is 0 and the term is its maxmem.
        # `mem` rides the same lagging resource list as the tags do, which is
        # good enough for a guard rail and not a promise.
        ours = [v for v in vms() if OURS in tags_of(v) and not v.get("template")]
        owed = [(v, max(0, (v.get("maxmem") or 0) - (v.get("mem") or 0)) // 1024**2) for v in ours]
        owed_mb = sum(mb for _, mb in owed)
        need_mb = sum(role_shape(profiles, r)["memory"] for r in roles)
        spare = free_mb - RESERVE_MB - owed_mb - need_mb
        detail = "%d MiB free - %d reserve - %d owed by ours - %d for %s = %d MiB" % (
            free_mb,
            RESERVE_MB,
            owed_mb,
            need_mb,
            ",".join(roles) or "nothing",
            spare,
        )
        if spare < 0 and owed_mb:
            detail += " (ours: %s)" % ", ".join(
                "%d %s %d MiB" % (v["vmid"], v.get("name", "?"), mb) for v, mb in owed if mb
            )
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
    shell.add_argument("cmd", nargs=argparse.REMAINDER)

    sync = sub.add_parser("sync", help="rsync the checkout onto a VM")
    sync.add_argument("vm")
    sync.add_argument("--no-delete", action="store_true")

    run = sub.add_parser("run", help="run a command in the synced checkout")
    run.add_argument("vm")
    run.add_argument("--sync", action="store_true")
    run.add_argument("--timeout", type=int)
    run.add_argument("--out")
    run.add_argument("--extend")
    run.add_argument("cmd", nargs=argparse.REMAINDER)

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


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.verb:
        parser.print_help()
        return 2
    try:
        cfg = Config.load()
        api = Api(cfg)
        return VERB_TABLE[args.verb](cfg, api, args) or 0
    except VmError as exc:
        sys.stderr.write("vm.py: %s\n" % exc)
        return exc.code
    except KeyboardInterrupt:
        sys.stderr.write("vm.py: interrupted\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
