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
Test-Löschung: apps/server/tests/test_notifications.py::test_email_names_only_the_server_of_its_subscription — die Kanäle kommen aus der Matrix, ein Bündel nennt die Server der Glocke; ersetzt durch test_every_channel_names_the_servers_of_the_bell; apps/server/tests/test_notifications.py::test_telegram_names_only_the_server_of_its_subscription — dasselbe Verhalten für Telegram, gedeckt durch test_every_channel_names_the_servers_of_the_bell; apps/server/tests/test_notifications.py::test_each_channel_names_the_servers_of_its_own_subscriptions — Kanäle je Abo gibt es nicht mehr, gedeckt durch test_every_channel_names_the_servers_of_the_bell; apps/server/tests/test_notifications.py::test_a_channel_without_a_server_gets_no_entry — umbenannt in test_a_member_channel_names_only_servers_they_may_see (ohne sichtbaren Server kein Eintrag); apps/server/tests/test_certificate_expiry_watch.py::test_only_admins_get_it_and_email_follows_their_subscription — umbenannt in test_only_admins_get_it_and_email_follows_their_matrix (die Matrix ersetzt das Häkchen)

### T2 — Server und Monitoring: SSRF-Sperre mit Opt-in für private Ziele (R-1080)  [x]
Komponente: server · Dateien: apps/server/app/core/ssrf.py, apps/monitoring/app/core/ssrf.py, apps/server/tests/test_ssrf.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @33a146925 2026-11-07T06:10:10+01:00
Review: approve (.ah-out/review/kern-notify-2/T2.verdict.json)
Änderung: `check_target(url, *, allow_networks=())` in beiden Kopien gleich (`test_ssrf_parity.py` verlangt identischen Code): eine private Adresse oder eine aus `100.64.0.0/10` ist erlaubt, wenn ein Netz der Liste sie enthält; Loopback, Link-Local (auch `169.254.169.254`), unspezifiziert, Multicast, reserviert und `0.0.0.0/8` bleiben gesperrt, auch als IPv4-mapped IPv6. Ohne das Argument ändert sich nichts (Hooks, Monitoring). Tests je Adressklasse mit und ohne Listeneintrag.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ssrf.py tests/test_ssrf_parity.py tests/test_ssrf_properties.py tests/test_ssrf_pin.py
Doku: → T7
Abhängt von: T1

### T3 — Server: Versand über ntfy, Telegram und Webhook mit SSRF-Sperre (R-1080)  [x]
Komponente: server · Dateien: apps/server/app/core/config.py, apps/server/app/modules/notifications/sender.py, apps/server/app/modules/notifications/outbox.py, apps/server/app/modules/notifications/incidents.py, .env.example, apps/server/tests/test_notification_channels.py, apps/server/tests/test_ssrf.py, apps/server/app/modules/notifications/models.py, apps/server/alembic/versions/f3a5c7e9b1d2_notification_settings.py, docker-compose.yml, apps/server/tests/test_notifications.py, apps/server/tests/test_notification_settings.py, apps/server/app/modules/notifications/router.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @f806090de 2026-11-07T06:39:26+01:00
Review: approve (.ah-out/review/kern-notify-2/T3.verdict.json)
Änderung: Vorher ntfy-Publish (Titel-Kodierung, `auth`) und Telegram `sendMessage` (Textlimit, `parse_mode`) in der offiziellen Doku nachlesen und die Belege unter `## Entscheidungen`. `TELEGRAM_BOT_TOKEN` und `NOTIFY_PRIVATE_TARGETS` (CIDR-Liste) in `config.py`. `drain_outbox` stellt `ntfy`, `telegram`, `webhook` zu (Format Spec), über `check_target(url, allow_networks=NOTIFY_PRIVATE_TARGETS)` (T2) und `pinned_client` ohne Redirects; ein gesperrtes Ziel ist sofort `failed`, sonst Backoff wie E-Mail; Logs und `last_error` ohne URL, Chat-ID, Token. `_queue` legt `ntfy`/`webhook` an und `telegram` nur mit Token. Tests mit `httpx.MockTransport`: Format je Kanal, Priorität, Kürzung, gesperrtes Ziel mit und ohne Listeneintrag, kein Redirect, kein Geheimnis im Log (`caplog`). Neue Datei mit SPDX-Header.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_channels.py tests/test_notifications.py tests/test_notification_settings.py tests/test_outbox.py
Doku: → T7
Abhängt von: T2

### T4 — Server: Test-Route je Kanal mit Sperre je Person (R-1080)  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/router.py, apps/server/app/modules/notifications/schemas.py, apps/server/tests/test_notification_prefs_test.py, apps/server/tests/openapi.snapshot.json, apps/server/app/modules/notifications/incidents.py, apps/server/tests/test_notification_incident_api.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @9c0765102 2026-11-07T06:54:42+01:00
Review: approve (.ah-out/review/kern-notify-2/T4.verdict.json)
Änderung: `POST /api/users/me/notification-prefs/test` mit `{"channel"}` (Spec): sofortiger Versand an das gespeicherte Ziel über die Sender aus T3, `200`/`409`/`422`/`502`/`429`, Sperre ein Test je Person und Kanal in zehn Sekunden über `app/core/rate_limit.py`, neutrale Fehlertexte. Prüft dabei, ob `RequestModel` alte Felder (`channel_email`) ablehnt, und hält das Ergebnis unter `## Entscheidungen` für T6 fest. Tests: jeder Status, die Sperre, kein Geheimnis in der Antwort; OpenAPI-Snapshot. Neue Datei mit SPDX-Header. Dazu (Review T3): `IncidentDetailOut.channels` und die Detailansicht des Vorfalls (`incidents.py`) nennen ntfy und Webhook neben E-Mail und Telegram (Spec, Betroffene Stellen), mit Test. Jede Ausnahme eines Senders wird in der Route neutral (`502`), nie ein `500` mit Traceback.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_prefs_test.py tests/test_notification_incident_api.py tests/test_openapi_snapshot.py
Doku: → T7
Abhängt von: T3

### T5 — Desktop-UI: Kanäle, Matrix und Kategorien in den Einstellungen, Toast-Gate (R-1080)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/NotificationPrefs.svelte, apps/desktop/ui/src/components/NotificationPrefs.test.ts, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/api/notifications.ts, apps/desktop/ui/src/lib/api/notifications.test.ts, apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/lib/stores/notifyPrefs.ts, apps/desktop/ui/src/lib/stores/notifyPrefs.test.ts, apps/desktop/ui/src/lib/stores/notifications.ts, apps/desktop/ui/src/components/AppShell.notifications.test.ts, apps/desktop/ui/src/lib/api/types.contract.test.ts, apps/desktop/ui/src/lib/i18n/i18n.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @4f1a1ef65 2026-11-07T07:31:09+01:00
Review: approve (.ah-out/review/kern-notify-2/T5.verdict.json)
Änderung: `NotificationPrefs.svelte` nach dem Mockup: Abschnitt Kanäle (Ziel, Schalter, Knopf Test; Desktop testet lokal, die übrigen über T4; ntfy- und Webhook-URL als Geheimnis maskiert; nicht `available` → Hinweis statt Test), Matrix Schweregrad × Kanal, Kategorien-Chips (`monitoring`, `security`, `tunnel`, `agent`); die Regeln ohne Kanal-Häkchen. `onNewNotifications` (`AppShell.svelte`) zeigt Toast und OS-Hinweis nur nach Matrix, Desktop-Schalter und Kategorie, ohne geladene Prefs wie heute. Typen ohne `any`, Texte DE+EN. Tests: Speichern schickt die neue Form, Test-Knopf und Fehlertext, Toast-Gate je Fall; `SettingsModal.workspace.test.ts` und weitere Aufrufer per `set-files`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: → T7
Abhängt von: T4

### T6 — Desktop-E2E und Test-Skripte: Prefs in der neuen Form (R-1080)  [x]
Komponente: desktop-e2e · Dateien: scripts/tests/sse_push_e2e.sh, scripts/tests/desktop_e2e_sse_push.sh, scripts/diagnostics.sh, scripts/tests/diagnostics_test.sh
Evidenz: run.sh[quick] desktop-e2e scripts: 7 passed, 0 failed, 11 skipped @01e772f2f 2026-11-07T07:52:35+01:00
Review: approve (.ah-out/review/kern-notify-2/T6.verdict.json)
Änderung: `ensureAllSubscription` (`live.js`) und die beiden SSE-Push-Skripte schicken Regeln ohne `channel_email`/`channel_telegram`; die Journeys laufen im Sammellauf (Heavy). Dazu (Review T3): `TELEGRAM_BOT_TOKEN` in `SECRET_KEYS` von `scripts/diagnostics.sh`, mit einem Fall in `diagnostics_test.sh`.
Verify: bash scripts/dev/verify.sh desktop-e2e scripts --strict
Doku: keine (Testcode; die Maskierung im Support-Bundle ist nicht einzeln dokumentiert)
Abhängt von: T1

### T7 — Doku und Changelog: Kanäle, Matrix, Kategorien, Env (R-1080)  [x]
Komponente: server · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/admin/betrieb.html, docs/en/admin/operations.html, docs/developer/server.html, docs/en/developer/server.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-notify-2.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @4c63d6917 2026-11-07T07:57:02+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Bedienung (Kanäle, Matrix, Kategorien, Test-Knopf), Betrieb (`TELEGRAM_BOT_TOKEN`, `NOTIFY_PRIVATE_TARGETS`, Sperre und Freigabe-Liste), Entwickler (Tabelle `notification_settings`, Outbox-Kanäle, Prefs-API und Test-Route samt Vertragsbruch der Abo-Felder) DE+EN; `changelog.d/kern-notify-2.md` (`### Added`, `### Changed`, umlautfrei). Vorher `python3 scripts/dev/doc-smoke.py --paths --env --strict`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_settings.py
Doku: alle oben DE+EN · changelog.d/kern-notify-2.md
Task-Review: am Ende
Abhängt von: T5


### T8 — Server: Drain stellt ein Ziel, das die Frist verfehlt, für den Rest des Laufs zurück (R-1080)  [ ]
Komponente: server · Dateien: apps/server/app/modules/notifications/sender.py, apps/server/app/modules/notifications/outbox.py, apps/server/tests/test_notification_channels.py
Änderung: Fund der Abschlussprüfung (security, Einzelheiten privat). `sender` meldet eine verfehlte Frist als eigene Unterklasse `SendTimeout(DeliveryFailed)`; `drain_outbox` merkt sich je Lauf (Kanal, Adresse) eines Eintrags mit `SendTimeout` und überspringt weitere Einträge mit demselben Ziel in diesem Lauf, ohne Versuch und ohne Änderung (sie kommen im nächsten Lauf). Test: zwei Einträge an ein tröpfelndes Ziel und einer an ein gutes; ein Lauf dauert eine Frist, der zweite Eintrag bleibt `pending` mit 0 Versuchen, der gute ist `sent`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_channels.py tests/test_outbox.py
Doku: docs/developer/server.html, docs/en/developer/server.html

### T9 — Desktop-UI: Vorfall-Detail zeigt ntfy mit Label (R-1080)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/models/notifications.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/lib/models/notifications.test.ts
Änderung: Nit der Abschlussprüfung: `CHANNELS` in `notifications.ts` kennt `ntfy` nicht, das Vorfall-Detail zeigt den Kanal roh; `ntfy` dazu, Schlüssel `notifications.channel.ntfy` DE+EN, Test für `channelLabel('ntfy')`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/models/notifications.test.ts src/lib/i18n/i18n.test.ts
Doku: keine (Label, kein dokumentiertes Verhalten)

### T10 — Doku: Kanäle im Vorfall-Detail und README (R-1080)  [ ]
Komponente: server · Dateien: docs/developer/api-reference.html, docs/en/developer/api-reference.html, README.md
Änderung: Funde der Abschlussprüfung: `channels` im Vorfall-Detail nennt seit T4 auch `ntfy` und `webhook` (DE+EN); die README-Zeile „Personal notifications“ nennt ntfy, Telegram und Webhook neben E-Mail und die Matrix.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_settings.py
Doku: alle oben DE+EN · README
Task-Review: am Ende

## Entscheidungen
- 2026-11-07 Planung: eigene Tabelle statt Spalten an `users`; Kanal-Schalter als Liste; ntfy-Zugang per `?auth=` in der URL; Webhook ohne Signatur; CGNAT unter dem Opt-in; fehlende neue Felder beim `PUT` behalten ihren Wert (Begründungen in der Spec).
- 2026-11-07 T1: `resolve_recipients` setzt neben `bell` den Schlüssel `out` (die Server des Kanaltexts, gleich `bell`); `_queue` legt ohne `out` nichts an, so bleibt `notify()`/`notify_users` glockenexklusiv, obwohl jetzt die Matrix der Person wählt.
- 2026-11-07 T1: Ein Bündel nennt in jedem Kanal die Server der Glocke (Spec, Routing); die Tests der Kanal-Server je Regel (`TestBundleChannels`, monitoring-alert-quality T18) folgen dieser Semantik: `test_telegram_names_only_the_server_of_its_subscription` und `test_each_channel_names_the_servers_of_its_own_subscriptions` entfallen (ersetzt durch `test_every_channel_names_the_servers_of_the_bell`), `test_a_channel_without_a_server_gets_no_entry` geht in `test_a_member_channel_names_only_servers_they_may_see` auf.
- 2026-11-07 T1: `RequestModel` verbietet keine Extra-Felder: ein altes `channel_email` in einer Regel wird still ignoriert (T4 bestätigt das für T6); `available.telegram` bleibt `false`, bis T3 `TELEGRAM_BOT_TOKEN` liest.
- 2026-11-07 T2: Kevin 2026-11-07: Die Freigabe privater Ziele ist eine CIDR-Liste `NOTIFY_PRIVATE_TARGETS` statt des Schalters `NOTIFY_ALLOW_PRIVATE_TARGETS`; nur die genannten Netze gehen auf, die harte Sperre liegt davor.
- 2026-11-07 T2: Die harte Sperre (`_always_blocked`) prüft auch die eingebettete IPv4 von 6to4 (`2002::/16`) und Teredo, sonst öffnete ein Listeneintrag wie `2002::/16` den Weg zu 169.254.169.254; sie gilt vor der Liste, auch für `0.0.0.0/0`. Dazu sperrt sie die Metadaten-Adressen außerhalb von Link-Local: `fd00:ec2::/32` (AWS IPv6), `fd20:ce::254` (GCP, nur IPv6), `100.100.100.200` (Alibaba). NAT64 (`64:ff9b::/96`) und IPv4-kompatible Adressen (`::/96`) fängt `is_reserved` schon heute. Die übrigen `is_private`-Bereiche (etwa `192.0.0.0/24`, `198.18.0.0/15`) sind nur mit einem Netz der Liste erlaubt.
- 2026-11-07 T3: Doku-Belege: ntfy (docs.ntfy.sh/publish) nimmt den Body als Nachricht, `X-Title` in UTF-8 oder RFC 2047, `X-Priority` 1–5, `?auth=` in der URL; ein Body über 4096 Bytes oder ohne gültiges UTF-8 wird zum Anhang, darum kürzt der Sender auf 4096 Bytes an einer Zeichengrenze. Telegram `sendMessage` (core.telegram.org/bots/api#sendmessage): `chat_id` und `text` Pflicht, „1-4096 characters after entities parsing“; ohne `parse_mode` geht der Text unverändert durch. Der Sender kürzt auf 4096 UTF-16-Einheiten (nicht verifiziert, ob Telegram so zählt; die konservative Lesart).
- 2026-11-07 T3: Ohne `TELEGRAM_BOT_TOKEN` legt `_queue` keine Telegram-Einträge an, und `drain_outbox` lässt vorhandene liegen (`pending`, kein Versuch): ein Token, das später kommt, stellt sie noch zu, solange das Outbox-Alter reicht (`test_skips_telegram_channel` bleibt).
- 2026-11-07 T3: Ein nicht auflösbarer Host (`UNRESOLVED`) ist ein Fehlversuch mit Backoff, kein gesperrtes Ziel; nur `PRIVATE` setzt den Eintrag sofort auf `failed`.
- 2026-11-07 T3: Ein ungültiger Eintrag in `NOTIFY_PRIVATE_TARGETS` (auch gesetzte Hostbits wie `192.168.1.5/16`) bricht den Start ab; enthält ein Netz eine Adresse des Hosts selbst, warnt der Start.
- 2026-11-07 T3: Die Outbox trägt die Stufe des Pings (`severity`, Migration f3a5, nullable): ntfy-Priorität und Webhook nehmen sie, alte Einträge die Stufe der Notification. `last_error` nennt bei einem unerwarteten Fehler nur Kanal und Typ (`_error_text`), bei `DeliveryFailed` dessen neutralen Text.
- 2026-11-07 T3 (Review): Jeder Versand liest nur den Status, nie den Body, und läuft in einem eigenen Daemon-Thread unter einer harten Frist von 30 s (`_SEND_DEADLINE`), denn der Timeout von httpx gilt je Leseoperation; bei Überschreitung schließt der Sender den Client (das beendet den Lesevorgang des Threads), der Versand ist ein Fehlversuch mit Backoff. Höchstens acht Versände ohne Antwort zugleich (`_SEND_MAX_INFLIGHT`, wie `ssrf._resolve`), darüber scheitert ein Versand sofort. Details privat.
- 2026-11-07 T3 (Review): `available.telegram` folgt `TELEGRAM_BOT_TOKEN`; `_warn_own_addresses` schlägt den eigenen Namen nur nach, wenn `NOTIFY_PRIVATE_TARGETS` Netze nennt; Telegram nennt einen Ping ohne eigenen Text nur einmal.
- 2026-11-07 T4: `RequestModel` verbietet keine zusätzlichen Felder (Pydantic-Standard `extra="ignore"`): `channel_email`/`channel_telegram` eines älteren Clients werden still ignoriert, kein `422` (Test `TestOldClients`). T6 entfernt sie trotzdem aus den Skripten, die Doku (T7) nennt das.
- 2026-11-07 T4: Die Test-Route antwortet `200` mit `{"channel"}`; `409` (nicht zustellbar oder kein Ziel) und `422` aus der Validierung zählen nicht gegen die Sperre, jeder Versandversuch schon (auch ein `502`). Ein abgeschalteter Kanal (`disabled_channels`) lässt sich testen: der Knopf prüft das Ziel, nicht die Weiterleitung. Text der Testnachricht englisch wie die übrigen Server-Texte.
- 2026-11-07 T4: Der Test der Vorfall-Kanäle steht in `test_notification_incident_api.py` neben dem bestehenden Detail-Test, nicht in `test_notification_incidents.py`; `sender.py` bleibt unverändert.
- 2026-11-07 T4 (Review): Höchstens ein laufender Test je Person (`_TESTS_RUNNING` im Prozess, geprüft vor dem Zähler), sonst `429`: ein Versand kann bis zur Frist von 30 s hängen, länger als die Sperre, und die Sender eines Prozesses teilen wenige Plätze. Details privat. Ein gesperrtes Ziel antwortet `422` mit Text in `detail`, die Validierung mit einer Liste: T5 liest beide Formen, T7 nennt es in der API-Doku.
- 2026-11-07 T5: Das Toast-Gate liegt im eigenen Store `lib/stores/notifyPrefs.ts` (`desktopWants`), geladen beim Start der Benachrichtigungen, verworfen beim Stopp und nach dem Speichern ersetzt; ohne geladene Kanaleinstellungen (Ladefehler, Server ohne Matrix) kommt alles wie bisher; ein Abruf, der nach Abmelden, Speichern oder einem neueren Abruf antwortet, setzt nichts (Generationszähler, Review). Ein Eintrag mit `state: resolved` folgt der Zeile `ok`, sonst seiner Stufe.
- 2026-11-07 T5: Der Test-Knopf ist bei einem ungespeicherten Ziel gesperrt (der Server testet das gespeicherte Ziel), ein abgeschalteter Kanal bleibt testbar (wie T4); ein Kanal, den der Server nicht zustellen kann (`available`), zeigt einen Hinweis statt des Knopfs. Der Desktop testet lokal (Toast, OS-Hinweis nur mit Opt-in). Fehlertexte kommen über `errMsg`: der Rust-Proxy liest `detail` als Text und als Liste (`error.rs`), daher keine eigene Behandlung der 422-Formen in der UI.
- 2026-11-07 T6: `ensureAllSubscription` (`live.js`) schickte die Kanalfelder schon nicht mehr und bleibt unverändert (aus `Dateien:` gestrichen). `TELEGRAM_BOT_TOKEN` steht in `SECRET_KEYS`; der Testfall prüft den Wert mit Doppelpunkt in einer Bot-URL (Gegenprobe: ohne den Schlüssel `LEAK`).
