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

### T1 — R-1423: Option `cron` zählen  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/app_wordpress_cron.go, apps/agent/internal/probe/app_wordpress_cron_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @b5f49beb3 2026-11-15T07:01:24+01:00
Review: approve (.ah-out/review/kern-monitoring-35/T1.verdict.json)
Änderung: Kleiner Parser für PHP-`serialize()` (nur `a:`, `i:`, `s:`, `b:`, `N;`, verschachtelt, Grenzen für Tiefe,
Länge und Einträge) und `wpCronCounts(data, now)`: zählt die ganzzahligen Schlüssel der obersten Ebene als
`events`, überfällig (älter als 10 Minuten) als `overdue`, dazu `oldest_overdue_s`; `version` und andere Schlüssel
zählen nicht. Kein Text der Option in Werten oder Fehlern. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T4

### T2 — R-1423: Ansicht `wordpress_cron` über das Socket des Datenbank-Containers  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/app_wordpress_cron.go, apps/agent/internal/probe/app_wordpress_cron_linux.go, apps/agent/internal/probe/app_wordpress_cron_test.go, apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/target.go, apps/agent/go.mod, apps/agent/go.sum, THIRD_PARTY_LICENSES.md, apps/agent/internal/probe/app_wordpress_cron_other.go, apps/agent/internal/probe/app_wordpress_cron_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @57d9df5ae 2026-11-15T07:36:01+01:00
Review: approve (.ah-out/review/kern-monitoring-35/T2.verdict.json)
Änderung: `wordpressCron` am Container (`containerKinds`): `WORDPRESS_DB_*` und `WORDPRESS_TABLE_PREFIX` aus
`Config.Env`, den Datenbank-Container über Alias/DNS-Namen in einem gemeinsamen Netz (genau einer, läuft, Image
`mariadb`/`mysql`), sein Socket unter `/proc/<pid>/root` über `os.Root`, Verbindung mit
`github.com/go-sql-driver/mysql` nur per Unix-Socket, 5 s Zeitlimit, eine feste Abfrage (Spec „Ablauf“). Alles
andere `unsupported`; Benutzer und Passwort nie in Fehlern. Gegen echte Container (`wordpress` + `mariadb`, Docker
der Dev-Box) einmal von Hand geprüft, Ergebnis in `## Entscheidungen`. Lizenz in `THIRD_PARTY_LICENSES.md`.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T4
Abhängt von: T1

### T3 — R-1423: Katalog `wordpress` v3 mit Check `cron`  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/wordpress.py, apps/monitoring/tests/test_catalog_wordpress.py, apps/monitoring/tests/test_catalog_sensors.py, apps/monitoring/app/catalog/sensors.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @10240dacd 2026-11-15T07:38:10+01:00
Review: approve (.ah-out/review/kern-monitoring-35/T3.verdict.json)
Änderung: Check `cron` (Sensor `app`, Ansicht `wordpress_cron`, Ziel Container, alle 900 s, Felder `events`,
`overdue`, `oldest_overdue_s`; `oldest_overdue_s` > 3600 warn, > 86400 crit), Version 3, Docstring (Grenzen,
Zugangsdaten bleiben lokal); Ansicht in der Sensor-Liste des Katalogs.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_wordpress.py tests/test_catalog_sensors.py
Doku: → T4
Abhängt von: T2

### T4 — Doku DE+EN und CHANGELOG  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-monitoring-35.md, docs/features/kern-monitoring-35.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @fc689607b 2026-11-15T07:48:50+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Modul `wordpress` (Check `cron`, was gelesen wird, was nie den Host verlässt, Grenzen) und Ansicht in der
Entwickler-Doku, DE+EN; Changelog-Fragment.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
- T1: Der Parser nimmt außer `a`, `i`, `s`, `b`, `N` auch `d:` und `O:` an: Argumente eines Ereignisses können Floats
  oder Objekte tragen (Prüfer-Nit T1). `R:`/`r:`, `C:` und `E:` bleiben Formfehler.
- T2 nimmt die Prüfer-Nits aus T1 mit (zweiter überfälliger Zeitstempel im Test; Text von `s:` nur, wo er gebraucht
  wird).
- T2: `WORDPRESS_DB_HOST`, `_NAME` und `WORDPRESS_TABLE_PREFIX` nehmen ungesetzt die Voreinstellungen von
  `wp-config-docker.php` (`mysql`, `wordpress`, `wp_`), so wie WordPress selbst; Benutzer und Passwort haben keine
  echte Voreinstellung und müssen gesetzt sein. Das weicht von „nicht raten“ der Spec ab: WordPress im Container
  verbindet sich genau so.
- T2: Den Datenbank-Container sucht ein `docker inspect` über alle laufenden Container (Aliase und DNS-Namen je Netz)
  statt `docker network inspect`: ein Aufruf, und `docker network` steht nicht auf der Freigabeliste.
- T2: Das Socket öffnet `os.Root` mit `O_PATH`, verbunden wird über `/proc/self/fd/<fd>`: kein Pfad außerhalb der
  Wurzel, kein Wettlauf zwischen Prüfen und Verbinden. Absolute Links nimmt `os.Root` als Ausbruch; darum zuerst der
  echte Pfad `run/mysqld/mysqld.sock`.
- T2: Der Treiber verbindet sich über seinen Connector direkt, ohne `database/sql`: eine Verbindung, kein stilles
  Wiederholen.
- T2: Von Hand geprüft 2026-11-15 mit `wordpress:latest` + `mariadb:11` (Compose auf der Dev-Box, Socket per
  Bind-Mount, `containerRoot` im Wegwerf-Test darauf umgebogen, sonst der echte Weg mit Docker): frische Site
  `events 3, overdue 0, oldest_overdue_s 0`; `'user'@'%'` des Images wird über das Socket angenommen. Gegenprobe
  falsches Passwort/Präfix/Datenbank: nur `error 1045`/`1146`/`1044`, weder Benutzer noch Passwort in der Ausgabe.
  `mysql` nicht real geprüft (Socket-Pfad aus der Image-Doku).
- T2: Zwischen Treiber und Socket liegt `wpDBGuard`: höchstens 2 MiB je Verbindung, und auf die Abfrage nur ein
  Fehler oder ein Ergebnis mit genau einer Spalte. Ein Kindprozess mit Speichergrenze oder ein eigener Client wären
  mehr Code für dieselbe Grenze. Gegenprobe ohne `wpDBGuard`: der Testprozess endet mit
  `fatal error: runtime: out of memory`.
- T2: Ein Container, der zwischen `docker ps` und `docker inspect` verschwindet, lässt die Ansicht weiterlaufen (wie
  `dockerPublications`, `goneSince`). Ein laufender Datenbank-Container geht vor gestoppten mit demselben Namen
  (Prüfer-Nit).
