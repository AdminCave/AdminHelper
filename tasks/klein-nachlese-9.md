<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-9 — Task-Ledger
Status: geplant · Branch: feature/klein-nachlese-9 · Review: am Ende
Spec: docs/features/klein-nachlese-9.md (Roadmap R-1457, R-1459, R-1471, R-1472, R-1482, R-1486, R-1496, R-1498)
Heavy: none — nur Monitoring-Katalog (Service) und Doku
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1471/R-1472, R-1482, R-1486, R-1498, R-1457 (Docstring): Socket-Pfad in Bytes, Docstrings, postfix-Tests  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/postfix.py, apps/monitoring/app/catalog/modules/samba_member.py, apps/monitoring/app/catalog/modules/windows_host.py, apps/monitoring/app/catalog/modules/dnsmasq.py, apps/monitoring/tests/test_catalog_sensors.py, apps/monitoring/tests/test_catalog_mail.py
Beweis: reviewer kern-monitoring-20 T7 2026-11-14 (R-1471, R-1472); reviewer kern-monitoring-11 T5/T8 2026-11-14; reviewer kern-monitoring-14 branch 2026-11-14
Änderung: `UnixSocketParams.path` prüft 107 Bytes (`field_validator`) statt 107 Zeichen, Test mit Mehrbyte-Pfad; Docstrings von `postfix` (Zeile umbrochen), `samba_member` (älteres Samba), `windows_host` („keine eigene Online-Suche“), `dnsmasq` (`--test` liest `/etc/dnsmasq.d` unter Debian nicht); Tests: smtp-Probe mit `status: error` ist critical, das Greeting-Ziel ist Loopback Port 25
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_mail.py tests/test_catalog_sensors.py
Doku: → T2

### T2 — R-1457, R-1459, R-1496: Doku DE+EN, Spec kern-monitoring-11, Changelog  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, docs/features/kern-monitoring-11.md, changelog.d/kern-monitoring-30.md, changelog.d/klein-nachlese-9.md
Task-Review: am Ende
Beweis: review kern-monitoring-31 / -30 / reviewer kern-monitoring-11 2026-11-14
Änderung: dnsmasq-Zeile (Konfigurationstest liest `/etc/dnsmasq.d` unter Debian nicht); Befehls-Freigabeliste im Agent-Handbuch nennt die Konfigurationstests; Wortlaut OpenLDAP-Zertifikats-Check bei älterem Agent (`unknown`, nicht `invalid`) in Doku und Fragment; Spec-Tabelle von `kern-monitoring-11` auf die Entscheidungen; Fragment zum Socket-Pfad in Bytes
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/klein-nachlese-9.md
Abhängt von: T1
