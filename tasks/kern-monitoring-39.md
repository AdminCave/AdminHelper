# HAProxy fehlender Reload, Platz in moodledata — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-39 · Review: am Ende
Spec: docs/features/kern-monitoring-39.md (Roadmap R-1502, R-1504)
Heavy: linux-full — neue Socket-Frage und App-Ansicht in apps/agent (Sammellauf)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1502: Agent — haproxy_certs vergleicht Datei und geladenes Zertifikat  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/app_haproxy.go, apps/agent/internal/probe/app_haproxy_certs_linux_test.go, docs/developer/agent.html, docs/en/developer/agent.html, tasks/kern-monitoring-39.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @fe66680dd 2026-11-17T07:55:12+01:00
Review: am Ende (Branch-Review)
Änderung: `haproxyCerts` fragt den Stats-Socket mit `show ssl cert` (Liste) und `show ssl cert <file>` (`notAfter`).
Gefragt werden nur Dateien aus `bind … crt`, die in der Liste stehen; `*`-Einträge werden übersprungen.
`reload_missing` zählt die Dateien, deren erstes Zertifikat länger läuft als das geladene. Kein Socket, eine
Ablehnung oder eine unbekannte Antwort: Das Feld fehlt. Tests mit Fake-Socket: Reload fehlt, gleich, nicht gelistet,
Ablehnung.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: docs/developer/agent.html DE+EN

### T2 — R-1504: Agent — Ansicht moodle_data  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/app_moodle.go, apps/agent/internal/probe/app_moodle_unix.go, apps/agent/internal/probe/app_moodle_windows.go, apps/agent/internal/probe/app_moodle_linux_test.go, apps/agent/internal/probe/sensor_app.go, docs/developer/agent.html, docs/en/developer/agent.html, tasks/kern-monitoring-39.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @42fcf8ffc 2026-11-17T07:59:38+01:00
Review: am Ende (Branch-Review)
Änderung: Neue vhost-Ansicht `moodle_data`. Sie liest das dataroot aus `config.php` (dieselbe Regel wie
`moodle_checks`, ohne Code auszuführen) und fragt `statfs` wie der Sensor `fs` (`used_pct`, `free_bytes`,
`inodes_used_pct`). Unter Windows `unsupported`. Tests: Werte, kein Moodle, kein dataroot.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: docs/developer/agent.html DE+EN

### T3 — R-1502, R-1504: Monitoring — Katalog und Doku  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/haproxy.py, apps/monitoring/app/catalog/modules/moodle_native.py, apps/monitoring/tests/test_catalog_web.py, apps/monitoring/tests/test_catalog_sensors.py, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-39.md, tasks/kern-monitoring-39.md, apps/monitoring/app/catalog/sensors.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @cce3c0b20 2026-11-17T08:05:35+01:00
Review: am Ende (Branch-Review)
Änderung: `haproxy`: Feld `reload_missing`, Regel `> 0` warning, Karte, Version +1. `moodle_native` v2: Check `data`
(`moodle_data`, 900 s; ab 80 % warning, ab 90 % critical, Inodes ab 90 % warning), Karte. Tests im Katalog. Die
Modultabelle DE und EN, CHANGELOG.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_web.py tests/test_catalog_sensors.py tests/test_catalog.py
Doku: docs/admin/monitoring.html DE+EN · changelog.d/kern-monitoring-39.md
Abhängt von: T1, T2

### T4 — R-1502: Abschlussprüfung — Semikolon im Dateinamen, CHANGELOG umlautfrei  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/app_haproxy.go, apps/agent/internal/probe/app_haproxy_certs_linux_test.go, changelog.d/kern-monitoring-39.md, tasks/kern-monitoring-39.md
Änderung: `haproxyLoaded` fragt keinen Namen mit `;` (die CLI trennt dort Befehle); Test dazu. Das CHANGELOG-Fragment
ohne Umlaute (changelog.d/README.md). Funde der Abschlussprüfung.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: keine (Verhalten unverändert dokumentiert)

## Entscheidungen
- T1: `*`-Einträge der Liste brauchen keinen eigenen Filter: sie stehen unter `# transaction` als `*<pfad>` und treffen keine Datei einer bind-Zeile (Gegenprobe ohne Filter grün, deshalb weggelassen). notAfter wird in UTC geparst (OpenSSL druckt GMT). Namen mit Leerzeichen oder Backslash werden nicht gefragt (die CLI würde sie teilen oder entschärfen).
- T2: Die Ansicht heißt im Code `moodleDataUsage` (der Test-Helfer `moodleData` war belegt); `moodleDataroot`, `maxMoodleConfig` und das Lesen des dataroot (`moodleDatarootOf`) liegen jetzt in `app_moodle.go`, damit die Ansicht ohne Build-Tag auskommt; Windows meldet über `dirStatfs` `unsupported`, `app_moodle_windows.go` bleibt unverändert.
- T3: Die HAProxy-Karte nimmt höchstens sechs Einträge; „Servers in maintenance“ weicht „Certificates not reloaded“ (servers_maint bleibt Feld des Checks, unbewertet). Die Regel reload_missing trägt `if_absent: ok`: ohne Socket der Stufe operator fehlt das Feld, und der Check bewertet die Dateien allein.
