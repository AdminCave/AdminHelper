<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Fühler http, tls und dns für die Katalog-Module — Task-Ledger
Status: geplant · Branch: feature/kern-monitoring-30 · Review: pro Task
Spec: docs/features/kern-monitoring-30.md (Roadmap R-1392, R-1394, R-1395, R-1433)
Heavy: linux-full — neue Parameter, Felder und ein Ziel für dns im Agent (`apps/agent`), kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Gebaut wird erst nach dem Merge von kern-monitoring-8 (dieselben Agent- und Katalog-Dateien); vor T1 `origin/main`
in den Branch mergen. Ein älterer Agent meldet die neuen Checks als `invalid`, der Check steht dann auf `unknown`.

### T1 — R-1392: http vergleicht eine kurze Klartext-Antwort  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_http.go, apps/agent/internal/probe/sensor_net_test.go
Änderung: Parameter `expect` (1–64 Zeichen, ohne Leer- und Steuerzeichen, nur mit `GET`) und Feld `body_match`
(bool). Der Agent liest höchstens 4 KiB, schneidet Leerraum am Rand ab und vergleicht genau; der Body verlässt den
Agent nie. `body_match` ohne `expect` ist `invalid`.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T8

### T2 — R-1395: http erkennt Klartext oder TLS am Port (Schema auto)  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_http.go, apps/agent/internal/probe/sensor_net_test.go, apps/agent/internal/probe/probe.go
Änderung: Schema `auto`: eigener TLS-Handshake über den Wächter; ein Nicht-TLS-Datensatz als Antwort ⇒ Klartext,
sonst HTTPS wie bisher ohne Zertifikatsprüfung. Feld `tls` (bool) meldet den Weg. Tests mit Klartext- und
TLS-Server auf Loopback.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T8
Abhängt von: T1

### T3 — R-1394: tls meldet Anteil der Laufzeit und Stunden bis Ablauf  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_tls.go, apps/agent/internal/probe/sensor_net_test.go
Änderung: `certValues` liefert zusätzlich `lifetime_pct` (Rest geteilt durch `NotAfter − NotBefore`, Prozent mit
einer Nachkommastelle, nie unter 0) und `hours_left` (ganze Stunden, abgerundet). Tests mit festem Zeitpunkt.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T8

### T4 — R-1433: dns fragt mit Ziel den Dienst direkt  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_dns.go, apps/agent/internal/probe/sensor_dns_test.go, apps/agent/internal/probe/sensor_net_test.go
Änderung: Ohne Ziel wie heute. Mit Ziel eine Anfrage nach RFC 1035 über TCP mit Längenpräfix (RFC 7766) durch den
Wächter an den Port; ohne EDNS, RD gesetzt; Felder `resolved`, `answers`, `duration_ms`, neu `rcode`
(`noerror|nxdomain|servfail|refused|other`). Neue Testdatei `sensor_dns_test.go` (SPDX-Header) mit einem
DNS-Stub auf Loopback, Antwortlänge begrenzt.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T8

### T5 — Katalog: neue Parameter, Felder, Schema auto, dns mit Ziel  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/model.py, apps/monitoring/tests/test_catalog_sensors.py, apps/monitoring/tests/test_check_configs.py
Änderung: `HttpParams.expect`, Felder `body_match`/`tls` (http), `lifetime_pct`/`hours_left` (tls), `rcode` (dns);
`auto` in `Target.scheme` und `Alternative.scheme`; `dns` nimmt ein optionales Ziel. Bestehende Module bleiben in
Version und Hash gleich.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_sensors.py tests/test_check_configs.py
Doku: → T8

### T6 — R-1392, R-1395: Module onlyoffice, keycloak, vaultwarden, mattermost  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/onlyoffice.py, apps/monitoring/app/catalog/modules/keycloak.py, apps/monitoring/app/catalog/modules/vaultwarden.py, apps/monitoring/app/catalog/modules/mattermost.py, apps/monitoring/tests/test_catalog_onlyoffice.py, apps/monitoring/tests/test_catalog_keycloak.py, apps/monitoring/tests/test_catalog_vaultwarden.py, apps/monitoring/tests/test_catalog_mattermost.py
Änderung: onlyoffice `/healthcheck` mit `expect: "true"`, `body_match` false ⇒ critical; keycloak, vaultwarden und
mattermost mit Schema `auto`, Docstring ohne „nicht abgedeckt: TLS“. Version je Modul +1.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_onlyoffice.py tests/test_catalog_keycloak.py tests/test_catalog_vaultwarden.py tests/test_catalog_mattermost.py
Doku: → T8
Abhängt von: T5

### T7 — R-1394, R-1433: openldap relativ zur Laufzeit, dns-Checks für Resolver  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/openldap.py, apps/monitoring/app/catalog/modules/pihole.py, apps/monitoring/app/catalog/modules/adguard.py, apps/monitoring/app/catalog/modules/unbound.py, apps/monitoring/app/catalog/modules/bind.py, apps/monitoring/tests/test_catalog_openldap.py, apps/monitoring/tests/test_catalog_dns.py
Änderung: openldap: `lifetime_pct lt 25` warning, `lt 10` critical, `hours_left lt 12` critical statt 22/9 Tage.
pihole, adguard, unbound, bind: dns-Check `localhost` A an Port 53 des Dienstes; critical bei `servfail` oder
Fehler der Anfrage, sonst ok. Vorher an der Doku der vier Resolver prüfen, wie sie `localhost` beantworten;
Unbelegtes im Docstring als „nicht verifiziert“. Version je Modul +1.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_openldap.py tests/test_catalog_dns.py
Doku: → T8
Abhängt von: T5

### T8 — Doku DE+EN und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-monitoring-30.md
Änderung: Modul-Tabelle (neun Module), Probe-Checks (Anteil der Laufzeit), Katalog (`HttpParams.expect`, Schema
`auto`, dns mit Ziel), Sensorliste; `changelog.d/kern-monitoring-30.md` unter `### Added`, ohne Umlaute.
`doc-smoke --env` lokal fahren.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die genannten Dateien
Task-Review: am Ende
Abhängt von: T6, T7

## Entscheidungen
- Kevin 2026-11-14: Offene Frage 1 wie empfohlen: dns-Check mit `localhost` A (nur lokal).
