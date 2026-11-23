# kern-events-1 — Server-Events nach dem Commit — Task-Ledger
Status: aktiv · Branch: feature/kern-events-1 · Review: pro Task
Spec: docs/features/kern-events-1.md (Roadmap R-0689)
Heavy: linux-full — Server-Handler aller CRUD-Routen (Events, Hooks, Benachrichtigungen) und Scheduler-Start
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-0689: Outbox je Session, begrenzte Warteschlange, Shutdown  [x]
Komponente: server · Dateien: apps/server/app/core/events.py, apps/server/app/core/database.py, apps/server/app/main.py, apps/server/tests/test_events_after_commit.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @75b9576dc 2026-11-23T14:58:05+01:00
Review: approve (.ah-out/review/kern-events-1/T1.verdict.json)
Änderung: `queue_event(db, type, data)` legt in `db.info` ab; Listener auf der Klasse `Session`: `after_commit` der Wurzel (nicht nested) gibt an den Executor, `after_transaction_end` der Wurzel verwirft, ein Fehler beim Abgeben wird geloggt. Executor mit Deckel 1000 (jedes weitere Event verworfen, Warnung mit Typ) und `shutdown_events(timeout=10)` am Ende des Lifespans. Neue Testdatei (SPDX): Commit → 1, Rollback → 0, `close()` → 0, SAVEPOINT-Commit → 0 bis zum äußeren Commit, `submit` wirft → `commit()` wirft nicht, Deckel, Shutdown.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_events_after_commit.py
Doku: → T4

### T2 — R-0689: Router und CLI reihen ein statt zu feuern  [x]
Komponente: server · Dateien: apps/server/app/modules/users/router.py, apps/server/app/modules/connections/router.py, apps/server/app/modules/servers/router.py, apps/server/app/modules/ansible/router.py, apps/server/app/modules/frp/tunnel_router.py, apps/server/app/modules/frp/config_router.py, apps/server/app/cli.py, apps/server/tests/test_event_whitelist.py, apps/server/tests/test_events_after_commit.py, apps/server/tests/test_servers_authz.py, apps/server/tests/test_frp_config.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @c5d65ad70 2026-11-23T15:30:26+01:00
Review: approve (.ah-out/review/kern-events-1/T2.verdict.json)
Änderung: Erst der rote Test: `delete_user` mit scheiternder `revoke_identity` bzw. scheiterndem Commit feuert kein `user.deleted`; erfolgreiches Löschen genau einmal mit gleichem Payload. Dann jede Aufrufstelle: Payload vor dem Commit (nach `db.flush()`, wo `id` gebraucht wird), `queue_event`, `commit`; die 2.48-Kommentare entfallen. `test_event_whitelist.py` erkennt beide Namen und erlaubt `fire_event` nur in `app/core/events.py`, `app/scheduler_main.py` und `modules/notifications/router.py`. Neun Dateien, weil alle Aufrufstellen gegen denselben Mechanismus und dieselbe Allowlist geprüft werden.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_events_after_commit.py tests/test_event_whitelist.py tests/test_users_promotion_event.py tests/test_users.py tests/test_connections_import.py tests/test_servers_authz.py tests/test_ansible.py tests/test_frp_tunnels.py tests/test_frp_config.py
Doku: → T4
Abhängt von: T1

### T3 — R-0689: server.startup einmal, vom Scheduler  [x]
Komponente: server · Dateien: apps/server/app/main.py, apps/server/app/scheduler_main.py, apps/server/tests/test_scheduler_schema_gate.py, apps/server/tests/test_event_whitelist.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @cf8169ab7 2026-11-23T15:35:04+01:00
Review: approve (.ah-out/review/kern-events-1/T3.verdict.json)
Änderung: Der Lifespan feuert `server.startup` nicht mehr; `scheduler_main.main()` feuert es nach `scheduler.start()` und ruft beim Stopp `shutdown_events`. Test: `main()` mit gestubbtem Scheduler und Signal feuert genau ein `server.startup`; der Lifespan feuert keins.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_scheduler_schema_gate.py tests/test_events_after_commit.py tests/test_event_whitelist.py tests/test_bootstrap.py
Doku: → T4
Abhängt von: T1

### T4 — R-0689: Doku DE+EN und Changelog  [ ]
Komponente: scripts · Dateien: docs/developer/hooks.html, docs/en/developer/hooks.html, docs/developer/server.html, docs/en/developer/server.html, changelog.d/kern-events-1.md
Änderung: `hooks.html`: `queue_event` vor dem Commit statt `fire_event`, Zeitpunkt (nach dem Commit, verworfen bei Rollback), Deckel 1000, Shutdown 10 s. `server.html:179`: `server.startup` einmal je Start, vom Scheduler. Changelog-Fragment (umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/hooks.html, docs/en/developer/hooks.html, docs/developer/server.html, docs/en/developer/server.html, changelog.d/kern-events-1.md
Task-Review: am Ende

## Entscheidungen
- Outbox über SQLAlchemy-Session-Events statt Wächter-Helfer (advisor 2026-11-23); `audit.record` bleibt explizit.
- `server.startup` einmal vom Scheduler; Warteschlange 1000 mit Verwerfen und 10 s Shutdown (Kevin 2026-11-23).
- T2 lässt `app/main.py` vorübergehend in der `fire_event`-Allowlist (dort feuert noch `server.startup`); T3 nimmt es heraus.
