# Server: Supervisor-Frist und 422-Form — Task-Ledger
Status: aktiv · Branch: feature/kern-server-10 · Review: am Ende
Spec: docs/features/kern-server-10.md (Roadmap R-1444, R-1494)
Heavy: none — nur Server-Tests und die Form vierer 422-Bodys, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1444: Frist der Supervisor-Tests auf 30 s  [x]
Komponente: server · Dateien: apps/server/tests/test_frps_supervisor.py, tasks/kern-server-10.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @c0ecad72d 2026-11-16T22:40:45+01:00
Review: am Ende (Branch-Review)
Änderung: `WAIT = 10.0` → `30.0` (`apps/server/tests/test_frps_supervisor.py:79`), alle Verwendungen sind
Obergrenzen einer Abfrage. Dauerlauf nach `testing.md` („Wackler“) über den betroffenen Test, Summary in den
Commit-Body.
Beweis: main-ci 2026-11-13 run 43496686654 attempt 1 (c16472cf9), `F` an Position 810 von Shard 1/2, nachgesammelt
auf c16472cf9: `test_a_valid_change_restarts_frps_once_from_the_new_copy[new token]`
Dedup-Key: bug:server:ci:server-shard-timeout · HEAD: c16472cf9
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frps_supervisor.py
Doku: keine (Test-Frist)

### T2 — R-1494: vier 422 als HTTPValidationError  [ ]
Komponente: server · Dateien: apps/server/app/modules/connections/router.py, apps/server/app/modules/ansible/router.py, apps/server/app/modules/notifications/router.py, apps/server/tests/test_connection_derived_names.py, apps/server/tests/test_ansible.py, apps/server/tests/test_notification_prefs_test.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-server-10.md, tasks/kern-server-10.md
Änderung: Die 422 an `connections/router.py:314`, `ansible/router.py:61` und `:154`, `notifications/router.py:602`
werfen `RequestValidationError` (`loc` `body.name`, `body.content`, `body.channel`; `msg` der bisherige Text) wie
`servers/router.py` `_invalid_name`. Tests prüfen `detail[0].loc` und `msg`, erst rot gegen den alten Router.
Beweis: reviewer kern-server-9 2026-11-14 @11fa9eb2f
Dedup-Key: bug:server:api:422-detail-string
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_connection_derived_names.py tests/test_ansible.py tests/test_notification_prefs_test.py tests/test_openapi_snapshot.py
Doku: docs/developer/api-reference.html DE+EN · changelog.d/kern-server-10.md (DE+EN im Fragment)

## Entscheidungen
