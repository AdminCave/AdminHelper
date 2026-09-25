<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness Stufe 5c — Test-Ausgaben und Pflicht-Tests gegen den Stack — Task-Ledger
Status: freigegeben · Branch: harness/stufe-5c · Commit-Granularität: pro Task · Review: pro Task (Sonnet, 10 min) · Modell: Opus
Spec: docs/features/harness-stufe-5.md (Roadmap R-0008, Teil 5c)
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: linux-full — Abschluss `run.sh integration` und `e2e` auf einer Pool-VM (Stack, Playwright live, JUnit), Kevins Wort vorausgesetzt.
DoD je Task: CLAUDE.md (Tests grün, ruff/shellcheck/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Hängt ab von: harness-stufe-5a (gemergt) — beide berühren `heavy.sh`

Externe Formate vor dem Bau per WebFetch nachlesen und im Commit zitieren: Playwright-Reporter
(playwright.dev/docs/test-reporters), `@wdio/junit-reporter` (webdriver.io/docs/junit-reporter).

### T1 — JUnit aus den pytest-Schritten, gesammelt vom Wochenlauf  [ ]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Änderung:
- Die pytest-Schritte in `run.sh` (monitoring :592, ca-issuer :598, server :606, schemathesis :626) bekommen `--junitxml="$AH_OUT_DIR/junit/<schritt-id>.xml"`.
- `heavy.sh` kopiert `.ah-out/junit/` in das Verzeichnis des Laufs (`$OUT/junit/`). Der Report nennt, wie viele XMLs dort liegen.
- Tests: `heavy_test.sh` mit Fake-XMLs im gezogenen Verzeichnis ⇒ im Report und im Laufverzeichnis. Ein Stub-pytest-Schritt ⇒ die XML entsteht am erwarteten Ort.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: DEVELOPMENT.md (wo JUnit liegt)

### T2 — JUnit aus Playwright und wdio  [ ]
Komponente: web · Dateien: apps/web/playwright.config.ts, apps/desktop/e2e/wdio.conf.js, apps/desktop/e2e/package.json
Änderung:
- `playwright.config.ts:13` bekommt zusätzlich `['junit', { outputFile: … }]`. Der Pfad kommt aus `AH_OUT_DIR`, mit Default wie im Repo üblich; ohne `AH_OUT_DIR` wird nichts geschrieben.
- `wdio.conf.js:67` bekommt `@wdio/junit-reporter` mit `outputDir`. Die Paketversion wird zur installierten `@wdio/cli` passend gepinnt, die Lockfile wird nachgezogen.
- Die Syntax beider Reporter steht in der Doku (WebFetch, Zitat im Commit).
- Test: `npm run check` und `lint` in `apps/web`. Die XML selbst entsteht erst im Abschluss-Beweis auf der VM.
Verify: bash scripts/tests/run.sh quick --strict --only web desktop-e2e
Doku: keine (T6)

### T3 — Postgres und Redis des Test-Stacks auf 127.0.0.1  [ ]
Komponente: scripts · Dateien: docker-compose.test.yml, scripts/tests/lib_e2e_stack.sh
Änderung:
- `docker-compose.test.yml` veröffentlicht Postgres und Redis nur auf `127.0.0.1`. Die Ports sind `ITEST_PG_PORT` und `ITEST_REDIS_PORT` und werden wie die übrigen ITEST-Ports pro PID gestreut.
- `lib_e2e_stack.sh` exportiert `ITEST_DATABASE_URL` und `ITEST_REDIS_URL`, die Zugangsdaten stammen aus der Wegwerf-`.env`.
- Das Produktions-`docker-compose.yml` bleibt unverändert.
- Test: `lib_e2e_stack.sh` wird hermetisch mit einem Fake-`docker` geprüft: Die URLs werden gebildet und zeigen auf 127.0.0.1.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: keine (T6)

### T4 — Die drei Pflicht-Tests laufen im Integration-Layer gegen den Stack  [ ]
Komponente: scripts · Dateien: scripts/tests/stack_pytest.sh (neu, SPDX), scripts/tests/run.sh, apps/server/tests/test_stream_redis.py
Änderung:
- `stack_pytest.sh` startet den Stack über `lib_e2e_stack.sh` und fährt drei Tests gegen dessen Dienste:
  - `apps/monitoring/tests/test_migrations_smoke.py` mit `DATABASE_URL=$ITEST_DATABASE_URL`;
  - `apps/server/tests/test_stream_redis.py` mit `AH_TEST_REDIS_URL=$ITEST_REDIS_URL`;
  - `apps/ca-issuer/tests/test_db_token_store.py::test_concurrent_consume_only_one_wins` mit `AH_TEST_DB=$ITEST_DATABASE_URL`.
- Jeder Test schreibt JUnit nach `junit/stack-*.xml`. Ein Skip gilt dort als Fehler, weil der Dienst ja da ist.
- `test_stream_redis.py` liest `AH_TEST_REDIS_URL`, Default ist wie heute `redis://localhost:6380/0`, damit ci.yml unverändert bleibt.
- `run.sh`: neuer Schritt `stack-pytest` im Integration-Layer und in `AH_HEAVY_INTEGRATION`.
- Test: der Skip-als-Fehler-Mechanismus hermetisch mit einem Stub-pytest, der „skipped“ meldet. Der echte Lauf folgt im Abschluss.
Verify: bash scripts/tests/run.sh quick --strict --only scripts server
Doku: keine (T6)
Abhängt von: T3

### T5 — Playwright-Projekt `live` ohne Mocks gegen den Stack  [ ]
Komponente: web · Dateien: apps/web/playwright.config.ts, apps/web/tests/live/smoke.live.spec.ts (neu, SPDX), scripts/tests/run.sh
Änderung:
- Neues Projekt `live` in `playwright.config.ts`:
  - `testDir: tests/live` und `baseURL` aus `ITEST_WEB_URL`, ohne `mockApi`;
  - das bestehende Projekt `chromium` bleibt unverändert und läuft weiter im PR-CI.
- Die Specs decken Smoke, Login mit dem Seed-Admin aus `lib_e2e_stack` und ein CRUD-Rundlauf (Server anlegen, sehen, löschen) ab.
- `run.sh`: neuer Schritt `web-live` im Integration-Layer (nicht e2e, nicht PR-CI), in `AH_HEAVY_INTEGRATION`.
- Test: `npm run check` und `lint`. Der echte Lauf folgt im Abschluss.
Verify: bash scripts/tests/run.sh quick --strict --only web
Doku: keine (T6)
Abhängt von: T2, T3

### T6 — Doku  [ ]
Komponente: scripts · Dateien: DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html
Änderung:
- `DEVELOPMENT.md`: JUnit-Ort, Stack-Ports, die zwei neuen Integration-Schritte.
- `cicd.html` DE+EN: was der Integration-Layer als Pflicht prüft und warum dieselben Tests im PR-CI weiter gegen Service-Container laufen.
- `CHANGELOG`: Eintrag unter „Unreleased“, Abschnitt „Changed“.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: DEVELOPMENT.md · docs/developer/cicd.html · docs/en/developer/cicd.html · CHANGELOG.md
Abhängt von: T1–T5

## Abschluss (nach T6, auf Kevins Wort, überwacht)

1. `iter.sh integration --strict` auf einer Pool-VM (`linux-full`). Erwartet:
   - `stack-pytest` und `web-live` sind grün;
   - die drei Pflicht-Tests erscheinen erstmals als PASS in `junit/stack-*.xml`;
   - die JUnit-XMLs liegen nach `vm.py pull` unter `.ah-out/junit/`.
2. Gegenprobe auf einem Wegwerf-Branch: ein absichtlich roter Test ⇒ genau dieser Fall steht als `failure` im JUnit.
3. `vm.py list` ist danach sauber.
