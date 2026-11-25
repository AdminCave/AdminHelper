# kern-server-15 — Task-Ledger
Status: bereit · Branch: feature/kern-server-15 · Review: pro Task
Spec: docs/features/kern-server-15.md (Roadmap R-1758, R-1763, R-1764, R-1773)
Heavy: linux-full — docker-compose.yml (Healthchecks von monitoring und ca-issuer)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1758: Healthchecks von monitoring und ca-issuer ohne Proxy  [x]
Komponente: server · Dateien: docker-compose.yml, apps/server/tests/test_compose_healthchecks.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @d88d5f220 2026-11-25T05:36:09+01:00
Review: approve (.ah-out/review/kern-server-15/T1.verdict.json)
Änderung: Die Healthchecks von `monitoring` und `ca-issuer` öffnen ihre Loopback-URL über `build_opener(ProxyHandler({}))`, wie der Server-Check. Ein Test fährt die beiden Befehle aus der Compose-Datei mit gesetztem `http_proxy` auf einen toten Port gegen einen lokalen HTTP-Server; ohne den Fix ist er rot.
Beweis: docker-compose.yml:396 und :611 @main 564be0395 (`urlopen` ohne ProxyHandler); Probe aus R-1758: `proxy_bypass('127.0.0.1')` ist False
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_compose_healthchecks.py
Doku: keine (Verhalten wie dokumentiert: der Check fragt den Dienst selbst)

### T2 — R-1773: LOG_LEVEL nur aus der festen Liste  [x]
Komponente: server · Dateien: apps/pycommon/ah_common/logging_config.py, apps/server/tests/test_logging_config.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @d7976474b 2026-11-25T05:39:16+01:00
Review: approve (.ah-out/review/kern-server-15/T2.verdict.json)
Änderung: `_resolve_level` prüft gegen die feste Liste DEBUG, INFO, WARNING, ERROR, CRITICAL wie der CA-Issuer, statt gegen `getLevelName`. Der Test `LOG_LEVEL=TRACE` (mit registriertem Level) erwartet `ConfigError`; ohne den Fix ist er rot.
Beweis: apps/pycommon/ah_common/logging_config.py:33 @main 564be0395; docs/admin/betrieb.html:133 nennt die fünf Namen für alle drei Dienste
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_logging_config.py
Doku: keine (betrieb.html beschreibt schon die feste Liste)

### T3 — R-1763, R-1764: Glocken-Notiz eines fehlgeschlagenen Hooks  [x]
Komponente: server · Dateien: apps/server/app/modules/hooks/script_runner.py, apps/server/app/modules/hooks/scheduler.py, apps/server/app/core/events.py, apps/server/app/modules/notifications/models.py, apps/server/tests/test_hooks.py, docs/features/kern-server-15.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @2836f80ab 2026-11-25T05:52:05+01:00
Review: approve (.ah-out/review/kern-server-15/T3.verdict.json)
Änderung: `notify_hook_failure` (script_runner.py:365) hält Prüfen und Schreiben je Hook unter einem Prozess-Lock, damit zwei gleichzeitige Fehlschläge nur eine Notiz geben (Test mit zwei Threads, ohne den Fix rot). Die Notiz zu einer Ausnahme des Hook-Laufs nennt nur deren Typ; Einzelheiten bleiben im Log (scheduler.py:155, events.py:74). Der Kommentar des Glocken-Vokabulars nennt `hooks`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hooks.py tests/test_events_after_commit.py
Doku: → T6

### T4 — R-1763: Kategorie hooks im Desktop  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/models/notifications.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/lib/models/notifications.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @58e49bad5 2026-11-25T05:56:57+01:00
Review: approve (.ah-out/review/kern-server-15/T4.verdict.json)
Änderung: `hooks` kommt in `NOTIFICATION_CATEGORIES` (nach `session`), mit Label DE „Hooks“ und EN „Hooks“; der Test prüft Label und Reihenfolge.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/models/notifications.test.ts
Doku: keine (Vokabular der Oberfläche, nicht dokumentiert)

### T5 — R-1763: Tag-Abgleich wartet nicht auf die Entwarnungen  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/tag_sync.py, apps/monitoring/tests/test_tag_sync.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @2fb29c167 2026-11-25T05:58:30+01:00
Review: approve (.ah-out/review/kern-server-15/T5.verdict.json)
Änderung: `_cleanup_orphans` (tag_sync.py:155) gibt `cleanup_server` ein `send_clears`, das die Entwarnungen in einem Daemon-Thread an den Hub schickt. Fehler werden geloggt. Der Test zeigt mit einem blockierenden Hub, dass der Abgleich zurückkehrt; ohne den Fix ist er rot.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_tag_sync.py
Doku: → T6

### T6 — Doku: Hook-Notiz, Changelog  [x]
Komponente: scripts · Dateien: docs/developer/hooks.html, docs/en/developer/hooks.html, changelog.d/kern-server-15.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @eae6e06e8 2026-11-25T06:09:34+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Die Hook-Seite nennt Kategorie `hooks` und den Fehlertext der Notiz (nur der Typ einer Ausnahme). Changelog-Fragment ohne Umlaute, neutral.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/hooks.html DE+EN · changelog.d/kern-server-15.md
Task-Review: am Ende
Abhängt von: T3, T5

## Entscheidungen
- T2: Auch die Alias-Namen WARN und FATAL, die `getLevelName` kennt, stoppen jetzt den Start. So halten es der CA-Issuer und betrieb.html (fünf Namen); ein Test belegt es.
- T3: Prozess-Lock statt DB-Lock. Ein Hook ist entweder geplant (Prozess `scheduler`) oder ereignisgesteuert (Web-Worker); das Restrisiko einer zweiten Notiz bei `WEB_CONCURRENCY` > 1 ist in der Spec genannt (Prüfer-Fund T3, Weg b).
