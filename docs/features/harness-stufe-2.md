<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness Stufe 2 — Proxmox-VM-Skill `vm.py` (Linux) und crabbox-Rückbau

Roadmap-Zeile R-0006 · Quelle: privates Roadmap-Dokument §Stufe 2 und §11, Entscheidungen D11/D17/D19/D20 ·
Stand 2026-09-15. Zwei Ledger: `tasks/vm-core.md` (2a, das Werkzeug) und `tasks/vm-migration.md` (2b, der Umzug).

## Problem / Motivation

Die schweren Suiten laufen auf ephemeren Proxmox-VMs, die heute das externe Binary `crabbox` least. Es liefert
genau vier Dinge (Vollklon, SSH-Lease, rsync-Sync, Stop) und hat in den letzten Wochenläufen drei eigene
Fehlerklassen beigesteuert, die `heavy.sh` als `infra` wegsortieren muss: verlorene Leases (Keep-Alive-Rennen,
Retry 3/3 in `crabbox_multibox.sh`), abgebrochene Setups („workspace owner release failed") und abgebrochene
Syncs („rsync failed: … ambiguous remote state"). Ein Vollklon dauert ~11 min, ein Capstone mit sieben Rollen
klont seriell über eine Stunde. Snapshots, Rollback, Lease-Wahrheit auf dem Hypervisor, ein Reaper ohne Timer
und Windows-Vorbereitung kann crabbox nicht. Alles Weitere (Bootstrap, Rollen-Skripte, `run.sh`, `heavy.sh`)
hat das Repo längst selbst gebaut — crabbox ist nur noch die dünne Schicht dazwischen, und die ist die unzuverlässigste.

**Was die Planung live verifiziert hat (2026-09-15, Wegwerf-Klone im Pool, danach zerstört, kein Rest):**

| Frage | Ergebnis |
|---|---|
| Linked Clone auf dem LVM-thin-Storage | `POST …/clone` mit `full=0` → Task `OK` in **2 s** (statt ~11 min Vollklon) |
| Guest-Agent im Fat-Template | `agent/ping` nach **27 s**, IPv4 aus `agent/network-get-interfaces` |
| Guest-Agent im Basis-Cloud-Image | ebenfalls vorhanden (`ping` nach 26 s) — Bakes aus der Basis brauchen keine Sonderbehandlung |
| SSH-Key per cloud-init auf den Klon | `PUT config sshkeys=<urlencoded>` vor dem Start → Login als `ciuser` des Templates beim ersten Versuch |
| Snapshot / Rollback auf dem Linked Clone | je **2 s**; direkt nach `rollback --start` hält der Start das Config-Lock noch kurz (`can't lock file … got timeout`) |
| Tags | `pve-tag-list` mit `;` angenommen, PVE sortiert sie alphabetisch zurück — als Menge lesen, nie als Reihenfolge |
| Rechte des Tokens | ACL-Set wie in §11.2 reicht für alle Verben; fremde VM → 403; `DELETE` mit Body → 501 („Unexpected content"), Parameter müssen in die Query |
| SSH-Port | 22 (OpenSSH 9.6); crabbox' Port 2222 ist auf den Templates geschlossen |
| Caches im Fat-Template | `~/.cargo` 693 MB und `~/go` im Home des Gast-Users; **kein** Quellbaum im Home — crabbox' Sync-Ziel lag außerhalb, die `target/`-/`node_modules/`-Caches sind für `vm.py` erst nach dem Rebake (2a T8) wieder warm |
| TLS | Root-CA ohne `keyUsage`; Python 3.13 verlangt es unter `VERIFY_X509_STRICT` → Flag löschen, sonst voll gegen `AH_PVE_CA` verifizieren; die URL muss einen Namen aus dem Zertifikats-SAN tragen |

## Ziel & Nicht-Ziele

**Ziel (2a).** `scripts/vm/vm.py` — Python-3-Stdlib, ~700 Zeilen, ohne Abhängigkeit, LLM-frei — mit den Verben
`doctor clone wait ssh sync run pull snap rollback delsnap destroy reap list bake`, hermetisch getestet gegen
aufgezeichnete Antworten, live verifiziert im Pool. Fehlerklassen 0/1/2/74 wie in §11.2. Jede Operation
verweigert VMs ohne Tag `ah` (fail-closed). Templates werden per Tag aufgelöst. Dazu `scripts/vm/lib.sh`
(Shell-Seite: `vm_load_env`, `vm_marker`, `vm_build_agent_deb`, `warm_get/set/clear` auf `.vm/warm.env`,
Lane aus `.vm/lane`) und `scripts/vm/rsync-exclude.txt`. 2a legt das Werkzeug **neben** crabbox — nichts
Bestehendes ändert sein Verhalten.

**Ziel (2b).** Die Wrapper wechseln auf `vm.py` bei **unveränderter Aufruf-Semantik**: `scripts/vm/{warm,iter,reap,bake}.sh`,
`scripts/tests/multibox.sh`, `heavy.sh` ändert nur Pfade und verliert Marker, die crabbox-spezifisch waren.
Ein Sweep entfernt crabbox aus Repo, Skills, Allowlist und Doku (`git grep -il crabbox` → nur CHANGELOG).
Der nächste Wochenlauf liefert dieselben Summary-Zeilen wie der letzte auf crabbox — das ist der Beweis.

**Nicht-Ziele.** Windows-Template, Windows-Rollen, `wdio.windows.conf.js` (Stufe 12; 2a hält nur die
Profil-Tabelle offen). Kein `proxmoxer`, kein `pvesh`-Wrapper, kein Provider-Abstraktion für andere Hypervisoren.
Kein hypervisor-seitiger Cron-Reaper (Frage 12, siehe offene Fragen). Keine parallelen Klon-Submits
(erst nach I/O-Messung). Keine `templates --prune`, `touch`, `lease`, `idle`-Verben (Skeptiker 3 #19).
Kein Runner-Token (Stufe 4). Keine Änderung an den ~800 Zeilen Rollen-Skripten außer Umbenennung und `. scripts/vm/lib.sh`.

## Betroffene Komponenten & Dateien

**Neu (2a):** `scripts/vm/vm.py`, `scripts/vm/lib.sh`, `scripts/vm/rsync-exclude.txt`, `scripts/vm/tests/test_vm.py`,
`scripts/vm/tests/fixtures/*.json` (aufgezeichnete, bereinigte API-Antworten), `scripts/vm/profiles.json`
(Profil → Template-Tag, Bootstrap-Profil, RAM/CPU je Rolle). Berührt: `scripts/tests/run.sh` (Lint-/Unit-Schritt
`vm-pytest`, shellcheck-Glob), `.github/workflows/ci.yml` (shellcheck-Glob im Job `ops-scripts`),
`scripts/tests/crabbox_bootstrap.sh` (nur: `qemu-guest-agent` in die Paketliste, damit jedes Bake ihn sicher hat),
`DEVELOPMENT.md`, `CHANGELOG.md`.

**Umzug (2b):** die Tabelle in §11.4 des Roadmap-Dokuments, konkret: `scripts/tests/crabbox_lib.sh` (ersetzt),
`crabbox_warm.sh`/`crabbox_iter.sh` (neu als `scripts/vm/warm.sh`, `iter.sh`), `crabbox_reap.sh`/`crabbox_bake.sh`
(→ `scripts/vm/reap.sh`, `bake.sh`), `crabbox_multibox.sh` (→ `scripts/tests/multibox.sh`), `crabbox_bootstrap.sh`
(→ `scripts/vm/bootstrap_linux.sh`), `crabbox_debug.sh` (→ `scripts/tests/box_debug.sh`), sieben Rollen-Skripte
(→ `scripts/tests/box_*.sh`), `.crabbox.yaml` und `.github/workflows/crabbox.yml` und `.agents/skills/crabbox/`
(gelöscht), `heavy.sh` + `heavy_test.sh` (Wrapper-Namen, Marker, Shims), `crabbox_iter_flags_test.sh`
(→ `iter_flags_test.sh`), `session_status_test.sh`/`verify_test.sh`/`run_flags_test.sh` (Pfade), `run.sh:149`
und `apps/desktop/e2e/wdio.conf.js:22` und `scripts/dev/verify.sh:69` und `scripts/dev/tree-hash.sh:31-33`
(`.crabbox-out` → `.ah-out`), `scripts/dev/lane.sh:68-90`, `scripts/dev/hooks/session-status.sh:123,153`,
`.gitignore`, `.claude/settings.json` (13 Einträge raus, 4 rein), `.claude/skills/vm/SKILL.md` (neu),
`.claude/skills/test/SKILL.md` (Neufassung), `.claude/skills/feature-build|feature-plan|feature-review/SKILL.md`,
`.claude/rules/testing.md`, `.claude/rules/release.md`, `CLAUDE.md` §8 (und Pool-Name `adminhelper-ci`),
`AUTONOMOUS.md`, `tasks/README.md`, `DEVELOPMENT.md` (Abschnitte ab Zeile ~470), `docs/developer/cicd.html` DE+EN,
`docs/index.html` DE+EN (Changelog-Spiegel bleibt), `apps/desktop/e2e/README.md`, drei Kommentare in
`apps/desktop/e2e/test/specs/*.live.js`, `scripts/tests/desktop_e2e_misc.sh`, `sse_push_e2e.sh`, `lib_e2e_stack.sh`,
`apps/agent/build-deb.sh`, `apps/ca-issuer/tests/conftest.py`, `.github/workflows/release.yml:113`,
`ci.yml` `frp-consistency` (Pfad des Bootstraps). Zählung der Exploration: 382 Fundstellen außerhalb der
`crabbox_*.sh`-Familie, davon 173 in der Familie selbst; `git grep -il crabbox` ist das Verify.

## Datenmodell / API / Migrationen

Keine DB, keine Migration, kein Produkt-Endpunkt. Zustand liegt **auf dem Hypervisor** (Tags) und lokal nur als
Cache:

- **VM-Name** `ah-<role>-<lane|main>-<4hex>`; **Tags** `ah;role-<role>;lane-<lane>;sc-<scenario>;ttl-<epoch>;tpl-<profil>`
  (Menge, nicht Reihenfolge). Templates: `ah-tpl-<profil>;built-<yyyymmdd>`; die drei heutigen Templates werden in 2a
  nachgetaggt (`linux-full` = Fat-Template, `base-ubuntu`, `base-debian`).
- **Gast-User** kommt aus `ciuser` der VM-Config (vom Template geerbt) — kein Konfigurationswert, kein zweiter Zustand.
- **`.vm/warm.env`** mit denselben Schlüsseln wie heute (`desktop=<vmid>`, `server=<vmid>`, `server_ip`, `server_admin_pw`,
  `server_monitor_key`, `server_sid`, `server_ptok`); Werte sind VMIDs statt Slugs. **`.vm/lane`** explizit
  (von `lane.sh new` geschrieben; Hauptcheckout = `main`).
- **Konfiguration** nur aus `.claude/settings.local.json` → `env` (`AH_PVE_URL|NODE|TOKEN|CA|STORAGE|BRIDGE|POOL|VMID_RANGE`,
  `AH_VM_SSH_KEY` (Pfad, Default `~/.config/adminhelper/vm_ed25519`), `AH_VM_MAX`, `AH_VM_LINKED`, optional
  `AH_VM_REMOTE_DIR` Default `~/adminhelper`); Umgebungsvariablen gewinnen über die Datei (für `ah-runner` ab Stufe 4).
- **Proxmox-API** (Schema `apidoc.js` 2026-09-15 geprüft): `GET /version`, `GET /cluster/resources?type=vm`,
  `GET /pools/{pool}`, `GET /nodes/{n}/status`, `GET /nodes/{n}/storage/{s}/status`, `POST …/qemu/{tpl}/clone`
  {`newid`,`name`,`full`,`pool`,`storage` nur bei `full=1`}, `PUT …/config` {`tags`,`sshkeys` (urlencoded),`agent`,
  `memory`,`cores`,`ipconfig0`}, `POST …/status/{start,stop,shutdown}`, `GET …/tasks/{upid}/status`,
  `POST …/agent/ping`, `GET …/agent/network-get-interfaces`, `POST …/snapshot` {`snapname`,`vmstate`},
  `POST …/snapshot/{s}/rollback` {`start`}, `DELETE …/snapshot/{s}`, `DELETE …/qemu/{vmid}?purge=1&destroy-unreferenced-disks=1`
  (Query!), `POST …/template`, `GET /access/permissions` (für `doctor`). Header `Authorization: PVEAPIToken=<id>=<secret>`;
  kein CSRF für Token. Antworten sind `{"data": …}`; Fehler 4xx/5xx tragen Text im Body.

## Externe Integrationen

Proxmox VE REST-API (Version 9.x auf dem Host; Schema wie oben). qemu-guest-agent (Ping, Netzwerk-Interfaces).
cloud-init über die PVE-Cloud-Init-Drive (`ciuser`, `sshkeys`, `ipconfig0=ip=dhcp`) — Klone bekommen beim ersten
Start eine neue Instance-ID, cloud-init läuft erneut und setzt den Key (verifiziert). rsync über SSH (Port 22,
`-az --delete --exclude-from scripts/vm/rsync-exclude.txt`, Excludes aus `.crabbox.yaml` übernommen). Kein FRP-,
Tauri- oder VictoriaMetrics-Format berührt.

## Trade-offs & Alternativen

1. **Python-Stdlib statt Bash+curl+jq oder `proxmoxer`** (§11.1): UPID-Polling, JSON, TLS-Verifikation, hermetischer
   Test — in Bash gleich lang und schlechter testbar; `proxmoxer` wäre eine Abhängigkeit für ~25 Endpunkte. Empfehlung Stdlib.
2. **Linked Clones als Default** (`AH_VM_LINKED` nach `doctor` gesetzt; Fall A verifiziert): 2 s statt 11 min, Capstone
   spart ~1 h. Trade-off: Linked Clones hängen am Template — `bake` templatet **immer einen frischen Klon**, nie eine
   geleaste VM; `destroy` verweigert Templates; Kevin löscht Templates von Hand (`doctor` listet sie).
3. **Lease-Wahrheit als Tags** (Frage 36): jeder Checkout sieht jede `ah`-VM samt Lane/Szenario/Frist; der Reaper
   braucht keinen lokalen Zustand; crabbox-Alt-VMs (ohne Tag) bleiben unsichtbar → gefahrlose Koexistenz während 2a.
   Trade-off: ein zweiter Rechner mit demselben Token sieht dieselben Leases (gewollt).
4. **Aufräumer ohne Timer**: jeder `vm.py`-Aufruf reapt am Ende die eigene Lane (ein GET); Wrapper enden mit `list`
   und Exit ≠ 0 bei Leak. Alternative Cron auf dem Host (Frage 12) — offene Frage, Empfehlung nein.
5. **Gast-User aus `ciuser`** statt Konfigurationswert: das Fat-Template heißt intern noch `crabbox`; erst der Rebake
   (2a T8) setzt `adminhelper` (D20). So läuft die Warm-Box vom ersten Tag auf dem alten Template, und der Umstieg
   ist ein Template-Tausch, kein Config-Sweep.
6. **Klon-Submits seriell**: parallele Klone erst nach I/O-Messung auf dem Thin-Pool; mit 2-s-Klonen ist der Gewinn ohnehin klein.
7. **Kapazität nach echtem RAM** (Frage 34): `doctor` rechnet geplante Rollen + bestehende `ah`-VMs gegen freies RAM
   (minus 4 GB Reserve) → Exit 74 `capacity` mit Liste **vor** dem ersten Klon; `AH_VM_MAX` bleibt als Zähl-Deckel je Lane.
8. **`heavy.sh` behält seine Marker-Liste vorerst**, wird aber kleiner: `vm.py` und die Wrapper liefern Exit 74 mit
   Grund (`capacity`, `no ip`, `clone failed`, `privilege`), crabbox-Strings (`lease failed`, `workspace owner release`,
   `rsync failed: … ambiguous`) entfallen; `capstone_scan` liest Rollen aus `ah-<role>-…`-Namen.

## Risiken & Rollback

- **Live-Proben kosten Zeit**: jede ~1–5 min (Klon 2 s, Boot ~30 s, Bootstrap 10–20 min bei Bakes). Budget im Ledger.
- **Lock-Kollisionen** nach Rollback/Start (verifiziert): `vm.py` wiederholt bei `can't lock file` mit Backoff bis 60 s,
  danach Exit 74. **Tag-Reihenfolge**: als Menge parsen. **DELETE-Parameter**: Query-String.
- **Sync-Zielpfad**: im heutigen Fat-Template liegen `target/`/`node_modules/` nicht unter dem neuen Ziel — der erste
  Warm-Loop baut sie einmal (~20 min), bis der Rebake sie im Template hat. Kein Korrektheitsrisiko.
- **`user-tag-access`** des Datacenters könnte Tags für Nicht-Admins einschränken (heute `free`, verifiziert durch die Probe);
  `doctor` prüft es beim Probe-Klon und meldet `privilege: tags`.
- **Umbenennungs-Sweep (2b)** vergisst eine Stelle → `git grep -il crabbox` ist das Verify; `heavy_test.sh` (152 Assertionen)
  und `crabbox_iter_flags_test.sh` bleiben als umbenannte Hermetik-Tests die Sicherung der Wrapper-Semantik.
- **Rollback**: 2a ist additiv (Verzeichnis `scripts/vm/` + zwei Zeilen in `run.sh`/`ci.yml`) → `git revert`. 2b ist ein
  PR; bis zum Merge läuft crabbox weiter, nach dem Merge ist der Weg zurück `git revert` des Merge-Commits, crabbox-Binary
  bleibt bis dahin installiert (Kevin deinstalliert erst nach leerem `crabbox list`).
- **Speicher auf dem Host**: `doctor` verweigert bei < Bedarf + 4 GB; Warm-Boxen werden nie automatisch gereapt.

## Doku-Impact

2a: `DEVELOPMENT.md` neuer Abschnitt „VMs mit `vm.py`" (Konfiguration, Verben, Fehlercodes, Probe-Ablauf), `CHANGELOG` Added.
2b: der Sweep — CLAUDE.md §8, AUTONOMOUS.md, `tasks/README.md`, `.claude/rules/testing.md`, `.claude/skills/test/SKILL.md`
(Neufassung als „Testen auf VMs"), `.claude/skills/vm/SKILL.md` (neu), `DEVELOPMENT.md` (crabbox-Abschnitte ersetzt),
`docs/developer/cicd.html` DE+EN (Wochenlauf-/Aggregator-Abschnitte), `apps/desktop/e2e/README.md`, `CHANGELOG` Changed/Removed.

## Offene Fragen (Design-Gate)

1. **Gast-User neuer Bakes `adminhelper`** (D20-konsistent; das Fat-Template behält `crabbox` bis zum Rebake). Empfehlung ja.
2. **VM-Namen und Tags behalten das kurze Präfix `ah`** (Tag-Liste, UI-Breite), nur Proxmox-Objekte heißen `adminhelper-*`. Empfehlung ja.
3. **Rebake des Fat-Templates in 2a** (`bake --profile linux-full`, ~45 min, ohne Prompt laut D17) plus erstes
   `linux-server`-Template — Empfehlung ja, als letzte 2a-Tasks; bis dahin Warm-Box mit Erstbau der Caches.
4. **Hypervisor-seitiger Reaper** (Cron auf dem Host, Frage 12) — Empfehlung nein: timerloser Reaper + `reap --all` von Hand reichen; ein Cron widerspricht „nichts läuft ohne Kevins Start".
5. **2a darf vor der Startbedingung „zwei grüne Wochenläufe" gebaut werden** — es berührt den Wochenlauf-Pfad nicht;
   2b wartet auf die zwei grünen Läufe als Vergleichsmaßstab. Empfehlung ja.
6. **2b ändert Harness-Dateien** (`.claude/settings.json`, Skills, `CLAUDE.md`, `lane.sh`, Hook) in einem PR — Warn-Trigger 4;
   die Roadmap plant es genau so. Empfehlung ja, ein Sweep (Frage 15).
7. **`AH_VM_SSH_KEY`**: eigener Schlüssel `~/.config/adminhelper/vm_ed25519`, von Kevin einmal mit `ssh-keygen` erzeugt
   (kein Schlüssel-Erzeugen als Nebenwirkung von `doctor`). Empfehlung ja.

## Verify-Prinzip

2a: `python3 -m pytest scripts/vm/tests -q` grün gegen aufgezeichnete Fixtures (Token-Header, VMID-Wahl, Clone→UPID→OK,
Fehler → 74, Tag-Menge, Reap-Auswahl, IP-Filter, genau ein Retry auf 5xx, Lock-Retry, `capacity` → 74, Clone-Timeout →
DELETE des `newid`, VM ohne `ah`-Tag → Exit 2, DELETE-Query). Live: `clone --profile linux-full --role probe --ttl 20m` →
`wait` < 5 min → `run -- 'bash scripts/tests/run.sh lint'` → `4 passed, 0 failed, 0 skipped` → `snap`/`rollback` →
`destroy` → `list` leer; falscher Token → 74 ohne VM; `destroy <fremde VMID>` → Exit 2, VM unberührt.
2b: `warm.sh desktop` einmal, `iter.sh quick` zweimal (≤ 15 min, dann ≤ 5 min), roter Test → Exit 1 und Box bleibt;
`AH_WARM_TTL=20m` + 25 min + `vm.py list` → Box weg; `multibox.sh --agents 1` → `5 ok, 0 failed, 0 skipped`;
`git grep -il crabbox -- ':!CHANGELOG.md'` → leer; `lane.sh new probe` → `warm.sh desktop` → `iter.sh quick` → `lane.sh done probe`;
Kevins nächster Wochenlauf: dieselben Summary-Zeilen wie der letzte auf crabbox.
