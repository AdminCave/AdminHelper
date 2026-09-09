<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness Stufe 1 — Grün heißt Beweis — Task-Ledger
Status: aktiv · Branch: feature/harness-stufe-1 · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: docs/features/harness-stufe-1.md
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: nach T8 einmal `bash scripts/tests/crabbox_iter.sh quick --strict` auf der warmen Desktop-Box (Exit 0, `0 test-skips`) — ask-first, kein Capstone nötig
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Vorab (Kevin, 2 min): `AH_REQUIRED` in `.devenv.sh` setzen (Vorschlag in der Spec, Frage 4); ohne die Zeile ist `--strict` auf der Dev-Box rot, weil `cargo test (desktop)` dort SKIP ist.
Roadmap: R-0002 · Hängt ab von: R-0001 (gemergt, PR #10)

### T1 — Session-Status-Hook mit hermetischem Test  [x] (AH-STATUS-Block, 7 Trigger, 35 hermetische Assertions)
Komponente: scripts/dev · Dateien: scripts/dev/hooks/session-status.sh (neu), scripts/tests/session_status_test.sh (neu), .claude/settings.json
Änderung: Statusblock `AH-STATUS` nach Spec (Checkout, Tag/Version, Roadmap „Als Nächstes", Ledger-Status, PRs/Draft per `gh` unter `timeout 3`, warm.env), sieben Warn-Trigger, Exit immer 0, `AH_AUTONOMOUS=1` ⇒ sofort Exit 0, `--for <x>` akzeptiert als No-op. `hooks.SessionStart` (ohne Matcher) in `.claude/settings.json`. Test baut ein Fixture-Repo unter `mktemp -d` (Tag, Bump ohne Tag, unpushed Commit, `env`-Block, ignorierte `.claude/rules/`) mit `gh`-Shim und prüft jede Zeile und jeden Trigger; SPDX-Header in beiden neuen Dateien.
Verify: `bash scripts/tests/session_status_test.sh` → `N passed, 0 failed`; `shellcheck --severity=warning scripts/dev/hooks/session-status.sh` leer
Doku: keine (intern; DEVELOPMENT.md-Absatz kommt in T16)

### T2 — tree-hash.sh  [x] (Wegwerf-Index, sieht untracked, ignoriert tasks/)
Komponente: scripts/dev · Dateien: scripts/dev/tree-hash.sh (neu)
Änderung: ~10 Zeilen: `GIT_INDEX_FILE=$(mktemp)`, `git add -A -- . ':(exclude)tasks/' ':(exclude).ah-out/' ':(exclude).crabbox-out/'`, `git write-tree`, Index-Datei löschen; druckt 40 Hex. SPDX-Header.
Verify: `h1=$(bash scripts/dev/tree-hash.sh); touch probe.tmp; h2=$(bash scripts/dev/tree-hash.sh); rm probe.tmp; [ "$h1" != "$h2" ] && echo ok` → `ok`; eine Änderung unter `tasks/` lässt den Hash gleich
Doku: keine (intern)

### T3 — run.sh: Flag-Parser, --strict, --only, --step, Required-Menge  [x] (Step-Ids, Probe-Lauf für --step, leerer strict-Lauf = Fehler, 25 Assertions)
Komponente: scripts/tests · Dateien: scripts/tests/run.sh, scripts/tests/run_flags_test.sh (neu)
Änderung: Argument-Parser (Layer positional, dann Flags), `AH_REQUIRED_DEFAULT` im Kopf, `AH_REQUIRED`-Override, unter `AH_STRICT=1`: SKIP eines Required-Steps oder eines per `--only` angeforderten Keys ⇒ FAIL mit `strict-failed: <step> (SKIP)`; Summary nennt die wirksame Required-Menge; `--step` führt genau einen Step aus. Hermetischer Test mit PATH-Shims (`go` maskiert ⇒ `strict-failed: go agent (SKIP)`; ohne `--strict` Exit 0 mit `K skipped`; unbekannter `--only`-Key ⇒ Exit 2). Kopf-Kommentar der Usage nachziehen.
Verify: `bash scripts/tests/run_flags_test.sh` → `N passed, 0 failed`; `bash scripts/tests/run.sh lint --only scripts` → Exit 0
Doku: keine (Doku-Task T15)

### T3b — crabbox_iter.sh reicht die run.sh-Flags an die Box weiter  [x] (Flags %q-gequotet, Layer validiert, AH_DRY_RUN, 8 Assertions)
Komponente: scripts/tests · Dateien: scripts/tests/crabbox_iter.sh, scripts/tests/crabbox_iter_flags_test.sh (neu)
Fund aus dem T3-Review (nicht in der Spec): `crabbox_iter.sh:71` liest nur `$1` und baut daraus `run.sh $LAYER` — alle weiteren Argumente fallen weg. Die `Heavy:`-Zeile dieses Ledger-Kopfs (`crabbox_iter.sh quick --strict`) liefe damit ohne strengen Modus und meldete trotzdem grün: genau der Fehlermodus, den Stufe 1 abschafft.
Änderung: Restargumente nach dem Layer einsammeln, jedes per `printf %q` shell-quoten (der String läuft als Remote-Befehl auf der Box) und an `run.sh` anhängen; unbekannte Flags hart ablehnen statt blind weiterreichen. Aus dem Review dazu: den Layer nach demselben Muster wie `AH_ONLY` validieren, **bevor** eine Box geleast wird (`crabbox_iter.sh --strict` wurde sonst zu `LAYER=--strict` und verbrannte eine VM); Usage-Kopf nachziehen; `AH_DRY_RUN=1` druckt den Remote-Befehl und beendet ohne Lease — erst dadurch ist die Argumentbehandlung überhaupt automatisiert prüfbar. SPDX-Header im neuen Test.
Verify: `bash scripts/tests/crabbox_iter_flags_test.sh` → `8 passed, 0 failed`, auch mit `PATH=/usr/bin:/bin` ohne `crabbox` und ohne `CRABBOX_PROVIDER` (der Trockenlauf überspringt die Provider-Prüfungen, ein crabbox-Shim im Test macht ein Durchrutschen zu Exit 99 statt zu einem Lease); `shellcheck --severity=warning scripts/tests/crabbox_iter.sh` leer. Realer Beweis im Heavy-Lauf (Ausgabe enthält dann `required (strict):`).
Doku: keine (intern)

### T4 — run.sh: pytest-Skips sichtbar, AH_TEST_DB-Fallback, last-<layer>.json  [x] (run_py_step + -rs, Vorbedingungen je Test, JSON-Artefakt, AH_ARGS, 43 Assertions)
Komponente: scripts/tests · Dateien: scripts/tests/run.sh, scripts/tests/run_flags_test.sh
Änderung: Python-Suiten unter `--strict` mit `-rs`; Skip-Zeilen parsen; Required-Tests je Vorbedingung (Postgres erreichbar ⇒ `test_migrations_smoke`, `test_auth_token_lifecycle`; Redis ⇒ `test_stream_redis`) ⇒ `strict-failed: <test> (test-skip)`; Summary `…, J test-skips, R reruns` (`reruns` fest 0); Server-Schritt `DATABASE_URL="${DATABASE_URL:-${AH_TEST_DB:-}}"`; Artefakt `$AH_OUT_DIR/last-<layer>.json` (Schema laut Spec, Tree-Hash aus T2). Test: Fixture-pytest mit einem Skip ⇒ `test-skip`; JSON hat `head` und `tree_hash`.
Verify: `bash scripts/tests/run_flags_test.sh` → `N passed, 0 failed`; `bash scripts/tests/run.sh lint --only scripts && python3 -c "import json;d=json.load(open('.crabbox-out/last-lint.json'));assert len(d['tree_hash'])==40"`
Zusätzlich (nicht in der Spec): `AH_ARGS` reicht Argumente an die Suite-Kommandos durch — ohne die Variable lässt sich T5 (`verify.sh <komp> -- <args>`) nicht bauen, und die Alternative wäre, `run.sh` zweimal anzufassen. Aus dem Review: `test_db_token_store` (ca-issuer, vierter pytest-interner Skip im Repo) als Required-Test bei gesetztem `AH_TEST_DB` ergänzt — in der Spec nicht aufgeführt.
Doku: keine (Doku-Task T15; `AH_ARGS` dort mit aufnehmen)
Abhängt von: T2, T3

### T5 — verify.sh und Allowlist-Eintrag  [ ]
Komponente: scripts/dev · Dateien: scripts/dev/verify.sh (neu), scripts/tests/verify_test.sh (neu), .claude/settings.json
Änderung: Interface laut Spec (`<komponente> [--strict] [--tree <pfad>] [-- <args>]`), sourct `.devenv.sh`/`$AH_DEVENV`, delegiert an `run.sh unit --only`, gezielte Args an pytest/go/vitest, `--tree` per `cd`, schreibt `last-verify.json` (Schema + `component`, `args`, `tree`), Exit durchgereicht. `permissions.allow` += `Bash(bash scripts/dev/verify.sh:*)`. Hermetischer Test mit Shims (Komponente `scripts`, `--tree` gegen ein zweites Fixture). SPDX-Header.
Verify: `bash scripts/tests/verify_test.sh` → `N passed, 0 failed`; `bash scripts/dev/verify.sh scripts --strict` → Exit 0 und `.crabbox-out/last-verify.json` existiert
Doku: keine (Doku-Task T16)
Abhängt von: T4

### T6 — desktop_e2e_*.sh: exit 0 → exit 75 im tauri-cli-Zweig  [ ]
Komponente: scripts/tests · Dateien: scripts/tests/desktop_e2e_live.sh, desktop_e2e_crud.sh, desktop_e2e_connect.sh, desktop_e2e_connect_tunnel.sh, desktop_e2e_tunnel.sh, desktop_e2e_monitoring.sh, desktop_e2e_sse_push.sh
Änderung: je Datei die eine Zeile `|| { echo "SKIP: tauri-cli (cargo tauri) not available"; exit 0; }` auf `exit 75`. Sonst nichts.
Verify: `git grep -n 'exit 0' scripts/tests/desktop_e2e_*.sh` → 0 Treffer im SKIP-Zweig; `shellcheck --severity=warning scripts/tests/desktop_e2e_*.sh` leer
Doku: keine (intern)

### T7 — desktop_e2e_skip_test.sh (hermetisch)  [ ]
Komponente: scripts/tests · Dateien: scripts/tests/desktop_e2e_skip_test.sh (neu)
Änderung: PATH-Shims für `docker`, `openssl`, `curl`, `python3`, `node`, `xvfb-run`, `WebKitWebDriver`, `tauri-driver`, `dbus-run-session`, `gnome-keyring-daemon`, `go` (Exit 0), `docker compose version`/`docker info` per Shim; `cargo` fehlt im PATH ⇒ jedes der sieben Skripte muss mit 75 enden und „SKIP: tauri-cli" drucken. SPDX-Header.
Verify: `bash scripts/tests/desktop_e2e_skip_test.sh` → `7 passed, 0 failed`
Doku: keine (intern)
Abhängt von: T6

### T8 — Shell-Sandbox-Tests: SKIP heißt 75, Bootstrap ohne || true  [ ]
Komponente: scripts/tests · Dateien: scripts/tests/agent_install_test.sh, scripts/tests/update_test.sh, scripts/tests/install_test.sh, scripts/tests/crabbox_bootstrap.sh
Änderung: `agent_install_test.sh:27,28,37,39` `exit 0` ⇒ `exit 75`; minisign-Weiche in `update_test.sh:33–38` und `install_test.sh:31–36`: fehlendes/unbrauchbares minisign ⇒ `echo "SKIP: minisign …"; exit 75` statt „neutralisiert"; `crabbox_bootstrap.sh:152–153` `|| true` entfernen (fehlgeschlagene Installation bricht den Bootstrap ab, Meldung nennt `tauri-cli`).
Verify: `bash scripts/tests/agent_install_test.sh` → `26 passed, 0 failed`; `update_test.sh` und `install_test.sh` auf einem PATH ohne minisign → Exit `75` (Shim-PATH aus Coreutils, im Lauf belegt); `shellcheck --severity=warning scripts/tests/crabbox_bootstrap.sh` leer
Doku: keine (intern)

### T9 — Scripts-Block im unit-Layer, CI ops-scripts über run.sh  [ ]
Komponente: scripts/tests · Dateien: scripts/tests/run.sh, .github/workflows/ci.yml
Änderung: neuer Step `scripts (hermetic)` unter Key `scripts` im unit-Layer: führt `install_test`, `update_test`, `init-secrets_test`, `uninstall_test`, `restore_guard_test`, `gateway_mtls_test`, `agent_install_test`, `diagnostics_test`, `session_status_test`, `run_flags_test`, `verify_test`, `desktop_e2e_skip_test` nacheinander aus (erster Fehler ⇒ FAIL, jeder 75 ⇒ SKIP des Blocks nur ohne `--strict`); `update_test`/`agent_install_test`/`diagnostics_test` aus `layer_integration` entfernen; `ops-scripts` in `ci.yml`: shellcheck-Zeile bleibt, die acht Test-Zeilen ⇒ `bash scripts/tests/run.sh unit --strict --only scripts`. `scripts` in `AH_REQUIRED_DEFAULT`.
Verify: `bash scripts/tests/run.sh unit --strict --only scripts` → Exit 0, Summary `… 0 skipped, 0 test-skips`; `python3 -c "import yaml;yaml.safe_load(open('.github/workflows/ci.yml'))"`
Doku: keine (Doku-Task T15)
Abhängt von: T1, T3, T4, T5, T7, T8

### T10 — crabbox_multibox.sh: skipped zählen, debian:9 als Marker  [ ]
Komponente: scripts/tests · Dateien: scripts/tests/crabbox_multibox.sh
Änderung: Zähler `SKIPPED` neben ok/bad; `:171` debian:9-Zweig setzt Marker `MB_DEBIAN9_SKIPPED` und zählt skipped; unter `AH_STRICT=1` ⇒ `bad` statt note; Summary-Zeile `multibox: N ok, M failed, K skipped`.
Verify: `shellcheck --severity=warning scripts/tests/crabbox_multibox.sh` leer; `grep -n 'K skipped\|SKIPPED' scripts/tests/crabbox_multibox.sh` zeigt Zähler und Summary; realer Lauf in der Heavy-Zeile des Ledger-Kopfs bzw. beim nächsten Capstone
Doku: keine (intern)

### T11 — CI-Job agent-windows  [ ]
Komponente: .github · Dateien: .github/workflows/ci.yml
Änderung: Job `agent-windows` (`name: Go Agent (test, Windows)`, `runs-on: windows-latest`, `timeout-minutes: 15`, `actions/setup-go` mit denselben Pins wie Job `agent`, `go-version: "1.25"`, `cache-dependency-path: apps/agent/go.sum`), Schritte `go test -v ./...`, `go build -o adminhelper-agent.exe ./cmd/adminhelper-agent`, `.\adminhelper-agent.exe version`; Workflow um `workflow_dispatch` ergänzen. Hart, kein `continue-on-error` (Spec Frage 2). Windows-Brüche im ersten Lauf sind Funde: als Folge-Tasks T11b… anhängen, Perm-Guards wie `enroll_test.go:131`.
Verify: `python3 -c "import yaml;d=yaml.safe_load(open('.github/workflows/ci.yml'));assert 'agent-windows' in d['jobs']"`; PR-CI: Job grün, Log enthält `TestReWinServiceName` und `PASS`
Doku: keine (Doku-Task T15)

### T12 — feature-build/plan/review Skills: Verify-Aufruf, restore statt checkout, fabelreport  [ ]
Komponente: .claude/skills · Dateien: .claude/skills/feature-build/SKILL.md, .claude/skills/feature-plan/SKILL.md, .claude/skills/feature-review/SKILL.md
Änderung: feature-build Schritt „Pro Iteration": Schnellsuite als `bash scripts/tests/run.sh quick --strict --only <komp>` bzw. `bash scripts/dev/verify.sh <komp> --strict`; Z. 66 `git checkout -- <datei>` ⇒ `git restore --source=HEAD --staged --worktree -- <datei>`, Revert-Check ausdrücklich nie im Builder-Tree (eigener Worktree); `fabelreport`-Verweise (feature-build:76, feature-plan:66, feature-review:19) auf „Spec-Feld des Ledger-Kopfs"; feature-plan Task-Schema: `Verify:` nur in Flag-Form (Beispielzeile).
Verify: `git grep -n 'git checkout --' .claude/skills` → 0; `git grep -n fabelreport .claude` → 0; `git grep -n 'verify.sh\|run.sh quick --strict' .claude/skills/feature-build/SKILL.md` ≥ 1
Doku: keine (Skill-Doku ist die Datei selbst)

### T13 — AUTONOMOUS.md, tasks/README.md, Verify-Zeilen in tasks/*.md  [ ]
Komponente: Repo-Root · Dateien: AUTONOMOUS.md, tasks/README.md, tasks/{code-review-fixes,dependency-refresh,merker-cleanup,monitoring-overhaul}.md
Änderung: `AUTONOMOUS.md:84` und `tasks/README.md:40` ohne `fabelreport.md`; „Aktueller Stand" in `tasks/README.md` auf Ist (`audit-fixes.md` gitignored und abgeschlossen, `harness-stufe-1.md` aktiv); die elf `Verify:`-Zeilen mit Env-Präfix (`source …`, gesetztes `DATABASE_URL`, gesetztes `AH_ONLY`) in den vier Ledgern auf `bash scripts/dev/verify.sh <komp> [-- <args>]`-Form (historische Ledger, Bedeutung unverändert).
Verify: `git grep -nE 'Verify:.*[A-Z_]{3,}=' tasks .claude` → 0; `git grep -n fabelreport -- ':!CHANGELOG.md' ':!.gitignore' ':!docs/features/harness-stufe-1.md' ':!tasks/harness-stufe-1.md'` → 0 (Spec und Ledger dieser Stufe nennen das Wort, weil sie die Aufgabe beschreiben)
Doku: keine (intern)
Abhängt von: T5

### T14 — ESLint no-unused-vars auf error (web + desktop-ui)  [ ]
Komponente: apps/web, apps/desktop/ui · Dateien: apps/web/eslint.config.js, apps/desktop/ui/eslint.config.js (+ betroffene Quelldateien, falls ≤ 10 Funde)
Änderung: Regel `@typescript-eslint/no-unused-vars` von `warn` auf `error`; vorher `npm run lint` zählen; ≤ 10 Funde in derselben Task fixen (Orphans), > 10 ⇒ `[?]` und Roadmap-Zeile REF (Spec Frage 3).
Verify: `bash scripts/tests/run.sh unit --strict --only web desktop-ui` → Exit 0; eine absichtlich eingebaute unbenutzte Variable macht `npm run lint` rot (danach zurücknehmen)
Doku: keine (intern)
Abhängt von: T3

### T15 — Doku cicd.html DE+EN  [ ]
Komponente: docs · Dateien: docs/developer/cicd.html, docs/en/developer/cicd.html
Änderung: „cargo check auf Windows" ⇒ `cargo test --locked`; neuer Job `agent-windows`; Abschnitt „Test-Aggregator" (den es noch nicht gibt — neu anlegen) mit Flags `--strict`/`--only`/`--step`/`AH_ARGS`, Exit-75-, test-skip- und rerun-Semantik, Required-Menge (`AH_REQUIRED`), `last-<layer>.json`/`last-verify.json` und Tree-Hash-Definition, `verify.sh` als Verify-Konvention; `ops-scripts` läuft über `run.sh`. Beide Sprachen gleichlautend.
Verify: `grep -c 'cargo check' docs/developer/cicd.html docs/en/developer/cicd.html` → 0 und 0; `grep -c 'agent-windows' docs/developer/cicd.html docs/en/developer/cicd.html` → ≥ 1 und ≥ 1
Doku: ist die Doku
Abhängt von: T9, T11

### T16 — DEVELOPMENT.md, CHANGELOG, Capstone-Ledger-Notiz  [ ]
Komponente: Repo-Root · Dateien: DEVELOPMENT.md, CHANGELOG.md, tasks/test-infra-capstone-release.md
Änderung: `DEVELOPMENT.md:394` toten CI-Job `desktop-e2e` entfernen; Abschnitte `verify.sh` (Aufruf, `last-verify.json`), `AH_REQUIRED` in `.devenv.sh`, Session-Status-Hook (was er druckt, `AH_AUTONOMOUS=1`); `CHANGELOG.md` Unreleased „Changed: Test-Aggregator strict/only/step, Exit 75 statt stillem PASS, verify.sh, agent-windows-Job, Session-Status-Hook"; im Capstone-Ledger unter A4 eine Notiz „Stand 2026-09: JUnit-Reporter nicht vorhanden (`wdio.conf.js:67` `spec`), kommt in Stufe 5".
Verify: `grep -n 'desktop-e2e' DEVELOPMENT.md` → 0 Treffer als CI-Job-Name; `grep -c 'verify.sh' DEVELOPMENT.md` ≥ 1; `grep -n 'JUnit-Reporter nicht vorhanden' tasks/test-infra-capstone-release.md` → 1
Doku: ist die Doku
Abhängt von: T5, T1
