<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness Stufe 5c — Test-Ausgaben und Pflicht-Tests gegen den Stack — Task-Ledger
Status: aktiv · Branch: harness/stufe-5c · Commit-Granularität: pro Task · Review: pro Task (Sonnet, 10 min) · Modell: Opus
Spec: docs/features/harness-stufe-5.md (Roadmap R-0008, Teil 5c)
Heavy: linux-full — Abschluss `run.sh integration` und `e2e` auf einer Pool-VM (Stack, Playwright live, JUnit), Kevins Wort vorausgesetzt.
DoD je Task: CLAUDE.md (Tests grün, ruff/shellcheck/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Hängt ab von: harness-stufe-5a (gemergt) — beide berühren `heavy.sh`

Externe Formate vor dem Bau per WebFetch nachlesen und im Commit zitieren: Playwright-Reporter
(playwright.dev/docs/test-reporters), `@wdio/junit-reporter` (webdriver.io/docs/junit-reporter).

### T1 — JUnit aus den pytest-Schritten, gesammelt vom Wochenlauf  [x]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/heavy.sh, scripts/tests/heavy_test.sh, scripts/tests/run_flags_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @70e91718 2026-09-27T11:41:01+02:00
Review: approve (sonnet)
Änderung:
- Die pytest-Schritte in `run.sh` (monitoring :592, ca-issuer :598, server :606, schemathesis :626) bekommen `--junitxml="$AH_OUT_DIR/junit/<schritt-id>.xml"`.
- `heavy.sh` kopiert `.ah-out/junit/` in das Verzeichnis des Laufs (`$OUT/junit/`). Der Report nennt, wie viele XMLs dort liegen.
- Tests: `heavy_test.sh` mit Fake-XMLs im gezogenen Verzeichnis ⇒ im Report und im Laufverzeichnis. Ein Stub-pytest-Schritt ⇒ die XML entsteht am erwarteten Ort.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: DEVELOPMENT.md (wo JUnit liegt)

### T2 — JUnit aus Playwright und wdio  [x]
Komponente: web · Dateien: apps/web/playwright.config.ts, apps/desktop/e2e/wdio.conf.js, apps/desktop/e2e/package.json, apps/desktop/e2e/package-lock.json
Evidenz: run.sh[quick]: 1 passed, 0 failed, 17 skipped @ec5e771f 2026-09-27T11:47:52+02:00
Review: approve (sonnet)
Änderung:
- `playwright.config.ts:13` bekommt zusätzlich `['junit', { outputFile: … }]`. Der Pfad kommt aus `AH_OUT_DIR`, mit Default wie im Repo üblich; ohne `AH_OUT_DIR` wird nichts geschrieben.
- `wdio.conf.js:67` bekommt `@wdio/junit-reporter` mit `outputDir`. Die Paketversion wird zur installierten `@wdio/cli` passend gepinnt, die Lockfile wird nachgezogen.
- Die Syntax beider Reporter steht in der Doku (WebFetch, Zitat im Commit).
- Test: `npm run check` und `lint` in `apps/web`. Die XML selbst entsteht erst im Abschluss-Beweis auf der VM.
Verify: bash scripts/tests/run.sh quick --strict --only web desktop-e2e
Doku: keine (T6)

### T3 — Postgres und Redis des Test-Stacks auf 127.0.0.1  [x]
Komponente: scripts · Dateien: docker-compose.test.yml, scripts/tests/lib_e2e_stack.sh, scripts/tests/lib_e2e_stack_test.sh, scripts/tests/run.sh
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @7bc9f6d0 2026-09-27T11:59:30+02:00
Review: approve (sonnet)
Änderung:
- `docker-compose.test.yml` veröffentlicht Postgres und Redis nur auf `127.0.0.1`. Die Ports sind `ITEST_PG_PORT` und `ITEST_REDIS_PORT` und werden wie die übrigen ITEST-Ports pro PID gestreut.
- `lib_e2e_stack.sh` exportiert `ITEST_DATABASE_URL` und `ITEST_REDIS_URL`, die Zugangsdaten stammen aus der Wegwerf-`.env`.
- Das Produktions-`docker-compose.yml` bleibt unverändert.
- Test: `lib_e2e_stack.sh` wird hermetisch mit einem Fake-`docker` geprüft: Die URLs werden gebildet und zeigen auf 127.0.0.1.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: keine (T6)

### T4 — Die drei Pflicht-Tests laufen im Integration-Layer gegen den Stack  [x]
Komponente: scripts · Dateien: scripts/tests/stack_pytest.sh (neu, SPDX), scripts/tests/run.sh, apps/server/tests/test_stream_redis.py, scripts/tests/stack_pytest_test.sh
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @5c34e8db 2026-09-27T12:36:07+02:00
Review: approve (sonnet); ensure_venv without || true after the diff-scan (no errexit in run.sh, same behaviour)
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

### T5 — Playwright-Projekt `live` ohne Mocks gegen den Stack  [x]
Evidenz: run.sh[quick]: 1 passed, 0 failed, 17 skipped @91434b32 2026-09-27T15:00:10+02:00
Review: request_changes -> approve (sonnet, 2 rounds: Verify line widened to web scripts)
Entscheidung: Kevin, 2026-09-27, übermittelt durch die Aufsichts-Session adminhelper-ac: Option A auf die Frage „Die Web-UI hat keine Server-Seite (apps/web/src/routes.ts: users, apikeys, hooks, frp, audit), der CRUD-Rundlauf ‚Server anlegen, sehen, löschen‘ ist im Browser nicht machbar — (A) Benutzer anlegen, in der Liste sehen, löschen, (B) Server per API seeden und im Web nur Smoke+Login, (C) API-Key oder Hook“. Dazu bleiben Smoke und Login mit dem Seed-Admin. Bestätigt: `live` nur mit `ITEST_WEB_URL`, `chromium` unverändert, Stack-Start in `scripts/tests/web_live.sh` (per set-files), JUnit über `PLAYWRIGHT_JUNIT_OUTPUT_FILE`.
Komponente: web · Dateien: apps/web/playwright.config.ts, apps/web/tests/live/smoke.live.spec.ts (neu, SPDX), scripts/tests/run.sh, scripts/tests/web_live.sh
Änderung:
- Neues Projekt `live` in `playwright.config.ts`:
  - `testDir: tests/live` und `baseURL` aus `ITEST_WEB_URL`, ohne `mockApi`;
  - das bestehende Projekt `chromium` bleibt unverändert und läuft weiter im PR-CI.
- Die Specs decken Smoke, Login mit dem Seed-Admin aus `lib_e2e_stack` und ein CRUD-Rundlauf (Benutzer anlegen, sehen, löschen — Entscheidung oben) ab.
- `run.sh`: neuer Schritt `web-live` im Integration-Layer (nicht e2e, nicht PR-CI), in `AH_HEAVY_INTEGRATION`.
- Test: `npm run check` und `lint`. Der echte Lauf folgt im Abschluss.
Verify: bash scripts/tests/run.sh quick --strict --only web scripts
Doku: keine (T6)
Abhängt von: T2, T3

### T6 — Doku  [x]
Komponente: scripts · Dateien: DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html, CHANGELOG.md
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @a93e0b7e 2026-09-27T15:12:36+02:00
Review: approve (sonnet)
Änderung:
- `DEVELOPMENT.md`: JUnit-Ort, Stack-Ports, die zwei neuen Integration-Schritte.
- `cicd.html` DE+EN: was der Integration-Layer als Pflicht prüft und warum dieselben Tests im PR-CI weiter gegen Service-Container laufen.
- `CHANGELOG`: Eintrag unter „Unreleased“, Abschnitt „Changed“.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: DEVELOPMENT.md · docs/developer/cicd.html · docs/en/developer/cicd.html · CHANGELOG.md
Abhängt von: T1–T5

### T7 — Live-Smoke lädt jede Admin-Seite wirklich neu; der wdio-Kommentar sagt, wer die XML sammelt  [x]
Komponente: web · Dateien: apps/web/tests/live/smoke.live.spec.ts, apps/desktop/e2e/wdio.conf.js
Evidenz: run.sh[quick]: 1 passed, 0 failed, 17 skipped @b15916f4 2026-09-27T15:51:40+02:00
Review: approve (sonnet)
Änderung: Funde 1 und 3 aus `/code-review high` über den Branch (2026-09-27, Kevin: „fix die echten Funde als T7/T8“). (1) `page.goto` auf dieselbe URL mit anderem Hash lädt nicht neu (playwright.dev, page.goto: „navigation to the same URL with a different hash, which would succeed and return `null`“) — die Smoke prüft damit weder `hydrate()` noch, dass die neue Seite rendert, und `.page-title` kann der alte Titel sein; nach jedem Hash ein `page.reload()`, das das Dokument frisch lädt. (3) Der Kommentar in `wdio.conf.js` nennt `box_desktopbox.sh` neben „collected by heavy.sh“; gesammelt wird nur, was `run.sh` auf der Box schreibt (Ebene `all`), der Capstone-Pfad nicht.
Verify: bash scripts/tests/run.sh quick --strict --only web desktop-e2e
Doku: keine (Test- und Kommentar-Korrektur)

### T8 — Stack-Skripte: AH_OUT_DIR absolut, Ports außerhalb des ephemeren Bereichs, Redis-URL mit Port-Default und Zugangsdaten  [ ]
Komponente: scripts · Dateien: scripts/tests/stack_pytest.sh, scripts/tests/web_live.sh, scripts/tests/lib_e2e_stack.sh, scripts/tests/lib_e2e_stack_test.sh, scripts/tests/stack_pytest_test.sh, scripts/tests/run.sh, scripts/tests/run_flags_test.sh, DEVELOPMENT.md
Änderung: Funde 5, 6 und 8 aus `/code-review high` über den Branch (2026-09-27). (5) `stack_pytest.sh` und `web_live.sh` machen ein relatives `AH_OUT_DIR` absolut, bevor sie in eine Komponente wechseln — sonst schreibt pytest bzw. Playwright die XML unter `apps/<komp>/` und das Urteil findet keine. (6) Die Postgres- und Redis-Ports von `e2e_init` liegen heute ganz im ephemeren Bereich von Linux (32768–60999); sie wandern darunter und unter den Datenpfad (21000–38999). (8) `redis_reachable` in `run.sh` nimmt ohne Port 6379 und streift Zugangsdaten ab, wie `redis.from_url`. Tests: Bereichsgrenzen in `lib_e2e_stack_test.sh`, ein relatives `AH_OUT_DIR` in `stack_pytest_test.sh`, eine URL mit Zugangsdaten gegen einen lokalen Listener in `run_flags_test.sh`. Nicht übernommen: Fund 2 (die VMs installieren `docker-ce` aus download.docker.com, Stand ≥ 28 — auf der Box geprüft im Abschluss), Fund 4 (die XML des roten Erstlaufs ist die Evidenz eines Flakes), Fund 7 (ein pip-Fehler ist rot wie in den Unit-Schritten).
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: DEVELOPMENT.md (Portbereiche)

## Abschluss (nach T6, auf Kevins Wort, überwacht)

1. `iter.sh integration --strict` auf einer Pool-VM (`linux-full`). Erwartet:
   - `stack-pytest` und `web-live` sind grün;
   - die drei Pflicht-Tests erscheinen erstmals als PASS in `junit/stack-*.xml`;
   - die JUnit-XMLs liegen nach `vm.py pull` unter `.ah-out/junit/`.
2. Gegenprobe auf einem Wegwerf-Branch: ein absichtlich roter Test ⇒ genau dieser Fall steht als `failure` im JUnit.
3. `vm.py list` ist danach sauber.
