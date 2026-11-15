<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# UniFi OS Server lokal — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-13 · Review: pro Task
Spec: docs/features/kern-monitoring-13.md (Roadmap R-1244)
Heavy: linux-full — neue Ansicht und HTTP-Client im Agent (`apps/agent`), kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1244: GET-only-Client und Ansicht `unifi_network`  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/app_unifi.go, apps/agent/internal/probe/app_unifi_test.go, apps/agent/internal/probe/sensor_app.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @09be28829 2026-11-15T10:33:36+01:00
Review: approve (.ah-out/review/kern-monitoring-13/T1.verdict.json)
Änderung:
- Neue Dateien mit SPDX-Header.
- Client über `secretGuard`: nur `GET`, Pfade nur aus der Freigabeliste der Spec, `CheckRedirect` endet mit
  Fehler, Antworten gedeckelt. Key per `authorize` (`header:X-API-KEY`), nie in Fehlern.
- Ansicht `unifi_network` an der Unit (Port aus `port_hint`, Standard 11443) mit dem Ablauf der Spec und den neun
  Zahlenfeldern.
- Tests mit `httptest`-TLS-Server:
  - die Werte
  - Seiten bis `totalCount`
  - Ursache vs. dahinter
  - 401/403 → `ErrDenied`
  - ein Redirect wird nicht verfolgt
  - kein `POST`, `DELETE` und kein Pfad außerhalb der Liste geht hinaus (Client direkt)
  - der Key steht in keinem Fehler
  - höchstens 20 Anfragen
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T4

### T2 — R-1244: Modul `unifi-os-server`  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/unifi_os_server.py, apps/monitoring/tests/test_catalog_unifi.py, apps/monitoring/tests/test_catalog_sensors.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @ba2c0e540 2026-11-15T10:41:29+01:00
Review: approve (.ah-out/review/kern-monitoring-13/T2.verdict.json)
Änderung:
- Ansicht `unifi_network` mit Feldern und Ziel Unit in `sensors.py`.
- Neues Modul (SPDX-Header), erkannt an der Unit `uosserver`, Instanz `unit`. Checks:
  - `service` (Unit)
  - `tls` am Web-Port
  - `network`: Ansicht, alle 300 s, Credential `header:X-API-KEY`. `gateways_offline` > 0 ist `critical`,
    `offline_root` > 0 ist `warning`.
- Karte: Dienst, offline, Updates.
- Docstring mit den Quellen und dem, was nicht abgedeckt ist.
- Test: Erkennung, Regeln, Credential, Karte.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_unifi.py tests/test_catalog_sensors.py
Doku: → T4
Abhängt von: T1

### T3 — R-1244: Lab-Test auf einer frisch installierten UOS-VM  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/app_unifi.go, apps/agent/internal/probe/app_unifi_test.go
Änderung:
- Eine Box der Lane (Profil `linux-server`) bekommt UOS 5.1.42 linux-x64. Der Installer kommt von
  `fw-update.ui.com`, der sha256 wird geprüft. Die Box wird nicht aus einer UOS-VM geklont (Kevin 2026-11-15).
- Den HTTPS-Port, den Header-Namen, die Antwort von `/v1/info` und `/v1/sites` und die Rechte eines
  View-Only-Keys mit einem Schreibversuch nur auf dieser Wegwerf-Box feststellen.
- Abweichungen in T1-Code und -Tests nachziehen. Der Docstring nennt die geprüfte Version.
- Keine Box-IP und kein Key in Dateien.
- Verlangt das Setup ein UI-Konto, wird die Task `[?]` mit Frage an Kevin.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T4
Abhängt von: T1

### T4 — Doku DE+EN und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-monitoring-13.md
Änderung:
- Admin-Doku: Modul `unifi-os-server` (Key anlegen, View-Only-Key bevorzugen, hinterlegen per Desktop, was
  gesendet wird, nicht abgedeckt).
- Entwickler-Doku: Ansicht und Client-Regeln.
- Changelog-Fragment.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: diese Task
Task-Review: am Ende
Abhängt von: T2, T3

## Entscheidungen
- Kevin 2026-11-15: hier nur Zähler, die Geräteliste kommt mit dem Reiter „Geräte“ in R-1518. Der View-Only-Test
  läuft auf einer frisch installierten UOS-VM im Pool.
- Gebaut wird nach dem Merge von feature/kern-monitoring-33: Beide ändern `sensor_app.go` und `sensors.py`.
