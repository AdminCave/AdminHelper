# Kanäle ntfy, Telegram, Webhook · Matrix Schweregrad × Kanal · Kategorien — Task-Ledger
Status: aktiv · Branch: feature/kern-notify-2 · Review: pro Task
Spec: docs/features/kern-notify-2.md (Roadmap R-1080)
Heavy: linux-full — Server-API und Alembic-Migration (notification-prefs), ausgehende Requests, Desktop-Journey SSE-Push (`desktop_e2e_sse_push.sh`); geht in den Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Server: Tabelle notification_settings, Migration aus den Häkchen, Routing über die Matrix, Prefs-API (R-1080)  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/models.py, apps/server/alembic/versions/f3a5c7e9b1d2_notification_settings.py, apps/server/app/modules/notifications/service.py, apps/server/app/modules/notifications/incidents.py, apps/server/app/modules/notifications/schemas.py, apps/server/app/modules/notifications/router.py, apps/server/tests/test_notification_settings.py, apps/server/tests/test_notifications.py, apps/server/tests/test_cli.py, apps/server/tests/test_openapi_snapshot.py, apps/server/tests/openapi.snapshot.json, apps/server/tests/test_users.py, apps/server/tests/test_bootstrap.py, apps/server/tests/test_certificate_expiry_watch.py, apps/server/tests/test_response_shapes.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @23f453790 2026-11-07T05:57:23+01:00
Review: approve (.ah-out/review/kern-notify-2/T1.verdict.json)
Änderung: Neue Tabelle `notification_settings` (Spec, Datenmodell); die Migration übernimmt `channel_email`/`channel_telegram` in die Matrix (Zeilen ≥ `min_severity`, `ok` wenn irgendeine Zeile, `desktop` überall) und entfernt die Spalten, der Downgrade stellt sie aus der Matrix her. `resolve_recipients` liefert nur noch die Glocke, `_queue` wählt die Kanäle aus Matrix (Zeile nach dem Ping-Schweregrad, unbekannt → `critical`), `disabled_channels`, `muted_categories` und den Zielen; bis T2 nur `email` und `telegram`. Prefs-API GET/PUT in der neuen Form (Spec), fehlende neue Felder behalten ihren Wert, URL-Form geprüft. Tests: Migration mit Gegenprobe (Häkchen → Matrix → Downgrade), Routing je Matrix-Zelle, stumme Kategorie und Schalter, Prefs-API; Aufrufer der alten Felder in den Tests nachgezogen (weitere per `set-files`, mehr als acht Dateien, weil das Entfernen der Spalten alle Leser in einem Commit verlangt). Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_settings.py tests/test_notifications.py tests/test_notification_category_migration.py tests/test_cli.py tests/test_users.py tests/test_bootstrap.py tests/test_certificate_expiry_watch.py tests/test_openapi_snapshot.py tests/test_response_shapes.py tests/test_alembic_builtin.py tests/test_notification_incidents.py tests/test_outbox.py tests/test_notification_bridge.py
Doku: → T7

### T2 — Server und Monitoring: SSRF-Sperre mit Opt-in für private Ziele (R-1080)  [x]
Komponente: server · Dateien: apps/server/app/core/ssrf.py, apps/monitoring/app/core/ssrf.py, apps/server/tests/test_ssrf.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @33a146925 2026-11-07T06:10:10+01:00
Review: approve (.ah-out/review/kern-notify-2/T2.verdict.json)
Änderung: `check_target(url, *, allow_networks=())` in beiden Kopien gleich (`test_ssrf_parity.py` verlangt identischen Code): eine private Adresse oder eine aus `100.64.0.0/10` ist erlaubt, wenn ein Netz der Liste sie enthält; Loopback, Link-Local (auch `169.254.169.254`), unspezifiziert, Multicast, reserviert und `0.0.0.0/8` bleiben gesperrt, auch als IPv4-mapped IPv6. Ohne das Argument ändert sich nichts (Hooks, Monitoring). Tests je Adressklasse mit und ohne Listeneintrag.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ssrf.py tests/test_ssrf_parity.py tests/test_ssrf_properties.py tests/test_ssrf_pin.py
Doku: → T7
Abhängt von: T1

### T3 — Server: Versand über ntfy, Telegram und Webhook mit SSRF-Sperre (R-1080)  [ ]
Komponente: server · Dateien: apps/server/app/core/config.py, apps/server/app/modules/notifications/sender.py, apps/server/app/modules/notifications/outbox.py, apps/server/app/modules/notifications/incidents.py, .env.example, apps/server/tests/test_notification_channels.py, apps/server/tests/test_ssrf.py
Änderung: Vorher ntfy-Publish (Titel-Kodierung, `auth`) und Telegram `sendMessage` (Textlimit, `parse_mode`) in der offiziellen Doku nachlesen und die Belege unter `## Entscheidungen`. `TELEGRAM_BOT_TOKEN` und `NOTIFY_PRIVATE_TARGETS` (CIDR-Liste) in `config.py`. `drain_outbox` stellt `ntfy`, `telegram`, `webhook` zu (Format Spec), über `check_target(url, allow_networks=NOTIFY_PRIVATE_TARGETS)` (T2) und `pinned_client` ohne Redirects; ein gesperrtes Ziel ist sofort `failed`, sonst Backoff wie E-Mail; Logs und `last_error` ohne URL, Chat-ID, Token. `_queue` legt `ntfy`/`webhook` an und `telegram` nur mit Token. Tests mit `httpx.MockTransport`: Format je Kanal, Priorität, Kürzung, gesperrtes Ziel mit und ohne Listeneintrag, kein Redirect, kein Geheimnis im Log (`caplog`). Neue Datei mit SPDX-Header.
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
Änderung: Bedienung (Kanäle, Matrix, Kategorien, Test-Knopf), Betrieb (`TELEGRAM_BOT_TOKEN`, `NOTIFY_PRIVATE_TARGETS`, Sperre und Freigabe-Liste), Entwickler (Tabelle `notification_settings`, Outbox-Kanäle, Prefs-API und Test-Route samt Vertragsbruch der Abo-Felder) DE+EN; `changelog.d/kern-notify-2.md` (`### Added`, `### Changed`, umlautfrei). Vorher `python3 scripts/dev/doc-smoke.py --paths --env --strict`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_settings.py
Doku: alle oben DE+EN · changelog.d/kern-notify-2.md
Task-Review: am Ende
Abhängt von: T5

## Entscheidungen
- 2026-11-07 Planung: eigene Tabelle statt Spalten an `users`; Kanal-Schalter als Liste; ntfy-Zugang per `?auth=` in der URL; Webhook ohne Signatur; CGNAT unter dem Opt-in; fehlende neue Felder beim `PUT` behalten ihren Wert (Begründungen in der Spec).
- 2026-11-07 T1: `resolve_recipients` setzt neben `bell` den Schlüssel `out` (die Server des Kanaltexts, gleich `bell`); `_queue` legt ohne `out` nichts an, so bleibt `notify()`/`notify_users` glockenexklusiv, obwohl jetzt die Matrix der Person wählt.
- 2026-11-07 T1: Ein Bündel nennt in jedem Kanal die Server der Glocke (Spec, Routing); die Tests der Kanal-Server je Regel (`TestBundleChannels`, monitoring-alert-quality T18) folgen dieser Semantik: `test_telegram_names_only_the_server_of_its_subscription` und `test_each_channel_names_the_servers_of_its_own_subscriptions` entfallen (ersetzt durch `test_every_channel_names_the_servers_of_the_bell`), `test_a_channel_without_a_server_gets_no_entry` geht in `test_a_member_channel_names_only_servers_they_may_see` auf.
- 2026-11-07 T1: `RequestModel` verbietet keine Extra-Felder: ein altes `channel_email` in einer Regel wird still ignoriert (T4 bestätigt das für T6); `available.telegram` bleibt `false`, bis T3 `TELEGRAM_BOT_TOKEN` liest.
- 2026-11-07 T2: Kevin 2026-11-07: Die Freigabe privater Ziele ist eine CIDR-Liste `NOTIFY_PRIVATE_TARGETS` statt des Schalters `NOTIFY_ALLOW_PRIVATE_TARGETS`; nur die genannten Netze gehen auf, die harte Sperre liegt davor.
- 2026-11-07 T2: Die harte Sperre (`_always_blocked`) prüft auch die eingebettete IPv4 von 6to4 (`2002::/16`) und Teredo, sonst öffnete ein Listeneintrag wie `2002::/16` den Weg zu 169.254.169.254; sie gilt vor der Liste, auch für `0.0.0.0/0`. Dazu sperrt sie die Metadaten-Adressen außerhalb von Link-Local: `fd00:ec2::/32` (AWS IPv6), `fd20:ce::254` (GCP, nur IPv6), `100.100.100.200` (Alibaba). NAT64 (`64:ff9b::/96`) und IPv4-kompatible Adressen (`::/96`) fängt `is_reserved` schon heute. Die übrigen `is_private`-Bereiche (etwa `192.0.0.0/24`, `198.18.0.0/15`) sind nur mit einem Netz der Liste erlaubt.
