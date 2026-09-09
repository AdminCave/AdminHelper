<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness Stufe 1 — Grün heißt Beweis

Stand 2026-09-09 · Status: Spec zum Design-Gate · Ledger: `tasks/harness-stufe-1.md` · Roadmap-Zeile R-0002

## Problem / Motivation

Die Test-Infrastruktur kann heute an mehreren Stellen „grün" melden, ohne dass etwas gelaufen ist:

- Sieben `scripts/tests/desktop_e2e_*.sh` enden mit `exit 0`, wenn `cargo tauri` fehlt (`_live.sh:34`,
  `_crud.sh:27`, `_monitoring.sh:28`, `_sse_push.sh:29`, `_tunnel.sh:36`, `_connect.sh:54`,
  `_connect_tunnel.sh:57`). `run.sh` zählt das als PASS. Ursache auf der VM: `crabbox_bootstrap.sh:152–153`
  installiert `tauri-driver`/`tauri-cli` mit `|| true`.
- `agent_install_test.sh:27,28,37,39` und die minisign-Weiche in `update_test.sh:33–38` /
  `install_test.sh:31–36` melden bei fehlender Voraussetzung `exit 0` bzw. „Signaturpfad neutralisiert".
- pytest-interne Skips (`test_stream_redis.py:30`, `monitoring/tests/test_migrations_smoke.py:21`)
  sind in der Summary unsichtbar; `run.sh:153–157` kennt `AH_TEST_DB` nicht, der Server-Schritt skippt
  auf der Dev-Box still, wenn `DATABASE_URL` nicht gesetzt ist.
- `run.sh` kennt keinen strengen Modus, keine Required-Menge und schreibt kein maschinenlesbares Ergebnis;
  `Verify:`-Zeilen in Ledgern tragen Env-Präfixe (`source .devenv.sh && … DATABASE_URL=…`), die eine
  Allow-Regel nie matcht (11 Zeilen in `tasks/*.md`).
- Der Go-Agent läuft in CI nie nativ unter Windows (`ci.yml:190` nur `GOOS=windows go vet`);
  `services_windows_test.go` wurde nie ausgeführt.
- Doku-Drift: `docs/developer/cicd.html:40` DE+EN „cargo check auf Windows" (real: `cargo test --locked`),
  `DEVELOPMENT.md:394` nennt einen CI-Job `desktop-e2e`, den es nicht gibt; fünf Verweise auf eine
  gitignorte `fabelreport.md`; `tasks/test-infra-capstone-release.md` A4 behauptet einen JUnit-Reporter
  (`wdio.conf.js:67` hat nur `spec`).
- Kevin hat seit Stufe 0 keinen Statusblock beim Session-Start; die fünf Warn-Trigger aus `CLAUDE.md`
  Abschnitt 3 haben noch keinen Erzeuger.

Alle sechs Release-Defekte der 0.43.x/0.44.0-Reihe kamen aus Ausführung; stille SKIPs sind der
wiederkehrende Fehlermodus. Ohne diese Stufe misst jede spätere Stufe mit einem lügenden Lineal.

## Ziel & Nicht-Ziele

**Ziel.** Kein Lauf kann ohne reale Ausführung grün sein, auch nicht durch pytest-interne Skips.
`Verify:`-Zeilen sind allowlist-tauglich (Flags, kein Env-Präfix) und erzeugen ein Evidenz-Artefakt mit
echtem Tree-Hash. Die Go-Suite läuft erstmals nativ unter Windows. Falsche Doku-Aussagen sind weg. Jede
Session beginnt mit einem Statusblock, der Fakten druckt und nur bei scheiternden oder irreversiblen
Handgriffen warnt.

**Nicht-Ziele.** Keine VM-Änderungen (crabbox bleibt, Stufe 2). Keine Modell-, Skill- oder Reviewer-Umbauten
über die genannten Zeilen hinaus. Kein `.ah-out/`-Umzug (`AH_OUT_DIR` bleibt `.crabbox-out` bis Stufe 2).
Keine JUnit-Produktion (Stufe 5). Kein `-race` unter Windows (cgo-Frage offen). Keine Änderung an
`permissions.allow` außer dem Eintrag für `verify.sh`.

## Betroffene Komponenten & Dateien

| Bereich | Dateien |
|---|---|
| Aggregator | `scripts/tests/run.sh` (280 Z.), neu `scripts/dev/tree-hash.sh`, neu `scripts/dev/verify.sh` |
| Session-Status | neu `scripts/dev/hooks/session-status.sh`, `.claude/settings.json` (`hooks.SessionStart`, `permissions.allow`) |
| SKIP-Härtung | `scripts/tests/desktop_e2e_{live,crud,connect,connect_tunnel,monitoring,sse_push,tunnel}.sh`, `scripts/tests/agent_install_test.sh`, `scripts/tests/update_test.sh`, `scripts/tests/install_test.sh`, `scripts/tests/crabbox_bootstrap.sh`, `scripts/tests/crabbox_multibox.sh` |
| Hermetische Tests (neu) | `scripts/tests/session_status_test.sh`, `scripts/tests/run_flags_test.sh`, `scripts/tests/verify_test.sh`, `scripts/tests/desktop_e2e_skip_test.sh` |
| CI | `.github/workflows/ci.yml` (Job `ops-scripts` → `run.sh unit --strict --only scripts`; neu Job `agent-windows`) |
| Skills / Konventionen | `.claude/skills/feature-build/SKILL.md`, `feature-plan/SKILL.md`, `feature-review/SKILL.md`, `AUTONOMOUS.md`, `tasks/README.md`, `tasks/*.md` (Verify-Zeilen) |
| Lint | `apps/web/eslint.config.js:38`, `apps/desktop/ui/eslint.config.js:38` |
| Doku | `docs/developer/cicd.html`, `docs/en/developer/cicd.html`, `DEVELOPMENT.md`, `CHANGELOG.md`, `tasks/test-infra-capstone-release.md` |

## Design

### run.sh: Flags, strenger Modus, Required-Menge

- Aufruf bleibt `bash scripts/tests/run.sh [layer] [--strict] [--only <keys…>] [--step <name>]`. Die Flags
  setzen intern `AH_STRICT=1`, `AH_ONLY`, `AH_STEP`; die Envs bleiben gültig, weil Skripte auf der VM ohne
  Allowlist laufen. `--only` nimmt mehrere Keys bis zum nächsten Flag; unbekannte Keys brechen wie heute
  hart ab (Exit 2). `--step` führt genau einen `run_step`-Namen aus (Substring-Match, eindeutig, sonst Exit 2).
- **Required-Menge:** Liste `AH_REQUIRED_DEFAULT` im Skriptkopf (`ruff`, `server pytest`, `monitoring pytest`,
  `ca-issuer pytest`, `go agent`, `cargo test (desktop)`, `desktop-ui vitest`, `web vitest`); `AH_REQUIRED`
  (Space-getrennt, aus `.devenv.sh`) überschreibt sie pro Host. Unter `--strict` gilt: SKIP eines
  Required-Steps ⇒ FAIL mit Zeile `strict-failed: <step> (SKIP)`; SKIP eines per `--only` angeforderten
  Keys ⇒ FAIL, auch wenn er nicht Required ist. Ohne `--strict` bleibt SKIP ein SKIP (Exit 0).
- **pytest-Skips:** unter `--strict` laufen die Python-Suiten mit `-rs`; `run.sh` parst die Skip-Zeilen und
  wertet Required-Tests je Vorbedingung: Postgres erreichbar ⇒ `test_migrations_smoke`,
  `test_auth_token_lifecycle`; Redis erreichbar ⇒ `test_stream_redis`. Ein übersprungener Required-Test ⇒
  `strict-failed: <test> (test-skip)`. Die Summary wird zu `N passed, M failed, K skipped, J test-skips,
  R reruns` (`reruns` ist in Stufe 1 immer 0, das Feld existiert, damit Stufe 3 es füllt).
- **`AH_TEST_DB`-Fallback:** nur der Server-Schritt setzt `DATABASE_URL="${DATABASE_URL:-$AH_TEST_DB}"`,
  kollisionsfrei mit dem Venv-Fallback aus `code-review-fixes` T6.
- **Artefakt:** jeder Lauf schreibt `$AH_OUT_DIR/last-<layer>.json` mit `head`, `tree_hash`, `started`,
  `finished`, `layer`, `strict`, `only`, `steps[] {name, result, seconds}`, `test_skips[]`, `reruns`.
  Tree-Hash liefert `scripts/dev/tree-hash.sh`: `GIT_INDEX_FILE=$(mktemp) git add -A -- . ':(exclude)tasks/'
  ':(exclude).ah-out/' ':(exclude).crabbox-out/' && git write-tree` — sieht untracked Inhalte und ignoriert
  Ledger-Edits.
- **Scripts-Block:** die hermetischen Shell-Tests (`install_test`, `update_test`, `init-secrets_test`,
  `uninstall_test`, `restore_guard_test`, `gateway_mtls_test`, `agent_install_test`, `diagnostics_test`
  plus die vier neuen) laufen als **ein** Step `scripts (hermetic)` im unit-Layer unter dem Key `scripts`;
  `update_test`/`agent_install_test`/`diagnostics_test` verlassen den integration-Layer. Der CI-Job
  `ops-scripts` ruft `bash scripts/tests/run.sh unit --strict --only scripts` statt acht Einzelzeilen.

### verify.sh

`bash scripts/dev/verify.sh <komponente> [--strict] [--tree <pfad>] [-- <args>]`: sourct `.devenv.sh`
(bzw. `$AH_DEVENV`), löst `AH_TEST_DB` auf, delegiert an `run.sh unit --only <komponente>` (`quick` für
`all`), optional gezielte Args (`-- tests/test_x.py`) für die pytest-/go-/vitest-Schritte, `--tree`
fährt gegen einen anderen Checkout (Worktree; Reviewer-Probe ab Stufe 6) und schreibt
`$AH_OUT_DIR/last-verify.json` im selben Schema plus `component`, `args`, `tree`. Exit = Exit von `run.sh`.
Allowlist: `Bash(bash scripts/dev/verify.sh:*)` neben dem vorhandenen `Bash(bash scripts/tests/run.sh:*)`.
Ab jetzt sind das die beiden einzigen Verify-Formen, die `/feature-plan` schreibt.

### Session-Status-Hook

`scripts/dev/hooks/session-status.sh`, ≈ 60–80 Zeilen, nur lesend, Exit immer 0, `AH_AUTONOMOUS=1` ⇒
sofort `exit 0` (Settings-Hooks laufen auch in `claude -p`). Druckt:

```
AH-STATUS <datum> · <branch> @<sha> · <n> dirty · origin <±n> · AH_TEST_DB <ok|fehlt>
Release: tauri <version> · letzter Tag <tag> · Draft: <ja|nein|?>
Roadmap: <erste 4 Zeilen „Als Nächstes"> | fehlt (tasks/private/ROADMAP.md)
Ledger aktiv|bereit: <slugs> · PRs offen: <n> · Wochenlauf: kein Report (ab 3) · Worker: — (ab 7)
VMs: warm.env <profile=slug|leer>
WARN: …   (nur bei Trigger)
```

Netzaufrufe (`gh pr list`, `gh release view`) unter `timeout 3`, Fehler still (`?`). Warn-Trigger (aus
`CLAUDE.md` Abschnitt 3 und Roadmap 3.5d): `tauri.conf.json`-Version ohne passenden Tag; `main` vor
`origin/main`; Draft-Release existiert; `.claude/rules/` oder `.claude/agents/` gitignored; `env`-Block
in `.claude/settings.json`; `tasks/private` mit ≥ 3 unpushed Commits oder ohne Remote; `AH_TEST_DB` leer.
Kein Trigger, keine `WARN:`-Zeile. `--for test|build-queue|find` wird akzeptiert und ist in Stufe 1 ein No-op
(Preflight-Haken für spätere Stufen). Einbindung: `hooks.SessionStart` ohne Matcher in `.claude/settings.json`.
Hermetischer Test: Fixture-Repo unter `mktemp -d` mit Tag, Bump ohne Tag, unpushed Commit, PATH-Shim für
`gh`; prüft jede Zeile und jeden Trigger, und dass `AH_AUTONOMOUS=1` nichts druckt.

### SKIP-Härtung

`exit 0` ⇒ `exit 75` an den neun Stellen; minisign-Weiche in `update_test.sh`/`install_test.sh` ⇒
`exit 75` (CI installiert minisign, dort läuft der Signaturpfad weiter); `crabbox_bootstrap.sh:152–153`
ohne `|| true` (fehlender `tauri-cli` bricht den Bootstrap ab, statt später sieben Suiten still zu
skippen); `crabbox_multibox.sh:171` debian:9-Skip als Marker `MB_DEBIAN9_SKIPPED`, Summary um `K skipped`,
unter `AH_STRICT=1` ⇒ FAIL. `desktop_e2e_skip_test.sh` maskiert `cargo tauri` per PATH-Shim, erfüllt
`e2e_require` per Shims und erwartet Exit 75 aus jedem der sieben Skripte.

### CI-Job agent-windows

`runs-on: windows-latest`, `timeout-minutes: 15`, `actions/setup-go` wie Job `agent`, Schritte `go test -v ./...`,
`go build -o adminhelper-agent.exe ./cmd/adminhelper-agent`, `.\adminhelper-agent.exe version`; zusätzlich
`workflow_dispatch`. Perm-Guards (`enroll_test.go:131`, `apply_test.go:74`) existieren; weitere
Windows-Brüche sind Funde dieses PR, keine Infra-Fehler. Der Job ist von Anfang an hart (kein
`continue-on-error`): rot im PR heißt fixen, nicht ausblenden (Frage 2).

### Konventionen und Skills

`feature-build/SKILL.md` Schritt 3 ruft `bash scripts/tests/run.sh quick --strict --only <komp>`; Z. 66
`git checkout -- <datei>` ⇒ `git restore --source=HEAD --staged --worktree -- <datei>`, Revert-Checks nie
im Builder-Tree. Alle elf `Verify:`-Zeilen mit Env-Präfix in `tasks/*.md` auf Flag-Form; fünf
`fabelreport.md`-Verweise auf „Spec-Feld des Ledger-Kopfs"; `tasks/README.md` „Aktueller Stand" auf
Ist-Stand (`audit-fixes.md` ist gitignored und abgeschlossen). ESLint `no-unused-vars` in beiden
Frontends von `warn` auf `error` — erster Baustein der Finder-Werkzeugschicht (Stufe 9 F0).

## Trade-offs & Alternativen

- **Flags statt Env** kosten Parser-Zeilen in `run.sh`, sind aber die einzige Form, die eine Allow-Regel
  matcht. Alternative „Wrapper-Skript pro Komponente" wäre zehn Dateien für eine Zeile Nutzen.
- **Required-Menge pro Host** ist eine zweite Wahrheit (`AH_REQUIRED` in `.devenv.sh`). Alternative
  „alles Required, überall" würde die Dev-Box (kein Docker, kein Display) unter `--strict` dauerhaft rot
  machen. `run.sh` druckt die wirksame Menge in die Summary, damit sie sichtbar bleibt.
- **Scripts-Block statt acht CI-Zeilen:** ein Step, ein Exit; Nachteil: ein roter Shell-Test verdeckt die
  anderen bis zum Log. Akzeptiert, weil die Tests hermetisch und sekundenschnell sind.
- **agent-windows hart ab Tag 1** statt Probelauf: spart einen PR-Zyklus; Risiko rot im ersten Lauf ist
  gewollt (Fund).

## Risiken & Rollback

- `--strict` auf der Dev-Box ist rot, bis Kevin `AH_REQUIRED` in `.devenv.sh` setzt (dokumentiert in
  `DEVELOPMENT.md`; Vorschlag steht im Ledger-Kopf). Rollback: Flag weglassen, Verhalten wie heute.
- `exit 75` statt `exit 0` macht den heutigen `run.sh e2e` auf einer Box ohne `tauri-cli` von „7 passed"
  zu „7 skipped" — das ist die Absicht; Warm-Boxen aus dem Fat-Template haben `tauri-cli`.
- `crabbox_bootstrap.sh` ohne `|| true` bricht Bootstraps ab, die bisher „durchliefen". Rollback per Revert
  der Zeile; besser: Ursache (Rust-Toolchain) fixen.
- `no-unused-vars: error` kann bestehende Warnungen zu Fehlern machen; Anzahl vor dem Umstellen messen,
  über 10 Funde ⇒ `[?]` statt still fixen (Frage 3).
- Der SessionStart-Hook läuft in jeder Session, auch in Worktrees ohne `.devenv.sh`; er darf nie blockieren:
  alle Aufrufe mit `timeout`, jeder Fehler wird `?`.

## Doku-Impact

`docs/developer/cicd.html` DE+EN: Absatz „Test-Aggregator" um `--strict`/`--only`/`--step`, Exit-75-,
test-skip- und rerun-Semantik, Required-Menge, `last-<layer>.json` und Tree-Hash-Definition, `verify.sh`
als Verify-Konvention, Job `agent-windows`, „cargo check" ⇒ `cargo test --locked`. `DEVELOPMENT.md`:
`verify.sh`, `AH_REQUIRED` in `.devenv.sh`, toten Job `desktop-e2e` entfernen. `CHANGELOG.md` Unreleased
(Changed). `AUTONOMOUS.md` und `tasks/README.md` nur Verweise. README unverändert.

## Offene Fragen (Design-Gate)

1. **Hook-Netzaufrufe:** `gh pr list`/`gh release view` bei jedem Session-Start (≈ 1 s, `timeout 3`) oder
   nur die lokalen Fakten? Empfehlung: mit Netz, weil Draft-Release und offene PRs zwei der Warn-Trigger
   sind; Trade-off: eine Sekunde je Start, offline erscheint `?`.
2. **agent-windows hart ab Tag 1** (Empfehlung) oder `continue-on-error` bis zum ersten grünen Lauf?
   Trade-off: ein roter erster Lauf blockiert den Stufe-1-PR, bis die Windows-Brüche gefixt sind.
3. **ESLint-Funde:** über 10 bestehende `no-unused-vars`-Warnungen in diesem Ledger fixen oder als REF-Zeile
   in die Roadmap? Empfehlung: bis 10 hier, darüber Roadmap.
4. **Required-Menge Dev-Box:** Vorschlag für `.devenv.sh`:
   `export AH_REQUIRED="ruff server-pytest monitoring-pytest ca-issuer-pytest go-agent desktop-ui-vitest web-vitest"`
   (ohne `cargo test (desktop)`, falls der frpc-Sidecar lokal fehlt — bitte prüfen: `ls apps/desktop/src-tauri/binaries/`).
