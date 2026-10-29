<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Entrypoint-Test: Leck-Probe mit eigenem Passwort — Task-Ledger
Status: erledigt · Branch: feature/entrypoint-test-password · Review: am Ende
Spec: docs/features/entrypoint-test-password.md (Roadmap R-0824)
Heavy: none — nur Testcode in `apps/server/tests/`; nach dem Merge fährt die Session den Schritt `server pytest` einzeln auf einer Box über `main`
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: Die Leck-Probe des Monitoring-Entrypoint-Tests schlägt nur an, wenn ein Passwort ausgegeben wird, in jeder
Umgebung (testcontainers mit Passwort `test`, PR-CI, lokale Test-DB). Zeilenangaben: origin/main@53a7dbc5.

### T1 — Leck-Probe mit Sentinel-Passwort statt des Container-Passworts  [x]
Komponente: server · Dateien: apps/server/tests/test_images_exec_only.py, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @6d716a4e 2026-10-23T06:31:02+02:00
Review: am Ende (Branch-Review)
Änderung: In `test_the_entrypoint_of_monitoring_creates_its_database_once` (`test_images_exec_only.py:315-361`) bekommt der gescheiterte Lauf zusätzlich `PGPASSWORD=<secrets.token_hex(16)>` (`run(ADMIN_DB=f"{name}-missing", PGPASSWORD=sentinel)`); die Probe prüft `sentinel not in failed.stdout + failed.stderr` statt `url.password`. Die übrigen Zusicherungen bleiben: Exit 1, `stderr` beginnt mit `[entrypoint] FEHLER: Datenbank {name}: `, die zwei erfolgreichen Läufe davor unverändert. Der Kommentar über der Probe nennt das Warum (ein Passwort wie `test` steht sonst im Datenbanknamen der Meldung). Zuerst rot: ohne die Änderung ist der Test ohne `DATABASE_URL` rot (Beweis); nach der Änderung grün mit testcontainers und mit der lokalen Test-DB. Gegenprobe im Commit-Body: eine Kopie des Entrypoint-Programms, die `os.environ["PGPASSWORD"]` in die Fehlermeldung schreibt, macht die neue Probe rot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_images_exec_only.py
Doku: CHANGELOG.md (Fixed, umlautfrei: Test des Monitoring-Entrypoints: die Leck-Probe nutzt ein eigenes Zufallspasswort und schlaegt nicht mehr an, wenn das Postgres-Passwort im Datenbanknamen steht (Sammellauf rot))
Beweis: origin/main@53a7dbc5 · `cd apps/server && env -u DATABASE_URL .venv/bin/python -m pytest -q -p no:randomly tests/test_images_exec_only.py -k entrypoint_of_monitoring` → dreimal `AssertionError: the output of the failed run names the password`, `1 failed, 6 deselected`; Sammellauf 2026-10-22-1215 auf der Box dreimal rot
Dedup-Key: reg:server-pytest
HEAD: 53a7dbc5
