<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-monitoring-module — Task-Ledger
Status: aktiv · Branch: feature/arch-monitoring-module · Review: pro Task
Spec: docs/features/arch-monitoring-module.md (Roadmap R-1223)
Heavy: linux-full — `apps/agent` (neuer Plan-Abruf, Report v4) und eine neue Agent-Route im Server-Proxy; der Sammellauf fährt agent-monitoring und den Stack
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@726c51d13`. R-1224 fährt im Folgezug `arch-monitoring-module-2` (15-Task-Grenze). Risikopfade
(`scripts/dev/review-risk.txt`): T2 (`alembic/versions/*`), T5 (`routers/agent.py`, `schemas.py`), T6 (`schemas.py`),
T3 (`types.ts`), T7 (`monitoring_proxy/*`): `security` je Task. Die Agent-Tasks T8–T14 stehen nicht auf der Liste,
tragen aber Ziel-Wächter, Zugangsdaten und Fremdprotokolle: `security` auch dort (die Liste zu erweitern ist ein
Harness-Pfad und wird eine zurückgestellte Roadmap-Zeile). Neue Quelldateien bekommen den SPDX-Header (`reuse
annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later <datei>`).

### T1 — Monitoring: Katalog-Modell, Lader und Modul `port` (R-1223)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/__init__.py, apps/monitoring/app/catalog/model.py, apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/loader.py, apps/monitoring/app/catalog/modules/__init__.py, apps/monitoring/app/catalog/modules/port.py, apps/monitoring/tests/test_catalog.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @5c1b3faae 2026-11-09T16:50:35+01:00
Review: approve (.ah-out/review/arch-monitoring-module/T1.verdict.json)
Änderung: Pydantic-Modelle für Modul, Erkennung, Instanz-Art, Check (Fühler, Ziel, Parameter, Takt aus {300, 900, 3600, 86400}, `test_object` ⇒ Takt ≥ 900, höchstens 32 Felder, Regeln mit `eq ne lt le gt ge in max_age delta_gt` und Stufe) und Karte; ein Parameter-Modell je Fühler in `sensors.py` (Plan und Katalog teilen es). Der Lader liest alle `MODULE`-Dicts aus `catalog/modules/`, prüft sie und bildet `catalog_version` (SHA-256 über die kanonische JSON-Form). Mitgeliefert nur das generische Modul `port`. Tests mit Fixture-Modulen: gültig, falscher Takt, Testobjekt unter 15 min, unbekannter Fühler, Parameter fremder Fühler, doppelte Keys, Version stabil und ändernd.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog.py
Doku: → T15

### T2 — Monitoring: Tabellen und Migration für Erkennung, Funde und Modul-Checks (R-1223)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/models.py, apps/monitoring/alembic/versions/b8d0f2a4c6e8_module_discovery.py, apps/monitoring/app/server_cleanup.py, apps/monitoring/tests/test_module_tables.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @92247c417 2026-11-09T16:54:54+01:00
Review: approve (.ah-out/review/arch-monitoring-module/T2.verdict.json)
Änderung: Modelle `MonitorDiscovery` und `MonitorFinding`, an `MonitorCheck` die Spalten `module_id` (Index), `module_instance`, `module_check_key`, `silent` (Standard `false`, `server_default`), Tabellen und Eindeutigkeit wie in der Spec; Alembic-Revision auf Kopf `3c66308d11a7` mit Downgrade. `cleanup_server` löscht Erkennung und Funde mit. Test: Upgrade/Downgrade/Upgrade, Altzeilen in `monitor_checks` bekommen `silent = false`, Eindeutigkeit der Funde, Aufräumen beim Server-Löschen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_tables.py tests/test_migrations_smoke.py tests/test_alembic_builtin.py tests/test_models_timestamps.py
Doku: → T15

### T3 — Monitoring: Check-Typ `probe` mit generischer Bewertung (R-1223)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/check_types.py, apps/monitoring/app/check_configs.py, apps/monitoring/app/checkers/probe.py, apps/monitoring/app/checkers/__init__.py, apps/monitoring/tests/test_probe_checker.py, apps/monitoring/tests/test_check_configs.py, apps/desktop/ui/src/lib/models/monitoring.ts, apps/desktop/ui/src/lib/api/types.ts, apps/monitoring/app/routers/checks.py, apps/monitoring/app/routers/agent.py
Evidenz: run.sh[quick] monitoring desktop-ui: 5 passed, 0 failed, 13 skipped @2fffecea3 2026-11-09T17:30:27+01:00
Review: approve (.ah-out/review/arch-monitoring-module/T3.verdict.json)
Änderung: Neuer push-ausgewerteter Check-Typ `probe` (Config: Fühler, Ziel, Parameter, Felder, Regeln, Takt, Zugang, Testobjekt; Parameter über das Fühler-Modell aus T1). Der Checker liest `report["probes"][<check-id>]`: Status des Agents (`denied`, `not_allowed`, `unsupported`, `ambiguous_target`, `invalid`, `no_credential` → unknown bzw. warning mit verständlicher Meldung), Frische (`ts` älter als zwei Takte plus Lauf → unknown), dann die Regeln (schlimmste Stufe gewinnt; `delta_gt` gegen die Vorgänger-Details). Registriert in `CHECK_TYPES`, `_REGISTRY`, `CONFIG_MODELS` und `CHECK_TYPE_METRICS`; die Desktop-Liste `PUSH_ONLY_CHECK_TYPES` und die Union `MonitorCheckType` bekommen `probe` (`test_push_only_ui_sync.py`, `test_check_type_parity.py`). Acht Dateien über zwei Komponenten: die Paritätstests verlangen die Desktop-Listen im selben Commit.
Verify: bash scripts/dev/verify.sh monitoring desktop-ui --strict
Doku: → T15
Abhängt von: T1

### T4 — Monitoring: Abgleich Inventar ↔ Katalog und Funde (R-1223)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/discovery.py, apps/monitoring/tests/test_discovery_match.py
Änderung: `discovery.py` (SPDX): Inventar speichern (Obergrenzen der Spec, Felder außerhalb des Vertrags verworfen), nächsten Scan planen (erster Scan sofort, dann 24–48 h Zufallsversatz; `scan_requested_at` erzwingt), Abgleich je Modul (Image-Präfix, Unit, Prozess, Marker, Port-Hinweis) zu Instanzen mit stabilem `instance_key`, Funde `new`/`changed`/`gone` als Upsert (ignorierte bleiben ignoriert, bis sich die Zusammenfassung ändert; verschwundene Instanzen erst nach zwei Scans ohne Treffer, damit ein Teil-Scan (`partial`) nichts verschwinden lässt). Unbekannte lauschende Nicht-Loopback-Ports mit erkanntem Protokoll ergeben Funde des Moduls `port`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_discovery_match.py
Doku: → T15
Abhängt von: T1, T2

### T5 — Monitoring: Plan-Route und Report-Blöcke v4 (R-1223)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/agent.py, apps/monitoring/app/module_plan.py, apps/monitoring/app/schemas.py, apps/monitoring/tests/test_agent_plan.py, apps/monitoring/tests/test_agent_report_v4.py, apps/monitoring/tests/openapi.snapshot.json
Änderung: `GET /agent/{server_id}/plan` (`require_agent` wie `/report`): Plan aus den aktiven `probe`-Checks des Servers, Marker-Suchliste des Katalogs und Scan-Flag (`module_plan.py`, SPDX). `POST /report` wertet die neuen Blöcke je Block isoliert aus: `discovery` → T4, `credentials` → `monitor_discovery.credentials`, `self.collectors` → Metriken `monitor_agent_collector_*`; ein gebremster Collector (`throttled`) setzt die Auswertung seiner Push-Checks für diesen Report aus (Zustand bleibt). Antwortform von `/report` unverändert. Tests: Plan nur mit eigenem Agent-Key, leerer Plan ohne Checks, Scan-Flag, kaputter Block verwirft den Report nicht, Throttle-Skip, alter Report v3 unverändert; OpenAPI-Snapshot.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_plan.py tests/test_agent_report_v4.py tests/test_agent_report.py tests/test_require_agent.py tests/test_openapi_snapshot.py
Doku: → T15
Abhängt von: T3, T4

### T6 — Monitoring: Funde-, Katalog- und Erkennungs-API, Übernehmen, stille Checks (R-1223)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/findings.py, apps/monitoring/app/routers/__init__.py, apps/monitoring/app/module_sync.py, apps/monitoring/app/alerter.py, apps/monitoring/app/routers/checks.py, apps/monitoring/app/schemas.py, apps/monitoring/app/main.py, apps/monitoring/tests/test_findings_api.py, apps/monitoring/tests/test_module_sync.py, apps/monitoring/tests/openapi.snapshot.json
Änderung: Admin-Routen aus der Spec (`/catalog`, `/discovery/{server_id}`, `/discovery/{server_id}/scan`, `/findings` …) in `routers/findings.py` (SPDX). `module_sync.py` (SPDX): Übernehmen legt die Checks der Instanz an (aktiv, nicht still) oder schaltet sie scharf; „verschwunden“ übernehmen schaltet sie ab, gelöscht wird nie; beim Start gleicht ein geänderter `catalog_version` übernommene Instanzen ab (neue Checks still plus Fund `changed`, entfallene bleiben und erscheinen im Fund). `muted_reason` (`alerter.py:353`) liefert für stille Checks einen Grund, damit das Nachholen nach dem Übernehmen greift. Check-Antworten tragen `module_id`, `module_instance`, `silent`. Zehn Dateien: Übernehmen, Stille und ihre Routen sind ein Vertrag und werden zusammen getestet.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_findings_api.py tests/test_module_sync.py tests/test_alerter.py tests/test_checks_crud.py tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_module_boundaries.py
Doku: → T15
Abhängt von: T4, T5

### T7 — Server: Plan-Route im Monitoring-Proxy und neue Admin-Präfixe (R-1223)  [ ]
Komponente: server · Dateien: apps/server/app/modules/monitoring_proxy/router.py, apps/server/tests/test_monitoring_proxy_plan.py, apps/server/tests/test_monitoring_proxy_allowlist.py, apps/server/tests/openapi.snapshot.json
Änderung: `GET /api/monitoring/agent/{server_id}/plan` neben `proxy_agent_report` (`router.py:108`) mit denselben Abhängigkeiten (`require_cert_server`, `require_scope(SCOPE_AGENT)`) und eigenem Ratenzähler je Adresse; Antwort des Dienstes unverändert durchgereicht, Fehler wie bei `/report`. `_ALLOWED_PATH_PREFIXES` (`router.py:78`) um `catalog`, `discovery`, `findings`. Tests: ohne Zertifikat/Scope abgelehnt, Ratenlimit, Durchreichen, Präfixe erlaubt und Nachbarpfade weiter verboten; OpenAPI-Snapshot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_monitoring_proxy_plan.py tests/test_monitoring_proxy_allowlist.py tests/test_monitoring_ingest_ratelimit.py tests/test_monitoring_proxy_errors.py tests/test_openapi_snapshot.py
Doku: → T15

### T8 — Agent: Plan holen, Takt-Planer, Probe-Rahmen und Report v4 (R-1223)  [ ]
Komponente: agent · Dateien: apps/agent/internal/execx/execx.go, apps/agent/internal/execx/execx_test.go, apps/agent/internal/monitor/plugins.go, apps/agent/internal/probe/probe.go, apps/agent/internal/probe/probe_test.go, apps/agent/internal/monitor/plan.go, apps/agent/internal/monitor/plan_test.go, apps/agent/internal/monitor/monitor.go, apps/agent/internal/monitor/report.go, apps/agent/internal/monitor/report_test.go
Änderung: `execx.Run` (SPDX) übernimmt `runTimed` wörtlich, `runTimed` in `plugins.go` ruft es nur noch auf: ein Exec-Pfad für alle Collector, Fühler und die Erkennung (Anknüpfung für R-1222). `probe.go`: Plan-Typen, Register der Fühler (unbekannt → `invalid`), Ergebnis-Cache mit `ts`. `plan.go`: Plan per GET über den Push-Client (Timeout 15 s), bei Erfolg 0600 in `MonitorDir()` gespeichert, bei Fehler oder 404 der gespeicherte Plan (Log auf Info); Takt-Planer im Report-Zustand (fällig nach `interval_s`, nie öfter als 5 min). `Push` (`monitor.go:182`) fährt fällige Proben im Restbudget; `report_version` 4 (`report.go:64`) mit `probes` (letztes Ergebnis jeder Probe) und `credentials`. Zehn Dateien: der Exec-Helfer gehört zum Probe-Rahmen, Report und Planer teilen den Zustand.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T15
Abhängt von: T5

### T9 — Agent: Selbstmessung und Selbstbremse (R-1223)  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/selfmeasure.go, apps/agent/internal/monitor/selfmeasure_test.go, apps/agent/internal/monitor/report.go, apps/agent/internal/monitor/reportstate.go, apps/agent/internal/monitor/report_test.go
Änderung: Jeder Collector läuft in einem Messrahmen (Dauer, CPU-Zeit aus rusage von Prozess und Kindern, Zeitlimit-Treffer); Block `self.collectors` im Report. Für die optionalen Collector (`docker`, `proxmox`, `zfs`, `smart`, Proben, Erkennung) verdoppeln zwei Zeitlimit-Treffer hintereinander den Faktor (höchstens 8), drei saubere Läufe halbieren ihn; ein gebremster Lauf meldet `throttled: true`. Faktor und Zähler im Report-Zustand (`.report-state.json`). Die Kern-Collector werden nie gebremst. Der Rahmen liegt in `report.go`, `plugins.go` bleibt außer T8 unberührt.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T15
Abhängt von: T8

### T10 — Agent: Ziel-Wächter, Feld-Freigabe, Zugangsbremse, Zugangsdaten und CLI (R-1223)  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go, apps/agent/internal/probe/fields.go, apps/agent/internal/probe/fields_test.go, apps/agent/internal/credentials/store.go, apps/agent/internal/credentials/store_test.go, apps/agent/cmd/adminhelper-agent/main.go, apps/agent/cmd/adminhelper-agent/credential_cmd_test.go
Änderung: `guard.go`: Dialer mit `Control`-Hook, der nur Loopback, Adressen eigener Interfaces und Adressen eigener Container zulässt (an der tatsächlich verbundenen Adresse), Sperrliste Ports 22, 3306, 9100–9107 und Prozesse `sshd`, `mysqld`, `mariadbd`; HTTP nur GET/HEAD, Weiterleitung nur auf dasselbe Ziel, Body-Deckel. `fields.go`: Feld-Freigabe (Pfad-Auswahl aus JSON, nur Skalare, 256 Zeichen, 32 Felder). Zugangsbremse: nach 401/403 Ruhe bis zum Wechsel des Fingerabdrucks der Zugangsdaten (Zustand lokal). `credentials/store.go` (SPDX): `credentials.json` in `MonitorDir()`, 0600, mit zu offenen Rechten verweigert; `adminhelper-agent monitor credential set <ref>` (Geheimnis nur über stdin), `delete`, `list` (nur Verweise). Acht Dateien: der Sicherheitsrahmen wird als Einheit geprüft.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T15
Abhängt von: T8

### T11 — Agent: lokale Fühler unit, process, socket, container, certfile, file_age (R-1223)  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_local.go, apps/agent/internal/probe/sensor_local_linux.go, apps/agent/internal/probe/sensor_local_windows.go, apps/agent/internal/probe/sensor_local_test.go, apps/agent/internal/probe/target.go, apps/agent/internal/probe/target_test.go
Änderung: `unit` (Linux `systemctl show` mit festen Properties, Windows Dienststatus), `process` (Anzahl, Laufzeit, RSS über gopsutil), `socket` (lauscht Port/Adresse), `container` (`docker inspect` Status, Health, Restart-Zähler), `certfile` (PEM-Datei: Ablauf, Aussteller, Subject; Fehler ohne Dateiinhalt), `file_age` (Alter per `stat`, nie Inhalt). `target.go`: Ziel-Auflösung `container`/`process`/`unit`/`port` auf den tatsächlich lauschenden Port (Hinweis-Port, sonst einziger, sonst `ambiguous_target`). Exec nur über `execx.Run` mit festen Argumenten.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T15
Abhängt von: T10

### T12 — Agent: Netz-Fühler http, tls, proto, unixsocket, dns (R-1223)  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_http.go, apps/agent/internal/probe/sensor_tls.go, apps/agent/internal/probe/sensor_proto.go, apps/agent/internal/probe/sensor_dns.go, apps/agent/internal/probe/sensor_net_test.go, apps/agent/internal/probe/sensor_proto_test.go
Änderung: `http` (GET/HEAD über den Wächter, Status, Dauer, Felder aus JSON), `tls` (Ablauf, Hostname-Prüfung, Kette lokal), `proto` (Banner bzw. protokolltypische Begrüßung für smtp, imap, pop3, ldap, postgres SSLRequest, redis INFO, fastcgi-Ping, haproxy `show stat`, mit STARTTLS wo vorgesehen; beendet jede Sitzung sauber, z. B. QUIT), `unixsocket` (Verbindung, optional HTTP oder eine `proto`-Art über den Socket), `dns` (Auflösung über den lokalen Resolver, Antwortzeit). Tests gegen lokale Fake-Server je Protokoll, Wächter-Ablehnung fremder Adressen, Zugangsbremse bei 401/403. Protokolle vorher in der Primärquelle nachlesen (Spec „Externe Integrationen“).
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T15
Abhängt von: T10, T11

### T13 — Agent: Fühler sql und log (R-1223)  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_sql.go, apps/agent/internal/probe/sensor_sql_test.go, apps/agent/internal/probe/sensor_log.go, apps/agent/internal/probe/sensor_log_linux.go, apps/agent/internal/probe/sensor_log_other.go, apps/agent/internal/probe/sensor_log_test.go
Änderung: `sql` nur Linux über `mariadb --protocol=socket` bzw. `runuser -u postgres -- psql` mit festen Abfrage-IDs im Agent (Erreichbarkeit, Verbindungen, Replikationsstand, Größe), fehlt das Programm → `unsupported`. `log` Linux über `journalctl` mit `--after-cursor`/`--show-cursor` und Zählung nach Unit und Priorität (nur Zahlen, keine Zeilen); Cursor im Report-Zustand; Windows → `unsupported` (W4).
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T15
Abhängt von: T10

### T14 — Agent: Erkennung mit Zeitrahmen (R-1223)  [ ]
Komponente: agent · Dateien: apps/agent/internal/discovery/discovery.go, apps/agent/internal/discovery/discovery_linux.go, apps/agent/internal/discovery/discovery_other.go, apps/agent/internal/discovery/discovery_test.go, apps/agent/internal/monitor/monitor.go, apps/agent/internal/monitor/report.go
Änderung: Bei `scan: true` im Plan: Units, lauschende Sockets mit Prozess bzw. Container, Container (Image, Compose-Labels, Ports, Health, Mount-Ziele), Marker (Pfad vorhanden, Paket installiert über `dpkg-query`/`rpm -q`) und Protokollerkennung unbekannter Nicht-Loopback-Ports über `proto` (Banner abwarten, dann typische Probe, dann TLS; nie Port 22, 3306, 9100–9107, nie Ports von `sshd`/`mysqld`/`mariadbd`, nie ein `Host`-Kopf). Zeitrahmen 60 s mit Timeout je Teil, `partial: true` bei Abbruch; nur Metadaten im Block `discovery`.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T15
Abhängt von: T8, T12

### T15 — Doku DE+EN und CHANGELOG-Fragment (R-1223)  [ ]
Komponente: monitoring · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/arch-monitoring-module.md
Änderung: Module, Erkennung, Funde-Eingang, stille Checks, `probe` in der Liste der Push-Checks, Sicherheitsmodell samt Restrisiko (Admin-Handbuch Monitoring); `monitor credential set|delete|list` in der CLI-Tabelle (Agent-Deployment); Katalog-Format, Check-Typ `probe`, Datenvertrag Plan/Report v4, Fühler, Ziel-Wächter, Takt-Planer, Selbstbremse (Entwickler); neue Routen (API-Referenz); CHANGELOG-Fragment unter `### Added`. Elf Dateien: fünf Seiten je DE+EN und das Fragment.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_openapi_snapshot.py
Doku: diese Task
Task-Review: am Ende
Abhängt von: T14

## Entscheidungen
- 2026-11-09 T1: Das Modul `port` prüft mit `proto` und `protocol: auto` (der Agent erkennt das Protokoll wie seine Erkennung und meldet es in `detail`) — ein Fund trägt das erkannte Protokoll, ohne Platzhalter in Katalog-Parametern bleibt jede Prüfung im eigenen Protokoll.
- 2026-11-09 T1: Ungültige Module lässt der Lader aus und nennt sie in `Catalog.errors`; `test_catalog.py` verlangt `errors == ()` — die Spec will den Test rot, nicht den Dienst.
- 2026-11-09 T1: Ein Katalog-Check trägt `timeout_s` (Standard 10, 1–30 s), Marker-IDs beginnen mit `<modul-id>.` — der Plan braucht ein Timeout je Probe, und Marker-IDs sind im Plan global.
- 2026-11-09 T3: Die Check-ID kommt als `config["_check_id"]` an den Probe-Checker; `_evaluate_push_check` setzt sie aus der Zeile, `ProbeConfig` (extra forbid) nimmt sie an der API nicht an — `test_check_type_parity` legt die Signatur `evaluate(config, report, prev_details)` fest.
- 2026-11-09 T3: `ProbeConfig` prüft über das Katalog-Modell `Check` (Fühler, Ziel, Parameter, Felder, Regeln, Takt, Testobjekt, `credential.use`) — eine Regelquelle für Katalog und Check; eigen sind nur `target.name`, `credential.ref` (Segmente ohne führenden Punkt) und die strikten Zahlen.
- 2026-11-09 T3: `max_age` liest den Feldwert als Unix-Sekunden und misst gegen das `ts` der Probe (Vertrag für die Fühler T11–T13); Frische und Alter rechnen mit der Agent-Uhr (`timestamp` des Reports), nur ohne gültige Angabe mit der Server-Uhr.
- 2026-11-09 T3: `delta_gt` vergleicht mit dem vorigen gemessenen Lauf (`measured_ts`, `values`, `baseline` in den Details); derselbe Lauf im nächsten Report behält seine Basis, ein fallender Zähler ist kein Anstieg.
- 2026-11-09 T3: Keine Metrik-Historie der Probe-Werte (`CHECK_TYPE_METRICS["probe"] = []`, Werte nur in den Details) — Kennzahlen-Verläufe entscheidet `arch-monitoring-ui`.
