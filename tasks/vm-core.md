<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Stufe 2a — vm-core: `scripts/vm/vm.py` neben crabbox — Task-Ledger
Status: aktiv · Branch: feature/vm-core · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: docs/features/harness-stufe-2.md
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: keine crabbox-Suite; die Live-Proben dieses Ledgers (T11, T12) laufen mit `vm.py` selbst im Pool `adminhelper-ci` (D17: Klonen, Baken, Zerstören im Pool ohne Prompt). Jede Probe endet mit `vm.py list` leer.
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Roadmap: R-0006 (Teil 1) · Hängt ab von: R-0002 (gemergt) · Startbedingung (Spec, offene Frage 5): keine — 2a berührt den Wochenlauf nicht
Regeln für diesen Ledger: Homelab-Namen, IPs, Token nie in versionierte Dateien — Fixtures werden bereinigt (`<node>`, `<host>`, `<ip>`, `<token>`); Konfiguration nur aus `.claude/settings.local.json`. Kein `pvesh`, kein `qm` — nur die REST-API. Jede Live-Probe zerstört ihre VM im selben Lauf.
Vorab verifiziert (Planung 2026-09-15, siehe Spec): Linked Clone 2 s · Guest-Agent in Fat- und Basis-Template · cloud-init-Key-Injektion · Snapshot/Rollback 2 s · Tags alphabetisch zurücksortiert · DELETE-Parameter in die Query · Lock-Retry nach `rollback --start` · SSH-Port 22 · TLS: `VERIFY_X509_STRICT` löschen, URL = SAN-Name.

## A — Fundament

### T1 — Fixtures aufzeichnen und bereinigen  [x] (30 Fixtures gegen PVE 9.2.3 aufgezeichnet + bereinigt; Wegwerf-Klone 3000/3001 zerstört)
Korrektur an der Vorab-Annahme: `agent/ping` antwortet ohne Agent **500**, nicht 503, und zwar in zwei Texten (`VM ... is not running`, `QEMU guest agent is not running`). Die Lock-Kollision ist ebenfalls kein HTTP-Fehler, sondern der `exitstatus` eines mit 200 angenommenen Tasks.
Komponente: scripts · Dateien: scripts/vm/tests/fixtures/*.json (neu), scripts/vm/tests/README.md (neu, SPDX-Kommentar im Markdown)
Änderung: Mit einem Wegwerf-Skript (nicht committen) die realen Antworten aufzeichnen: `GET /version`, `/cluster/resources?type=vm`, `/pools/<pool>`, `/nodes/<node>/status`, `/nodes/<node>/storage/<storage>/status`, `/access/permissions`, Template-`config`, `clone`-UPID, `tasks/<upid>/status` (running und stopped/OK), Klon-`config` nach PUT, `agent/ping` (503 solange kein Agent, dann 200), `agent/network-get-interfaces`, `snapshot`/`rollback`, Fehlerkörper 403 (fremde VM), 501 (DELETE mit Body), Lock-Timeout-Text. Bereinigen: Hostnamen, IPs, MACs, Token, UUIDs durch Platzhalter; VMIDs bleiben. README erklärt Herkunft und Bereinigungsregel.
Verify: python3 -c 'import json,glob; [json.load(open(f)) for f in glob.glob("scripts/vm/tests/fixtures/*.json")]; print("ok")'   und   grep -rEn '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+|PVEAPIToken=' scripts/vm/tests/fixtures/ | grep -v '127\.0\.0\.1' (leer — der Loopback bleibt, der IP-Filter in T4 hängt genau daran)
Doku: keine (intern)

### T2 — `vm.py` Kern: Konfiguration, HTTP, UPID, Fehlerklassen  [x] (Config/Api/wait_task/Fehlerklassen + Verb-Stubs; 45 Tests)
Komponente: scripts · Dateien: scripts/vm/vm.py (neu, SPDX), scripts/vm/tests/test_vm.py (neu, SPDX), scripts/vm/tests/conftest.py (neu, SPDX)
Änderung: Argparse-Skelett mit allen Verben (Stubs), `Config` aus `.claude/settings.local.json` → `env` mit Umgebungsvariablen-Override; `Api` mit `urllib` (`Authorization: PVEAPIToken=…`, 30-s-Timeout, `ssl` mit `cafile=AH_PVE_CA` und gelöschtem `VERIFY_X509_STRICT` — Grund als Kommentar, DELETE-Parameter in der Query, genau **ein** Retry bei 5xx/Verbindungsfehler, `{"data": …}`-Entpacken), `wait_task(upid, limit)` mit Backoff 1→5 s, Lock-Retry (`can't lock file` → bis 60 s), Fehlerklassen als Exceptions → Exit 0/1/2/74 in `main()`, Zeit-Bounds aus §11.2 als Konstanten. Tests: Fake-`urlopen` aus Fixtures (Token-Header, Retry genau 1×, 403 → 74 mit Privileg-Name, DELETE-Query, Lock-Retry, Timeout).
Verify: bash scripts/dev/verify.sh scripts --strict   (nach T9; bis dahin: python3 -m pytest scripts/vm/tests -q)
Doku: keine (intern)

### T3 — `doctor`  [x] (profiles.json + 7 Checks, live gegen den Pool gefahren; 68 Tests)
Präzisierung der Kapazitätsformel: der Ledger sagt „freies RAM − 4 GB − RAM **aller** `ah`-VMs". Gerechnet wird mit dem **noch nicht bezogenen** RAM (`maxmem − mem`) jeder `ah`-VM. Für gestoppte VMs ist das ihr volles `maxmem` (der Ledger-Wortlaut), für laufende nur der noch offene Rest — ihr angefasstes RAM ist bereits aus `memory.free` heraus und würde sonst doppelt zählen, während „laufende gar nicht zählen" die frisch gebootete 6-GB-Box verschenken würde. Die Detailzeile nennt jeden Summanden einzeln. Im PR-Body erwähnt.
Komponente: scripts · Dateien: scripts/vm/vm.py, scripts/vm/tests/test_vm.py, scripts/vm/profiles.json (neu)
Änderung: `profiles.json`: Profil → Template-Tag, Bootstrap-Profil, Rollen mit RAM/CPU (`server` 4096/2, `desktop` 6144/4, `agent|tunnel|visitor|moncheck|rpm` 2048/2, `probe` 2048/2). `doctor` prüft nacheinander und druckt je Zeile `ok|FAIL <check>: <detail>`: API + Token (`/version`), Rechte je Klasse aus `/access/permissions` gegen die Soll-Privilegien auf `/pool/<pool>`, `/storage/<storage>`, `/nodes/<node>` (fehlende namentlich), Storage-Typ → `linked=yes|no snapshots=yes|no` (lvmthin/zfspool/dir-qcow2 = ja), Templates im Pool je Profil-Tag (neuestes `built-`), `agent` in der Template-Config, Bridge des Templates == `AH_PVE_BRIDGE`, VMID-Bereich frei/belegt, **Kapazität**: freies RAM − 4 GB − RAM aller `ah`-VMs ≥ Bedarf der übergebenen Rollen (`--roles server,agent` … Default: eine `probe`) → sonst `FAIL capacity` mit Liste der belegenden VMs. Exit 74 bei mindestens einem FAIL. `--json` gibt die Zeilen als Objekt aus (für Wrapper).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T10)

## B — Verben

### T4 — `clone` und `wait`  [x] (124 Tests; live gefahren nach dem Umbau: Klon 6,3 s, Tags `ah;lane-main;role-probe;sc-smoke;tpl-linux-full;ttl-…`, `wait` 31,6 s inkl. SSH-Login als `crabbox` mit dem injizierten Schlüssel, VM zerstört, Pool leer)
Zusätzlich zum Ledger-Text umgesetzt: `AH_VM_MAX` als Zähl-Deckel **je Lane** (Spec, Trade-off 7 — die Variable ist konfiguriert und wäre sonst wirkungslos). Der `sc-`-Tag entsteht nur, wenn `--scenario` gegeben ist (statt eines Platzhalters `sc-none`); `destroy --scenario` und `list` lesen ihn als Menge. Der öffentliche Schlüssel wird **vor** dem Klon gelesen: eine VM ohne Schlüssel ist unerreichbar, und das erst danach zu merken kostet einen Klon für nichts. `--scenario` wird wie die Lane gesäubert — ungefiltert könnte ein `;` ein zweites `ttl-` in die Tag-Menge schmuggeln, und welches dann gewinnt, wäre Zufall.
[?] **Für Kevin:** `.claude/settings.local.json` setzt `AH_VM_MAX=3`. Der Capstone hält **sieben** Leases gleichzeitig auf Lane `main` (`crabbox_multibox.sh --capstone`: srv, agent, moncheck, rpm, tunnel, visitor, desktop) — ab 2b bräche der vierte `clone` mit Exit 74 ab. Der Default in `vm.py` steht deshalb auf 8; die lokale Einstellung fasse ich nicht an. Entweder dort auf ≥ 8 anheben oder bewusst bei 3 belassen (dann läuft 2b nur ohne Capstone).
Komponente: scripts · Dateien: scripts/vm/vm.py, scripts/vm/tests/test_vm.py
Änderung: `clone --profile p --role r [--lane l] [--scenario id] [--ttl 8h] [--memory MB] [--cores N] [--name n]`: Kapazitätsprüfung wie `doctor`; kleinste freie VMID im Bereich (Klone im unteren, Templates im oberen Hunderter des Bereichs); Template = neuestes `ah-tpl-<p>`-Tag im Pool; `POST clone` {`newid`,`name`,`full` (0 bei `AH_VM_LINKED=1`, sonst 1 + `storage`),`pool`} → UPID → OK; `PUT config` {`tags` (`ah;role-…;lane-…;sc-…;ttl-<epoch>;tpl-…`), `sshkeys` (öffentlicher Teil von `AH_VM_SSH_KEY`, urlencoded), `agent=enabled=1`, `memory`, `cores`, `ipconfig0=ip=dhcp`} → `POST status/start`; jeder Fehler nach dem Clone → `DELETE …?purge=1&destroy-unreferenced-disks=1` des `newid` → Exit 74. Druckt `VMID NAME`. `wait <vm> [--timeout 900]`: `agent/ping` alle 5 s, dann IPv4 aus `network-get-interfaces` (ohne lo, link-local, IPv6), dann `ssh -o BatchMode=yes -o ConnectTimeout=5 <ciuser>@<ip> true` (User aus der VM-Config `ciuser`), druckt IP; Timeout → 74 `no ip`/`no ssh`. Tests: VMID-Wahl, Tag-Aufbau, Linked vs Full, Aufräumen bei Fehler, IP-Filter, Timeout.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T10)
Abhängt von: T3

### T5 — `ssh`, `sync`, `run`, `pull`  [x] (152 Tests; live: `sync` 5,8 s, `run -- 'bash scripts/tests/run.sh lint'` → `3 passed, 0 failed, 1 skipped` in 33,8 s, Re-Sync 0,9 s, `--extend` versetzt den `ttl-`Tag, VM zerstört)
Fund beim Bauen: `run <vm> --sync -- <cmd>` war mit `argparse.REMAINDER` nicht baubar — ein REMAINDER **nach** einem Positional schluckt jede spätere Option (`--sync` landete im Kommando). `cmd` nutzt jetzt `nargs="*"` und den `--`-Trenner der Shell; ein Test pinnt beide Schreibweisen.
Zwei Fehler, die erst der Review fand: `--out` holte aus `<remote>/.ah-out/`, das niemand anlegt — rsync antwortet auf eine fehlende Quelle mit Exit 23, und das hätte den Remote-Exit (also das Testergebnis) durch eine Infra-Störung ersetzt; jetzt wird das Verzeichnis vorher per ssh angelegt. Und `sync` nahm `./` als Quelle: aus einem Unterverzeichnis aufgerufen hätte es einen Teilbaum geschoben und den Rest auf der Box per `--delete` gelöscht — Quelle ist jetzt `ROOT`.
Fund für T12: auf dem heutigen Fat-Template meldet `run.sh` auf der Box `go=no cargo=no` — die Toolchains liegen im Home des Template-Users und sind unter dem neuen Remote-Pfad nicht im PATH. Das Rebake muss sie für den Gast-User `adminhelper` in den PATH legen, sonst SKIPpt die schwere Suite in 2b lautlos.
Komponente: scripts · Dateien: scripts/vm/vm.py, scripts/vm/rsync-exclude.txt (neu), scripts/vm/tests/test_vm.py
Änderung: Ziel-VM per VMID oder Name; IP über Agent (gecacht je Aufruf); User aus `ciuser`; Schlüssel `AH_VM_SSH_KEY`; `-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=.vm/known_hosts`. `ssh <vm> [-- cmd]` (interaktiv ohne cmd). `sync <vm> [--no-delete]`: `rsync -az --delete --exclude-from scripts/vm/rsync-exclude.txt ./ <user>@<ip>:<AH_VM_REMOTE_DIR>/` (Excludes = die Liste aus `.crabbox.yaml`, plus `.vm`, `.ah-out`); rsync-Exit ≠ 0 → 74 `sync failed`. `run <vm> [--sync] [--timeout S] [--out DIR] [--extend 8h] -- <cmd>`: `cd <remote>` + Kommando über ssh mit Streaming, Remote-Exit 1:1, ssh 255 → 74, `--out` zieht `<remote>/.ah-out/**` per rsync nach DIR, `--extend` setzt den `ttl-`Tag neu. `pull <vm> <glob> <dir>`. Tests mit Fake-`subprocess` (Argumentaufbau, Exit-Mapping, `--extend`-Tag).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T10)
Abhängt von: T4

### T6 — `snap`, `rollback`, `delsnap`, `destroy`, `reap`, `list`  [x] (203 Tests; live: `snap` 1,3 s, `rollback --start` 1,3 s, `delsnap` 35,6 s — die 35 s sind der Lock-Retry, der nach `rollback --start` genau wie aufgezeichnet greift; `list` meldete den Leak, `destroy 9402` wurde als Template mit Exit 2 verweigert, `destroy <vm>` grün, Pool danach leer)
Fail-closed gilt nicht nur für `destroy`: auch `snap`/`rollback`/`delsnap` verweigern Templates und VMs ohne `ah`-Tag (Spec-Ziel 2a). `destroy` prüft **alle** ausgewählten VMs, bevor es die erste zerstört — eine Verweigerung mittendrin ließe ein halb abgebautes Szenario zurück. Geprüft wird dabei gegen `status/current`, nicht gegen `/cluster/resources`: die Ressourcenliste ist ein Cache, der laut T1-Aufzeichnung beim **Namen** hinterherhinkt — `destroy <name>` hätte sonst die falsche VM treffen können, und der Reaper hätte eine Sekunden zuvor per `--extend` verlängerte Box trotzdem geholt. Beide Rennen sind mit Tests gepinnt. Eine VM, die zwischen Listing und Bestätigung schon verschwunden ist (fremder Sweep, Handarbeit), hält weder `destroy` noch `reap` auf — sie wird übersprungen, der Rest kommt trotzdem herunter. Die Verweigerung eines Templates ist nach dem Umbau live nachgefahren: `destroy 9402` → Exit 2, kein DELETE, Pool unverändert. Der Auto-Reap läuft in einem `finally`, also auch nach einem **fehlgeschlagenen** Verb (ein an `capacity` gescheitertes `clone` ist genau der Moment, in dem die abgelaufenen VMs weg müssen), nur nach Ctrl-C nicht; den Exit-Code des Verbs fasst er nie an. Neu in `conftest.py`: eine `no_network`-Fixture, die jeden nicht abgefangenen echten HTTP-Aufruf zur Assertion macht — eine hermetische Suite, die still den echten Hypervisor erreicht, ist keine.
[?] **Für Kevin:** Der Auto-Reap nimmt auch eine Warm-Box mit, deren `ttl-` abgelaufen ist — auch die, mit der der Aufruf gerade gearbeitet hat (`ssh`/`sync`/`pull` haben kein `--extend`). Der Ledger sagt „alle `ah`-VMs mit `ttl-` < jetzt", die Spec sagt unter Risiken „Warm-Boxen werden nie automatisch gereapt", und das 2b-Verify erwartet wiederum `AH_WARM_TTL=20m` + 25 min → Box weg. Umgesetzt ist die Ledger-/2b-Lesart (die TTL ist die Wahrheit; `.vm/warm.env` schützt nur vor dem Leak-Report). Wenn Warm-Boxen wirklich unantastbar sein sollen, ist das eine Zeile in `reap_lane` — dann muss aber das 2b-Verify angepasst werden.
Komponente: scripts · Dateien: scripts/vm/vm.py, scripts/vm/tests/test_vm.py
Änderung: `snap <vm> <name> [--ram]`, `rollback <vm> <name> [--start]`, `delsnap <vm> <name>` (Storage ohne Snapshot-Fähigkeit → 74 mit Grund; Lock-Retry). `destroy <vm>… | --scenario id | --lane l | --role r`: verweigert Templates und VMs ohne Tag `ah` (Exit 2), `stop` → Poll → `DELETE …?purge=1&destroy-unreferenced-disks=1`. `reap [--all] [--dry-run]`: alle `ah`-VMs mit `ttl-<epoch>` < jetzt, ohne `--all` nur eigene Lane (`.vm/lane`, Default `main`), nie Templates. `list [--json] [--lane l]`: VMID, Name, Rolle, Lane, Szenario, IP (Agent, best effort), Status, TTL-Rest, `EXPIRED`; VMs ohne `ah`-Tag nur gezählt; Exit ≠ 0, wenn eine `ah`-VM der eigenen Lane weder in `.vm/warm.env` noch im aktiven Szenario (`AH_VM_SCENARIO`) steht (Leak-Sweep). **Auto-Reap:** jedes Verb außer `list`/`doctor` ruft am Ende `reap` für die eigene Lane (`AH_VM_NO_AUTOREAP=1` schaltet ab). Tests: Tag-Fail-closed, Reap-Auswahl (ttl/lane/template), Leak-Exit, Szenario-Filter.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T10)
Abhängt von: T4

### T7 — `bake --profile linux-full|linux-server`  [ ]
Komponente: scripts · Dateien: scripts/vm/vm.py, scripts/vm/tests/test_vm.py, scripts/tests/crabbox_bootstrap.sh (nur: `qemu-guest-agent` in die apt-Liste, `systemctl enable --now qemu-guest-agent`)
Änderung: `bake --profile p [--from <template-tag>]`: Klon der Basis (`ah-tpl-base-ubuntu`, Default) mit `ciuser`-Override `adminhelper` (offene Frage 1) und Rolle `bake`, `wait`, `sync`, `run -- 'AH_BOOTSTRAP_PROFILE=<full|server> bash scripts/tests/crabbox_bootstrap.sh'` (Timeout 2700 s), `run -- 'AH_ALLOW_REAL=1 bash scripts/tests/run.sh unit'` (Caches), Clean (`apt-get clean; cloud-init clean; docker system prune -af; truncate -s0 /etc/machine-id`), `POST status/shutdown` → Poll, `POST …/template`, Tags `ah-tpl-<p>;built-<yyyymmdd>`, Name `ah-tpl-<p>-<yyyymmdd>`, VMID aus dem oberen Hunderter des Bereichs. Bricht ein Schritt ab: Klon zerstören, Exit 74. Tests: Ablauf-Reihenfolge und Aufräumen mit Fake-API/Fake-ssh.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T10)
Abhängt von: T5, T6

### T8 — `scripts/vm/lib.sh` und Templates nachtaggen  [ ]
Komponente: scripts · Dateien: scripts/vm/lib.sh (neu, SPDX), scripts/tests/lib_vm_test.sh (neu, SPDX), scripts/tests/run.sh (nur `AH_SCRIPT_TESTS_DEFAULT`)
Änderung: `vm_load_env` (liest `.claude/settings.local.json` → `env`, exportiert `AH_PVE_*`/`AH_VM_*`), `vm_marker` (= `cbx_marker`), `vm_build_agent_deb` (= `cbx_build_agent_deb`), `warm_get/set/clear` auf `.vm/warm.env`, `vm_lane` (aus `.vm/lane`, Default `main`; `AH_LANE` überschreibt). Hermetischer Test für warm_*/vm_marker/vm_lane. Dazu einmalig, per `vm.py` selbst (kein neues Verb, `python3 - <<…` in der Task dokumentiert): die drei Templates im Pool taggen — Fat → `ah-tpl-linux-full;built-<Datum des Bakes>`, Basis-Ubuntu → `ah-tpl-base-ubuntu`, Basis-Debian → `ah-tpl-base-debian` (`PUT config tags` auf Templates ist per Pool-ACL erlaubt; Bestandstag `crabbox` bleibt).
Verify: bash scripts/tests/run.sh unit --strict --only scripts
Doku: keine (T10)

## C — Verdrahtung, Doku, Live-Beweis

### T9 — Lint/Test-Verdrahtung: `vm-pytest`-Schritt, ruff und shellcheck über `scripts/vm`  [ ]
Komponente: scripts · Dateien: scripts/tests/run.sh, .github/workflows/ci.yml (Job `ops-scripts`: shellcheck-Glob `scripts/vm/*.sh`), scripts/tests/run_flags_test.sh (Schritt-Id in den Erwartungen)
Änderung: Schritt `vm-pytest` (`python3 -m pytest scripts/vm/tests -q`, dep-gated python3, Key `scripts`, in `AH_REQUIRED_DEFAULT`), `ruff`-Schritt deckt `scripts/vm` ab (prüfen: `ruff.toml` im Root → sonst Pfad ergänzen), shellcheck-Glob um `scripts/vm/*.sh` in `run.sh` und `ci.yml`. `verify.sh scripts --strict` fährt damit Lint + Unit von `scripts/vm`.
Verify: bash scripts/dev/verify.sh scripts --strict   und   bash scripts/tests/run_flags_test.sh
Doku: keine (intern)
Abhängt von: T2

### T10 — DEVELOPMENT.md „VMs mit vm.py" + CHANGELOG  [ ]
Komponente: docs · Dateien: DEVELOPMENT.md, CHANGELOG.md
Änderung: Neuer Abschnitt neben „Schwere Suites auf crabbox" (der bleibt bis 2b): Konfiguration (`AH_PVE_*`, `AH_VM_*`, SSH-Schlüssel `ssh-keygen -t ed25519 -f ~/.config/adminhelper/vm_ed25519 -N ''`, CA-Datei, URL = SAN-Name), Verben mit je einem Satz, Fehlercodes 0/1/2/74, Tags als Lease-Wahrheit, `doctor`-Ausgabe, Probe-Ablauf aus der Spec, TLS-Hinweis. CHANGELOG Unreleased/Added.
Verify: grep -c 'vm.py' DEVELOPMENT.md   (≥ 5) — plus `bash scripts/tests/run.sh lint --strict --only scripts`
Doku: DEVELOPMENT.md · CHANGELOG

### T11 — Live-Beweis 2a (Probe-Klon)  [ ]
Komponente: scripts · Dateien: tasks/vm-core.md (Ergebnisse als Anhang), keine Codeänderung erwartet
Änderung: Nacheinander, alle Ausgaben in den Ledger-Anhang: `vm.py doctor --roles probe` → alle `ok`; `vm.py clone --profile linux-full --role probe --ttl 20m` → `VMID NAME`; `vm.py wait <vm>` → IP in < 5 min; `vm.py run <vm> --sync -- 'bash scripts/tests/run.sh lint'` → Summary `N passed, 0 failed, 0 skipped`; `vm.py snap <vm> s1` → `vm.py rollback <vm> s1 --start` → `vm.py delsnap <vm> s1`; `vm.py destroy <vm>` → `vm.py list` leer (Exit 0). Negativ: `AH_PVE_TOKEN=falsch vm.py clone …` → Exit 74, keine VM entstanden; `vm.py destroy <VMID einer VM außerhalb des Pools>` → Exit 2 und 403-frei (die VM ist nicht sichtbar); Klon mit `--ttl 1m`, 2 min warten, `vm.py list` → weg (Auto-Reap). Rote Schritte → Fix im jeweiligen Verb-Task, dann wiederholen.
Verify: python3 scripts/vm/vm.py list   → Exit 0, keine `ah`-VM   (nach der Probe)
Doku: keine
Abhängt von: T9

### T12 — Live-Beweis Bake: `linux-server` und Rebake `linux-full`  [ ]
Komponente: scripts · Dateien: tasks/vm-core.md (Anhang), scripts/vm/profiles.json (falls Tag/Namen nachjustiert)
Änderung: `vm.py bake --profile linux-server` (~25 min) und `vm.py bake --profile linux-full` (~45 min), jeweils gefolgt von Probe-Klon → `wait` → `run -- 'bash scripts/tests/run.sh lint'` → `N passed, 0 failed, 0 skipped` → `destroy`. `doctor` zeigt danach je Profil das neue `built-<datum>` als Auswahl. Alte Templates bleiben (Kevin löscht von Hand). Ergebnis (Dauer, VMIDs, Tags) in den Anhang.
Verify: python3 scripts/vm/vm.py doctor --roles probe   → `ok templates: linux-full built-<datum>, linux-server built-<datum>, …`
Doku: keine
Abhängt von: T11

## Abschluss
- `bash scripts/tests/run.sh quick --strict` grün; `bash scripts/dev/verify.sh all --strict` grün.
- Kein Warm-Profil-Lauf auf crabbox nötig: 2a ändert weder Produktcode noch Wrapper.
- `python3 scripts/vm/vm.py list` leer; `crabbox list` leer.
- PR-Body: Probe-Ergebnisse aus T11/T12 (Dauer je Schritt), Fixture-Herkunft, offene Fragen der Spec mit Entscheidung.
