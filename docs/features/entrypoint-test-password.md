<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Entrypoint-Test: Leck-Probe mit eigenem Passwort

Roadmap: R-0824 (REG) · Quelle: Sammellauf 2026-10-22-1215 über `main@237b450a`, Schritt `server pytest`

## Befund

`apps/server/tests/test_images_exec_only.py::test_the_entrypoint_of_monitoring_creates_its_database_once` prüft, dass
die Ausgabe eines gescheiterten Laufs das Passwort nicht nennt:

```python
failed = run(ADMIN_DB=f"{name}-missing")
leaked = bool(url.password) and url.password in failed.stdout + failed.stderr
```

Ohne `DATABASE_URL` (Pool-Box im Sammellauf, lokal ohne `.devenv.sh`) startet `pg_engine` einen
testcontainers-Postgres mit Benutzer und Passwort `test`. Der Datenbankname des Tests heißt
`ah-test-Monitor-<hex>`, und die Fehlermeldung des Entrypoints nennt ihn (`[entrypoint] FEHLER: Datenbank <name>: …`,
psycopg: `database "<name>-missing" does not exist`). `"test"` steht damit in jeder Ausgabe, die Probe schlägt an,
ohne dass ein Passwort ausgegeben wurde. In der PR-CI (`cipw`) und mit der lokalen Test-DB trifft der Teilstring
nicht, dort ist der Test grün. Der Entrypoint selbst gibt das Passwort nicht aus: libpq liest es aus `PGPASSWORD`,
es ist weder Argument noch Teil der Meldung (`apps/monitoring/docker-entrypoint.sh:34-55`).

Beleg: dreimal identisch rot auf `origin/main@53a7dbc5` mit
`env -u DATABASE_URL .venv/bin/python -m pytest -q -p no:randomly tests/test_images_exec_only.py -k entrypoint_of_monitoring`
(`AssertionError: the output of the failed run names the password`, `1 failed, 6 deselected`); im Sammellauf auf der
Box dreimal rot (erster Lauf, zwei Wiederholungen).

## Soll

Die Leck-Probe ist nur aussagekräftig mit einem Passwort, das nicht zufällig in Namen, Benutzer oder Host steht. Der
gescheiterte Lauf bekommt deshalb zusätzlich zur fehlenden `ADMIN_DB` ein zufälliges Sentinel-Passwort
(`secrets.token_hex(16)`) als `PGPASSWORD`; geprüft wird, dass das Sentinel in keiner Ausgabe steht. Je nach
`pg_hba` scheitert der Lauf an der Anmeldung (Passwort-Auth, CI und testcontainers) oder an der fehlenden Datenbank
(trust); beide Wege enden im selben `except psycopg.Error`, mit Exit 1 und der Zeile
`[entrypoint] FEHLER: Datenbank <name>: …`, die der Test weiter zusichert.

Verworfen:
- eigene Rolle mit Zufallspasswort: die lokale Test-DB hat kein `CREATEROLE` (geprüft: `rolcreaterole = false`).
- Datenbankname ohne `test`: verschiebt das Problem nur, das Passwort einer anderen Umgebung kann wieder im Namen,
  im Benutzer oder im Host stehen.

## Nicht-Ziele

Die Meldungstexte des Entrypoints (englisch) ändert `docs-residual-risks` T10; dieses Vorhaben lässt sie, damit
beide nicht dieselben Zeilen ändern. `docs-residual-risks` T10 baut nach dem Merge hiervon.

## Heavy

`none` als Merge-Gate: nur Testcode in `apps/server/tests/`. Nach dem Merge fährt die Session den Schritt einzeln auf
einer Box über `main` (`run.sh all --strict --step "server pytest"`), damit der Sammellauf-Befund geschlossen ist.
