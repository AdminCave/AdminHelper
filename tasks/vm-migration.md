<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Stufe 2b — vm-migration: Wrapper auf `vm.py`, crabbox-Rückbau — Task-Ledger
Status: erledigt · Branch: feature/vm-migration · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: docs/features/harness-stufe-2.md (Abschnitt 2b) und privates Roadmap-Dokument §11.4 (Umzugstabelle)
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: die Live-Beweise T10 laufen mit den neuen Wrappern im Pool; der reale Beweis der Migration ist Kevins nächster `heavy.sh weekly` nach dem Merge (gleiche Summary-Zeilen wie der letzte Lauf auf crabbox). Kein crabbox-Lauf mehr.
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Roadmap: R-0006 (Teil 2), schließt R-0025, R-0026, R-0027 · Hängt ab von: tasks/vm-core.md (gemergt) · Startbedingung aufgehoben (Kevin 2026-09-17: „ignore weekly, ich will weitermachen"); Vergleichsmaßstab für die Migration sind der Wochenlauf 2026-09-11 (`all` PASS 29/0/0) und der Capstone-Beweis 2026-09-11-2022 (22/3/0, drei Folgefehler eines crabbox-Sync-Abbruchs); der erste `heavy.sh weekly` auf `vm.py` nach dem Merge ist der Beweis
Warnung (CLAUDE.md Trigger 4): dieser Ledger ändert Harness-Dateien (`.claude/settings.json`, Skills, `CLAUDE.md`, `lane.sh`, Session-Hook) — laut Roadmap §11.4 in einem Sweep (Frage 15); am Gate bestätigt.
Regel: unveränderte Aufruf-Semantik der Wrapper — dieselben Flags, Env-Namen, Ausgabezeilen; `heavy_test.sh` und `iter_flags_test.sh` sind die Sicherung.

## A — Wrapper

### T1 — `scripts/vm/warm.sh` und `scripts/vm/reap.sh`  [x] (warm/reap auf vm.py, hermetischer Recorder-Test; `vm_py()` kam nach `lib.sh` statt viermal kopiert)
Komponente: scripts · Dateien: scripts/vm/warm.sh (neu, SPDX), scripts/vm/reap.sh (neu, SPDX), scripts/tests/vm_wrappers_test.sh (neu, SPDX; hermetisch mit Fake-`vm.py` im PATH, in `AH_SCRIPT_TESTS_DEFAULT`)
Änderung: `warm.sh <desktop|server|pond>` mit der Logik von `crabbox_warm.sh` 1:1: Reuse über `warm_get` + `vm.py list --json` (Status running), sonst `vm.py clone --profile linux-full --role desktop --ttl ${AH_WARM_TTL:-8h}` → `wait` → `run --sync -- 'AH_BOOTSTRAP_PROFILE=full bash scripts/vm/bootstrap_linux.sh'`; Server-Rolle: `linux-server`-Profil, `box_serverbox.sh`, Marker `MB_SID/MB_PTOK/MB_ADMIN_PW/MB_MONITOR_KEY` → `.vm/warm.env` (Schlüssel wie heute). `reap.sh [--lane l] [--all]`: `vm.py destroy` der warm.env-Einträge, dann `vm.py reap`, `warm_clear`. Hermetischer Test: Reuse-Pfad, Neu-Lease-Pfad, Marker-Extraktion, reap-Aufrufe (Fake-`vm.py` protokolliert Argumente).
Verify: bash scripts/tests/run.sh unit --strict --only scripts
Doku: keine (T9)

### T2 — `scripts/vm/iter.sh`  [x] (iter auf vm.py run; Flags-Test umbenannt + um die vm.py-Argumentliste und den 74-Durchgriff erweitert)
Komponente: scripts · Dateien: scripts/vm/iter.sh (neu, SPDX), scripts/tests/iter_flags_test.sh (umbenannt aus crabbox_iter_flags_test.sh, Erwartungen angepasst), scripts/tests/run.sh (`AH_SCRIPT_TESTS_DEFAULT`)
Änderung: Drei Aufrufformen wie heute (`<layer> [--strict] [--only …] [--step …]`, `--cmd '…'`, `--desktop [spec…]`); `AH_NO_SYNC`, `AH_DRY_RUN`, `AH_ONLY`/`AH_REQUIRED`-Charset-Prüfung, `AH_ALLOW_REAL=1 AH_CAPTURE=1`, `AH_HEAD`/`AH_TREE_HASH` aus `evidence_envs`; Ausführung `vm.py run <desktop> [--sync] --timeout <3000|6000> --out .ah-out --extend ${AH_WARM_TTL:-8h} -- "<ENVS> bash scripts/tests/run.sh …"`; Remote-Exit 1:1, 74 durchreichen; Box bleibt bei Fehler; `report_fail` druckt `vm.py ssh <vmid>`-Hinweis. Der Flags-Test läuft weiter über `AH_DRY_RUN=1` (Fake-`vm.py` darf nie gerufen werden).
Verify: bash scripts/tests/run.sh unit --strict --only scripts
Doku: keine (T9)
Abhängt von: T1

### T3 — `scripts/vm/bake.sh` und `scripts/vm/bootstrap_linux.sh`  [x] (Bootstrap umgezogen + sieben `|| true` hart (locale-gen, update-locale, ruff, pytest, docker enable, usermod, rustup component), bake.sh als dünner vm.py-Aufruf; `crabbox_bake.sh` gelöscht statt bis T6 mit totem Bootstrap-Pfad liegen zu lassen)
Komponente: scripts · Dateien: scripts/vm/bake.sh (neu, SPDX), scripts/vm/bootstrap_linux.sh (git mv aus scripts/tests/crabbox_bootstrap.sh; `|| true`-Stellen hart), .github/workflows/ci.yml (Job `frp-consistency`: Pfad des Bootstraps)
Änderung: `bake.sh <linux-full|linux-server>` = dünner Aufruf von `vm.py bake --profile …` mit Ergebniszeile (VMID, Tag, Dauer). Bootstrap-Umzug ohne Logikänderung außer den harten Fehlern; `vm.py bake` und `warm.sh` zeigen auf den neuen Pfad. `frp-consistency` greppt `FRP_VERSION`/SHA aus `scripts/vm/bootstrap_linux.sh`.
Verify: bash scripts/tests/run.sh lint --strict --only scripts   — plus nach dem Push: Job `frp-consistency` grün
Doku: keine (T9)

### T4 — `scripts/tests/multibox.sh` aus `crabbox_multibox.sh`  [x] (Szenario-Tag statt Pond, Teardown per `destroy --scenario`, `doctor` vor dem ersten Klon, kein Lease-Retry; hermetischer Test fand den `if ! cmd; then rc=$?`-Fehler, der eine abgelehnte Kapazitätsprüfung als Exit 0 durchgehen ließ. `heavy.sh` zieht komplett in T5 um statt hier nur den Wrapper-Namen zu tauschen — eine Datei, ein Commit)
Komponente: scripts · Dateien: scripts/tests/multibox.sh (git mv + Umbau), scripts/tests/multibox_test.sh (neu, SPDX; hermetisch mit Fake-`vm.py`, in `AH_SCRIPT_TESTS_DEFAULT`), scripts/tests/heavy.sh (nur Wrapper-Name)
Änderung: `lease()` = `vm.py clone --profile <linux-server|linux-full> --role <r> --scenario $sc --ttl 90m` + `vm.py wait`; Rollen-RAM aus `profiles.json`; vor dem ersten Klon `vm.py doctor --roles <alle geplanten>` → Exit 74 `capacity` mit Liste; Klone seriell; Teardown per `trap`: `vm.py destroy --scenario $sc` (`--keep` lässt stehen); `AH_DESKTOP_VM` (Alias `AH_DESKTOP_ID` ein Release lang) statt Slug; Summary `multibox: N ok, M failed, K skipped  (server=<ip>, agents=…)`; Flags `--agents --rpm --tunnel --desktop --moncheck --enforce --capstone --keep --strict` unverändert; kein Lease-Retry mehr (crabbox-Rennen entfällt; ein Klon-Fehler ist Exit 74 aus `vm.py`). Hermetischer Test: Reihenfolge der `vm.py`-Aufrufe, Teardown bei Fehler, `--keep`, Summary-Format.
Verify: bash scripts/tests/run.sh unit --strict --only scripts
Doku: keine (T9)
Abhängt von: T1

### T5 — `heavy.sh` und `heavy_test.sh` auf die neuen Wrapper  [x] (Wrapper-Pfade, `vm.py doctor/list --json` statt `crabbox doctor/list`, `.ah-out`, neue `infra_marker`- und `capstone_scan`-Marker, `.ah-worktrees/w2`; `recover_artifacts` entfernt — der crabbox-Tarball, den es suchte, entsteht nicht mehr. `session_status_test.sh` wandert nach T7: es prüft den Session-Hook, und der zieht dort um — sonst wäre der Test zwei Commits lang rot. `heavy_test: 161 passed`; nach Review zusätzlich: `infra_marker` trennt jetzt Ganz-Lauf-Gründe (`capacity`, `privilege`, Server-Lease) von Rollen-Abbrüchen — ein einzelner verlorener Klon im Capstone wird von `capstone_scan` der Rolle zugeordnet statt den ganzen Lauf auf UNVERIFIED zu setzen)
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh, scripts/tests/session_status_test.sh (Pfade `.vm/`, `.ah-out/`)
Änderung: `$WRAPPERS/warm.sh|iter.sh|multibox.sh` (Default-Verzeichnis `scripts/vm` bzw. `scripts/tests`), `vm.py doctor`/`vm.py list` statt `crabbox doctor`/`crabbox list`, `AH_OUT_DIR` Default `.ah-out`, `BOX_OUT` = `.ah-out/last.out.log`; `infra_marker`: crabbox-Strings (`\blease failed`, `FAIL server lease`, `rsync failed: … ambiguous`) raus, rein die `vm.py`-Gründe (`^vm.py: (capacity|no ip|no ssh|clone failed|sync failed|privilege)`) plus Exit 74 der Wrapper als Ebenen-INFRA; `capstone_scan`: Rollen aus `ah-<role>-…`-Namen und `multibox:`-Summary, Abbruch-Marker = `vm.py: … (74)` je Rolle; UNVERIFIED-Grund-Text ohne „crabbox". `heavy_test.sh`: Shims heißen `warm.sh`/`iter.sh`/`multibox.sh`, Fake-`vm.py` statt Fake-`crabbox`, Fixture-Strings angepasst; Fallzahl bleibt ≥ 152.
Verify: bash scripts/tests/run.sh unit --strict --only scripts
Doku: keine (T9)
Abhängt von: T2, T4

## B — Sweep

### T6 — Rollen-Skripte, Debug, Ausgabeverzeichnis, Excludes  [x] (acht `git mv` + `. scripts/vm/lib.sh`/`vm_marker`/`vm_build_agent_deb`/Bootstrap-Pfad, `.ah-out` überall, `.crabbox*` aus `.gitignore` und `rsync-exclude.txt`, `.crabbox.yaml`/`crabbox.yml`/`.agents/skills/crabbox/` gelöscht, dazu die toten `crabbox_warm|reap|iter.sh`. Zwei Abweichungen: `verify_test.sh` musste mit (seine Fixtures hängen an `verify.sh`s Ausgabeverzeichnis, das hier umzieht — sonst zwei Commits rot), und `test_vm.py`s Exclude-Test verglich gegen `.crabbox.yaml`; er prüft jetzt die Eigenschaft selbst gegen den Index: kein Exclude verdeckt getrackte Quelle. **Verify nur teilweise leer:** `git grep -l 'crabbox_' -- scripts apps` zeigt noch `scripts/dev/lane.sh` und `scripts/tests/crabbox_lib.sh` — die Lib hat mit `lane.sh` ihren letzten Nutzer, beide ziehen in T7 um. Der Ledger plant das so; die T6-Verify-Zeile kann deshalb erst nach T7 leer sein. Dritte Abweichung: `.crabbox/` und `.crabbox-out/` bleiben **ignoriert** statt aus `.gitignore` zu fliegen — das Repo ist öffentlich, `.crabbox/` trägt unredigierte Failure-Bundles, und jede nicht aufgeräumte Box würde ihre Reste sonst in `tree-hash.sh` einrechnen. Kommentar im `.gitignore` sagt, dass der Block mit den beiden Verzeichnissen verschwindet. Nach dem Review zusätzlich: die beiden Verzeichnisse stehen aus demselben Grund wieder in `rsync-exclude.txt` — ohne sie reisen sie auf jede Box und ins nächste Template. Dort ist jetzt auch `.claude/settings.local.json` ausgeschlossen: eine Wegwerf-VM braucht die lokale Provider-Konfiguration nicht, und `bake` hätte sie ins Template geschrieben. Der Exclude-Test prüft slash-lose Muster jetzt gegen jedes Pfadsegment — rsync matcht sie in jeder Tiefe, ein Präfix-Vergleich hätte `apps/agent/dist/…` durchgewunken)
Komponente: scripts · Dateien: scripts/tests/box_{server,desktop,agent,agentbox_rpm,tunnel,visitor,moncheck}box.sh (git mv), scripts/tests/box_debug.sh (git mv), scripts/tests/run.sh (`AH_OUT_DIR` Default `.ah-out`, Kommentare), scripts/dev/verify.sh:69, scripts/dev/tree-hash.sh:31-33, apps/desktop/e2e/wdio.conf.js:22, scripts/tests/desktop_e2e_misc.sh, sse_push_e2e.sh, lib_e2e_stack.sh, apps/desktop/e2e/test/specs/{enroll-form,theme-toggle}.live.js (Kommentare), .gitignore (`.crabbox*` raus), .crabbox.yaml (gelöscht), .github/workflows/crabbox.yml (gelöscht), .agents/skills/crabbox/ (gelöscht)
Änderung: Umbenennung ohne Logikänderung; einzige Codeänderung in den Rollen-Skripten `. scripts/vm/lib.sh` und `vm_marker`/`vm_build_agent_deb`; `scripts/vm/rsync-exclude.txt` ist bereits die Exclude-Wahrheit (2a).
Verify: bash scripts/tests/run.sh unit --strict --only scripts   und   git grep -l 'crabbox_' -- scripts apps   (leer)
Doku: keine (T9)
Abhängt von: T3

### T7 — Harness: `lane.sh`, Session-Hook, Allowlist, Skills  [x] (lane.sh schreibt `.vm/lane` und reapt über `reap.sh --lane` mit dem State-Dir der Lane; Hook auf `.vm`/`.ah-out`; `/vm`-Skill neu, `/test` neu gefasst, die drei anderen Skills und beide Regeln nachgezogen; `crabbox_lib.sh` gelöscht, damit ist `git grep -l 'crabbox_' -- scripts apps` leer. Allowlist wie D17: alle vier Einträge in `allow`. Eine Zeile mehr in `ask`, die D17 nicht kennen konnte: `bootstrap_linux.sh` ist erst in T3 nach `scripts/vm/` gezogen und damit neu vom Glob gedeckt — es ist das einzige Skript dort, das die Maschine verändert, auf der es läuft (sudo apt, Docker, usermod), und die Dev-Box hat bewusst kein Docker. Zweite Verify-Zeile `git grep -il crabbox -- .claude scripts/dev` ist bis auf `scripts/dev/tree-hash.sh` leer — dort steht `.crabbox-out` absichtlich weiter im `git rm --cached`-Aufruf (T6-Entscheidung). `session_status_test.sh` aus T5 hier mit erledigt. Nach dem Review: der Slug-Guard gilt jetzt für beide Verben — `done` reapt nach Lane, ein Slug, den nur `new` ablehnt, hätte die falsche Lane gekehrt)
Komponente: .claude · Dateien: scripts/dev/lane.sh, scripts/dev/hooks/session-status.sh, .claude/settings.json, .claude/skills/vm/SKILL.md (neu), .claude/skills/test/SKILL.md (Neufassung „Testen auf VMs"), .claude/skills/{feature-build,feature-plan,feature-review}/SKILL.md, .claude/rules/{testing,release}.md
Änderung: `lane.sh new` schreibt `.vm/lane`, `lane.sh done` ruft `vm.py reap --lane <slug>` (kein `command -v crabbox`, kein `cbx_load_env`), `lane.sh list` liest `.vm/warm.env`; Hook liest `.vm/warm.env` und `.ah-out`; Allowlist: 13 crabbox-Einträge raus, rein `Bash(python3 scripts/vm/vm.py *)`, `Bash(bash scripts/vm/*.sh *)`, `Bash(bash scripts/tests/multibox.sh *)`, `Bash(bash scripts/tests/heavy.sh *)` (D17); `/vm`-Skill (Verben, Fehlercodes, Regeln: nie Templates löschen, nie außerhalb des Pools, `list` nach jedem Lauf); `/test` neu geschrieben um `warm.sh`/`iter.sh`/`multibox.sh`; die drei anderen Skills und die zwei Regeln: Pfade und Begriffe (`Fast-Suite: vm`).
Verify: bash scripts/tests/run.sh unit --strict --only scripts   (session_status_test, verify_test) und   git grep -il crabbox -- .claude scripts/dev   (leer)
Doku: keine (die Skills sind die Doku)
Abhängt von: T6

### T8 — Sweep der Restfundstellen  [x] (fünf Kommentare in build-deb.sh, ca-issuer/conftest.py, release.yml, upgrade_path_test.sh, e2e/README.md; `run_flags_test.sh` und `verify_test.sh` aus der Dateiliste waren in T6/T7 schon mit erledigt. Nach dem Review drei weitere: `vm.py` und `test_vm.py` behaupteten, das Fat-Template heiße noch `crabbox` — der Rebake ist laut `tasks/vm-core.md` T12 gelaufen, die Kommentare waren damit schlicht falsch. Und `docs/features/harness-stufe-2.md` ist die AKTIVE Spec, keine Historie: sie schrieb `git grep -il crabbox` → leer als Abnahmekriterium fest und hätte 2b damit nie abnehmbar gemacht — dort steht jetzt die Ausschlussliste mit ihren vier Gründen. **Die Verify-Zeile stimmt so nicht und kann es nicht:** `git grep -il crabbox` ist nach T9 nicht leer, sondern hält genau vier Klassen, die bleiben müssen — (1) `.gitignore`, `tree-hash.sh`, `rsync-exclude.txt`: die bewusste Behandlung der Altverzeichnisse aus T6; (2) `scripts/vm/tests/**`: aufgezeichnete Proxmox-Antworten — sie zu ändern hieße, die Tests lügen zu lassen; (3) `docs/features/*.md` und die abgeschlossenen `tasks/*.md`: Historie, die laut `.claude/rules/testing.md` stehen bleibt; (4) dieser Ledger selbst. Verify daher: `git grep -il crabbox -- wie in der T9-Zeile unten (die abgeschlossenen Ledger einzeln, `tasks/README.md` ausdrücklich nicht)` — nach T9 leer)
Komponente: scripts · Dateien: scripts/tests/{run_flags,verify,upgrade_path}_test.sh, apps/agent/build-deb.sh, apps/ca-issuer/tests/conftest.py, .github/workflows/release.yml:113, apps/desktop/e2e/README.md
Änderung: Kommentare und Pfade; keine Logik.
Verify: git grep -il crabbox mit der Pathspec aus T9 (die abgeschlossenen Ledger einzeln, `tasks/README.md` ausdrücklich nicht)   (leer)
Doku: keine
Abhängt von: T7

### T9 — Doku-Sweep  [x] (CLAUDE.md §2 Pool `adminhelper-ci` und §8 neu, AUTONOMOUS.md, tasks/README.md, DEVELOPMENT.md, beide `cicd.html`, CHANGELOG mit Changed + Removed. **Zusammen mit T8 in EINEM Commit**, entgegen `Commit-Granularität: pro Task`: der T8-Review verlangte die Korrektur des Abnahmekriteriums, und das steht in `docs/features/harness-stufe-2.md` — einer Datei, die T9 ohnehin anfasst. Ein Split hätte einen Commit mit halb korrigierter Spec erzeugt. Nach dem Review drei Stellen, die das Wort `crabbox` gar nicht enthielten und deshalb durch jeden grep fielen: der w2-Absatz beider `cicd.html` sprach weiter von einem Pond `ah-warm-w2`, DEVELOPMENT.md führte den toten Marker `rsync failed: … ambiguous remote state`, und beide Doku-Dateien versprachen, `destroy` sei lane-gebunden — ist es nicht, `select_vms` nimmt jede genannte VMID; lane-gebunden sind `reap`, der Auto-Sweep und die Leak-Prüfung)
Komponente: docs · Dateien: CLAUDE.md (§2 Pool `adminhelper-ci`, §8 „Testen auf VMs"), AUTONOMOUS.md, tasks/README.md, DEVELOPMENT.md (Abschnitte „Schwere Suites auf crabbox" und „Wochenlauf" ersetzt; Abschnitt aus 2a wird der Hauptabschnitt), docs/developer/cicd.html + docs/en/developer/cicd.html (Aggregator-/Wochenlauf-Abschnitte), CHANGELOG.md (Changed: Wrapper auf vm.py; Removed: crabbox)
Änderung: Begriffe, Pfade, Aufrufe; Pool-Name in CLAUDE.md auf `adminhelper-ci` (D20).
Verify: git grep -il crabbox -- ':!CHANGELOG.md' ':!docs/index.html' ':!docs/en/index.html' ':!docs/features' ':!tasks/harness-stufe-1.md' ':!tasks/harness-stufe-3.md' ':!tasks/harness-stufe-3b.md' ':!tasks/harness-stufe-8a.md' ':!tasks/dependency-refresh.md' ':!tasks/merker-cleanup.md' ':!tasks/admincave-design-adoption.md' ':!tasks/vm-core.md' ':!tasks/vm-migration.md' ':!scripts/vm/tests' ':!.gitignore' ':!scripts/dev/tree-hash.sh' ':!scripts/vm/rsync-exclude.txt'   (leer — `tasks/README.md` ist bewusst NICHT ausgeschlossen, es ist T9-Pflicht) und   python3 scripts/dev/doc-smoke.py --strict
Doku: alle genannten
Abhängt von: T8

## D — Aus dem Branch-Review

### T11 — Fünf Funde des `/code-review` über den Branch-Diff  [x]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh, scripts/dev/lane.sh, scripts/vm/iter.sh, Mode-Bits von multibox.sh + iter_flags_test.sh
Änderung: (1) `capstone_scan` nannte die Visitor-Rolle `visitor`, `role_of_lease_fail` filet ihren FAIL aber unter `tunnel` — ein verlorener Visitor-Klon wäre als Produktfehler gemeldet worden, genau die Verwechslung, die der Scan verhindern soll. Beide Hälften sagen jetzt `tunnel` (wie vorher `role_of_slug`); Mutations-Probe: ohne den Fix `rc=1` und `…,fail,` statt `…,infra,`. (2) `lane.sh done` konnte eine Lane, deren Worktree von Hand entfernt wurde, nicht mehr aufräumen — ohne warm.env zerstört `reap.sh` nichts, `vm.py reap` nimmt nur Abgelaufenes, und die Schluss-Liste bricht mit 74 ab. DEVELOPMENT.md versprach das Gegenteil; jetzt `vm.py destroy --lane` im Else-Zweig. (3) `vm.py run` fügt sein Kommando mit Leerzeichen zusammen — ein leeres `server_admin_pw` wäre verschwunden und der Monitor-Key in seine Position gerutscht. Die Desktop-Etappe von `iter.sh` übergibt jetzt einen gequoteten String wie `multibox.sh`. (4) Im `weekly` bleibt die 6-GB-Desktop-Box des `all`-Laufs stehen, während der Capstone seit T4 vorab Kapazität für sieben Rollen prüft — `heavy.sh` reicht sie jetzt als `AH_DESKTOP_VM` weiter, das nimmt die Desktop-Rolle aus der Summe und spart den Re-Bootstrap. (5) Zwei Umbenennungen hatten das Exec-Bit verloren.
Nachtrag aus dem Review dieses Fixes, drei weitere: (6) die Übergabe der Warm-Box hing nicht am Modus — `warm.env` überlebt Läufe, ein `heavy.sh capstone` hätte einen toten oder fremden Eintrag ungeprüft weitergereicht, und `vm.py: no VM … in pool` matcht keine Abbruch-Regel: derselbe Falschbefund wie Fund 1, nur an neuer Stelle. Jetzt `[ "$MODE" = weekly ]`. (7) `lane.sh done` räumte den Branch nicht ab — ein von Hand gelöschtes Verzeichnis lässt den Worktree registriert, `git branch -d` verweigert auch bei gemergtem Branch, und die Meldung log über den Grund; `git worktree prune` dazu. (8) `heavy_test.sh` leitete als einziges `AH_VM_STATE_DIR` nicht ins Fixture um — `warm_get` las das echte `.vm/warm.env` des Repos, der grüne Lauf ging also nur durch den leeren Zweig, und auf einer Box mit warmem Desktop hätte dieselbe Suite einen anderen Pfad genommen. Dazu zwei Nits: die vierte Abbruch-Form `clone printed no VMID for role` und ein Testfall für die Desktop-Argumentliste. Drei Mutations-Proben bestätigt (Visitor-Rolle, weekly-Gate, leeres Credential).
Verify: bash scripts/tests/run.sh unit --strict --only scripts   (`heavy_test` 166, `iter_flags_test` 24)
Doku: keine (die DEVELOPMENT.md-Zusage stimmt jetzt wirklich)

## C — Live-Beweis

### T10 — Live-Beweis 2b  [x] (alles live im Pool `adminhelper-ci` gefahren, 2026-09-18; Messwerte im Anhang)
Komponente: scripts · Dateien: tasks/vm-migration.md (Anhang)
Änderung: `bash scripts/vm/warm.sh desktop` (einmal, Dauer notieren); `bash scripts/vm/iter.sh quick` zweimal (erster ≤ 15 min, zweiter ≤ 5 min); absichtlich roter Test auf Wegwerf-Branch → `iter.sh` Exit 1, Box steht; `AH_WARM_TTL=20m bash scripts/vm/warm.sh desktop` auf einer zweiten Lane + 25 min + `vm.py list` → Box weg; `bash scripts/tests/multibox.sh --agents 1` → `multibox: 5 ok, 0 failed, 0 skipped`; `bash scripts/dev/lane.sh new probe` → `warm.sh desktop` → `iter.sh quick` → `lane.sh done probe` räumt; am Ende `vm.py list` leer und `crabbox list` leer. Ergebnisse in den Anhang und PR-Body.
Verify: python3 scripts/vm/vm.py list   → Exit 0, leer
Doku: keine
Abhängt von: T9

## Abschluss
- `bash scripts/tests/run.sh quick --strict` grün; `bash scripts/dev/verify.sh all --strict` grün; CI grün inkl. `frp-consistency` und `ops-scripts`.
- Kevin nach dem Merge: `heavy.sh weekly` → Summary-Zeilen wie der letzte crabbox-Lauf; dann `crabbox list` leer → Binary deinstallieren; crabbox-Einträge aus `.claude/settings.local.json` entfernen; Roadmap R-0025/26/27 schließen.

## Anhang: Live-Beweis T10 (2026-09-18, Pool `adminhelper-ci`)

| Probe | Ergebnis | Ledger-Erwartung |
|---|---|---|
| `warm.sh desktop` | VM 3000 `ah-desktop-main-5834`, **113 s** | einmal, Dauer notieren ✓ |
| `iter.sh quick --strict` #1 | `run.sh[quick]: 16 passed, 0 failed, 0 skipped, 6 test-skips, 0 reruns` — **787 s** | ≤ 15 min ✓ |
| `iter.sh quick --strict` #2 | dieselbe Summary — **544 s**, Kopfzeile `reuse desktop box 3000 (already warm)` | ≤ 5 min ✗ (siehe unten) |
| Absichtlich roter Lauf | **Exit 1**, Box bleibt stehen, Hinweis `python3 scripts/vm/vm.py ssh 3000` | Exit 1, Box steht ✓ |
| `reap.sh` | Box zerstört, warm.env geleert, `0 ours, 5 not ours` | — |
| `multibox.sh --agents 1` | `multibox: 9 ok, 0 failed, 1 skipped  (server=192.168.250.176, agents=3001)` — **426 s**, Teardown über `sc=mb-1352682` vollständig | `5 ok, 0 failed, 0 skipped` ✗ (siehe unten) |
| `lane.sh new probe` | `.vm/lane` = `probe`, `.devenv.sh` Symlink, `settings.local.json` Kopie | ✓ |
| Lane-Warm-Box | `ah-desktop-probe-24c0`, Tag `lane=probe`, **96 s**; der Haupt-Checkout meldet sie **nicht** als Leak | Lane-Isolation ✓ |
| `iter.sh lint --strict` in der Lane | `run.sh[lint]: 6 passed, 0 failed, 0 skipped` — **30 s** | statt `quick`: der Haupt-Lane-Lauf hat `quick` schon zweimal bewiesen |
| TTL-Ablauf | `AH_WARM_TTL=3m` → Frist lief ab, `list` zeigt `EXPIRED` (ein Bericht räumt bewusst nicht auf), `vm.py reap` → `reaped 3000 ah-desktop-probe-24c0 (lane probe)`, danach `0 ours` | Box weg ✓ |
| `lane.sh done probe` | `destroy` meldet, die VM sei nicht mehr im Pool (der Reaper war schneller), und bricht **nicht** ab; `reap expired` leer, Liste leer, Worktree entfernt, Branch gelöscht | räumt ✓ |

**Drei Abweichungen von den Ledger-Zahlen, ohne Schönrechnen:**

1. **Zweite Iteration 544 s statt ≤ 5 min.** Der `quick`-Layer fährt auf der Box den kompletten Skript-Block mit
   (allein `heavy_test` mit 166 Fällen), und der ist nicht cache-abhängig. Die Ersparnis von 31 % steckt in Cargo
   und npm. Die Ledger-Zahl war für einen engeren Umfang kalibriert, nicht für `quick` über alle Komponenten.
2. **`multibox: 9 ok` statt `5 ok`.** Die Assertion-Zahl im Ledger war veraltet; seit Stufe 3 melden mehr Guards
   über `ok()`. Der eine SKIP ist der MTLS_ENFORCE-Guard, der ohne `--enforce` korrekt übersprungen wird —
   genau deshalb laufen Teilläufe laut `.claude/rules/testing.md` ohne `--strict`. **0 failed** ist die Aussage.
3. **Die Lane forkt von `main`.** `lane.sh new` legt den Worktree auf `main` an — dort gibt es `scripts/vm/warm.sh`
   noch nicht, das ist ja dieser Branch. Für die Probe wurde der Worktree auf den Branch-Stand detacht. Kein
   Fehler von `lane.sh`, sondern eine Eigenschaft der Reihenfolge: der erste echte Lane-Lauf auf `vm.py` ist
   möglich, sobald 2b gemergt ist.

**Nebenbefunde, die der Lauf bestätigt hat:**
- Der Gast-User ist **`adminhelper`** (`/home/adminhelper/adminhelper/…`) — der Rebake aus `vm-core` T12 hat
  gegriffen, die in T8 korrigierten Kommentare stimmen.
- Eine frisch geklonte Box gilt als „leaked", bis der Bootstrap den Slot beansprucht (T1-Entwurf, live gesehen).
- `doctor --roles server,agent` läuft **vor** dem ersten Klon: `16187 MiB free - 4096 reserve - 0 owed - 6144
  für server,agent = 5947 MiB`. Unter crabbox gab es diese Vorabprüfung nicht.

Der Pool war am Ende leer: `0 ours, 5 not ours` — die fünf fremden VMs (Kevins Homelab) blieben über den ganzen
Lauf unangetastet.

**Ein neuer Fund (Roadmap-Zeile R-0049, nicht in diesem Branch behoben):** `iter.sh` verlängert die Frist mit seinem
eigenen `AH_WARM_TTL`-Default (8h), nicht mit der Frist, mit der die Box gewärmt wurde. Eine bewusst kurzlebige
Box (`AH_WARM_TTL=20m warm.sh desktop`) wird bei der nächsten Iteration still zur 8-Stunden-Box, solange der
Aufrufer die Variable nicht wiederholt. Live gesehen: 18m → 7h58m nach einem `iter.sh lint`.

## Aus 2a mitgebracht (T8-Review)
- `scripts/vm/lib.sh` und `scripts/tests/crabbox_lib.sh` definieren beide `warm_get/set/clear` — gleiche Namen, verschiedene Dateien (`.vm/warm.env` vs. `.crabbox/warm.env`). Heute sourct nichts beide. Beim Umbau von `scripts/dev/lane.sh` (das heute `crabbox_lib.sh` sourct) darauf achten: wer beide sourct, liest still die falsche Datei.
- ~~`scripts/tests/heavy_test.sh:381` Flake~~ — **in 2a behoben** (Commit zu T12): der Teilstring-Vergleich ist durch den exakten Pfad ersetzt, nachdem der Flake einen `verify.sh`-Lauf dieses Vorhabens rot gemacht hatte. Keine Roadmap-Zeile mehr nötig.
