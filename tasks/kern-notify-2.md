# Kanäle ntfy, Telegram, Webhook · Matrix Schweregrad × Kanal · Kategorien — Task-Ledger
Status: geplant · Branch: feature/kern-notify-2 · Review: pro Task
Spec: docs/features/kern-notify-2.md (Roadmap R-1080)
Heavy: linux-full — Server-API und Alembic-Migration (notification-prefs), ausgehende Requests, Desktop-Journey SSE-Push (`desktop_e2e_sse_push.sh`); geht in den Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Server: Tabelle notification_settings, Migration aus den Häkchen, Routing über die Matrix, Prefs-API (R-1080)  [ ]
Komponente: server · Dateien: apps/server/app/modules/notifications/models.py, apps/server/alembic/versions/f3a5c7e9b1d2_notification_settings.py, apps/server/app/modules/notifications/service.py, apps/server/app/modules/notifications/incidents.py, apps/server/app/modules/notifications/schemas.py, apps/server/app/modules/notifications/router.py, apps/server/tests/test_notification_settings.py, apps/server/tests/test_notifications.py, apps/server/tests/test_cli.py, apps/server/tests/test_openapi_snapshot.py, apps/server/tests/openapi.snapshot.json
Änderung: Neue Tabelle `notification_settings` (Spec, Datenmodell); die Migration übernimmt `channel_email`/`channel_telegram` in die Matrix (Zeilen ≥ `min_severity`, `ok` wenn irgendeine Zeile, `desktop` überall) und entfernt die Spalten, der Downgrade stellt sie aus der Matrix her. `resolve_recipients` liefert nur noch die Glocke, `_queue` wählt die Kanäle aus Matrix (Zeile nach dem Ping-Schweregrad, unbekannt → `critical`), `disabled_channels`, `muted_categories` und den Zielen; bis T2 nur `email` und `telegram`. Prefs-API GET/PUT in der neuen Form (Spec), fehlende neue Felder behalten ihren Wert, URL-Form geprüft. Tests: Migration mit Gegenprobe (Häkchen → Matrix → Downgrade), Routing je Matrix-Zelle, stumme Kategorie und Schalter, Prefs-API; Aufrufer der alten Felder in den Tests nachgezogen (weitere per `set-files`, mehr als acht Dateien, weil das Entfernen der Spalten alle Leser in einem Commit verlangt). Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_settings.py tests/test_notifications.py tests/test_notification_category_migration.py tests/test_cli.py tests/test_openapi_snapshot.py
Doku: → T7

### T2 — Server und Monitoring: SSRF-Sperre mit Opt-in für private Ziele (R-1080)  [ ]
Komponente: server · Dateien: apps/server/app/core/ssrf.py, apps/monitoring/app/core/ssrf.py, apps/server/tests/test_ssrf.py
Änderung: `check_target(url, *, allow_private=False)` in beiden Kopien gleich (`test_ssrf_parity.py` verlangt identischen Code): mit `True` sind private Adressen und `100.64.0.0/10` erlaubt; Loopback, Link-Local (auch `169.254.169.254`), unspezifiziert, Multicast, reserviert und `0.0.0.0/8` bleiben gesperrt, auch als IPv4-mapped IPv6. Ohne das Argument ändert sich nichts (Hooks, Monitoring). Tests je Adressklasse mit und ohne Opt-in.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ssrf.py tests/test_ssrf_parity.py tests/test_ssrf_properties.py tests/test_ssrf_pin.py
Doku: → T7
Abhängt von: T1

### T3 — Server: Versand über ntfy, Telegram und Webhook mit SSRF-Sperre (R-1080)  [ ]
Komponente: server · Dateien: apps/server/app/core/config.py, apps/server/app/modules/notifications/sender.py, apps/server/app/modules/notifications/outbox.py, apps/server/app/modules/notifications/incidents.py, .env.example, apps/server/tests/test_notification_channels.py, apps/server/tests/test_ssrf.py
Änderung: Vorher ntfy-Publish (Titel-Kodierung, `auth`) und Telegram `sendMessage` (Textlimit, `parse_mode`) in der offiziellen Doku nachlesen und die Belege unter `## Entscheidungen`. `TELEGRAM_BOT_TOKEN` und `NOTIFY_ALLOW_PRIVATE_TARGETS` in `config.py`. `drain_outbox` stellt `ntfy`, `telegram`, `webhook` zu (Format Spec), über `check_target(url, allow_private=NOTIFY_ALLOW_PRIVATE_TARGETS)` (T2) und `pinned_client` ohne Redirects; ein gesperrtes Ziel ist sofort `failed`, sonst Backoff wie E-Mail; Logs und `last_error` ohne URL, Chat-ID, Token. `_queue` legt `ntfy`/`webhook` an und `telegram` nur mit Token. Tests mit `httpx.MockTransport`: Format je Kanal, Priorität, Kürzung, gesperrtes Ziel mit und ohne Opt-in, kein Redirect, kein Geheimnis im Log (`caplog`). Neue Datei mit SPDX-Header.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_channels.py tests/test_notifications.py
Doku: → T7
Abhängt von: T2

### T4 — Server: Test-Route je Kanal mit Sperre je Person (R-1080)  [ ]
Komponente: server · Dateien: apps/server/app/modules/notifications/router.py, apps/server/app/modules/notifications/schemas.py, apps/server/app/modules/notifications/sender.py, apps/server/tests/test_notification_prefs_test.py, apps/server/tests/openapi.snapshot.json
Änderung: `POST /api/users/me/notification-prefs/test` mit `{"channel"}` (Spec): sofortiger Versand an das gespeicherte Ziel über die Sender aus T3, `200`/`409`/`422`/`502`/`429`, Sperre ein Test je Person und Kanal in zehn Sekunden über `app/core/rate_limit.py`, neutrale Fehlertexte. Prüft dabei, ob `RequestModel` alte Felder (`channel_email`) ablehnt, und hält das Ergebnis unter `## Entscheidungen` für T6 fest. Tests: jeder Status, die Sperre, kein Geheimnis in der Antwort; OpenAPI-Snapshot. Neue Datei mit SPDX-Header.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_prefs_test.py tests/test_openapi_snapshot.py
Doku: → T7
Abhängt von: T3

### T5 — Desktop-UI: Kanäle, Matrix und Kategorien in den Einstellungen, Toast-Gate (R-1080)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/NotificationPrefs.svelte, apps/desktop/ui/src/components/NotificationPrefs.test.ts, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/api/notifications.ts, apps/desktop/ui/src/lib/api/notifications.test.ts, apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/SettingsModal.save.test.ts
Änderung: `NotificationPrefs.svelte` nach dem Mockup: Abschnitt Kanäle (Ziel, Schalter, Knopf Test; Desktop testet lokal, die übrigen über T4; ntfy- und Webhook-URL als Geheimnis maskiert; nicht `available` → Hinweis statt Test), Matrix Schweregrad × Kanal, Kategorien-Chips (`monitoring`, `security`, `tunnel`, `agent`); die Regeln ohne Kanal-Häkchen. `onNewNotifications` (`AppShell.svelte`) zeigt Toast und OS-Hinweis nur nach Matrix, Desktop-Schalter und Kategorie, ohne geladene Prefs wie heute. Typen ohne `any`, Texte DE+EN. Tests: Speichern schickt die neue Form, Test-Knopf und Fehlertext, Toast-Gate je Fall; `SettingsModal.workspace.test.ts` und weitere Aufrufer per `set-files`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: → T7
Abhängt von: T4

### T6 — Desktop-E2E und Test-Skripte: Prefs in der neuen Form (R-1080)  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/lib/live.js, scripts/tests/sse_push_e2e.sh, scripts/tests/desktop_e2e_sse_push.sh
Änderung: `ensureAllSubscription` (`live.js`) und die beiden SSE-Push-Skripte schicken Regeln ohne `channel_email`/`channel_telegram`; die Journeys laufen im Sammellauf (Heavy).
Verify: bash scripts/dev/verify.sh desktop-e2e scripts --strict
Doku: keine (Testcode)
Abhängt von: T1

### T7 — Doku und Changelog: Kanäle, Matrix, Kategorien, Env (R-1080)  [ ]
Komponente: server · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/admin/betrieb.html, docs/en/admin/operations.html, docs/developer/server.html, docs/en/developer/server.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-notify-2.md
Änderung: Bedienung (Kanäle, Matrix, Kategorien, Test-Knopf), Betrieb (`TELEGRAM_BOT_TOKEN`, `NOTIFY_ALLOW_PRIVATE_TARGETS`, Sperre und Opt-in), Entwickler (Tabelle `notification_settings`, Outbox-Kanäle, Prefs-API und Test-Route samt Vertragsbruch der Abo-Felder) DE+EN; `changelog.d/kern-notify-2.md` (`### Added`, `### Changed`, umlautfrei). Vorher `python3 scripts/dev/doc-smoke.py --paths --env --strict`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_settings.py
Doku: alle oben DE+EN · changelog.d/kern-notify-2.md
Task-Review: am Ende
Abhängt von: T5

## Entscheidungen
- 2026-11-07 Planung: eigene Tabelle statt Spalten an `users`; Kanal-Schalter als Liste; ntfy-Zugang per `?auth=` in der URL; Webhook ohne Signatur; CGNAT unter dem Opt-in; fehlende neue Felder beim `PUT` behalten ihren Wert (Begründungen in der Spec).
