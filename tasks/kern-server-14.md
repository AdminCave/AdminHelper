# kern-server-14 — Task-Ledger
Status: bereit · Branch: feature/kern-server-14 · Review: pro Task
Spec: docs/features/kern-server-14.md (Roadmap R-1694, R-1695, R-1697, R-1698, R-1699, R-1734, R-1737, R-1744, R-1715)
Heavy: linux-full — Server-API (neue Route), docker-compose.yml (Healthcheck), Monitoring-Abgleich
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1694: Glocken-Notiz an die Admins bei einem fehlgeschlagenen Hook  [x]
Komponente: server · Dateien: apps/server/app/modules/hooks/scheduler.py, apps/server/app/core/events.py, apps/server/app/modules/hooks/script_runner.py, apps/server/tests/test_hooks.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @cc18d0601 2026-11-24T15:37:24+01:00
Review: approve (.ah-out/review/kern-server-14/T1.verdict.json)
Änderung: Scheitert ein geplanter oder ein Event-Hook (auch „Hook-Limit erreicht“), bekommen die Admins über `notify_users` eine Glocken-Notiz, entprellt je Hook. Der Log-Eintrag bleibt. Der Test belegt Notiz, Entprellung und den Fall des vollen Semaphors.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hooks.py
Doku: → T7

### T2 — R-1695: keine DB-Verbindung über den Monitoring-Forward  [x]
Komponente: server · Dateien: apps/server/app/modules/monitoring_proxy/router.py, apps/server/app/core/identity.py, apps/server/tests/test_monitoring_proxy_plan.py, apps/server/tests/test_monitoring_proxy_audit.py, apps/server/tests/conftest.py, apps/server/tests/test_mtls_scope.py, apps/server/tests/test_certificate_check.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @b0fb13224 2026-11-24T15:54:55+01:00
Review: approve (.ah-out/review/kern-server-14/T2.verdict.json)
Änderung: `proxy_agent_report` und `proxy_agent_plan` prüfen den Scope auf einer kurzen eigenen Session, wie `authenticate_stream_user`. `proxy_to_monitoring` gibt seine Session vor dem Forward frei. Der Test zählt die ausgeliehenen Pool-Verbindungen während eines gestubbten Forwards (0) und prüft, dass Scope-Ablehnung und Audit unverändert bleiben.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_monitoring_proxy_plan.py tests/test_monitoring_proxy_audit.py tests/test_mtls_scope.py tests/test_certificate_check.py
Doku: keine (internes Verhalten)

### T3 — R-1697: Waisen gelöschter Server im Tag-Abgleich abräumen  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/tag_sync.py, apps/monitoring/app/server_cleanup.py, apps/monitoring/tests/test_tag_sync.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @4ab88ed0c 2026-11-24T15:42:04+01:00
Review: approve (.ah-out/review/kern-server-14/T3.verdict.json)
Änderung: Der periodische Tag-Abgleich ruft `cleanup_server` für jede `server_id` auf, die das Monitoring kennt und das Inventar nicht, nur bei erfolgreich geholtem, nicht leerem Inventar. Tests: Waise wird entfernt; leeres und gescheitertes Inventar entfernen nichts.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_tag_sync.py
Doku: → T7

### T4 — R-1698: Digest-Fehlschlag mit Backoff wie der normale Versand  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/digest.py, apps/server/tests/test_notification_digest.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @ee24d908f 2026-11-24T15:49:52+01:00
Review: approve (.ah-out/review/kern-server-14/T4.verdict.json)
Änderung: Ein fehlgeschlagener Digest setzt `next_attempt_at` wie `outbox.py` (linear); die Auswahl nimmt nur fällige Einträge. Test: ein Relay-Ausfall von 20 min verwirft den Digest nicht mehr, der Versuch danach geht.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_digest.py
Doku: → T7

### T5 — R-1699, R-1737: FRP-Policy und Bulk-ZIP mit fester Abfragezahl  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/policy.py, apps/server/app/modules/frp/_helpers.py, apps/server/app/modules/frp/generate_router.py, apps/server/tests/test_frp_policy.py, apps/server/tests/test_frp_query_count.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @528f946dc 2026-11-24T16:04:21+01:00
Review: approve (.ah-out/review/kern-server-14/T5.verdict.json)
Änderung: `build_policy` lädt Admin-Namen und `server_id -> usernames` einmal und reicht sie durch; die Policy bleibt byte-gleich. Neue Tests zählen die Statements von `sync_policy` (unabhängig von der Serverzahl) und von `gen_bulk_zip` mit drei Benutzern (Muster `tests/test_auth_query_count.py`). Neue Testdatei mit SPDX-Header.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_policy.py tests/test_frp_query_count.py
Doku: keine (internes Verhalten)

### T6 — R-1734: Nachlese kern-server-11  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/router.py, apps/server/tests/test_bootstrap.py, apps/server/tests/test_users_last_admin.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @efbb49e98 2026-11-24T16:06:59+01:00
Review: approve (.ah-out/review/kern-server-14/T6.verdict.json)
Änderung: Routen-Tests für die 409 bei einem vergebenen Benutzernamen (Bootstrap und API), den veralteten Kommentar berichtigen, den Prüfpunkt aus der privaten Nachlese klären (Ergebnis unter `## Entscheidungen`; ein Fix nur, wenn er sich bestätigt).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_bootstrap.py tests/test_users_last_admin.py
Doku: keine (Tests und Kommentar)

### T7 — R-1744, R-1715: Route /api/health, Compose-Healthcheck, Doku  [x]
Komponente: server · Dateien: apps/server/app/main.py, apps/server/tests/test_health.py, apps/server/tests/openapi.snapshot.json, apps/server/tests/test_compose_healthchecks.py, docker-compose.yml, docs/admin/installation.html, docs/en/admin/installation.html, changelog.d/kern-server-14.md, docs/developer/hooks.html, docs/en/developer/hooks.html
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @8a9c12804 2026-11-24T16:16:45+01:00
Review: approve (.ah-out/review/kern-server-14/T7.verdict.json)
Änderung: `GET /api/health` → `200 {"status":"ok"}`, ohne Auth und DB, vor der Catch-all-Route. Der Compose-Healthcheck des Servers fragt sie per HTTP ab, der Kommentar zur Migrations-Reihenfolge bleibt. Doku DE und EN passend dazu, dazu die Hook-Notiz (T1). Changelog-Fragment für T1, T3, T4, T7. Neue Testdatei mit SPDX-Header.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_health.py tests/test_openapi_snapshot.py tests/test_compose_healthchecks.py
Doku: docs/admin/installation.html, docs/en/admin/installation.html, Hook-Seite DE+EN, changelog.d/kern-server-14.md

### T8 — R-1744: /api/health im Inventar der öffentlichen Routen  [x]
Komponente: server · Dateien: apps/server/tests/test_route_auth_gate.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @57ae50d65 2026-11-24T16:38:14+01:00
Review: approve (.ah-out/review/kern-server-14/T8.verdict.json)
Beweis: feature/kern-server-14@27c1119e9 tests/test_route_auth_gate.py::test_every_api_route_is_guarded_or_explicitly_public rot (1 failed, 4 passed), Abschlussprüfung
Änderung: `("GET", "/api/health")` mit Begründung (Liveness ohne Auth und DB, R-1744) in `_PUBLIC_ROUTES`. Der Test war vor der Änderung rot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_route_auth_gate.py tests/test_health.py
Doku: keine (Test-Inventar)

### T9 — R-1694: Glocken-Notiz wirft nach einem Rollback nicht  [x]
Komponente: server · Dateien: apps/server/app/modules/hooks/script_runner.py, apps/server/tests/test_hooks.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @6d5cf2af8 2026-11-24T16:47:50+01:00
Review: approve (.ah-out/review/kern-server-14/T9.verdict.json)
Beweis: feature/kern-server-14@27c1119e9 app/modules/hooks/script_runner.py:403-404 (`hook.name` nach `db.rollback()` lädt das abgelaufene Objekt nach; bei toter DB wirft `notify_hook_failure`, in `core/events.py:71-74` bricht das die übrigen Hooks des Events ab)
Änderung: `notify_hook_failure` liest Name und ID des Hooks vor dem `try` und nutzt danach nur die lokalen Werte. Test erst rot: scheitert das Schreiben und ist die DB danach nicht mehr erreichbar, wirft die Funktion nicht.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hooks.py
Doku: keine (Fehlerpfad)

## Entscheidungen
- 2026-11-24: R-1694 als Glocken-Notiz, keine Migration (Kevin). R-1744/R-1715 als Route `/api/health` ohne DB (Kevin).
- 2026-11-24 T3: Die bekannten Server-IDs werden vor dem Holen des Inventars gelesen. Der Hub legt einen Server an, bevor das Monitoring Daten zu ihm bekommt, so kann ein gerade angelegter Server nicht als Waise gelten. `test_assignment_of_a_server_missing_from_the_inventory_stays` sicherte das alte Verhalten ab, das R-1697 absichtlich ändert. Er ist ersetzt durch `test_server_missing_from_the_inventory_is_cleaned_up`, dazu kommen Tests für leeres und gescheitertes Inventar.
- 2026-11-24 T6: Prüfpunkt aus der Nachlese bestätigt sich nicht, kein Fix. Ein `create-admin` per `docker compose exec` läuft als root und hinterlässt die Policy-Datei root-eigen (0644, für frps lesbar). Der Server-Prozess ersetzt sie trotzdem: `_replace_atomically` schreibt eine Temp-Datei und benennt sie per `os.replace` um, dafür reicht Schreibrecht auf das Verzeichnis, und das gehört nach `chown -R` im Entrypoint `app`. Aus Code und rename-Semantik gelesen, nicht im Container gefahren.
- 2026-11-24 T7: Der Compose-Healthcheck des Servers wertet jede HTTP-Antwort als gesund, auch ein 403. `IPFilterMiddleware` sieht beim Check im Container `127.0.0.1`; ist `ALLOWED_IPS` gesetzt und enthält Loopback nicht, antwortet der Server 403, und ein Check, der nur 2xx gelten ließe, machte den Dienst `unhealthy` (dann rollte `update.sh` mit `up --wait` zurück). `/api/health` vom IP-Filter auszunehmen hätte das Sicherheitsverhalten geändert. Ungesund heißt so: keine Antwort binnen 2 s, wie bei einem hängenden Prozess.
