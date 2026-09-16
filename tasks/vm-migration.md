<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Stufe 2b — vm-migration: Wrapper auf `vm.py`, crabbox-Rückbau — Task-Ledger
Status: geplant · Branch: feature/vm-migration · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: docs/features/harness-stufe-2.md (Abschnitt 2b) und privates Roadmap-Dokument §11.4 (Umzugstabelle)
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: die Live-Beweise T10 laufen mit den neuen Wrappern im Pool; der reale Beweis der Migration ist Kevins nächster `heavy.sh weekly` nach dem Merge (gleiche Summary-Zeilen wie der letzte Lauf auf crabbox). Kein crabbox-Lauf mehr.
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Roadmap: R-0006 (Teil 2), schließt R-0025, R-0026, R-0027 · Hängt ab von: tasks/vm-core.md (gemergt) · Startbedingung: zwei grüne Wochenlauf-Reports auf crabbox als Vergleichsmaßstab (Spec, offene Frage 5)
Warnung (CLAUDE.md Trigger 4): dieser Ledger ändert Harness-Dateien (`.claude/settings.json`, Skills, `CLAUDE.md`, `lane.sh`, Session-Hook) — laut Roadmap §11.4 in einem Sweep (Frage 15); am Gate bestätigt.
Regel: unveränderte Aufruf-Semantik der Wrapper — dieselben Flags, Env-Namen, Ausgabezeilen; `heavy_test.sh` und `iter_flags_test.sh` sind die Sicherung.

## A — Wrapper

### T1 — `scripts/vm/warm.sh` und `scripts/vm/reap.sh`  [ ]
Komponente: scripts · Dateien: scripts/vm/warm.sh (neu, SPDX), scripts/vm/reap.sh (neu, SPDX), scripts/tests/vm_wrappers_test.sh (neu, SPDX; hermetisch mit Fake-`vm.py` im PATH, in `AH_SCRIPT_TESTS_DEFAULT`)
Änderung: `warm.sh <desktop|server|pond>` mit der Logik von `crabbox_warm.sh` 1:1: Reuse über `warm_get` + `vm.py list --json` (Status running), sonst `vm.py clone --profile linux-full --role desktop --ttl ${AH_WARM_TTL:-8h}` → `wait` → `run --sync -- 'AH_BOOTSTRAP_PROFILE=full bash scripts/vm/bootstrap_linux.sh'`; Server-Rolle: `linux-server`-Profil, `box_serverbox.sh`, Marker `MB_SID/MB_PTOK/MB_ADMIN_PW/MB_MONITOR_KEY` → `.vm/warm.env` (Schlüssel wie heute). `reap.sh [--lane l] [--all]`: `vm.py destroy` der warm.env-Einträge, dann `vm.py reap`, `warm_clear`. Hermetischer Test: Reuse-Pfad, Neu-Lease-Pfad, Marker-Extraktion, reap-Aufrufe (Fake-`vm.py` protokolliert Argumente).
Verify: bash scripts/tests/run.sh unit --strict --only scripts
Doku: keine (T9)

### T2 — `scripts/vm/iter.sh`  [ ]
Komponente: scripts · Dateien: scripts/vm/iter.sh (neu, SPDX), scripts/tests/iter_flags_test.sh (umbenannt aus crabbox_iter_flags_test.sh, Erwartungen angepasst), scripts/tests/run.sh (`AH_SCRIPT_TESTS_DEFAULT`)
Änderung: Drei Aufrufformen wie heute (`<layer> [--strict] [--only …] [--step …]`, `--cmd '…'`, `--desktop [spec…]`); `AH_NO_SYNC`, `AH_DRY_RUN`, `AH_ONLY`/`AH_REQUIRED`-Charset-Prüfung, `AH_ALLOW_REAL=1 AH_CAPTURE=1`, `AH_HEAD`/`AH_TREE_HASH` aus `evidence_envs`; Ausführung `vm.py run <desktop> [--sync] --timeout <3000|6000> --out .ah-out --extend ${AH_WARM_TTL:-8h} -- "<ENVS> bash scripts/tests/run.sh …"`; Remote-Exit 1:1, 74 durchreichen; Box bleibt bei Fehler; `report_fail` druckt `vm.py ssh <vmid>`-Hinweis. Der Flags-Test läuft weiter über `AH_DRY_RUN=1` (Fake-`vm.py` darf nie gerufen werden).
Verify: bash scripts/tests/run.sh unit --strict --only scripts
Doku: keine (T9)
Abhängt von: T1

### T3 — `scripts/vm/bake.sh` und `scripts/vm/bootstrap_linux.sh`  [ ]
Komponente: scripts · Dateien: scripts/vm/bake.sh (neu, SPDX), scripts/vm/bootstrap_linux.sh (git mv aus scripts/tests/crabbox_bootstrap.sh; `|| true`-Stellen hart), .github/workflows/ci.yml (Job `frp-consistency`: Pfad des Bootstraps)
Änderung: `bake.sh <linux-full|linux-server>` = dünner Aufruf von `vm.py bake --profile …` mit Ergebniszeile (VMID, Tag, Dauer). Bootstrap-Umzug ohne Logikänderung außer den harten Fehlern; `vm.py bake` und `warm.sh` zeigen auf den neuen Pfad. `frp-consistency` greppt `FRP_VERSION`/SHA aus `scripts/vm/bootstrap_linux.sh`.
Verify: bash scripts/tests/run.sh lint --strict --only scripts   — plus nach dem Push: Job `frp-consistency` grün
Doku: keine (T9)

### T4 — `scripts/tests/multibox.sh` aus `crabbox_multibox.sh`  [ ]
Komponente: scripts · Dateien: scripts/tests/multibox.sh (git mv + Umbau), scripts/tests/multibox_test.sh (neu, SPDX; hermetisch mit Fake-`vm.py`, in `AH_SCRIPT_TESTS_DEFAULT`), scripts/tests/heavy.sh (nur Wrapper-Name)
Änderung: `lease()` = `vm.py clone --profile <linux-server|linux-full> --role <r> --scenario $sc --ttl 90m` + `vm.py wait`; Rollen-RAM aus `profiles.json`; vor dem ersten Klon `vm.py doctor --roles <alle geplanten>` → Exit 74 `capacity` mit Liste; Klone seriell; Teardown per `trap`: `vm.py destroy --scenario $sc` (`--keep` lässt stehen); `AH_DESKTOP_VM` (Alias `AH_DESKTOP_ID` ein Release lang) statt Slug; Summary `multibox: N ok, M failed, K skipped  (server=<ip>, agents=…)`; Flags `--agents --rpm --tunnel --desktop --moncheck --enforce --capstone --keep --strict` unverändert; kein Lease-Retry mehr (crabbox-Rennen entfällt; ein Klon-Fehler ist Exit 74 aus `vm.py`). Hermetischer Test: Reihenfolge der `vm.py`-Aufrufe, Teardown bei Fehler, `--keep`, Summary-Format.
Verify: bash scripts/tests/run.sh unit --strict --only scripts
Doku: keine (T9)
Abhängt von: T1

### T5 — `heavy.sh` und `heavy_test.sh` auf die neuen Wrapper  [ ]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh, scripts/tests/session_status_test.sh (Pfade `.vm/`, `.ah-out/`)
Änderung: `$WRAPPERS/warm.sh|iter.sh|multibox.sh` (Default-Verzeichnis `scripts/vm` bzw. `scripts/tests`), `vm.py doctor`/`vm.py list` statt `crabbox doctor`/`crabbox list`, `AH_OUT_DIR` Default `.ah-out`, `BOX_OUT` = `.ah-out/last.out.log`; `infra_marker`: crabbox-Strings (`\blease failed`, `FAIL server lease`, `rsync failed: … ambiguous`) raus, rein die `vm.py`-Gründe (`^vm.py: (capacity|no ip|no ssh|clone failed|sync failed|privilege)`) plus Exit 74 der Wrapper als Ebenen-INFRA; `capstone_scan`: Rollen aus `ah-<role>-…`-Namen und `multibox:`-Summary, Abbruch-Marker = `vm.py: … (74)` je Rolle; UNVERIFIED-Grund-Text ohne „crabbox". `heavy_test.sh`: Shims heißen `warm.sh`/`iter.sh`/`multibox.sh`, Fake-`vm.py` statt Fake-`crabbox`, Fixture-Strings angepasst; Fallzahl bleibt ≥ 152.
Verify: bash scripts/tests/run.sh unit --strict --only scripts
Doku: keine (T9)
Abhängt von: T2, T4

## B — Sweep

### T6 — Rollen-Skripte, Debug, Ausgabeverzeichnis, Excludes  [ ]
Komponente: scripts · Dateien: scripts/tests/box_{server,desktop,agent,agentbox_rpm,tunnel,visitor,moncheck}box.sh (git mv), scripts/tests/box_debug.sh (git mv), scripts/tests/run.sh (`AH_OUT_DIR` Default `.ah-out`, Kommentare), scripts/dev/verify.sh:69, scripts/dev/tree-hash.sh:31-33, apps/desktop/e2e/wdio.conf.js:22, scripts/tests/desktop_e2e_misc.sh, sse_push_e2e.sh, lib_e2e_stack.sh, apps/desktop/e2e/test/specs/{enroll-form,theme-toggle}.live.js (Kommentare), .gitignore (`.crabbox*` raus), .crabbox.yaml (gelöscht), .github/workflows/crabbox.yml (gelöscht), .agents/skills/crabbox/ (gelöscht)
Änderung: Umbenennung ohne Logikänderung; einzige Codeänderung in den Rollen-Skripten `. scripts/vm/lib.sh` und `vm_marker`/`vm_build_agent_deb`; `scripts/vm/rsync-exclude.txt` ist bereits die Exclude-Wahrheit (2a).
Verify: bash scripts/tests/run.sh unit --strict --only scripts   und   git grep -l 'crabbox_' -- scripts apps   (leer)
Doku: keine (T9)
Abhängt von: T3

### T7 — Harness: `lane.sh`, Session-Hook, Allowlist, Skills  [ ]
Komponente: .claude · Dateien: scripts/dev/lane.sh, scripts/dev/hooks/session-status.sh, .claude/settings.json, .claude/skills/vm/SKILL.md (neu), .claude/skills/test/SKILL.md (Neufassung „Testen auf VMs"), .claude/skills/{feature-build,feature-plan,feature-review}/SKILL.md, .claude/rules/{testing,release}.md
Änderung: `lane.sh new` schreibt `.vm/lane`, `lane.sh done` ruft `vm.py reap --lane <slug>` (kein `command -v crabbox`, kein `cbx_load_env`), `lane.sh list` liest `.vm/warm.env`; Hook liest `.vm/warm.env` und `.ah-out`; Allowlist: 13 crabbox-Einträge raus, rein `Bash(python3 scripts/vm/vm.py *)`, `Bash(bash scripts/vm/*.sh *)`, `Bash(bash scripts/tests/multibox.sh *)`, `Bash(bash scripts/tests/heavy.sh *)` (D17); `/vm`-Skill (Verben, Fehlercodes, Regeln: nie Templates löschen, nie außerhalb des Pools, `list` nach jedem Lauf); `/test` neu geschrieben um `warm.sh`/`iter.sh`/`multibox.sh`; die drei anderen Skills und die zwei Regeln: Pfade und Begriffe (`Fast-Suite: vm`).
Verify: bash scripts/tests/run.sh unit --strict --only scripts   (session_status_test, verify_test) und   git grep -il crabbox -- .claude scripts/dev   (leer)
Doku: keine (die Skills sind die Doku)
Abhängt von: T6

### T8 — Sweep der Restfundstellen  [ ]
Komponente: scripts · Dateien: scripts/tests/{run_flags,verify,upgrade_path}_test.sh, apps/agent/build-deb.sh, apps/ca-issuer/tests/conftest.py, .github/workflows/release.yml:113, apps/desktop/e2e/README.md
Änderung: Kommentare und Pfade; keine Logik.
Verify: git grep -il crabbox -- ':!CHANGELOG.md' ':!docs/index.html' ':!docs/en/index.html'   (leer; die Changelog-Spiegel behalten den historischen Eintrag)
Doku: keine
Abhängt von: T7

### T9 — Doku-Sweep  [ ]
Komponente: docs · Dateien: CLAUDE.md (§2 Pool `adminhelper-ci`, §8 „Testen auf VMs"), AUTONOMOUS.md, tasks/README.md, DEVELOPMENT.md (Abschnitte „Schwere Suites auf crabbox" und „Wochenlauf" ersetzt; Abschnitt aus 2a wird der Hauptabschnitt), docs/developer/cicd.html + docs/en/developer/cicd.html (Aggregator-/Wochenlauf-Abschnitte), CHANGELOG.md (Changed: Wrapper auf vm.py; Removed: crabbox)
Änderung: Begriffe, Pfade, Aufrufe; Pool-Name in CLAUDE.md auf `adminhelper-ci` (D20).
Verify: git grep -il crabbox -- ':!CHANGELOG.md' ':!docs/index.html' ':!docs/en/index.html'   (leer) und   python3 scripts/dev/doc-smoke.py --strict   (falls 8a gemergt; sonst Pfade von Hand geprüft)
Doku: alle genannten
Abhängt von: T8

## C — Live-Beweis

### T10 — Live-Beweis 2b  [ ]
Komponente: scripts · Dateien: tasks/vm-migration.md (Anhang)
Änderung: `bash scripts/vm/warm.sh desktop` (einmal, Dauer notieren); `bash scripts/vm/iter.sh quick` zweimal (erster ≤ 15 min, zweiter ≤ 5 min); absichtlich roter Test auf Wegwerf-Branch → `iter.sh` Exit 1, Box steht; `AH_WARM_TTL=20m bash scripts/vm/warm.sh desktop` auf einer zweiten Lane + 25 min + `vm.py list` → Box weg; `bash scripts/tests/multibox.sh --agents 1` → `multibox: 5 ok, 0 failed, 0 skipped`; `bash scripts/dev/lane.sh new probe` → `warm.sh desktop` → `iter.sh quick` → `lane.sh done probe` räumt; am Ende `vm.py list` leer und `crabbox list` leer. Ergebnisse in den Anhang und PR-Body.
Verify: python3 scripts/vm/vm.py list   → Exit 0, leer
Doku: keine
Abhängt von: T9

## Abschluss
- `bash scripts/tests/run.sh quick --strict` grün; `bash scripts/dev/verify.sh all --strict` grün; CI grün inkl. `frp-consistency` und `ops-scripts`.
- Kevin nach dem Merge: `heavy.sh weekly` → Summary-Zeilen wie der letzte crabbox-Lauf; dann `crabbox list` leer → Binary deinstallieren; crabbox-Einträge aus `.claude/settings.local.json` entfernen; Roadmap R-0025/26/27 schließen.
