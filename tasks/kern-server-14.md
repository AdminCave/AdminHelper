# kern-server-14 — Task-Ledger
Status: geplant · Branch: feature/kern-server-14 · Review: pro Task
Spec: docs/features/kern-server-14.md (Roadmap R-1694, R-1695, R-1697, R-1698, R-1699, R-1734, R-1737, R-1744, R-1715)
Heavy: linux-full — Server-API (neue Route), docker-compose.yml (Healthcheck), Monitoring-Abgleich
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1694: Glocken-Notiz an die Admins bei einem fehlgeschlagenen Hook  [ ]
Komponente: server · Dateien: apps/server/app/modules/hooks/scheduler.py, apps/server/app/core/events.py, apps/server/app/modules/hooks/script_runner.py, apps/server/tests/test_hooks.py
Änderung: Scheitert ein geplanter oder ein Event-Hook (auch „Hook-Limit erreicht“), bekommen die Admins über `notify_users` eine Glocken-Notiz, entprellt je Hook. Der Log-Eintrag bleibt. Der Test belegt Notiz, Entprellung und den Fall des vollen Semaphors.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hooks.py
Doku: → T7

### T2 — R-1695: keine DB-Verbindung über den Monitoring-Forward  [ ]
Komponente: server · Dateien: apps/server/app/modules/monitoring_proxy/router.py, apps/server/app/core/identity.py, apps/server/tests/test_monitoring_proxy_plan.py, apps/server/tests/test_monitoring_proxy_audit.py
Änderung: `proxy_agent_report` und `proxy_agent_plan` prüfen den Scope auf einer kurzen eigenen Session, wie `authenticate_stream_user`. `proxy_to_monitoring` gibt seine Session vor dem Forward frei. Der Test zählt die ausgeliehenen Pool-Verbindungen während eines gestubbten Forwards (0) und prüft, dass Scope-Ablehnung und Audit unverändert bleiben.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_monitoring_proxy_plan.py tests/test_monitoring_proxy_audit.py
Doku: keine (internes Verhalten)

### T3 — R-1697: Waisen gelöschter Server im Tag-Abgleich abräumen  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/tag_sync.py, apps/monitoring/app/server_cleanup.py, apps/monitoring/tests/test_tag_sync.py
Änderung: Der periodische Tag-Abgleich ruft `cleanup_server` für jede `server_id` auf, die das Monitoring kennt und das Inventar nicht, nur bei erfolgreich geholtem, nicht leerem Inventar. Tests: Waise wird entfernt; leeres und gescheitertes Inventar entfernen nichts.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_tag_sync.py
Doku: → T7

### T4 — R-1698: Digest-Fehlschlag mit Backoff wie der normale Versand  [ ]
Komponente: server · Dateien: apps/server/app/modules/notifications/digest.py, apps/server/tests/test_notification_digest.py
Änderung: Ein fehlgeschlagener Digest setzt `next_attempt_at` wie `outbox.py` (linear); die Auswahl nimmt nur fällige Einträge. Test: ein Relay-Ausfall von 20 min verwirft den Digest nicht mehr, der Versuch danach geht.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_digest.py
Doku: → T7

### T5 — R-1699, R-1737: FRP-Policy und Bulk-ZIP mit fester Abfragezahl  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/policy.py, apps/server/app/modules/frp/_helpers.py, apps/server/app/modules/frp/generate_router.py, apps/server/tests/test_frp_policy.py, apps/server/tests/test_frp_query_count.py
Änderung: `build_policy` lädt Admin-Namen und `server_id -> usernames` einmal und reicht sie durch; die Policy bleibt byte-gleich. Neue Tests zählen die Statements von `sync_policy` (unabhängig von der Serverzahl) und von `gen_bulk_zip` mit drei Benutzern (Muster `tests/test_auth_query_count.py`). Neue Testdatei mit SPDX-Header.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_policy.py tests/test_frp_query_count.py
Doku: keine (internes Verhalten)

### T6 — R-1734: Nachlese kern-server-11  [ ]
Komponente: server · Dateien: apps/server/app/modules/notifications/router.py, apps/server/tests/test_bootstrap.py, apps/server/tests/test_users_last_admin.py
Änderung: Routen-Tests für die 409 bei einem vergebenen Benutzernamen (Bootstrap und API), den veralteten Kommentar berichtigen, den Prüfpunkt aus der privaten Nachlese klären (Ergebnis unter `## Entscheidungen`; ein Fix nur, wenn er sich bestätigt).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_bootstrap.py tests/test_users_last_admin.py
Doku: keine (Tests und Kommentar)

### T7 — R-1744, R-1715: Route /api/health, Compose-Healthcheck, Doku  [ ]
Komponente: server · Dateien: apps/server/app/main.py, apps/server/tests/test_health.py, apps/server/tests/openapi.snapshot.json, apps/server/tests/test_compose_healthchecks.py, docker-compose.yml, docs/admin/installation.html, docs/en/admin/installation.html, changelog.d/kern-server-14.md
Änderung: `GET /api/health` → `200 {"status":"ok"}`, ohne Auth und DB, vor der Catch-all-Route. Der Compose-Healthcheck des Servers fragt sie per HTTP ab, der Kommentar zur Migrations-Reihenfolge bleibt. Doku DE und EN passend dazu, dazu die Hook-Notiz (T1). Changelog-Fragment für T1, T3, T4, T7. Neue Testdatei mit SPDX-Header.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_health.py tests/test_openapi_snapshot.py tests/test_compose_healthchecks.py
Doku: docs/admin/installation.html, docs/en/admin/installation.html, Hook-Seite DE+EN, changelog.d/kern-server-14.md

## Entscheidungen
- 2026-11-24: R-1694 als Glocken-Notiz, keine Migration (Kevin). R-1744/R-1715 als Route `/api/health` ohne DB (Kevin).
