# kern-server-12 — Ein Monitoring-Client im Server, Internal-Key-Gate nach core — Task-Ledger
Status: erledigt · Branch: feature/kern-server-12 · Review: pro Task
Spec: docs/features/kern-server-12.md (Roadmap R-0691)
Heavy: linux-full — Server-API (Server löschen, Provisioning, Internal-Ingress)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-0691: core/monitoring_client für alle Wege zum Monitoring  [x]
Komponente: server · Dateien: apps/server/app/core/monitoring_client.py, apps/server/app/modules/servers/router.py, apps/server/app/modules/provisioning/helpers.py, apps/server/app/modules/provisioning/progress.py, apps/server/app/modules/monitoring_proxy/router.py, apps/server/tests/test_monitoring_client.py, apps/server/tests/test_tag_sync_notify.py, apps/server/tests/test_frp_policy.py, apps/server/tests/test_identity_revocation.py, apps/server/tests/test_provisioning.py, apps/server/tests/test_servers_authz.py, changelog.d/kern-server-12.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @848e7db23 2026-11-23T18:20:37+01:00
Review: approve (.ah-out/review/kern-server-12/T1.verdict.json)
Änderung: Neue Datei `core/monitoring_client.py` (SPDX) mit `base_url()` und `request(method, path, *, timeout)`. Tag-Sync, Cleanup, Agent-Key und Fortschritt rufen `request` mit ihrem bisherigen Timeout, der Proxy nimmt `base_url()`. Test erst rot: Mit `MONITOR_SERVICE_URL` mit Slash am Ende treffen Tag-Sync und Cleanup die URL ohne `//`. Zwölf Dateien, weil fünf Tests `servers_router.httpx` patchen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_monitoring_client.py tests/test_tag_sync_notify.py tests/test_frp_policy.py tests/test_identity_revocation.py tests/test_provisioning.py tests/test_servers_authz.py tests/test_provisioning_progress.py tests/test_monitoring_proxy_errors.py tests/test_monitoring_proxy_plan.py tests/test_monitoring_proxy_lifespan.py tests/test_monitoring_proxy_audit.py
Doku: changelog.d/kern-server-12.md

### T2 — R-0691: require_internal_key nach core/auth  [x]
Komponente: server · Dateien: apps/server/app/core/auth.py, apps/server/app/modules/notifications/router.py, apps/server/app/modules/servers/router.py, apps/server/tests/test_route_auth_gate.py, apps/server/tests/test_notifications.py, apps/server/tests/test_schemathesis.py, apps/server/tests/test_internal_servers.py, apps/server/tests/test_notify_internal_config.py, apps/server/tests/test_notification_incidents.py, apps/server/tests/test_response_shapes.py, apps/server/tests/test_text_bounds.py, apps/server/tests/test_server_name_and_address.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @b696cbe15 2026-11-23T18:31:00+01:00
Review: approve (.ah-out/review/kern-server-12/T2.verdict.json)
Änderung: `_internal_key_scheme` und `require_internal_key` ziehen unverändert nach `core/auth.py`; `notifications/router.py` und `servers/router.py` importieren von dort. Der OpenAPI-Snapshot bleibt gleich (Scheme `InternalKey`), das Routen-Gate erkennt den Namen weiter.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_route_auth_gate.py tests/test_openapi_snapshot.py tests/test_notifications.py tests/test_servers_authz.py tests/test_tag_sync_notify.py tests/test_internal_servers.py tests/test_notify_internal_config.py tests/test_notification_incidents.py tests/test_response_shapes.py tests/test_text_bounds.py tests/test_server_name_and_address.py
Doku: keine (interner Ort, Verhalten gleich)
Abhängt von: T1

## Entscheidungen
- T1: Rot vor dem Fix per Probe gegen den Stand von main belegt: `_do_notify_tag_sync` mit `MONITOR_SERVICE_URL=http://monitor.test/` rief `http://monitor.test//templates/tag-sync`. Die Tests patchen jetzt `servers_router.monitoring_request` statt des globalen `httpx.post`/`httpx.delete`; `MONITOR_API_KEY` wird zur Aufrufzeit aus `app.core.config` gelesen, deshalb setzt der Fixture `monitor_key_set` dort.
- T1: Der Proxy behält `_MONITOR_BASE` als Wert zur Importzeit (Tests lesen ihn), nimmt ihn aber aus `monitoring_client.base_url()`.
