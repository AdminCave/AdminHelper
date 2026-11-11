# Monitoring: Härtung der Probe-Anlage, der Probe-Ziele und der Probe-Zugangsdaten — Task-Ledger
Status: bereit · Branch: feature/kern-monitoring-19 · Review: pro Task
Spec: docs/features/kern-monitoring-19.md (Roadmap R-1252, R-1266, R-1299)
Heavy: linux-full — apps/agent (Ziel-Abgleich, Fühler, Zugangsdaten) und apps/monitoring (Checks-API, Plan)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1299: Ziel-Abgleich bei veröffentlichten Container-Ports ohne Host-Listener  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go, apps/agent/internal/probe/sensor_local.go, apps/agent/internal/probe/target.go, apps/agent/internal/probe/sensor_local_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @28b198dfc 2026-11-11T12:23:30+01:00
Review: approve (.ah-out/review/kern-monitoring-19/T1.verdict.json)
Änderung:
- Hat `checkListener` für Adresse und Port keinen Host-Listener, liest der Guard die Port-Maps der laufenden
  Container (`docker inspect`, Form vorher in der Docker-Engine-Doku nachlesen) mit TTL wie die Listener-Liste. Ist
  der Port ein veröffentlichter Host-Port mit gesperrtem Container-Port (`blockedPort`), lehnt er ab.
- Ohne Docker gibt es nichts abzugleichen. Ist Docker da, aber die Abfrage scheitert, scheitert der Guard
  geschlossen. Ein gestoppter Dienst ohne Veröffentlichung behält `connection refused`.
- Tests über die Seams: veröffentlicht auf gesperrten Port → abgelehnt, auf freien Port → erlaubt, kein Docker →
  erlaubt, Docker unlesbar → abgelehnt; Gegenprobe mit Listener bleibt beim heutigen Weg.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/...
Doku: → T5

### T2 — R-1252 (Agent): Steuerdienste und Socket-Pfade, die der Agent nie anspricht  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go, apps/agent/internal/probe/sensor_local_linux.go, apps/agent/internal/probe/sensor_local_linux_test.go, apps/agent/internal/probe/sensor_unixsocket.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @882be1194 2026-11-11T12:35:49+01:00
Review: approve (.ah-out/review/kern-monitoring-19/T2.verdict.json)
Änderung:
- `hostDaemons`/`hostDaemonPrefixes` um die Proxmox-API-Dienste und weitere VM-Prozesse ergänzen (Liste aus der
  Roadmap-Notiz R-1252).
- Eine Sperrliste von Pfad-Präfixen für Unix-Sockets (Laufzeitverzeichnisse von Container-, VM-, Bus- und
  Sitzungsdiensten); geprüft am angegebenen und am aufgelösten Pfad (Symlinks), vor dem Peer-Abgleich, der bleibt.
- Tests: jeder gesperrte Pfad und Prozess → `not_allowed`, auch über einen Symlink; die Socket-Pfade des Katalogs
  bleiben erlaubt.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/...
Doku: → T5

### T3 — R-1266: Zugangsdaten an das Ziel ihres Moduls binden  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/probe.go, apps/agent/internal/probe/probe_test.go, apps/agent/internal/probe/sensor_http.go, apps/agent/internal/probe/sensor_proto.go, apps/agent/internal/probe/sensor_unixsocket.go, apps/agent/internal/monitor/reportstate.go, apps/agent/internal/monitor/reportstate_test.go, apps/agent/internal/monitor/report.go, apps/agent/internal/monitor/monitor.go, apps/agent/internal/monitor/plan_test.go, docs/features/kern-monitoring-19.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @1c702f707 2026-11-11T12:45:36+01:00
Review: approve (.ah-out/review/kern-monitoring-19/T3.verdict.json)
Änderung:
- Ein Sensor bekommt das Secret erst, nachdem er sein Ziel aufgelöst hat (Sensor, Übergabe, Ziel-Art und -Name,
  Port bzw. Socket-Pfad). Beim ersten Einsatz einer Credential-ID bindet der Agent sie daran; ein anderes Ziel ergibt
  `not_allowed`, bis das Secret neu gesetzt ist (neue ID). Die Bindung hält der Report-Zustand wie die Bremse.
- Tests: gleicher Ref mit anderem Ziel, Port, Pfad, Sensor oder Übergabe → verweigert, kein Secret an den Sensor;
  Neusetzen löst die Bindung; die Bindung überlebt einen Lauf (Report-Zustand).
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/... ./internal/monitor/...
Doku: → T5

### T4 — R-1252 (Monitoring): Probe-Checks nur aus übernommenen Modulen  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/checks.py, apps/monitoring/app/schemas.py, apps/monitoring/app/module_plan.py, apps/monitoring/tests/test_checks_crud.py, apps/monitoring/tests/test_agent_plan.py, apps/monitoring/tests/test_templates_router.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @55c838097 2026-11-11T12:25:48+01:00
Review: approve (.ah-out/review/kern-monitoring-19/T4.verdict.json)
Änderung:
- `POST /checks` mit `check_type=probe` → 422; `PUT /checks/{id}` mit Wechsel von oder zu `probe` → 422; an einer
  Probe-Config ändern sich nur `rules`, `interval_s`, `timeout_s` (Mess-Teile gleich, sonst 422).
- `TemplateCheckDef` lehnt `probe` ab (422).
- `_probes` (`module_plan.py`) nimmt nur Probe-Checks mit `module_id` in den Plan.
- Docstrings der Routen bleiben (OpenAPI-Snapshot); Tests für jeden Weg, Gegenprobe: Modul-Übernahme legt weiter
  Probe-Checks an, Regeln bleiben änderbar. Bestehende Tests, die Probe-Checks über `POST /checks` anlegen, legen
  sie künftig über die Übernahme oder direkt in der DB an (kein Test entfällt).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_checks_crud.py tests/test_agent_plan.py tests/test_templates_router.py tests/test_module_sync.py tests/test_openapi_snapshot.py
Doku: → T5

### T5 — Doku DE+EN und CHANGELOG  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-19.md, docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @6789ce0f2 2026-11-11T12:47:58+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Probe-Checks nur über Module (Check-Typen, Config-Tabelle, Dashboard-Karte), Bindung der Zugangsdaten,
was der Agent nie anspricht; CHANGELOG-Fragment neutral (`### Security`/`### Changed`).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-19.md
Task-Review: am Ende

### T6 — Katalog: ein Credential-Slot gehört zu einem Ziel  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/model.py, apps/monitoring/tests/test_catalog.py, docs/developer/monitoring.html, docs/en/developer/monitoring.html
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @fb4ac8db2 2026-11-11T13:01:30+01:00
Review: approve (.ah-out/review/kern-monitoring-19/T6.verdict.json)
Änderung: `Module._consistent` lehnt ein Modul ab, dessen Checks einen Credential-Slot mit anderem Sensor, anderer
Übergabe, anderem Ziel oder (bei `unixsocket`) anderem Pfad teilen; der Agent bindet die Zugangsdaten beim ersten
Einsatz an ein Ziel (T3), ein zweites bliebe dauerhaft `not_allowed`. Tests: gleiches Ziel erlaubt, je abweichendes
Teil abgelehnt. Quelle: Abschlussprüfung (R-1266).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog.py
Doku: docs/developer/monitoring.html, docs/en/developer/monitoring.html

## Entscheidungen
- 2026-11-11: Bindung der Zugangsdaten beim ersten Einsatz nach dem Setzen (Spec, Trade-offs), innerhalb von Kevins
  Entscheidung „Secret im Agent an Ziel und Port seines Moduls binden“.
- 2026-11-11: Überschneidung mit `feature/arch-freebsd-agent` und `feature/arch-opnsense-plugin` (`probe/guard.go`
  u. a.) wie bei kern-monitoring-15/16 hingenommen (Kevin 2026-11-11: der arch-Branch zieht main später nach).
- 2026-11-11 (T1): Der Abgleich der veröffentlichten Ports läuft für jede Adresse und jeden Port, auch neben einem
  Host-Listener (Docker leitet per NAT vor ihm um), und nur unter Linux (Docker Desktop lauscht immer mit eigenem
  Prozess). Ohne Docker heißt: kein Daemon am Socket; antwortet einer, scheitert der Guard bei jedem Lesefehler
  geschlossen, auch ohne CLI im PATH. Fehlt in der Antwort von `docker inspect` ein Container, muss er auch aus
  `docker ps` verschwunden sein. Ein Lesefehler wird nicht zwischengespeichert (nächster Dial fragt neu).
- 2026-11-11 (T4): An einem Probe-Check bleiben über die API Name, Beschreibung, Schweregrad, an/aus,
  `consecutive_*` und in der Config `rules`, `interval_s`, `timeout_s` änderbar; fehlende Mess-Teile der Config gelten
  mit ihren Vorgaben als gleich. Ein Wechsel des Servers wird abgelehnt (der Check gehört zum Modul seines Servers).
  Die Ablehnung beim Anlegen steht im Schema `CheckCreate` (vor dem Config-Abgleich), nicht in der Route.
- 2026-11-11 (T2): Die Sperrliste der Socket-Pfade (`controlSockets`) prüft den angegebenen und den aufgelösten Pfad
  (`/var/run` gilt als `/run`), gewählt wird dann der aufgelöste. Neben den Prozessen aus der Roadmap-Notiz sperrt sie
  auch `spiceproxy` (Konsolen der Proxmox-Gäste), `xenstored`, die API-Dienste von Proxmox Backup Server und Mail
  Gateway, kubelet, k3s und buildkitd (Prüfer-Nits). VirtualBox und Cloud Hypervisor stehen als
  Präfix, weil der Kernel Namen auf 15 Zeichen kürzt. Ein Katalog-Modul mit Unix-Socket gibt es auf `main` noch
  nicht; der Test prüft die üblichen Pfade von php-fpm, Redis, HAProxy, PostgreSQL und nginx.
- 2026-11-11 (T3): Die Bindung gilt dem Ziel, wie der Plan es nennt (Sensor, Übergabe, Art, Name, Port-Hinweis,
  Schema, bei `unixsocket` der Pfad), nicht dem aufgelösten Port: sie steht vor dem Sensor fest, die Sensoren bleiben
  unverändert, und das Ziel löst der Guard ohnehin nur auf diesem Host auf. Ein anderer Pfad derselben HTTP-Seite oder
  andere Felder sind dasselbe Ziel. Ein Neustart des Dienstes auf anderem Port bricht die Bindung nicht. `register` im
  Test schreibt den vorigen Sensor zurück (der Test mit dem echten Namen `unixsocket` löschte ihn sonst).
