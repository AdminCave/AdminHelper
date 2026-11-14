<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Fühler http, tls und dns für die Katalog-Module — Task-Ledger
Status: bereit · Branch: feature/kern-monitoring-30 · Review: pro Task
Spec: docs/features/kern-monitoring-30.md (Roadmap R-1392, R-1394, R-1395, R-1433)
Heavy: linux-full — neue Parameter, Felder und ein Ziel für dns im Agent (`apps/agent`), kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Gebaut wird erst nach dem Merge von kern-monitoring-8 (dieselben Agent- und Katalog-Dateien); vor T1 `origin/main`
in den Branch mergen. Ein älterer Agent meldet die neuen Checks als `invalid`, der Check steht dann auf `unknown`.

### T1 — R-1392: http vergleicht eine kurze Klartext-Antwort  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_http.go, apps/agent/internal/probe/sensor_net_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @f54a29ead 2026-11-14T09:04:02+01:00
Review: approve (.ah-out/review/kern-monitoring-30/T1.verdict.json)
Änderung: Parameter `expect` (1–64 Zeichen, ohne Leer- und Steuerzeichen, nur mit `GET`) und Feld `body_match`
(bool). Der Agent liest höchstens 4 KiB, schneidet Leerraum am Rand ab und vergleicht genau; der Body verlässt den
Agent nie. `body_match` ohne `expect` ist `invalid`.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T8

### T2 — R-1395: http erkennt Klartext oder TLS am Port (Schema auto)  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_http.go, apps/agent/internal/probe/sensor_net_test.go, apps/agent/internal/probe/probe.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @1a06f239d 2026-11-14T09:15:13+01:00
Review: approve (.ah-out/review/kern-monitoring-30/T2.verdict.json)
Änderung: Schema `auto`: eigener TLS-Handshake über den Wächter; ein Nicht-TLS-Datensatz als Antwort ⇒ Klartext,
sonst HTTPS wie bisher ohne Zertifikatsprüfung. Feld `tls` (bool) meldet den Weg. Tests mit Klartext- und
TLS-Server auf Loopback.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T8
Abhängt von: T1

### T3 — R-1394: tls meldet Anteil der Laufzeit und Stunden bis Ablauf  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_tls.go, apps/agent/internal/probe/sensor_net_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @5425607b3 2026-11-14T09:22:18+01:00
Review: approve (.ah-out/review/kern-monitoring-30/T3.verdict.json)
Änderung: `certValues` liefert zusätzlich `lifetime_pct` (Rest geteilt durch `NotAfter − NotBefore`, Prozent mit
einer Nachkommastelle, nie unter 0) und `hours_left` (ganze Stunden, abgerundet). Tests mit festem Zeitpunkt.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T8

### T4 — R-1433: dns fragt mit Ziel den Dienst direkt  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_dns.go, apps/agent/internal/probe/sensor_dns_test.go, apps/agent/internal/probe/sensor_net_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @13f191f09 2026-11-14T09:32:55+01:00
Review: approve (.ah-out/review/kern-monitoring-30/T4.verdict.json)
Änderung: Ohne Ziel wie heute. Mit Ziel eine Anfrage nach RFC 1035 über TCP mit Längenpräfix (RFC 7766) durch den
Wächter an den Port; ohne EDNS, RD gesetzt; Felder `resolved`, `answers`, `duration_ms`, neu `rcode`
(`noerror|nxdomain|servfail|refused|other`). Neue Testdatei `sensor_dns_test.go` (SPDX-Header) mit einem
DNS-Stub auf Loopback, Antwortlänge begrenzt.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T8

### T5 — Katalog: neue Parameter, Felder, Schema auto, dns mit Ziel  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/model.py, apps/monitoring/tests/test_catalog_sensors.py, apps/monitoring/tests/test_check_configs.py, apps/monitoring/tests/test_catalog.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @d03e34231 2026-11-14T09:39:22+01:00
Review: approve (.ah-out/review/kern-monitoring-30/T5.verdict.json)
Änderung: `HttpParams.expect`, Felder `body_match`/`tls` (http), `lifetime_pct`/`hours_left` (tls), `rcode` (dns);
`auto` in `Target.scheme` und `Alternative.scheme`; `dns` nimmt ein optionales Ziel. Bestehende Module bleiben in
Version und Hash gleich.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_sensors.py tests/test_check_configs.py tests/test_catalog.py
Doku: → T8

### T6 — R-1392, R-1395: Module onlyoffice, keycloak, vaultwarden, mattermost  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/onlyoffice.py, apps/monitoring/app/catalog/modules/keycloak.py, apps/monitoring/app/catalog/modules/vaultwarden.py, apps/monitoring/app/catalog/modules/mattermost.py, apps/monitoring/tests/test_catalog_onlyoffice.py, apps/monitoring/tests/test_catalog_keycloak.py, apps/monitoring/tests/test_catalog_vaultwarden.py, apps/monitoring/tests/test_catalog_mattermost.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @638f54010 2026-11-14T09:43:54+01:00
Review: approve (.ah-out/review/kern-monitoring-30/T6.verdict.json)
Änderung: onlyoffice `/healthcheck` mit `expect: "true"`, `body_match` false ⇒ critical; keycloak, vaultwarden und
mattermost mit Schema `auto`, Docstring ohne „nicht abgedeckt: TLS“. Version je Modul +1.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_onlyoffice.py tests/test_catalog_keycloak.py tests/test_catalog_vaultwarden.py tests/test_catalog_mattermost.py
Doku: → T8
Abhängt von: T5

### T7 — R-1394, R-1433: openldap relativ zur Laufzeit, dns-Checks für Resolver  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/openldap.py, apps/monitoring/app/catalog/modules/pihole.py, apps/monitoring/app/catalog/modules/adguard.py, apps/monitoring/app/catalog/modules/unbound.py, apps/monitoring/app/catalog/modules/bind.py, apps/monitoring/tests/test_catalog_openldap.py, apps/monitoring/tests/test_catalog_dns.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @0582b5761 2026-11-14T09:54:44+01:00
Review: approve (.ah-out/review/kern-monitoring-30/T7.verdict.json)
Änderung: openldap: `lifetime_pct lt 25` warning, `lt 10` critical, `hours_left lt 12` critical statt 22/9 Tage.
pihole, adguard, unbound, bind: dns-Check `localhost` A an Port 53 des Dienstes; critical bei `servfail` oder
Fehler der Anfrage, sonst ok. Vorher an der Doku der vier Resolver prüfen, wie sie `localhost` beantworten;
Unbelegtes im Docstring als „nicht verifiziert“. Version je Modul +1.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_openldap.py tests/test_catalog_dns.py
Doku: → T8
Abhängt von: T5

### T8 — Doku DE+EN und CHANGELOG  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-monitoring-30.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @32e7ff437 2026-11-14T09:59:29+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Modul-Tabelle (neun Module), Probe-Checks (Anteil der Laufzeit), Katalog (`HttpParams.expect`, Schema
`auto`, dns mit Ziel), Sensorliste; `changelog.d/kern-monitoring-30.md` unter `### Added`, ohne Umlaute.
`doc-smoke --env` lokal fahren.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die genannten Dateien
Task-Review: am Ende
Abhängt von: T6, T7

### T9 — Doku: aelterer Agent und HTTP-Check mit Schema auto  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-30.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @504a0372c 2026-11-14T10:08:30+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Abschlussprüfung 2026-11-14: ein Agent älter als der Monitoring-Dienst lässt die geänderten Checks (keycloak, vaultwarden, mattermost wegen `auto`, onlyoffice wegen `expect`, dns mit Ziel) `unknown` („invalid“): Punkt nach dem Muster „Neuer Parameter `host`“ DE+EN und ein Satz im CHANGELOG-Fragment; der Punkt „HTTP-Check“ nennt das Schema `auto` statt „nur HTTPS ist critical“ ohne Ausnahme.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die genannten Dateien
Task-Review: am Ende

### T10 — Test speaksTLS: der Klartext-Server liest das ganze ClientHello  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_net_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @0aeb110b3 2026-11-14T10:43:48+01:00
Review: approve (.ah-out/review/kern-monitoring-30/T10.verdict.json)
Änderung: PR-CI 2026-11-14, Job „Go Agent (test, Windows)“: `TestSpeaksTLSTellsAServerOfPlainTextByItsAnswerOrSilence` „an answer of HTTP = true“. Der Test-Server las nur 16 Bytes des ClientHello und schloss mit ungelesenen Daten; Windows sendet dann ein RST und verwirft die schon gesendete HTTP-Antwort beim Client. Der Server liest den ganzen TLS-Datensatz (Kopf und Länge), wie es ein echter HTTP-Server mit seiner Anfrage tut, bevor er antwortet.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: keine (nur Test)

## Entscheidungen
- Kevin 2026-11-14: Offene Frage 1 wie empfohlen: dns-Check mit `localhost` A (nur lokal).
- T2 `auto`: Schweigen bis `answerWait` (2 s) zählt als Klartext, nicht nur ein Nicht-TLS-Datensatz: ein Go-HTTP-Server (etwa Mattermost) wartet auf ein `\n` im ClientHello und antwortet nie. Ein Abbruch oder Alert zählt als TLS, ein abgelaufener Probe-Kontext ist ein Fehler.
- T4 dns mit Ziel: `answers` ist ANCOUNT aus dem Kopf (zählt etwa eine CNAME-Kette mit), der Rest der Antwort wird nicht gelesen; ohne Ziel zählt der Resolver weiter nur die Endergebnisse. Ein IPv6-PTR-Name steht wie bisher als ip6.arpa-Name im Parameter. Der alte Fall "a target" in `TestDNSSensorTakesItsParams` prüft jetzt ein Ziel ohne Port (gewollte Verhaltensänderung).
- T5: `dns` nimmt ein optionales Ziel (`OPTIONAL_TARGET_SENSORS`); `test_catalog.py::test_target_must_fit_the_sensor` prüfte „takes no target“ am dns-Fühler und nimmt dafür jetzt `file_age` (gewollte Verhaltensänderung, gleichwertiger Ersatz). `auto` nur für den Fühler `http`: die App-Ansichten (`app_db.go`) und `proto`/`tls` kennen den Wert nicht. `body_match` nur mit `expect`, `expect` nur mit `GET`, wie der Agent.
- T7 Resolver-Doku (2026-11-14): nur Unbound belegt `localhost` (unbound.conf(5): Standardzone `localhost.` redirect, 127.0.0.1); dnsmasq lädt /etc/hosts (dnsmasq(8)), ob FTL und AdGuard Home `localhost` daraus beantworten, ist nicht verifiziert; BIND: keine Stelle im ARM. Deshalb ist nur SERVFAIL oder ein Fehler der Anfrage critical, NXDOMAIN und REFUSED zählen als Antwort; die Docstrings sagen „nicht verifiziert“. Die Karte von Pi-hole und AdGuard zeigt statt „DNS port“ die DNS-Antwort (höchstens sechs Kartenfelder; die Antwort setzt das Lauschen voraus). Versionskonflikt mit feature/kern-monitoring-31 (unbound, bind je 1→2): wer zuerst merged, der andere zieht auf 3.
