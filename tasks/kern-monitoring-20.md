<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Katalog-Updates, Grabsteine für Modul-Checks, Fühler-Erweiterungen — Task-Ledger
Status: erledigt · Branch: feature/kern-monitoring-20 · Review: pro Task
Spec: docs/features/kern-monitoring-20.md (Roadmap R-1264, R-1301)
Heavy: linux-full — Alembic-Migration im Monitoring-Dienst, neue Params und Zugänge im Agent (`apps/agent`), Desktop-Inbox; kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Gebaut wird nach dem Merge von kern-monitoring-8 und kern-monitoring-30 (`sensors.py`, `model.py`, `sensor_proto.go`);
vor T1 `origin/main` in den Branch mergen.

### T1 — R-1264: Migration Grabstein-Tabelle und Definitions-Hash  [x]
Komponente: monitoring · Dateien: apps/monitoring/alembic/versions/a7c9e1f3b5d7_module_check_tombstones.py, apps/monitoring/app/models.py, apps/monitoring/tests/test_migrations_smoke.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @19e25bf6c 2026-11-14T11:12:14+01:00
Review: approve (.ah-out/review/kern-monitoring-20/T1.verdict.json)
Änderung: Tabelle `monitor_module_tombstones` (`id`, `server_id` indiziert, `module_id`, `instance_key`,
`check_key`, `created_at`; eindeutig über die vier Schlüssel) und Spalte `monitor_checks.module_check_hash`
(nullable); Downgrade entfernt beide. Modell `MonitorModuleTombstone`. Neue Datei mit SPDX-Header.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_migrations_smoke.py
Doku: → T9

### T2 — R-1264: Grabsteine beim Löschen, Abgleich und Übernehmen  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/module_sync.py, apps/monitoring/app/routers/checks.py, apps/monitoring/app/server_cleanup.py, apps/monitoring/tests/test_module_sync.py, apps/monitoring/tests/test_findings_api.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @1005870d3 2026-11-14T11:29:12+01:00
Review: approve (.ah-out/review/kern-monitoring-20/T2.verdict.json)
Änderung: `delete_check` legt für einen Modul-Check einen Grabstein an (idempotent). `_adopt` und `sync_catalog`
legen keinen Check an, dessen Schlüssel einen Grabstein hat; ein Fund, dem nur so ein Check fehlt, wird nicht
`changed`. `server_cleanup` löscht die Grabsteine des Servers.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py tests/test_findings_api.py
Doku: → T9
Abhängt von: T1

### T3 — R-1264: geänderte Katalog-Definition als Update anbieten  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/module_sync.py, apps/monitoring/app/routers/findings.py, apps/monitoring/tests/test_module_sync.py, apps/monitoring/tests/test_findings_api.py, apps/monitoring/app/schemas.py, apps/monitoring/tests/openapi.snapshot.json
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @c4395ea86 2026-11-14T11:37:25+01:00
Review: approve (.ah-out/review/kern-monitoring-20/T3.verdict.json)
Änderung: `_create` speichert den Hash der Katalog-Definition (`model_dump(mode="json")`, sortiert, SHA-256).
`sync_catalog` öffnet einen Fund `changed`, wenn ein aktiver Check einen anderen Hash hat; ohne Hash (Altzeile)
setzt er den heutigen, ohne Update. Fund `updatableChecks`; `_adopt` schreibt für diese Checks die neue
Konfiguration und den Hash, Name, Intervall und Schalter des Admins bleiben; Adopt-Antwort `updatedChecks`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py tests/test_findings_api.py
Doku: → T9
Abhängt von: T2

### T4 — R-1301: compose-Fund nennt den gebundenen Container  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/discovery.py, apps/monitoring/tests/test_discovery_match.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @7d1e5036b 2026-11-14T11:40:09+01:00
Review: approve (.ah-out/review/kern-monitoring-20/T4.verdict.json)
Änderung: Die Summary eines `compose_project`-Funds trägt `containers` (`{Dienst: Container}`); `_seen_again`
vergleicht die Summary ohne diesen Schlüssel und speichert die neue Summary trotzdem. Test: ein umbenannter
Container lässt einen übernommenen Fund `adopted`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_discovery_match.py
Doku: → T9

### T5 — R-1264, R-1301: Desktop-Inbox zeigt Updates und Container  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/card/FindingsInbox.svelte, apps/desktop/ui/src/components/monitoring/card/FindingsInbox.test.ts, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @496c5d175 2026-11-14T11:49:29+01:00
Review: approve (.ah-out/review/kern-monitoring-20/T5.verdict.json)
Änderung: Ein `changed`-Fund nennt die Zahl der Checks mit neuer Definition; ein compose-Fund den Container je
Dienst. Typen `updatableChecks`, `updatedChecks`, `containers` in `types.ts`, Texte DE+EN in `dictionaries.ts`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/card/FindingsInbox.test.ts
Doku: → T9
Abhängt von: T3, T4

### T6 — R-1264: proto mit implizitem TLS, Redis mit ACL-Nutzer  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_proto.go, apps/agent/internal/probe/sensor_unixsocket.go, apps/agent/internal/probe/sensor_http.go, apps/agent/internal/probe/sensor_proto_test.go, apps/agent/internal/probe/probe.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @a6439605a 2026-11-14T12:07:46+01:00
Review: approve (.ah-out/review/kern-monitoring-20/T6.verdict.json)
Änderung: Param `tls` (bool) bei `proto` für `smtp`, `imap`, `pop3`, `ldap`, `redis`, `banner`: TLS-Handshake vor dem
Protokoll, ohne Zertifikatsprüfung; `tls` und `starttls` zusammen sind `invalid`. Zugang `redis_acl` (Geheimnis
`user:password`, `AUTH <user> <passwort>`), über `proto` und `unixsocket`; kein Fehlertext zitiert Nutzer oder
Geheimnis. Vorher Redis `AUTH` an der Doku prüfen.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T9

### T7 — R-1264: Katalog: tls, redis_acl, dns mit Unterstrich, Socket-Pfad  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/model.py, apps/monitoring/app/check_configs.py, apps/monitoring/tests/test_catalog_sensors.py, apps/monitoring/tests/test_check_configs.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @dd8a84ef8 2026-11-14T12:12:29+01:00
Review: approve (.ah-out/review/kern-monitoring-20/T7.verdict.json)
Änderung: `ProtoParams.tls` (nicht zusammen mit `starttls`); `Credential.use` und `ProbeCredential` nehmen
`redis_acl`; `DnsParams.name` nach dem Muster des Agents (`dnsName`, mit Unterstrich); `UnixSocketParams.path`
höchstens 107 Zeichen. Bestehende Module bleiben in Version und Hash gleich.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_sensors.py tests/test_check_configs.py
Doku: → T9

### T8 — R-1264: credential use none  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/model.py, apps/monitoring/app/check_configs.py, apps/monitoring/app/module_sync.py, apps/monitoring/app/module_plan.py, apps/monitoring/tests/test_catalog.py, apps/monitoring/tests/test_module_sync.py, apps/monitoring/tests/test_agent_plan.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @87063a57a 2026-11-14T12:18:22+01:00
Review: approve (.ah-out/review/kern-monitoring-20/T8.verdict.json)
Änderung: nach Kevins Antwort (Spec, Offene Fragen 1): `credential.optional`; der Plan lässt einen optionalen Zugang weg, solange der Host ihn nicht als hinterlegt meldet.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog.py tests/test_module_sync.py tests/test_agent_plan.py tests/test_check_configs.py tests/test_catalog_sensors.py
Doku: → T9

### T9 — Doku DE+EN und CHANGELOG  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-monitoring-20.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @8a39658b9 2026-11-14T12:23:15+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Katalog-Updates als Angebot, Grabsteine, Container im compose-Fund, implizites TLS, `redis_acl`, dns mit
Unterstrich; `changelog.d/kern-monitoring-20.md` unter `### Added`/`### Changed`, ohne Umlaute. `doc-smoke --env`
lokal fahren.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die genannten Dateien
Task-Review: am Ende
Abhängt von: T3, T4, T5, T6, T7

## Entscheidungen
- `fastcgi status_path` aus R-1264 ist schon gebaut (Agent `sensor_proto.go` `statusPath`, Katalog `ProtoParams`,
  `UnixSocketParams`); keine Task.
- Kevin 2026-11-14: T8 `credential use none` heißt optionaler Zugang: ohne ihn läuft der Check, mit ihm liest er mehr.
- T8: Der Server lässt den optionalen Zugang im Plan weg, solange der Bericht des Hosts die Referenz nicht als hinterlegt meldet (`MonitorDiscovery.credentials`); der Agent bleibt unverändert. `optional` steht im Katalog-Dump nur, wenn gesetzt (Hash der übrigen Module bleibt).
- T3: Ein Update übernimmt die Katalog-Definition samt Regeln; `interval_s`/`timeout_s` der gespeicherten Konfiguration,
  Name, Intervall und Schalter des Admins bleiben. Bindet die neue Definition nicht, bleibt die alte (Grund in
  `skippedChecks`). Zeilen ohne Hash bekommen beim Start den heutigen, für alle Funde, ohne Angebot.
- T9-Doku nennt: Übernehmen eines Updates ersetzt die Regeln (Schwellen) des Admins durch die des Katalogs (security-Nit T3).
- T4: Laufen mehrere Container eines Dienstes (scale), nennt `containers` den ersten nach Namen; die Bindung meldet mehrere ohnehin in `skippedChecks`.
