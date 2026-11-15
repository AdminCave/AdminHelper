<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# WordPress-Cron aus der Site-Datenbank — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-35 · Review: pro Task
Spec: docs/features/kern-monitoring-35.md (Roadmap R-1423)
Heavy: linux-full — neue Ansicht und Abhängigkeit im Agent (`apps/agent`), kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Baut erst, wenn kern-monitoring-28 (#542) gemergt ist (`sensor_app.go`, Katalog), dann `origin/main` hineinmergen.
Nur lesende feste Abfragen, nur über das Unix-Socket des Datenbank-Containers, der Zugang verlässt den Host nie
(Kevin 2026-11-14). `security` je Task (Zugangsdaten, fremde Container-Wurzel).

### T1 — R-1423: Option `cron` zählen  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/app_wordpress_cron.go, apps/agent/internal/probe/app_wordpress_cron_test.go
Änderung: Kleiner Parser für PHP-`serialize()` (nur `a:`, `i:`, `s:`, `b:`, `N;`, verschachtelt, Grenzen für Tiefe,
Länge und Einträge) und `wpCronCounts(data, now)`: zählt die ganzzahligen Schlüssel der obersten Ebene als
`events`, überfällig (älter als 10 Minuten) als `overdue`, dazu `oldest_overdue_s`; `version` und andere Schlüssel
zählen nicht. Kein Text der Option in Werten oder Fehlern. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T4

### T2 — R-1423: Ansicht `wordpress_cron` über das Socket des Datenbank-Containers  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/app_wordpress_cron.go, apps/agent/internal/probe/app_wordpress_cron_linux.go, apps/agent/internal/probe/app_wordpress_cron_test.go, apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/target.go, apps/agent/go.mod, apps/agent/go.sum, THIRD_PARTY_LICENSES.md
Änderung: `wordpressCron` am Container (`containerKinds`): `WORDPRESS_DB_*` und `WORDPRESS_TABLE_PREFIX` aus
`Config.Env`, den Datenbank-Container über Alias/DNS-Namen in einem gemeinsamen Netz (genau einer, läuft, Image
`mariadb`/`mysql`), sein Socket unter `/proc/<pid>/root` über `os.Root`, Verbindung mit
`github.com/go-sql-driver/mysql` nur per Unix-Socket, 5 s Zeitlimit, eine feste Abfrage (Spec „Ablauf“). Alles
andere `unsupported`; Benutzer und Passwort nie in Fehlern. Gegen echte Container (`wordpress` + `mariadb`, Docker
der Dev-Box) einmal von Hand geprüft, Ergebnis in `## Entscheidungen`. Lizenz in `THIRD_PARTY_LICENSES.md`.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T4
Abhängt von: T1

### T3 — R-1423: Katalog `wordpress` v3 mit Check `cron`  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/wordpress.py, apps/monitoring/tests/test_catalog_wordpress.py, apps/monitoring/tests/test_catalog_sensors.py
Änderung: Check `cron` (Sensor `app`, Ansicht `wordpress_cron`, Ziel Container, alle 900 s, Felder `events`,
`overdue`, `oldest_overdue_s`; `oldest_overdue_s` > 3600 warn, > 86400 crit), Version 3, Docstring (Grenzen,
Zugangsdaten bleiben lokal); Ansicht in der Sensor-Liste des Katalogs.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_wordpress.py tests/test_catalog_sensors.py
Doku: → T4
Abhängt von: T2

### T4 — Doku DE+EN und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-monitoring-35.md
Änderung: Modul `wordpress` (Check `cron`, was gelesen wird, was nie den Host verlässt, Grenzen) und Ansicht in der
Entwickler-Doku, DE+EN; Changelog-Fragment.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
