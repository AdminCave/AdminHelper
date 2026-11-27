# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The monitoring part of upgrade_path_test.sh (R-1637): switched-off checks and ignore
lists of the previous release become exceptions on the upgrade, without a visible change.

    upgrade_exceptions.py seed <base> <token> <server_id> <state.json>
    upgrade_exceptions.py checks <base> <token> <server_id> <out.json>
    upgrade_exceptions.py dry-run <state.json> <report.json>
    upgrade_exceptions.py after <base> <token> <server_id> <state.json> <checks.json>
    upgrade_exceptions.py restored <base> <token> <server_id> <state.json> <checks.json>
    upgrade_exceptions.py normalize <dump.sql>

Every assertion is one line, "ok <what>" or "FAIL <what>", which the shell counts. Exit
0 means every assertion ran; anything else (an HTTP error, a missing file) means the
step could not be checked, and the shell counts that as a failure of its own.

The expectations are those of app.exception_scope: a name is masked ([*], [[]), a
service entry stays the glob it is, a VMID becomes its number, a VMID as a string stays
in the config.
"""

import json
import sys
import time
import urllib.error

from e2e_api import _call

# Role -> what the previous release gets: the check (manual) and, after the migration,
# its exceptions (kind, pattern, unstable) and the config entries that stay.
MANUAL = {
    "agent": {
        "check_type": "agent_resources",
        "config": {"ignore_mounts": ["/mnt/backup*", "/srv/data[1]"]},
    },
    "service": {
        "check_type": "service_process",
        "config": {"mode": "auto", "ignore": ["cron*", "app[1].service"]},
    },
    "smart": {"check_type": "smart_health", "config": {"ignore_devices": ["/dev/sdb"]}},
    "docker": {
        "check_type": "docker_health",
        "config": {"ignore_containers": ["watchtower", "test-*"]},
    },
    "backup": {"check_type": "proxmox_backup", "config": {"exclude_vmids": [101, 205, "999"]}},
    "ping": {"check_type": "ping", "config": {"target": "192.0.2.10"}, "enabled": False},
}
TEMPLATE_DEFS = [
    {
        "name": "upgrade-tpl-agent",
        "check_type": "agent_resources",
        "config": {"ignore_mounts": ["/boot/efi"]},
    },
    {"name": "upgrade-tpl-ping", "check_type": "ping", "config": {"target": "192.0.2.11"}},
]
TPL_AGENT_CONFIG = {"ignore_mounts": ["/boot/efi", "/mnt/usb"]}

# Per role: the report row the dry run must give (exceptions as a set of
# (kind, pattern, unstable); config only the keys that change).
EXPECTED = {
    "agent": {
        "skip": False,
        "exceptions": {("mount", "/mnt/backup[*]", False), ("mount", "/srv/data[[]1]", False)},
        "config": {"ignore_mounts": [["/mnt/backup*", "/srv/data[1]"], []]},
        "fallback": False,
    },
    "service": {
        "skip": False,
        "exceptions": {("service", "cron*", False), ("service", "app[1].service", False)},
        "config": {"ignore": [["cron*", "app[1].service"], []]},
        "fallback": False,
    },
    "smart": {
        "skip": False,
        "exceptions": {("disk", "/dev/sdb", True)},
        "config": {"ignore_devices": [["/dev/sdb"], []]},
        "fallback": False,
    },
    "docker": {
        "skip": False,
        "exceptions": {("container", "watchtower", True), ("container", "test-[*]", True)},
        "config": {"ignore_containers": [["watchtower", "test-*"], []]},
        "fallback": False,
    },
    "backup": {
        "skip": False,
        "exceptions": {("guest-backup", "101", False), ("guest-backup", "205", False)},
        "config": {"exclude_vmids": [[101, 205, "999"], ["999"]]},
        "fallback": False,
    },
    "ping": {"skip": True, "exceptions": set(), "enabled": [False, True], "fallback": False},
    "tpl_agent": {
        "skip": False,
        "exceptions": {("mount", "/mnt/usb", False)},
        "config": {"ignore_mounts": [["/boot/efi", "/mnt/usb"], ["/boot/efi"]]},
        "marks": [["config"], []],
        "fallback": True,
    },
    "tpl_ping": {
        "skip": True,
        "exceptions": set(),
        "enabled": [False, True],
        "marks": [["enabled"], []],
        "fallback": False,
    },
}
# The list key of each check type with one: the API shows it composed, sorted.
LIST_KEYS = {
    "agent_resources": "ignore_mounts",
    "service_process": "ignore",
    "smart_health": "ignore_devices",
    "docker_health": "ignore_containers",
    "proxmox_backup": "exclude_vmids",
}
# The fields of GET /checks a migration or a restore must keep.
KEPT = ("id", "name", "checkType", "config", "enabled", "templateId", "overriddenFields")


def say(ok, what):
    print(("ok   " if ok else "FAIL ") + what, flush=True)


def api(base, token, method, path, body=None):
    # Right after a start the gateway and the server answer before the monitoring
    # service does, and the server's proxy says 502 until then. Only a GET waits: a
    # 502 can also follow a write the service received, and a repeated POST would
    # seed a second check.
    deadline = time.monotonic() + (120 if method == "GET" else 0)
    while True:
        try:
            return _call(base, token, method, "/api/monitoring" + path, body)
        except urllib.error.HTTPError as exc:
            if exc.code in (502, 503) and time.monotonic() < deadline:
                time.sleep(2)
                continue
            detail = exc.read()[:300].decode(errors="replace")
            raise SystemExit(f"{method} /api/monitoring{path}: HTTP {exc.code} {detail}") from None
        except (urllib.error.URLError, ConnectionError) as exc:
            if time.monotonic() < deadline:
                time.sleep(2)
                continue
            raise SystemExit(f"{method} /api/monitoring{path}: {exc}") from None


def list_checks(base, token, server_id):
    return api(base, token, "GET", f"/checks?server_id={server_id}&limit=1000")


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def dump(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)


def seed(base, token, server_id, state_path):
    say(list_checks(base, token, server_id) == [], "no monitoring check on the fresh server yet")
    state = {}
    for role, spec in MANUAL.items():
        body = {
            "server_id": server_id,
            "name": f"upgrade-{role}",
            "check_type": spec["check_type"],
            "config": spec["config"],
            "enabled": spec.get("enabled", True),
        }
        state[role] = api(base, token, "POST", "/checks", body)["id"]
    tpl = api(
        base,
        token,
        "POST",
        "/templates",
        {"name": "upgrade-exceptions", "check_definitions": TEMPLATE_DEFS},
    )
    state["template"] = tpl["id"]
    assign = {"server_id": server_id, "hostname": "upgrade.local", "server_name": "upgrade-srv"}
    created = api(base, token, "POST", f"/templates/{tpl['id']}/assign", assign)["checksCreated"]
    by_type = {
        c["checkType"]: c["id"]
        for c in list_checks(base, token, server_id)
        if c["id"] in created and c.get("templateId") == tpl["id"]
    }
    state["tpl_agent"] = by_type.get("agent_resources")
    state["tpl_ping"] = by_type.get("ping")
    if not state["tpl_agent"] or not state["tpl_ping"]:
        raise SystemExit(f"the template made no agent and ping check: {by_type}")
    api(base, token, "PUT", f"/checks/{state['tpl_agent']}", {"config": TPL_AGENT_CONFIG})
    api(base, token, "PUT", f"/checks/{state['tpl_ping']}", {"enabled": False})
    dump(state_path, state)

    # Read back on the release itself: an assertion after the upgrade is worth only as
    # much as the state it starts from.
    shown = {c["id"]: c for c in list_checks(base, token, server_id)}
    for role, spec in MANUAL.items():
        c = shown.get(state[role], {})
        say(
            c.get("config") == spec["config"] and c.get("enabled") == spec.get("enabled", True),
            f"seeded {role} ({spec['check_type']}) reads back on the release",
        )
    agent, ping = shown.get(state["tpl_agent"], {}), shown.get(state["tpl_ping"], {})
    say(
        agent.get("config") == TPL_AGENT_CONFIG and agent.get("overriddenFields") == ["config"],
        "template check with an own entry carries the mark config on the release",
    )
    say(
        ping.get("enabled") is False and ping.get("overriddenFields") == ["enabled"],
        "switched-off template check carries the mark enabled on the release",
    )


def checks(base, token, server_id, out_path):
    rows = list_checks(base, token, server_id)
    dump(out_path, rows)
    print(f"{len(rows)} check(s) of server {server_id} saved")


def dry_run(state_path, report_path):
    state = load(state_path)
    report = load(report_path)
    say(report.get("migrated") is False, "dry run: the release is not yet migrated")
    rows = {r["check_id"]: r for r in report.get("checks", [])}
    role_of = {state[role]: role for role in EXPECTED}
    for role, want in EXPECTED.items():
        row = rows.get(state[role])
        if row is None:
            say(False, f"dry run lists {role} ({state[role]})")
            continue
        got = {(x["kind"], x["pattern"], x["unstable"]) for x in row["exceptions"]}
        problems = []
        if got != want["exceptions"]:
            problems.append(f"exceptions {sorted(got)} != {sorted(want['exceptions'])}")
        for field in ("skip", "fallback"):
            if row.get(field) != want[field]:
                problems.append(f"{field} {row.get(field)} != {want[field]}")
        for field in ("config", "enabled", "marks"):
            if row.get(field) != want.get(field):
                problems.append(f"{field} {row.get(field)} != {want.get(field)}")
        if "own_values" in row:
            problems.append(f"own_values {row['own_values']}")
        say(
            not problems,
            f"dry run: {role} as expected" + (f" ({'; '.join(problems)})" * bool(problems)),
        )
    stray = sorted(set(rows) - set(role_of))
    say(not stray, f"dry run touches no other check{f' ({stray})' if stray else ''}")
    skips = {role_of.get(cid, cid) for cid, r in rows.items() if r.get("skip")}
    say(
        skips == {"ping", "tpl_ping"},
        f"dry run: skip exactly for the two checks that are off ({sorted(skips)})",
    )


def _same_check(before, after, check_type):
    """The check as the API showed it before, with the list compared as a set: the API
    sorts the composed list, the order of the exceptions says nothing."""
    key = LIST_KEYS.get(check_type)
    b, a = dict(before.get("config") or {}), dict(after.get("config") or {})
    if key is not None:
        bl, al = b.pop(key, []), a.pop(key, [])
        if sorted(map(json.dumps, bl)) != sorted(map(json.dumps, al)):
            return f"{key} {bl} -> {al}"
    if a != b:
        return f"config {before.get('config')} -> {after.get('config')}"
    return None


def after(base, token, server_id, state_path, checks_path):
    state = load(state_path)
    before = {c["id"]: c for c in load(checks_path)}
    now = {c["id"]: c for c in list_checks(base, token, server_id)}
    say(set(now) == set(before), f"every check is still there ({len(before)} -> {len(now)})")

    for role, want in EXPECTED.items():
        cid = state[role]
        rows = api(base, token, "GET", f"/exceptions?check_id={cid}")
        got = {
            (x["objectKind"], x["objectPattern"], x["unstable"])
            for x in rows
            if x["effect"] == "no_rating"
        }
        skips = [x for x in rows if x["effect"] == "skip"]
        problems = []
        if got != want["exceptions"]:
            problems.append(f"no_rating {sorted(got)} != {sorted(want['exceptions'])}")
        if len(skips) != int(want["skip"]):
            problems.append(f"{len(skips)} skip exception(s)")
        for x in rows:
            scope = "check" if x["effect"] == "skip" else "object"
            if (x["origin"], x["scopeKind"], x["durationKind"], x["enabled"]) != (
                "migration",
                scope,
                "permanent",
                True,
            ):
                problems.append(
                    f"{x['id']}: origin {x['origin']} scope {x['scopeKind']}"
                    f" {x['durationKind']} enabled {x['enabled']}"
                )
        say(
            not problems,
            f"exceptions of {role} after the upgrade"
            + (f" ({'; '.join(problems)})" * bool(problems)),
        )

        b, a = before.get(cid, {}), now.get(cid, {})
        diff = _same_check(b, a, b.get("checkType"))
        say(
            diff is None,
            f"GET /checks shows {role} with the list it had" + (f" ({diff})" * bool(diff)),
        )
        say(
            a.get("enabled") == b.get("enabled"),
            f"{role} stays enabled={b.get('enabled')} ({a.get('enabled')})",
        )
    for role in ("tpl_agent", "tpl_ping"):
        marks = now.get(state[role], {}).get("overriddenFields")
        say(marks == [], f"{role}: the mark of the migrated value is gone ({marks})")


def restored(base, token, server_id, state_path, checks_path):
    state = load(state_path)
    before = {c["id"]: c for c in load(checks_path)}
    now = {c["id"]: c for c in list_checks(base, token, server_id)}
    say(
        set(now) == set(before),
        f"the release shows the checks it had ({len(before)} -> {len(now)})",
    )
    for role in EXPECTED:
        cid = state[role]
        b = {k: before.get(cid, {}).get(k) for k in KEPT}
        a = {k: now.get(cid, {}).get(k) for k in KEPT}
        say(
            a == b,
            f"{role} on the release after the way back as before the update"
            + (f" ({b} -> {a})" * (a != b)),
        )


def normalize(path):
    """A pg_dump made comparable: no per-run \\restrict key, no comments, no blank lines,
    the rows of each COPY block sorted (pg_dump writes them in heap order, which an
    UPDATE changes without changing the data)."""
    out, rows = [], None
    with open(path, encoding="utf-8") as fh:
        for line in fh.read().splitlines():
            if rows is not None:
                if line == "\\.":
                    out.extend(sorted(rows))
                    out.append(line)
                    rows = None
                else:
                    rows.append(line)
                continue
            if (
                not line.strip()
                or line.startswith("--")
                or line.startswith(("\\restrict", "\\unrestrict"))
            ):
                continue
            out.append(line)
            if line.startswith("COPY ") and line.endswith("FROM stdin;"):
                rows = []
    if rows is not None:
        raise SystemExit(f"{path}: a COPY block without its end")
    sys.stdout.write("\n".join(out) + "\n")


COMMANDS = {
    "seed": (seed, 4),
    "checks": (checks, 4),
    "dry-run": (dry_run, 2),
    "after": (after, 5),
    "restored": (restored, 5),
    "normalize": (normalize, 1),
}

if __name__ == "__main__":
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if cmd not in COMMANDS or len(args) != COMMANDS[cmd][1]:
        raise SystemExit(__doc__)
    COMMANDS[cmd][0](*args)
