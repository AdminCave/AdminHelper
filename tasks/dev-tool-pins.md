<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Werkzeug-Pins: npm-Lockfiles ohne Audit-Befund, ein ruff überall (R-0038, R-0074) — Task-Ledger
Status: freigegeben · Branch: harness/dev-tool-pins · Commit-Granularität: pro Task · Review: pro Task (feature-review; Harness-Pfad scripts/dev ⇒ Reviewer Opus) · Modell: Opus
Freigabe: Kevin, 2026-09-30 („alle freigeben“), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: docs/features/dev-tool-pins.md (Roadmap R-0038, R-0074)
Heavy: none — nur Lockfiles von dev-only-Paketen, requirements-dev, ruff.toml und der Offline-Lockstep; kein Stack-, Gateway-, PKI- oder Install-Pfad. Belegt wird es in der PR-CI (web check/lint/unit und Playwright, desktop-ui, python-lint, tools-Job) und mit einem `audit.yml`-Lauf auf dem Branch (`gh workflow run audit.yml --ref harness/dev-tool-pins`, npm-Job grün).
DoD je Task: CLAUDE.md (Tests grün, ruff/shellcheck/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-09-30 von der Aufsicht (adminhelper-ac) auf Kevins Wort; Entscheidungen Runde B: alle npm-Funde mit
einmaligem `npx -y npm@11 … --package-lock-only`, vitest 4.1.11 (nicht 5), `ruff==0.15.20` mit Gleichheit im
Lockstep, dazu `required-version` in `ruff.toml`.
Branch `harness/`, weil T3/T4 `scripts/dev/toolchain-lockstep.sh` ändern: Bau interaktiv durch Worker B in
`../AdminHelper-harness-b`, keine Lane. Reihenfolge npm zuerst: `audit.yml` (`:94–106`,
`npm audit --audit-level=high`) liefert heute in allen drei Verzeichnissen rc 1, der nächste Cron läuft Montag
2026-10-05 06:17 UTC.

### T1 — web: vitest 4.1.11 und die offenen npm-Funde  [ ]
Komponente: web · Dateien: apps/web/package.json, apps/web/package-lock.json, CHANGELOG.md
Änderung: In `apps/web` einmalig `npx -y npm@11 install --package-lock-only --ignore-scripts vitest@4.1.11
@vitest/coverage-v8@4.1.11`, danach `npx -y npm@11 audit fix --package-lock-only --ignore-scripts`; nichts von
Hand im Lockfile. Die Ranges in `package.json` (`:28` `@vitest/coverage-v8`, `:40` `vitest`) werden `^4.1.11`
(npm@11 schreibt das selbst). Erwartet (Probe 2026-09-30): 12 Pakete bewegen sich — die 9 vitest-Pakete,
brace-expansion 5.0.12, devalue 5.9.4, undici 7.30.0 —, sonst nichts; mehr ist ein STOPP mit Bericht. Die
Box-npm 10.9.8 bricht bei vitest in arborist ab (`Cannot read properties of null (reading 'edgesOut')`), deshalb
npm@11 nur zum Schreiben; danach `npm ci` mit der Box-npm als Gegenprobe. CHANGELOG [Unreleased] Security: ein
Eintrag „npm-Abhängigkeiten (dev) ohne Audit-Befund“, T2 ergänzt ihn.
Beweis: origin/main@8224e84c · `npm audit --json` in apps/web → moderate 4, high 2 (brace-expansion
GHSA-qhr7-859c-m2p7/GHSA-6j4f-fj2g-mc7p, undici GHSA-rfgv-xxqx-mfg5/GHSA-w293-vg96-wgc3, vitest
GHSA-82fw-gwwq-j7x9, devalue GHSA-9rgm-9g3h-6x36); `npm audit --audit-level=high` rc 1.
Zusatzbeleg (vor dem Close von Hand, Ausgabe in die Evidenz): `npm audit --audit-level=moderate` in apps/web →
rc 0; `npm ci` mit npm 10.9.8 fehlerfrei; `git diff --stat` nur die beiden package-Dateien und CHANGELOG.
Verify: bash scripts/dev/verify.sh web --strict
Doku: CHANGELOG [Unreleased] Security

### T2 — desktop-ui und desktop/e2e: dieselben Funde  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/package.json, apps/desktop/ui/package-lock.json, apps/desktop/e2e/package-lock.json, CHANGELOG.md
Änderung: `apps/desktop/ui` wie T1, zusätzlich `@vitest/ui@4.1.11`; Ranges in `package.json` (`:25`
`@vitest/coverage-v8`, `:26` `@vitest/ui`, `:39` `vitest`) werden `^4.1.11`. Erwartet: dieselben 12 Pakete,
`@vitest/mocker` wandert im Lockfile aus `vitest/node_modules` nach oben. `apps/desktop/e2e`: nur
`npm audit fix --package-lock-only --ignore-scripts` mit der Box-npm (package.json unverändert; erwartet 7
Einträge: brace-expansion ×4, undici 6.29.0 und 7.30.0, ip-address 10.7.2). Den CHANGELOG-Eintrag aus T1 um
desktop-ui und e2e ergänzen.
Beweis: origin/main@8224e84c · `npm audit --json` in apps/desktop/ui → moderate 5, high 2; in apps/desktop/e2e →
moderate 1, high 2 (dazu ip-address GHSA-j6r3-76f7-8jcv/GHSA-h3mg-xc3c-68pw); `--audit-level=high` jeweils rc 1.
Zusatzbeleg (von Hand vor dem Close, in die Evidenz): `npm audit --audit-level=moderate` in apps/desktop/ui und
apps/desktop/e2e → rc 0; `npm ci` mit der Box-npm in beiden; `bash scripts/dev/verify.sh desktop-e2e --strict`
(task-close fährt nur die Task-Komponente, R-0104).
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: CHANGELOG [Unreleased] Security (Eintrag aus T1 ergänzen)
Abhängt von: T1

### T3 — ruff: requirements-dev pinnt, was CI pinnt, und der Lockstep verlangt Gleichheit  [ ]
Komponente: scripts · Dateien: scripts/dev/toolchain-lockstep.sh, scripts/tests/toolchain_lockstep_test.sh, apps/server/requirements-dev.txt, .github/workflows/ci.yml, scripts/vm/bootstrap_linux.sh, docs/developer/cicd.html, docs/en/developer/cicd.html, DEVELOPMENT.md, CHANGELOG.md
Änderung: `apps/server/requirements-dev.txt:18` `ruff>=0.15` → `ruff==0.15.20` (nur server führt ruff).
`toolchain-lockstep.sh` Prüfung 2 (`:95–128`): statt des Bodens (`sed 's/^ruff>=…'` `:120`, `sort -V` `:124`)
die Zeile `ruff==X.Y.Z` lesen und Gleichheit mit `RUFF_BOOT` verlangen; Meldungen „no pinned 'ruff==X.Y.Z' in
apps/server/requirements-dev.txt“ und „ruff pin drift: apps/server/requirements-dev.txt pins …, …“; Ausgabe
`ruff: ci.yml=… bootstrap=… dev=…`; Kopfkommentar `:24–30` nachziehen. Kommentare „floor“ → „pin“ in
`ci.yml:98–100` und `bootstrap_linux.sh:24–30`. Gewollte Folge: `run.sh` installiert `requirements-dev.txt` ins
`AH_VENV` (`run.sh:631`) und zieht ein vorhandenes 0.16.x auf 0.15.20 zurück.
Test (zuerst, gegen heute rot): Die Fixture (`toolchain_lockstep_test.sh:50`, `:56`) schreibt `ruff==%s`, Default
0.15.20. Neue Fälle: `ruff>=0.15` → Exit 1 „no pinned 'ruff=='“ (heute Exit 0); `ruff==0.15.19` bei Pin 0.15.20
→ Exit 1 „ruff pin drift … requirements-dev.txt“ (heute andere Meldung). RFLOOR (`:164–165`), RVER (`:167–168`)
und RNOFLOOR (`:175–177`) auf die Pin-Form umstellen. Der REAL_ROOT-Fall (`:181–186`) liest den echten Baum:
Skript und `requirements-dev.txt` gehören in denselben Commit. Meldet diff-scan die umgestellten `run_case`-Zeilen
als geänderte Assertions, zuerst `Test-Löschung:` prüfen, sonst STOPP und Kevin fragen (Handcommit nur auf sein
Wort).
Beweis: origin/main@8224e84c · `bash scripts/dev/toolchain-lockstep.sh` → „ruff: ci.yml=0.15.20
bootstrap=0.15.20 floor>=0.15“, rc 0, obwohl `~/.cache/ah-venv` ruff 0.16.8 trägt; `ruff check --no-cache` über
`apps/server apps/monitoring apps/ca-issuer scripts` mit 0.16.8 → 841 Treffer, mit 0.15.20 → keiner.
Zusatzbeleg (von Hand vor dem Close, in die Evidenz): `bash scripts/dev/verify.sh server --strict` — zieht das
`AH_VENV` auf 0.15.20; `ruff --version` im Venv danach.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/cicd.html:40 + docs/en/developer/cicd.html:40 („Boden … darf nicht darüber liegen“ → „pinnt dieselbe Version“); DEVELOPMENT.md „Python-Lint/Format (ruff)“ (`:129–144`) ein Satz; CHANGELOG [Unreleased] Changed

### T4 — ruff.toml verlangt die gepinnte Version  [ ]
Komponente: scripts · Dateien: ruff.toml, scripts/dev/toolchain-lockstep.sh, scripts/tests/toolchain_lockstep_test.sh, DEVELOPMENT.md, CHANGELOG.md
Änderung: `ruff.toml` bekommt top-level `required-version = "==0.15.20"` (vor `line-length`, mit einem
Kommentar zum Warum). Der Lockstep liest den Wert in Prüfung 2 und verlangt Gleichheit mit `RUFF_BOOT`; fehlt er
oder weicht er ab → Exit 1 mit „ruff.toml required-version …“. Warum: `run.sh:497–503` nimmt das erste `ruff`
im `PATH`, der Pin aus T3 heilt nur neu installierte Venvs; mit required-version bricht ein anderes ruff mit
Exit 2 ab, statt still andere Regeln anzuwenden. Bewusste Folge (im DEVELOPMENT.md-Satz nennen):
`scripts/dev/format-file.sh:27` formatiert mit einem falschen ruff still gar nicht (sein Exit bleibt 0).
Test (zuerst, rot): Die Fixture schreibt `ruff.toml` mit `required-version = "==<ruff_boot>"`; Fälle: fehlt →
Exit 1, weicht ab → Exit 1, gleich → Exit 0; REAL_ROOT bleibt grün.
Beweis: Probe 2026-09-30 · ruff 0.16.8 mit `required-version = "==0.15.20"` → Exit 2 („Required version
`==0.15.20` does not match the running version“), 0.15.20 → Exit 0; ruff-Doku: https://docs.astral.sh/ruff/settings/#required-version
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md „Python-Lint/Format (ruff)“ ein Satz; CHANGELOG [Unreleased] Changed (Eintrag aus T3 ergänzen)
Abhängt von: T3

Abschluss-Evidenz (PR-Body): PR-CI grün (web check/lint/unit, Web-Frontend (Playwright E2E), desktop-ui,
python-lint, tools-Job mit Lockstep) und ein `audit.yml`-Lauf auf dem Branch mit grünem npm-Job — den startet
die Aufsicht nach dem Push.
