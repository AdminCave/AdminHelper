# kern-server-11 — Ein Weg für neue Benutzer, FRP-Startprüfungen aus main.py — Task-Ledger
Status: aktiv · Branch: feature/kern-server-11 · Review: pro Task
Spec: docs/features/kern-server-11.md (Roadmap R-0690)
Heavy: linux-full — Server-API (Bootstrap, Benutzer anlegen) und der Start des Servers (frps.toml)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-0690: users/service.create_user als einziger Weg  [x]
Komponente: server · Dateien: apps/server/app/modules/users/service.py, apps/server/app/modules/users/router.py, apps/server/app/modules/users/auth_router.py, apps/server/app/cli.py, apps/server/app/main.py, apps/server/tests/test_users_service.py, apps/server/tests/test_bootstrap.py, apps/server/tests/test_cli.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @09538ae8f 2026-11-23T16:43:52+01:00
Review: approve (.ah-out/review/kern-server-11/T1.verdict.json)
Änderung: Neue Datei `users/service.py` (SPDX) mit `create_user(db, *, username, password, is_admin, servers, actor, audit_action="user.created") -> User` und `UsernameTaken`: Insert, Basis-Abo-Regel eines Admins, `queue_event("user.created")`, Commit mit Fang des `IntegrityError`, `sync_policy`, Audit. `POST /api/users`, `POST /api/auth/bootstrap` (Audit `auth.bootstrap`, Lock und Token unverändert), `cli create-admin` und `_ensure_admin` rufen ihn. Neue Testdatei (SPDX): je Weg genau ein `user.created`, ein Audit-Eintrag, Policy-Sync, Wettlauf → `UsernameTaken` ohne Event.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_users_service.py tests/test_bootstrap.py tests/test_cli.py tests/test_users.py tests/test_users_promotion_event.py tests/test_event_whitelist.py tests/test_openapi_snapshot.py
Doku: → T4

### T2 — R-0690: frps_fields liefert die Felder strukturiert  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/config_generator.py, apps/server/app/main.py, apps/server/tests/test_config_generator.py, apps/server/tests/test_frp_extra_config.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @1a7db5543 2026-11-23T17:05:11+01:00
Review: approve (.ah-out/review/kern-server-11/T2.verdict.json)
Änderung: `frps_fields(config) -> dict[str, str | int | bool]` liefert Schlüssel und Werte vor `[transport.tls]`; `generate_frps_toml` schreibt sie, `_report_rejected_fields` liest sie statt den Text an ` = ` zu zerlegen. Test: der erzeugte Text ist für eine Reihe von Konfigurationen (Dashboard an/aus, vhost, subDomainHost, extra_config) Byte für Byte der vorherige (festgehaltene Erwartung), und `_report_rejected_fields` meldet dieselben Felder.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_config_generator.py tests/test_frp_extra_config.py tests/test_frp_toml_roundtrip.py tests/test_frp_input_hardening.py tests/test_frps_supervisor.py
Doku: keine (interne Struktur, frps.toml unverändert)
Abhängt von: T1

### T3 — R-0690: FRP-Startprüfungen nach frp/startup_checks.py  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/startup_checks.py, apps/server/app/main.py, apps/server/tests/test_frp_extra_config.py, apps/server/tests/test_frp_docker_manager.py, apps/server/tests/test_frp_policy.py, apps/server/tests/test_frp_config.py, apps/server/tests/test_notifications.py, apps/server/tests/test_notification_category_migration.py, apps/server/app/modules/frp/config_generator.py, apps/server/app/modules/frp/docker_manager.py, apps/server/app/modules/frp/config_router.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @f7281b24d 2026-11-23T17:11:32+01:00
Review: approve (.ah-out/review/kern-server-11/T3.verdict.json)
Änderung: `_tell_admins`, `_remove_rejected_extra_config`, `_report_rejected_fields`, `_check_frps_server_configs` und `_ensure_frps_config` ziehen unverändert in die neue Datei (SPDX, öffentliche Namen ohne Unterstrich für die beiden Einstiege); `_run_startup_tasks` ruft sie von dort. Die Tests patchen den neuen Ort. Acht Dateien, weil sechs Tests die verschobenen Funktionen über `app.main` erreichen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_extra_config.py tests/test_frp_docker_manager.py tests/test_frp_policy.py tests/test_frp_config.py tests/test_notifications.py tests/test_notification_category_migration.py tests/test_bootstrap.py
Doku: → T4
Abhängt von: T2

### T4 — R-0690: Doku DE+EN und Changelog  [ ]
Komponente: scripts · Dateien: docs/developer/hooks.html, docs/en/developer/hooks.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-server-11.md
Änderung: Event-Katalog: `user.created` feuert jeder Weg, der einen Benutzer anlegt (API, Bootstrap, CLI, `ADMIN_PASSWORD` beim Start). API-Referenz: der Bootstrap feuert `user.created`. Changelog-Fragment (umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/hooks.html, docs/en/developer/hooks.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-server-11.md
Task-Review: am Ende

## Entscheidungen
