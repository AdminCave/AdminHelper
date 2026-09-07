# Code-Review-Fixes — Task-Ledger
Status: aktiv · Branch: feature/code-review-fixes · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: docs/features/code-review-fixes.md
Fast-Suite: lokal · Warm-Profil: desktop
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Hinweis: Fünf Befunde, sechs Tasks (B1 zerfällt in Backend und UI, weil es zwei
Komponenten sind; B5 kam beim Nachprüfen am 03.09. hinzu). Jeder Task bringt
einen Test mit, der auf dem alten Code rot ist — sonst ist nicht bewiesen, dass
er den Befund trifft. T1/T2 hängen zusammen (API-Vertrag), der Rest ist
unabhängig. Verifiziert: `run.sh quick` läuft lokal grün (10 Schritte), node
22 / npm 10 kommen über `source .devenv.sh`. Kein `Abschluss: multibox`:
der Diff berührt keinen Cross-Host-Pfad; ob die schwere Suite nötig ist,
entscheidet der Abschluss anhand des realen Diffs (B4 fasst die Server-API an).

## Phase 1 — B1: Der stille No-op (Hoch)

### T1 — Backend: manueller Lauf sagt die Wahrheit  [ ]
Komponente: apps/monitoring · Dateien: app/routers/checks.py, tests/test_checks_crud.py
Änderung: **Der `/run`-Endpunkt ist heute von keinem einzigen Test abgedeckt** (verifiziert) — das ist der Grund, warum der No-op überlebt hat; die neuen Fälle gehören zu den bestehenden Router-Tests in `test_checks_crud.py`. `run_check_now` (Z. 288–301) prüft VOR dem Aufruf von `execute_check`: ist `check.check_type` in `PUSH_ONLY_TYPES` oder ist der Check deaktiviert, dann `409 Conflict` mit verständlichem `detail` statt eines 200 mit unverändertem State. Grund: `execute_check` steigt für beide Fälle still aus (`check_engine.py` Z. 117 `enabled`-Filter, Z. 129–130 Push-Only-Return), der Endpunkt meldete das aber als Erfolg. Die Prüfung gehört in den Router — `execute_check` selbst wird vom Scheduler aufgerufen und darf dort weiter still aussteigen.
Verify: `cd apps/monitoring && .venv/bin/python -m pytest -q tests/` mit neuen Fällen: (a) `smart_health`-Check → 409, State unverändert; (b) deaktivierter `ping`-Check → 409; (c) aktiver `ping`-Check → weiterhin 200 und `execute_check` lief. Dann `source .devenv.sh && AH_ONLY='monitoring' bash scripts/tests/run.sh quick`.
Doku: CHANGELOG (Fixed) — im selben Commit

### T2 — Desktop-UI: keine tote Aktion mehr anbieten  [ ]
Komponente: apps/desktop/ui · Dateien: src/components/monitoring/section/MonCheckLine.svelte, src/lib/i18n/dictionaries.ts, src/components/monitoring/MonCheckLine.run.test.ts (**neue Datei ⇒ SPDX-Header**; Konvention: der Test liegt eine Ebene über der Komponente und importiert `./section/MonCheckLine.svelte` — siehe MonCheckLine.edit.test.ts)
Änderung: Den „Jetzt prüfen"-Button (Z. 84) für push-ausgewertete und für deaktivierte Checks ausblenden bzw. deaktivieren, mit erklärendem `title` (neuer i18n-Key **DE und EN**, analog zu `monitoring.check.runNow` in `dictionaries.ts` Z. 559/1149). Die Push-Typen-Liste darf im UI nicht neu erfunden werden — sie muss aus einer einzigen Stelle kommen (Konstante im UI-Modell, kommentiert mit dem Verweis auf `apps/monitoring/app/check_types.py` als Quelle der Wahrheit). Die zweite Aufrufstelle `infra/tabs/MonitoringTab.svelte` Z. 78 mitziehen, damit dort nicht dieselbe tote Aktion bleibt.
Verify: `source .devenv.sh && AH_ONLY='desktop-ui' bash scripts/tests/run.sh quick` (svelte-check, eslint, vitest) mit einem neuen Komponententest: bei `check_type='smart_health'` und bei `enabled=false` ist der Run-Button nicht klickbar, bei `ping` + enabled schon.
Doku: docs/admin/monitoring.html + docs/en/… (ein Satz: push-ausgewertete Checks werden nur per Agent-Push aktualisiert und lassen sich nicht manuell auslösen) — im selben Commit
Abhängt von: T1

## Phase 2 — Die übrigen drei Befunde

### T3 — B2: Semaphore-Leak im Hook-Runner schließen  [ ]
Komponente: apps/server · Dateien: app/modules/hooks/script_runner.py, tests/test_hook_isolation.py
Änderung: Das in Z. 127 geholte Permit wird erst ab Z. 170 durch `try`/`finally` (Z. 188–189) geschützt. Alles dazwischen — `subprocess.Popen` (Z. 138) und die beiden `Thread.start()` (Z. 168–169) — kann werfen und das Permit dauerhaft verlieren; bei `BoundedSemaphore(8)` sind Hooks nach acht solchen Fehlschlägen bis zum Neustart tot und melden irreführend „Server ausgelastet". Den geschützten Bereich so ausweiten, dass er unmittelbar nach dem `acquire` beginnt.
Verify: `source .devenv.sh && cd apps/server && DATABASE_URL="$AH_TEST_DB" .venv/bin/python -m pytest -q tests/` mit einem neuen Test, der `subprocess.Popen` auf `OSError` patcht: nach N Aufrufen ist der Semaphore-Zähler unverändert und ein anschließender regulärer Hook läuft noch (auf dem alten Code rot). Dann `source .devenv.sh && AH_ONLY='server' bash scripts/tests/run.sh quick`.
Doku: CHANGELOG (Fixed) — im selben Commit

### T4 — B3: Statusübergänge im Push-Pfad loggen  [ ]
Komponente: apps/monitoring · Dateien: app/routers/agent.py, tests/test_agent_report.py
Änderung: Im Push-Pfad (Z. 288–289) fehlt beim Statuswechsel die Log-Zeile, die der Scheduler-Pfad schreibt (`check_engine.py` Z. 213–221: `logger.info("Check '%s': %s -> %s (%s)")`). Dieselbe Zeile ergänzen, gleiches Format. Ohne sie hinterlässt ein unterdrückter Übergang (Maintenance, Host-down) nirgends eine Spur — `MonitorAlertLog` hält nur versendete Alerts.
Verify: `cd apps/monitoring && .venv/bin/python -m pytest -q tests/` mit einem Test, der über `caplog` prüft: ein Push, der einen Check von ok auf critical bringt, erzeugt genau eine Übergangs-Log-Zeile; ein Push ohne Statuswechsel keine.
Doku: keine (intern)

### T5 — B4: Internal-Key-Gate im Server nachhärten  [ ]
Komponente: apps/server · Dateien: app/modules/notifications/router.py, tests/test_notifications.py
Änderung: `require_internal_key` (Z. 161) übergibt rohe `str` an `secrets.compare_digest`; ein Nicht-ASCII-Header löst dort einen `TypeError` aus → unbehandelter 500 statt 403. Die Monitoring-Fassung (`apps/monitoring/app/core/auth.py` Z. 14–19) ist bereits gehärtet: Byte-Vergleich, `None`-tolerant, mit Docstring-Begründung. Den Server auf dieselbe Semantik ziehen (fail-closed bei leerem erwarteten Key bleibt unverändert).
Verify: `source .devenv.sh && cd apps/server && DATABASE_URL="$AH_TEST_DB" .venv/bin/python -m pytest -q tests/` mit einem Test: `X-Internal-Key` mit Nicht-ASCII-Zeichen ergibt 403 (nicht 500); gültiger Key weiterhin 202; leerer erwarteter Key lehnt weiterhin alles ab.
Doku: keine (intern)

## Phase 3 — Nachtrag aus der Verifikation

### T6 — run.sh überspringt das Python-Lint-Gate stillschweigend  [ ]
Komponente: scripts · Dateien: scripts/tests/run.sh
Änderung: **Nicht aus dem Review vom 12.08., sondern beim Nachprüfen am 03.09. gefunden.** `run.sh` sucht `ruff` per `have ruff` im PATH (Z. 108); das Binary liegt aber unter `apps/server/.venv/bin/ruff` und ist nicht im PATH. Ergebnis: Der Lauf meldet „10 passed, 0 failed, 1 skipped", ohne dass Python jemals gelintet wurde — dieselbe Klasse von stillem Fehlschlag wie B1, und laut CLAUDE.md heißt SKIP „nicht verifiziert", nicht „ok". Zusätzlich lintet der Schritt nur `apps/server apps/monitoring`, obwohl CLAUDE.md alle **drei** Python-Komponenten nennt: `apps/ca-issuer` fehlt. Beides beheben: die Venv-Pfade als Fallback zur PATH-Suche heranziehen und `apps/ca-issuer` in beide ruff-Aufrufe aufnehmen.
Verify: `bash scripts/tests/run.sh quick` zeigt `PASS ruff check` und `PASS ruff format check` statt SKIP (real geprüft: der Lint ist inhaltlich sauber — `ruff check` meldet „All checks passed!", `ruff format --check` „263 files already formatted" über alle drei Komponenten). Gegenprobe: ein absichtlicher Formatfehler in `apps/ca-issuer` färbt den Schritt rot.
Doku: keine (intern)
