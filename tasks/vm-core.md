<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Stufe 2a — vm-core: `scripts/vm/vm.py` neben crabbox — Task-Ledger
Status: erledigt (alle zwölf Tasks `[x]`; die vier `[?]` sind Entscheidungen für Kevin, keine offene Arbeit — sie stehen im PR-Body) · Branch: feature/vm-core · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
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
Fund, in T11 behoben: `run.sh` meldete auf der Box `go=no cargo=no`. Ursache war nicht das Template, sondern die fehlende Login-Shell — `run` nutzt jetzt `bash -lc`, danach `go=yes cargo=yes` und `lint` grün ohne Skips.
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

### T7 — `bake --profile linux-full|linux-server`  [x] (219 Tests; Live-Bake ist T12)
Die Klon-Maschinerie aus T4 ist zu `create_vm()` herausgezogen, statt sie ein zweites Mal zu schreiben — `bake` braucht denselben Rollback für eine VM, die von Anfang an im **Template-Hundert** steht (ein geglücktes Bake wird dort zum Template, ein misslungenes von dort weggeräumt). Der Klon trägt einen Lease-Tag mit 4 h TTL, damit ein abgebrochenes Bake reapbar bleibt; die Lease-Tags fallen **erst** weg, wenn das Template fertig ist. `ciuser=adminhelper` (D20, offene Frage 1). `crabbox_bootstrap.sh` installiert und aktiviert `qemu-guest-agent` — ein Template ohne ihn wäre eines, dessen Klone nie eine Adresse bekommen.
Drei Abweichungen vom Ledger-Wortlaut, alle begründet: (1) Die drei Bake-Schritte laufen unter **`bash -lc`**. Ohne Login-Shell sourct `ssh host cmd` weder `/etc/profile.d` noch `~/.cargo/env`, `run.sh` dep-gated sich in `go=no cargo=no` (genau der T5-Fund), wärmt nichts und beendet trotzdem mit 0. (2) Der Warmup ist **kein Gate** — `crabbox_bake.sh` fuhr denselben Schritt mit `|| true`; ein einzelner flakiger Unit-Test darf nicht eine halbe Stunde Bootstrap wegwerfen. Sein Exit-Code wird gedruckt, damit ein Warmup, der nichts gewärmt hat, sichtbar bleibt. (3) Die Clean-Liste hat `rm -f /etc/ssh/ssh_host_*` dazubekommen (cloud-init erzeugt sie neu) — T12 sieht beim ersten Klon also neue Host-Keys in `.vm/known_hosts`. Dazu: `shutdown` mit `forceStop` nach 4 min, und `list` meldet eine `role-bake`-VM nicht mehr als Leak (45 min Bake in einem Terminal machten `list` im anderen rot).
Komponente: scripts · Dateien: scripts/vm/vm.py, scripts/vm/tests/test_vm.py, scripts/tests/crabbox_bootstrap.sh (nur: `qemu-guest-agent` in die apt-Liste, `systemctl enable --now qemu-guest-agent`)
Änderung: `bake --profile p [--from <template-tag>]`: Klon der Basis (`ah-tpl-base-ubuntu`, Default) mit `ciuser`-Override `adminhelper` (offene Frage 1) und Rolle `bake`, `wait`, `sync`, `run -- 'AH_BOOTSTRAP_PROFILE=<full|server> bash scripts/tests/crabbox_bootstrap.sh'` (Timeout 2700 s), `run -- 'AH_ALLOW_REAL=1 bash scripts/tests/run.sh unit'` (Caches), Clean (`apt-get clean; cloud-init clean; docker system prune -af; truncate -s0 /etc/machine-id`), `POST status/shutdown` → Poll, `POST …/template`, Tags `ah-tpl-<p>;built-<yyyymmdd>`, Name `ah-tpl-<p>-<yyyymmdd>`, VMID aus dem oberen Hunderter des Bereichs. Bricht ein Schritt ab: Klon zerstören, Exit 74. Tests: Ablauf-Reihenfolge und Aufräumen mit Fake-API/Fake-ssh.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T10)
Abhängt von: T5, T6

### T8 — `scripts/vm/lib.sh` und Templates nachtaggen  [x] (31 hermetische Fälle, im `scripts`-Block verdrahtet)
Templates einmalig getaggt (per `vm.py`, kein neues Verb): 9400 → `ah-tpl-base-ubuntu;crabbox`, 9401 → `ah-tpl-base-debian;crabbox`, 9402 → `ah-tpl-linux-full;built-20260711;crabbox` (das Datum ist `created_at` aus der crabbox-Lease-Beschreibung des Fat-Templates). Der Bestandstag `crabbox` bleibt überall stehen. `doctor` meldet danach nur noch `FAIL templates: no template tagged for linux-server` — das backt T12.
Der Test vergleicht `vm_lane` **zeichenweise gegen `vm.py current_lane()`** über zwölf Schreibweisen: die Lane entscheidet, wessen VMs ein Sweep nehmen darf, und eine Uneinigkeit zwischen Shell- und Python-Seite ließe eine Seite wegräumen, was die andere für geleast hält. Dafür liest `vm.py` `AH_VM_STATE_DIR` jetzt auch aus der Umgebung — denselben Namen, den `lib.sh` benutzt. Der Vergleich hat sofort eine echte Divergenz gefunden: `tr -cs` staucht Bindestrich-Folgen, `tag_safe()` in `vm.py` nicht — `a-b` und `a--b` wären für die Shell **eine** Lane und für `vm.py` **zwei** gewesen, und ein `destroy --lane "$(vm_lane)"` hätte damit die VMs der falschen Lane erwischt. Das `-s` ist raus, gestrippt wird jetzt beidseitig vollständig; 31 Fälle, davon zwölf im Kreuzvergleich. Dokumentierte Grenze: `tr` zählt Bytes, Python Codepoints — Lanes sind ASCII (`lane.sh new` schreibt ohnehin nur `[a-z0-9-]`).
Komponente: scripts · Dateien: scripts/vm/lib.sh (neu, SPDX), scripts/tests/lib_vm_test.sh (neu, SPDX), scripts/tests/run.sh (nur `AH_SCRIPT_TESTS_DEFAULT`), scripts/vm/vm.py (nur `AH_VM_STATE_DIR`)
Änderung: `vm_load_env` (liest `.claude/settings.local.json` → `env`, exportiert `AH_PVE_*`/`AH_VM_*`), `vm_marker` (= `cbx_marker`), `vm_build_agent_deb` (= `cbx_build_agent_deb`), `warm_get/set/clear` auf `.vm/warm.env`, `vm_lane` (aus `.vm/lane`, Default `main`; `AH_LANE` überschreibt). Hermetischer Test für warm_*/vm_marker/vm_lane. Dazu einmalig, per `vm.py` selbst (kein neues Verb, `python3 - <<…` in der Task dokumentiert): die drei Templates im Pool taggen — Fat → `ah-tpl-linux-full;built-<Datum des Bakes>`, Basis-Ubuntu → `ah-tpl-base-ubuntu`, Basis-Debian → `ah-tpl-base-debian` (`PUT config tags` auf Templates ist per Pool-ACL erlaubt; Bestandstag `crabbox` bleibt).
Verify: bash scripts/tests/run.sh unit --strict --only scripts
Doku: keine (T10)

## C — Verdrahtung, Doku, Live-Beweis

### T9 — Lint/Test-Verdrahtung: `vm-pytest`-Schritt, ruff und shellcheck über `scripts/vm`  [x] (`run.sh quick --strict --only scripts` → `5 passed, 0 failed, 11 skipped`; `run_flags_test` 66 passed)
`ruff` über `scripts/vm` bekommt einen **eigenen** Schritt (`ruff-vm`) statt drei weiterer Pfade am bestehenden: der `scripts`-Key muss sein eigenes Python linten können, ohne `apps/` mitzuziehen, und `--only server` hat am VM-Harness nichts zu suchen. Beide neuen Ids stehen in `AH_REQUIRED_DEFAULT`.
CI hat zwei Lücken mitbekommen, die der Review fand: der `python-lint`-Job lintet jetzt auch `scripts/vm` (vorher wäre ein ruff-Verstoß dort grün durchgemergt — den fing nur `verify.sh scripts --strict` lokal), und `ops-scripts` installiert `pytest`, weil es dort `run.sh unit --strict --only scripts` fährt und der neue `vm-pytest`-Schritt sonst mit „No module named pytest" **rot** statt SKIP gewesen wäre. Der Schritt dep-gated jetzt auf `import pytest` → eine Box ohne pytest bekommt SKIP, und `--strict` macht daraus „nicht verifiziert". Beide Skip-Zweige von `ruff-vm` tragen dieselben zwei Schritt-Namen wie der Run-Zweig — sonst hinge die Schritt-Menge daran, was auf der Box installiert ist, und `run_flags_test` wäre in CI rot geworden.
[?] **Für Kevin:** Dein gitignoriertes `.devenv.sh` setzt `AH_REQUIRED` von Hand und gewinnt damit über `AH_REQUIRED_DEFAULT` — die beiden neuen Ids fehlen dort, also verlangt ein lokales `verify.sh … --strict` sie nicht. Zeile 15 sollte lauten:
`export AH_REQUIRED="ruff ruff-vm shellcheck server-pytest monitoring-pytest ca-issuer-pytest go-agent desktop-cargo desktop-ui-vitest web-vitest scripts vm-pytest"`
(Belegt: mit `env -u AH_REQUIRED` druckt der Lauf die vollständige Liste und ist grün.)
Komponente: scripts · Dateien: scripts/tests/run.sh, .github/workflows/ci.yml (Job `ops-scripts`: shellcheck-Glob `scripts/vm/*.sh` + pytest; Job `python-lint`: ruff über `scripts/vm`), scripts/tests/run_flags_test.sh (Schritt-Ids in den Erwartungen), DEVELOPMENT.md (nur die `AH_REQUIRED`-Beispielzeile)
Änderung: Schritt `vm-pytest` (`python3 -m pytest scripts/vm/tests -q`, dep-gated python3, Key `scripts`, in `AH_REQUIRED_DEFAULT`), `ruff`-Schritt deckt `scripts/vm` ab (prüfen: `ruff.toml` im Root → sonst Pfad ergänzen), shellcheck-Glob um `scripts/vm/*.sh` in `run.sh` und `ci.yml`. `verify.sh scripts --strict` fährt damit Lint + Unit von `scripts/vm`.
Verify: bash scripts/dev/verify.sh scripts --strict   und   bash scripts/tests/run_flags_test.sh
Doku: keine (intern)
Abhängt von: T2

### T10 — DEVELOPMENT.md „VMs mit vm.py" + CHANGELOG  [x] (`grep -c 'vm.py' DEVELOPMENT.md` → 18; Lint grün, `doc-smoke.py --strict` grün)
Der Abschnitt steht **vor** „Schwere Suites auf crabbox", der unverändert bleibt — bis 2b durch ist, sind beide Wege gültig. Enthalten: Konfigurationstabelle, `ssh-keygen`-Zeile, Verbtabelle, Exit-Codes 0/1/2/74 mit dem Grund für die Trennung 1/74, Tags als Lease-Wahrheit samt Auto-Reap und Fail-closed, Probe-Ablauf, die Leak-Bedingung von `list`, der TLS-Hinweis (nur `VERIFY_X509_STRICT` fällt, deshalb muss die URL ein SAN-Name sein) und die Shell-Seite. Doku in `docs/**/*.html` bleibt aus: 2a ändert kein Produktverhalten, und der Sweep dort ist ausdrücklich 2b.
Komponente: docs · Dateien: DEVELOPMENT.md, CHANGELOG.md
Änderung: Neuer Abschnitt neben „Schwere Suites auf crabbox" (der bleibt bis 2b): Konfiguration (`AH_PVE_*`, `AH_VM_*`, SSH-Schlüssel `ssh-keygen -t ed25519 -f ~/.config/adminhelper/vm_ed25519 -N ''`, CA-Datei, URL = SAN-Name), Verben mit je einem Satz, Fehlercodes 0/1/2/74, Tags als Lease-Wahrheit, `doctor`-Ausgabe, Probe-Ablauf aus der Spec, TLS-Hinweis. CHANGELOG Unreleased/Added.
Verify: grep -c 'vm.py' DEVELOPMENT.md   (≥ 5) — plus `bash scripts/tests/run.sh lint --strict --only scripts`
Doku: DEVELOPMENT.md · CHANGELOG

### T11 — Live-Beweis 2a (Probe-Klon)  [x] (alles live gefahren; `doctor` 6/7 — `linux-server` fehlt bis T12 —, Pool danach leer)
Ein Fund, der dabei behoben wurde: `run` fuhr ohne Login-Shell, und damit meldete `run.sh` auf der Box `go=no cargo=no` — `bash scripts/tests/run.sh lint` kam auf `3 passed, 0 failed, 1 skipped` statt der geforderten 0 Skips. Auf der Box liegt `go` in `/etc/profile.d/go.sh` und `cargo` in `~/.cargo/env` über `~/.profile`; ein blankes `ssh host cmd` liest beides nicht. `run` nimmt jetzt `bash -lc` (wie `bake` seit T7), `ssh` bleibt der rohe Griff. Das war der T5-Fund, der laut Notiz für T12 vorgemerkt war — er betraf schon 2a.
Komponente: scripts · Dateien: tasks/vm-core.md (Ergebnisse als Anhang), keine Codeänderung erwartet
Änderung: Nacheinander, alle Ausgaben in den Ledger-Anhang: `vm.py doctor --roles probe` → alle `ok`; `vm.py clone --profile linux-full --role probe --ttl 20m` → `VMID NAME`; `vm.py wait <vm>` → IP in < 5 min; `vm.py run <vm> --sync -- 'bash scripts/tests/run.sh lint'` → Summary `N passed, 0 failed, 0 skipped`; `vm.py snap <vm> s1` → `vm.py rollback <vm> s1 --start` → `vm.py delsnap <vm> s1`; `vm.py destroy <vm>` → `vm.py list` leer (Exit 0). Negativ: `AH_PVE_TOKEN=falsch vm.py clone …` → Exit 74, keine VM entstanden; `vm.py destroy <VMID einer VM außerhalb des Pools>` → Exit 2 und 403-frei (die VM ist nicht sichtbar); Klon mit `--ttl 1m`, 2 min warten, `vm.py list` → weg (Auto-Reap). **Soll-Text überholt:** `list` ist nebenwirkungsfrei (Bericht ohne Reap, siehe T6); gekehrt wird beim nächsten beliebigen anderen Verb — im Anhang so belegt. Rote Schritte → Fix im jeweiligen Verb-Task, dann wiederholen.
Verify: python3 scripts/vm/vm.py list   → Exit 0, keine `ah`-VM   (nach der Probe)
Doku: keine
Abhängt von: T9

### T12 — Live-Beweis Bake: `linux-server` und Rebake `linux-full`  [x] (beide Bakes grün, `doctor --roles probe` danach **vollständig ok**)
Drei Funde, die erst der echte Bake zutage gefördert hat — zwei davon hätten auch CI rot gemacht:
1. **`vm.py run … -- <cmd>` war auf Python 3.12 kaputt.** argparse lernt erst in 3.13, das `--` vor einem `nargs="*"`-Positional zu entfernen; auf der Box (Ubuntu 24.04, Python 3.12) starb genau die Syntax, die der Ledger vorschreibt, mit `unrecognized arguments: -- true`. `main()` schneidet das `--` jetzt selbst ab (`split_command`), die Testhelfer ebenso. **Der CI-Job `ops-scripts` läuft auf demselben Python** — der `vm-pytest`-Schritt aus T9 wäre dort rot geworden.
2. **Der TLS-Test setzte 3.13 voraus.** `VERIFY_X509_STRICT` ist erst ab 3.13 per Default gesetzt; die Vorab-Assertion („das Flag ist im Default an") wurde auf 3.12 zum Testfehler. Sie ist durch die portable Fassung ersetzt: gleich dem Default **minus** dem Flag — das pinnt auf beiden Pythons „strict ist aus und sonst wurde nichts angefasst".
3. **`crabbox_bootstrap.sh` installierte `ruff` ungepinnt** (Zeile 124). Das frisch gebackene Template bekam heute eine neuere ruff mit Default-Regeln, die dieses Repo nie aktiviert hat (`UP017`, `B008`, `RUF100`) — `run.sh lint` auf der Box ging rot, während Dev-Box und CI grün waren. **Das hätte jedes künftige Rebake getroffen**, nicht nur diesen Lauf. Jetzt auf `0.15.20` gepinnt, dieselbe Version, die `ci.yml` installiert, mit Kommentar auf die Kopplung (`ci.yml` ↔ `apps/server/requirements-dev.txt` ↔ Bootstrap). **Über den Ledger-Text hinaus** (T7 erlaubte an dieser Datei nur die `qemu-guest-agent`-Zeile) — ohne den Pin ist das `Verify` dieser Task aber nicht erreichbar, und die Ursache liegt genau dort.
Dazu eine Ergänzung an `bake` selbst: es meldete fertig, **bevor** sein Template in `/cluster/resources` sichtbar war, und der unmittelbar folgende `clone --profile linux-server` bekam „no template tagged" für ein Template, das es gab — der Cache-Verzug aus der T1-Aufzeichnung. `bake` wartet jetzt begrenzt (60 s) auf die eigene Sichtbarkeit und sagt es, wenn der Cache nicht nachkommt.
[?] **Für Kevin:** Das erste, mit ungepinnter ruff gebackene `linux-server`-Template **3900** bleibt stehen — `destroy` verweigert Templates bewusst. Das neue gewinnt automatisch (gleiches `built-`-Datum, höhere VMID), aber 3900 gehört von Hand gelöscht.
Nachfolge-Vorschlag für die Roadmap: ein Lockstep-Guard für den ruff-Pin (wie `toolchain-lockstep.sh` für die Go-Module), damit die drei Stellen nicht wieder auseinanderlaufen.
Komponente: scripts · Dateien: tasks/vm-core.md (Anhang), scripts/vm/vm.py (`split_command`, Sichtbarkeits-Warten), scripts/vm/tests/test_vm.py, scripts/tests/crabbox_bootstrap.sh (ruff-Pin) — `profiles.json` blieb unverändert
Änderung: `vm.py bake --profile linux-server` (~25 min) und `vm.py bake --profile linux-full` (~45 min), jeweils gefolgt von Probe-Klon → `wait` → `run -- 'bash scripts/tests/run.sh lint'` → `N passed, 0 failed, 0 skipped` → `destroy`. `doctor` zeigt danach je Profil das neue `built-<datum>` als Auswahl. Alte Templates bleiben (Kevin löscht von Hand). Ergebnis (Dauer, VMIDs, Tags) in den Anhang.
Verify: python3 scripts/vm/vm.py doctor --roles probe   → `ok templates: linux-full built-<datum>, linux-server built-<datum>, …`
Doku: keine
Abhängt von: T11

## Nachtrag — Befunde aus `/code-review high` über den Branch-Diff (alle behoben)

| Fund | Wirkung | Behebung |
|---|---|---|
| `.vm/known_hosts` mit `accept-new`, aber nie aufgeräumt | Der Pool vergibt DHCP-Adressen wieder und jedes Bake löscht `/etc/ssh/ssh_host_*` — beim zweiten Mal auf derselben IP scheitert jeder ssh-Pfad dauerhaft (`wait` 900 s in `no ssh`, `run`/`sync` bei 255), bis jemand die Datei löscht. | Kein Host-Key-Gedächtnis mehr (`StrictHostKeyChecking=no`, `UserKnownHostsFile=/dev/null`, `LogLevel=ERROR`). Gewonnen war nichts: beim ersten Kontakt wurde ohnehin jeder Schlüssel akzeptiert. |
| Der eine Retry auf dem `clone`-POST | Landet der erste Versuch und geht nur die Antwort verloren, meldet der zweite „config file already exists" — und der Pfad purgt bewusst **nicht**. Zurück bleibt eine **untaggte** VM, die `destroy` verweigert, `reap` nie sieht und `list` nur zählt. | `Infra.retried` merkt den Wiederholungsfall; nur dann wird bei „already exists" aufgeräumt. Ohne Retry bedeutet dieselbe Meldung „fremde Lane hat die VMID" — die darf nicht zerstört werden. Beide Fälle getestet. |
| Ein Selektor, der zu `""` gesäubert wird | `destroy --lane main --scenario '+++'` hätte alle Lane-VMs **ohne** `sc-`-Tag zerstört, weil der Leerwert gegen den Default verglich. | `select_vms` verweigert jetzt wie `clone` (Exit 2). |
| `free_vmid` ignorierte `high` | Bei einem Bereich schmaler als 100 VMIDs hätte es Nummern **außerhalb** des reservierten Bereichs vergeben. | `min(low + 99, high)` — das Gegenstück zu `free_template_vmid`. |
| `--extend` schrieb die Tag-Menge aus dem hinkenden Cache zurück | Ein Tag, den ein anderer Lauf in diesem Fenster gesetzt hat, wäre rückgängig gemacht worden; eine seither neu vergebene VMID hätte die Tags ihres Vorgängers bekommen, Lane inklusive. | `fresh_entry` vor dem PUT — dieselbe Regel, nach der `destroy` und `reap` schon lesen. |
| `crabbox_bootstrap.sh`: `systemctl enable qemu-guest-agent \|\| echo WARNUNG` | Der Kommentar sagte „nicht stillgelegt", der Code schluckte den Fehler — und baute damit ein Template, dessen Klone nie eine Adresse bekommen. | Schlägt jetzt hart fehl. |
| `lib.sh`: `%r` im `eval` | Ein Wert mit einfachem Anführungszeichen kippt Pythons `repr` auf doppelte — und dann expandiert die Shell `$…`, Backticks und `\` im Wert. | `shlex.quote`, mit eigenem Testfall (`/srv/it's $HOME \`id\``). |
| `vm-pytest` auf einer gebakenen Box | Der Bootstrap installierte kein pytest; bei `--only scripts` baut `run.sh` kein venv, der Schritt SKIPpt und `--strict` macht daraus Rot — auf einer Box, an der nichts falsch ist. | `pytest` gepinnt im Bootstrap, neben ruff. |

## Abschluss
- `bash scripts/tests/run.sh quick --strict` grün; `bash scripts/dev/verify.sh all --strict` grün.
- Kein Warm-Profil-Lauf auf crabbox nötig: 2a ändert weder Produktcode noch Wrapper.
- `python3 scripts/vm/vm.py list` leer; `crabbox list` leer.
- PR-Body: Probe-Ergebnisse aus T11/T12 (Dauer je Schritt), Fixture-Herkunft, offene Fragen der Spec mit Entscheidung.


## Anhang — Live-Beweis T11 (2026-09-16, Pool `adminhelper-ci`)

Alle Läufe mit `vm.py` selbst, jede VM im selben Lauf wieder zerstört; `vm.py list` endete mit `0 ours, 3 not ours`, Exit 0.

| Schritt | Ergebnis |
|---|---|
| `doctor --roles probe` | 6 von 7 `ok`, Exit **74**; `FAIL templates: no template tagged for linux-server` — das backt T12, alles andere grün. |
| `clone --profile linux-full --role probe --ttl 40m` (40 statt 20 min, damit der Lauf nicht unter mir wegreapt) | `3000 ah-probe-main-b9a4` in **6,3 s** (Linked Clone). |
| `wait 3000` | IPv4 aus dem Pool-Netz nach **32,7 s** (Agent, Adresse, SSH-Login als `crabbox` mit dem injizierten Schlüssel). |
| `sync 3000` | **25,2 s** für den Erstsync des Checkouts. |
| `run 3000 --sync -- 'bash scripts/tests/run.sh lint'` | **`6 passed, 0 failed, 0 skipped`** in 28,2 s — inklusive `ruff check (scripts/vm)` und `ruff format check (scripts/vm)` aus T9, `go=yes cargo=yes display=yes`. |
| `snap 3000 s1` · `rollback 3000 s1 --start` · `delsnap 3000 s1` | **1,3 s** · **1,3 s** · **35,5 s** — die 35 s sind der Lock-Retry, den die T1-Aufzeichnung vorhergesagt hat. |
| `destroy 3000` | **2,2 s**, danach `list` → `0 ours, 3 not ours`, Exit 0. |
| **Negativ:** falsches Token | Exit **74** (`HTTP 401`), **keine** VM entstanden — der Pool zeigte danach nur die drei Templates. |
| **Negativ:** `destroy 100` (VM außerhalb des Pools) | Exit **2**, `no VM '100' in pool adminhelper-ci` — kein 403, die VM ist für das Token nicht einmal sichtbar. |
| **Negativ:** `destroy 9402` (Template) | Exit **2**, `9402 is a template — those are Kevin's to delete, not ours`. |
| **Auto-Reap:** `--ttl 1m`, 130 s warten | `list` zeigt die VM weiter als `EXPIRED` und meldet den Leak (Exit ≠ 0) — ein Bericht hat keine Nebenwirkungen. Der nächste beliebige Verb-Aufruf kehrt sie weg, **auch wenn er selbst scheitert**: `snap 9999 s1` → Exit 2 und `vm.py: reaped expired 3000 ah-probe-main-c07a`. |


## Anhang — Live-Beweis T12 (2026-09-17, Pool `adminhelper-ci`)

Zwei Bakes plus je ein Probe-Klon, jede VM im selben Lauf zerstört.

| Schritt | Ergebnis |
|---|---|
| `bake --profile linux-server` | **22,5 min** → Template **3901** `ah-tpl-linux-server;built-20260917`, `ciuser=adminhelper`. Warmup auf der Box: `run.sh unit` → `9 passed, 0 failed, 1 skipped` (der Skip ist die Desktop-GUI, die es auf dem Server-Profil nicht gibt). |
| Probe `linux-server` | Klon 6,3 s · `wait` 41,4 s · `run.sh lint` **`6 passed, 0 failed, 0 skipped`** in 33,3 s · zerstört; 83 s im Ganzen. |
| `bake --profile linux-full` | **56,4 min** → Template **3902** `ah-tpl-linux-full;built-20260917`. Warmup: `run.sh unit` → **`10 passed, 0 failed, 0 skipped`** — ein vollständig warmes Template, alle Toolchains da. |
| Probe `linux-full` | Klon 6,3 s · `wait` 46,8 s · `run.sh lint` **`6 passed, 0 failed, 0 skipped`** in 46,1 s · zerstört; 104 s im Ganzen. |
| `doctor --roles probe` | **alle sieben `ok`**, u. a. `templates: base-debian undated (9401), base-ubuntu undated (9400), linux-full 20260917 (3902), linux-server 20260917 (3901)` und `template-config: guest agent on, bridge vmbr1, 4 template(s)`. |
| `list` | keine eigene VM; Pool trägt nur Templates. |

**Der verworfene erste Durchlauf, vollständigkeitshalber:** `bake --profile linux-server` lief in **22,8 min** durch (Template 3900), aber seine Probe war **rot** — `run.sh lint` auf der frischen Box meldete `4 passed, 2 failed, 0 skipped` mit `UP017`, `B008` und `RUF100`, weil das Template die ungepinnte, zu neue ruff trug. Genau dieser rote Lauf ist der Beleg für Fund 3. Der anschließend laufende `linux-full`-Bake wurde abgebrochen (sein Klon hätte dieselbe ruff bekommen), sein Klon von Hand weggeräumt — er trug seinen 4-h-Lease-Tag, wäre also auch vom Reaper erfasst worden. Nach dem Pin wurden beide Profile neu gebacken. `newest_template` wählt bei gleichem `built-`-Datum die höhere VMID, 3901 gewinnt also gegen 3900; 3900 gehört trotzdem von Hand gelöscht.

## Nachtrag — Befunde aus `/code-review high` über den Branch-Diff (alle behoben)

| Fund | Wirkung | Behebung |
|---|---|---|
| `.vm/known_hosts` mit `accept-new`, aber nie aufgeräumt | Der Pool vergibt DHCP-Adressen wieder und jedes Bake löscht `/etc/ssh/ssh_host_*` — beim zweiten Mal auf derselben IP scheitert jeder ssh-Pfad dauerhaft (`wait` 900 s in `no ssh`, `run`/`sync` bei 255), bis jemand die Datei löscht. | Kein Host-Key-Gedächtnis mehr (`StrictHostKeyChecking=no`, `UserKnownHostsFile=/dev/null`, `LogLevel=ERROR`). Gewonnen war nichts: beim ersten Kontakt wurde ohnehin jeder Schlüssel akzeptiert. |
| Der eine Retry auf dem `clone`-POST | Landet der erste Versuch und geht nur die Antwort verloren, meldet der zweite „config file already exists" — und der Pfad purgt bewusst **nicht**. Zurück bleibt eine **untaggte** VM, die `destroy` verweigert, `reap` nie sieht und `list` nur zählt. | `Infra.retried` merkt den Wiederholungsfall; nur dann wird bei „already exists" aufgeräumt. Ohne Retry bedeutet dieselbe Meldung „fremde Lane hat die VMID" — die darf nicht zerstört werden. Beide Fälle getestet. |
| Ein Selektor, der zu `""` gesäubert wird | `destroy --lane main --scenario '+++'` hätte alle Lane-VMs **ohne** `sc-`-Tag zerstört, weil der Leerwert gegen den Default verglich. | `select_vms` verweigert jetzt wie `clone` (Exit 2). |
| `free_vmid` ignorierte `high` | Bei einem Bereich schmaler als 100 VMIDs hätte es Nummern **außerhalb** des reservierten Bereichs vergeben. | `min(low + 99, high)` — das Gegenstück zu `free_template_vmid`. |
| `--extend` schrieb die Tag-Menge aus dem hinkenden Cache zurück | Ein Tag, den ein anderer Lauf in diesem Fenster gesetzt hat, wäre rückgängig gemacht worden; eine seither neu vergebene VMID hätte die Tags ihres Vorgängers bekommen, Lane inklusive. | `fresh_entry` vor dem PUT — dieselbe Regel, nach der `destroy` und `reap` schon lesen. |
| `crabbox_bootstrap.sh`: `systemctl enable qemu-guest-agent \|\| echo WARNUNG` | Der Kommentar sagte „nicht stillgelegt", der Code schluckte den Fehler — und baute damit ein Template, dessen Klone nie eine Adresse bekommen. | Schlägt jetzt hart fehl. |
| `lib.sh`: `%r` im `eval` | Ein Wert mit einfachem Anführungszeichen kippt Pythons `repr` auf doppelte — und dann expandiert die Shell `$…`, Backticks und `\` im Wert. | `shlex.quote`, mit eigenem Testfall (`/srv/it's $HOME \`id\``). |
| `vm-pytest` auf einer gebakenen Box | Der Bootstrap installierte kein pytest; bei `--only scripts` baut `run.sh` kein venv, der Schritt SKIPpt und `--strict` macht daraus Rot — auf einer Box, an der nichts falsch ist. | `pytest` gepinnt im Bootstrap, neben ruff. |

## Abschluss

- Nach den Review-Fixes live nachgefahren: `clone` → `wait` 40,5 s → `run -- 'echo …; id -un'` → **`adminhelper`** (der Gast-User des neuen Templates, D20) → `run --extend 2h` versetzt den `ttl-`Tag → `destroy` → `list` leer. Kein Host-Key-Gedächtnis mehr nötig, keine Warnung.
- `bash scripts/dev/verify.sh all --strict` → **16 passed, 0 failed, 0 skipped** (5 pytest-interne test-skips, Bestand); nach jedem Fix erneut gefahren.
- `bash scripts/tests/run.sh quick` → `14 passed, 0 failed, 2 skipped` ohne gesourctes `.devenv.sh`; mit Toolchain (`verify.sh all`) 0 Skips.
- Keine crabbox-Schwersuite: der Branch-Diff berührt keinen der path-gated Pfade (`apps/server`-API/Gateway, `ca-issuer`, `gateway`, `agent`, Desktop-Connect/Tunnel/Enrollment, `docker-compose*`, `Dockerfile`, `scripts/install|update`, FRP/PKI). Stattdessen sind **drei echte Bakes und drei Probe-Klone** auf echten VMs gelaufen (der erste Bake verworfen, siehe unten) — der stärkere Beweis für genau diese Änderung.
- `vm.py list` leer, `crabbox list` unberührt (crabbox wurde in diesem Vorhaben nicht angefasst).
- **CI auf PR #20: 21× pass, 1× skipping** (der from-outside-mTLS-Stack überspringt auf PRs by design). Damit sind die beiden T9-Lücken auch dort belegt: `Ops scripts` fährt den neuen `vm-pytest`-Schritt auf Python 3.12 mit dem gepinnten pytest, `Python (ruff check + format)` deckt jetzt `scripts/vm` mit ab.
- **Ehrlich vermerkt:** ein `verify.sh scripts --strict` war einmal rot (`4 passed, 1 failed`), der Wiederholungslauf grün. Rot-dann-grün ist `flaky`, nicht PASS — also aufgeklärt statt weggeklickt: Ursache war `scripts/tests/heavy_test.sh:381`, wo `git worktree list | grep w2` die **ganze** Zeile greppt und der `mktemp`-Pfad des Fixtures den Zufallssuffix enthält (`/tmp/tmp.tOAiKkw2Uv/…` trifft auf `w2`). Der T8-Reviewer hatte das als Nebenbefund benannt; da es die Evidenz dieses PRs selbst unzuverlässig macht, ist es hier behoben (exakter Pfadvergleich statt Teilstring) — **über den Ledger hinaus**, mit Begründung. `heavy_test` danach dreimal in Folge `152 passed, 0 failed`.
