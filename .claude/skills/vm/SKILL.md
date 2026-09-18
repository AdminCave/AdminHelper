---
name: vm
description: Lease, drive and destroy ephemeral Proxmox VMs for AdminHelper's heavy test tiers with scripts/vm/vm.py — clone/wait/ssh/sync/run/pull/snap/rollback/destroy/reap/list/bake plus the warm/iter/reap/bake wrappers. Use to warm a box, iterate on it, inspect a kept box after a red run, sweep leases, check what is running, or bake a template. Not for running suites — that is /test.
---

# VMs mit `vm.py`

Alles Schwere läuft auf ephemeren Proxmox-VMs; die Dev-Box hat weder Docker noch Display.
`scripts/vm/vm.py` ist das ganze Werkzeug (Python-3-Stdlib, keine Abhängigkeit), die vier
Wrapper darüber sind der Alltag. **Nichts startet von selbst** — jeder Klon, jedes Bake,
jeder Lauf ist ein Befehl, den jemand tippt.

## Der Alltag: vier Wrapper

| Befehl | Was er tut |
|---|---|
| `bash scripts/vm/warm.sh <desktop\|server\|pond>` | einmal klonen + hydrieren, VMID nach `.vm/warm.env`; idempotent |
| `bash scripts/vm/iter.sh <layer> [--strict] [--only …] [--step …]` | `run.sh <layer>` auf der warmen Box, Artefakte nach `.ah-out/` |
| `bash scripts/vm/iter.sh --cmd '<befehl>'` | ein einzelner Befehl auf der warmen Box (das `Verify:` einer Task) |
| `bash scripts/vm/iter.sh --desktop [spec…]` | die echte Tauri-GUI auf der Desktop-Box gegen die Server-Box |
| `bash scripts/vm/reap.sh [--lane l] [--all]` | warme Boxen zerstören, Abgelaufenes wegräumen, `.vm/warm.env` leeren |
| `bash scripts/vm/bake.sh <linux-full\|linux-server>` | neues Template bauen (~45 min, **provisioniert eine VM**) |

`iter.sh` verlängert bei jedem Lauf die Frist der warmen Box; eine vergessene Box stirbt
nach Ablauf beim nächsten `vm.py`-Aufruf. Nach einem roten Lauf **bleibt die Box stehen** —
die Ausgabe liegt in `.ah-out/last.out.log`, rein kommt man mit `vm.py ssh <vmid>`.

## Die Verben darunter

```
python3 scripts/vm/vm.py <verb> [options]
```

`doctor` (Konfiguration, Rechte, Templates, Kapazität — `--roles a,b,c` rechnet den echten
RAM-Bedarf) · `clone --profile <p> --role <r> [--lane|--scenario|--ttl|--memory|--cores]` ·
`wait <vm>` · `ssh <vm> [cmd…]` · `sync <vm>` · `run <vm> [--sync] [--timeout s] [--out dir]
[--extend 8h] -- <cmd>` · `pull <vm> <glob> <dir>` · `snap|rollback|delsnap <vm> <name>` ·
`destroy <vm…> | --scenario s | --lane l | --role r` · `reap [--all] [--dry-run]` ·
`list [--json] [--lane l]` · `bake --profile <p>`.

Eine VM wird über ihre **VMID** angesprochen (auch über den Namen). Profile stehen in
`scripts/vm/profiles.json`: `linux-full` (Toolchains, Docker, Caches — die schweren Tiers),
`linux-server` (Server-/Agent-Rollen, kein Desktop), `base-ubuntu`/`base-debian` (die
Cloud-Images, aus denen gebacken wird). Die Rolle bestimmt RAM und Kerne.

**Zustand liegt auf dem Hypervisor**, als Tags: `ah;role-…;lane-…;sc-…;ttl-<epoch>;tpl-…`.
Lokal liegt nur `.vm/warm.env` (welche VMID gerade warm ist) und `.vm/lane`. Konfiguration
und Token kommen ausschließlich aus `.claude/settings.local.json` → `env` (gitignored);
eine echte Umgebungsvariable gewinnt.

## Exit-Codes

| Code | Bedeutung |
|---|---|
| 0 | ok |
| 1 | der Befehl auf der Box ist rot — ein Testergebnis, kein Werkzeugfehler |
| 2 | Aufruf falsch, **oder** die VM gehört uns nicht (Verweigerung) |
| 74 | Infrastruktur: API, Kapazität, keine IP, kein SSH, fehlendes Recht |

74 ist die Klasse, die `heavy.sh` als `infra` wegsortiert statt als roten Test zu melden.
Die Wrapper reichen den Code unverändert durch.

## Regeln

- **Nie ein Template löschen.** `destroy` verweigert Templates; alte Templates löscht Kevin
  von Hand (`vm.py doctor` listet sie). Ein `bake` templatet immer einen frischen Klon.
- **Nie eine VM außerhalb des Pools anfassen.** Jede Operation verweigert eine VM ohne den
  Tag `ah` — fail-closed, weil eine VMID vier Ziffern hat und ein Tippfehler ein Tastendruck ist.
- **Nach jedem Lauf `python3 scripts/vm/vm.py list`.** Eine geleakte VM ist ein Fehler, kein
  Detail; `list` endet mit Exit 74, wenn auf dieser Lane etwas läuft, das niemand beansprucht.
- **`bake` nur bewusst** — es provisioniert eine VM und läuft ~45 min. Kein Bestandteil einer
  Schleife.
- **Parallele Lanes teilen nichts.** `lane.sh new <slug>` schreibt `.vm/lane`; `reap` und
  `destroy` arbeiten auf der eigenen Lane, `--all` erweitert nur den Ablauf-Sweep.
- **Suiten fährt `/test`, nicht dieser Skill.** Hier steht, wie man an eine Box kommt.
