<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-notify-6 — Benachrichtigungs-Kanäle und Mail-Design im Admin-Panel — Task-Ledger
Status: aktiv · Branch: feature/kern-notify-6 · Review: pro Task
Spec: docs/features/kern-notify-6.md (Roadmap R-1527, R-1531, R-1533)
Heavy: linux-full — neue Server-API und Migrationen, internes Endpoint server↔monitoring, Alerter-Mailweg; kein Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1527: _send_test-Docstring und API-Referenz zum gesperrten Ziel  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/router.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html, tasks/kern-notify-6.md, apps/server/tests/test_notification_prefs_test.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @3757b7deb 2026-11-18T12:22:36+01:00
Review: approve (.ah-out/review/kern-notify-6/T1.verdict.json)
Änderung: Docstring von `_send_test` (`router.py:590`) nennt neben der neutralen HTTPException den 422
(`RequestValidationError`) für ein von der SSRF-Sperre abgewiesenes Ziel. API-Referenz `:265` DE+EN sagt
ausdrücklich, dass das gesperrte Ziel ein Versandversuch ist und gegen das 10-s-Limit zählt. Kein Verhalten neu.
Beweis: reviewer kern-server-10 2026-11-16 @f8f701c3f (Nit)
Dedup-Key: bug:server:notifications/router.py:_send_test
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_prefs_test.py
Doku: docs/developer/api-reference.html, docs/en/developer/api-reference.html

### T2 — R-1531: Kanal-Konfiguration in der DB, verschlüsselt, Panel vor .env  [x]
Komponente: server · Dateien: apps/server/app/core/secretbox.py, apps/server/app/modules/notifications/channel_config.py, apps/server/app/modules/notifications/models.py, apps/server/alembic/versions/c4e8a1f2b3d5_notify_channel_config.py, apps/server/app/modules/notifications/sender.py, apps/server/app/modules/notifications/outbox.py, apps/server/app/modules/notifications/escalation.py, apps/server/app/modules/notifications/incidents.py, apps/server/app/modules/notifications/router.py, apps/server/tests/test_notify_channel_config.py, tasks/kern-notify-6.md, apps/server/app/modules/notifications/digest.py, apps/server/tests/test_email_sender.py, apps/server/tests/test_notification_channels.py, apps/server/tests/test_notification_escalation.py, docs/features/kern-notify-6.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @1f6886f04 2026-11-18T12:48:25+01:00
Review: approve (.ah-out/review/kern-notify-6/T2.verdict.json)
Änderung: `secretbox.py` (AES-GCM, Schlüssel per HKDF-SHA256 aus `SECRET_KEY`, Nonce ‖ Chiffrat; unlesbar →
`None` + Log-Warnung). Tabelle `notify_channel_config` (eine Zeile, Spec „Datenmodell“) mit Migration samt
`downgrade`. `channel_config.py` liefert die wirksamen Werte je Feld (Panel, wenn gesetzt, sonst `.env`) und ihre
Quelle, ohne Cache; kommt der Relay-Host aus dem Panel, gelten User und Passwort nur aus dem Panel. Alle Leser von `SMTP_*`, `TELEGRAM_BOT_TOKEN` und
`NOTIFY_PRIVATE_TARGETS` (sender, outbox, escalation, incidents, `router._available`) lesen über den Auflöser.
Tests: Vorrang je Feld, Rückfall nach Schlüsselwechsel, Chiffrat ≠ Klartext in der DB, Migration hin und zurück.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notify_channel_config.py tests/test_notification_channels.py tests/test_notification_prefs_test.py tests/test_migrations_smoke.py tests/test_email_sender.py tests/test_outbox.py tests/test_notification_escalation.py tests/test_notification_digest.py tests/test_notifications.py tests/test_notification_settings.py
Doku: → T10

### T3 — R-1531: Admin-API für die Kanäle mit Test-Versand  [ ]
Komponente: server · Dateien: apps/server/app/modules/notifications/admin_router.py, apps/server/app/modules/notifications/schemas.py, apps/server/app/main.py, apps/server/tests/test_notify_admin_channels.py, apps/server/tests/openapi.snapshot.json, tasks/kern-notify-6.md
Änderung: `GET/PUT /api/admin/notify/channels` und `POST /api/admin/notify/channels/test` nur für Admins (Spec
„Datenmodell / API“): Passwort und Token write-only (fehlt/`null` behalten, `""` löschen), Antwort mit
`passwordSet`/`tokenSet` und Quelle je Feld, Warnung bei unlesbarem Chiffrat; CIDR-Prüfung wie beim Start; Port
1–65535; Audit-Eintrag ohne Geheimnis; Test-Versand an eine angegebene Adresse/Chat-ID mit Limit und neutralen
Fehlern wie der persönliche Test. OpenAPI-Snapshot nachgezogen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notify_admin_channels.py tests/test_openapi_snapshot.py
Doku: → T10

### T4 — R-1533: Mail-Vorlage, Renderer und HTML-Versand im Hub  [ ]
Komponente: server · Dateien: apps/server/app/modules/notifications/mail_template.py, apps/server/app/modules/notifications/models.py, apps/server/alembic/versions/d7b2e4c6a8f0_notify_mail_template.py, apps/server/app/modules/notifications/sender.py, apps/server/app/modules/notifications/outbox.py, apps/server/app/modules/notifications/digest.py, apps/server/app/modules/notifications/router.py, apps/server/tests/test_notify_mail_template.py, apps/server/tests/fixtures/mail_template_parity.json, tasks/kern-notify-6.md
Änderung: Tabelle `notify_mail_template` (eine Zeile) mit Migration. `mail_template.py`: Platzhalter-Ersetzung
(Spec „Platzhalter“; HTML-escaped im HTML-Teil, roh im Text; unbekannter Platzhalter = Fehler), Standard ohne
Zeile = heutiger Text und Betreff. `send_email` baut bei gesetzter Vorlage multipart/alternative (Text + HTML),
mit Logo multipart/related mit `Content-ID: <logo>`; `From` mit Absendername; Betreff-Präfix. Outbox, Digest und
persönlicher Test senden über die Vorlage. Paritäts-Fixtures (Eingaben → erwartete Ausgabe) als JSON, die T7
im Monitoring wiederverwendet.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notify_mail_template.py tests/test_notification_digest.py tests/test_notifications.py tests/test_migrations_smoke.py
Doku: → T10

### T5 — R-1533: Admin-API für die Vorlage mit Vorschau, Logo und Test  [ ]
Komponente: server · Dateien: apps/server/app/modules/notifications/admin_router.py, apps/server/app/modules/notifications/schemas.py, apps/server/tests/test_notify_admin_template.py, apps/server/tests/openapi.snapshot.json, tasks/kern-notify-6.md
Änderung: `GET/PUT/DELETE /api/admin/notify/template`, `POST …/template/preview` (ungespeicherte Vorlage,
Beispieldaten, Logo als `data:`-URL), `POST …/template/test`, `PUT/DELETE …/template/logo` (PNG/JPEG per
Magic-Bytes, ≤ 200 KB). Größengrenzen für HTML/Text, 422 bei unbekanntem Platzhalter, Audit. OpenAPI-Snapshot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notify_admin_template.py tests/test_openapi_snapshot.py
Doku: → T10

### T6 — R-1531/R-1533: internes Endpoint für das Monitoring  [ ]
Komponente: server · Dateien: apps/server/app/modules/notifications/router.py, apps/server/app/modules/notifications/schemas.py, apps/server/tests/test_notify_internal_config.py, apps/server/tests/openapi.snapshot.json, tasks/kern-notify-6.md
Änderung: `GET /api/internal/notify-config` hinter `require_internal_key`: wirksame SMTP-Werte samt Passwort
(nur hier entschlüsselt herausgegeben) und die Vorlage (Logo base64) oder `null` für den Standard. Tests: 403 ohne
bzw. mit falschem Key, Inhalt bei Panel- und bei `.env`-Werten, kein Geheimnis in Logs.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notify_internal_config.py tests/test_openapi_snapshot.py
Doku: → T10

### T7 — R-1531/R-1533: Monitoring nimmt zentralen Relay und Vorlage  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/notify_config.py, apps/monitoring/app/mail_template.py, apps/monitoring/app/alerter.py, apps/monitoring/app/alert_bundle.py, apps/monitoring/tests/test_notify_config.py, apps/monitoring/tests/test_mail_template_parity.py, apps/monitoring/tests/fixtures/mail_template_parity.json, apps/monitoring/tests/test_alerter.py, tasks/kern-notify-6.md
Änderung: `notify_config.py` holt `/api/internal/notify-config` (60 s Cache, bei Fehler der letzte gute Stand,
ohne einen die `.env`). `_send_email` nimmt für Regeln ohne eigenen Relay die zentralen SMTP-Werte, für alle Regeln
die Vorlage; ohne Vorlage bleiben Betreff `[AdminHelper Monitor] …` und reiner Text. `mail_template.py` ist die
Kopie des Server-Renderers; der Paritätstest fährt dieselben Fixtures (Kopie der Server-Datei, Test prüft
Gleichheit beider Dateien nicht, sondern die Ausgaben).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_notify_config.py tests/test_mail_template_parity.py tests/test_alerter.py tests/test_alert_bundle.py
Doku: → T10

### T8 — R-1531: Web-Admin-Seite Benachrichtigungen, Abschnitt Kanäle  [ ]
Komponente: web · Dateien: apps/web/src/pages/Notifications.svelte, apps/web/src/pages/Notifications.test.ts, apps/web/src/lib/api/notify.ts, apps/web/src/lib/api/types.ts, apps/web/src/routes.ts, apps/web/src/lib/components/layout/Sidebar.svelte, apps/web/src/lib/i18n/dictionaries.ts, tasks/kern-notify-6.md
Änderung: Neue Admin-Seite `/notifications` (SPDX-Header in neuen Dateien): SMTP-Felder, Passwort/Token als
write-only (Platzhalter „gesetzt“, Löschen ausdrücklich), private Netze, Quelle je Feld (`aus .env`), Warnung bei
unlesbarem Geheimnis, Test-Versand je Kanal. Komponenten aus `components/ui`, DE+EN-Texte.
Verify: bash scripts/dev/verify.sh web --strict -- src/pages/Notifications.test.ts
Doku: → T10

### T9 — R-1533: Web-Abschnitt Mail-Design mit Vorschau  [ ]
Komponente: web · Dateien: apps/web/src/pages/Notifications.svelte, apps/web/src/pages/Notifications.test.ts, apps/web/src/lib/api/notify.ts, apps/web/src/lib/api/types.ts, apps/web/src/lib/i18n/dictionaries.ts, tasks/kern-notify-6.md
Änderung: Abschnitt Mail-Design: Betreff-Präfix, Absendername, HTML- und Text-Editor (Textarea), Platzhalter-Liste,
Logo hoch/löschen, Vorschau in `<iframe sandbox>` (ohne `allow-scripts`) über das Preview-Endpoint, Test-Versand,
Zurücksetzen auf Standard.
Verify: bash scripts/dev/verify.sh web --strict -- src/pages/Notifications.test.ts
Doku: → T10

### T10 — Doku DE+EN, .env.example, Compose-Kommentare, CHANGELOG  [ ]
Komponente: server · Dateien: docs/admin/betrieb.html, docs/en/admin/operations.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/developer/server.html, docs/en/developer/server.html, .env.example, docker-compose.yml, changelog.d/kern-notify-6.md, tasks/kern-notify-6.md
Änderung: Betrieb: Kanäle im Panel, Vorrang Panel vor `.env`, Verhalten nach `SECRET_KEY`-Wechsel, Mail-Vorlage
und Platzhalter. Monitoring: Regel-Mails mit zentralem Relay und Vorlage. API-Referenz: Admin-Routen und internes
Endpoint. `.env.example`/Compose: Variablen sind Rückfall. CHANGELOG Added/Fixed.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_openapi_snapshot.py
Doku: docs/admin/betrieb.html, docs/en/admin/operations.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/developer/server.html, docs/en/developer/server.html, changelog.d/kern-notify-6.md

## Entscheidungen
- 2026-11-18 Plan: Kevin — Geheimnisse verschlüsselt (Schlüssel aus SECRET_KEY), freie HTML-Vorlage, gilt für Hub- und Monitoring-Regel-Mails.
- 2026-11-18 Plan: Platzhalter-Ersetzung statt Template-Engine — keine Code-Ausführung aus der Vorlage, keine neue Abhängigkeit.
- 2026-11-18 Plan: Monitoring holt die Konfiguration per internem GET (Cache 60 s) statt über den Hub zu versenden — Regel-Ergebnis im AlertLog und SMTP je Regel bleiben.
- 2026-11-18 T2: Login gehört zum Relay — kommt `smtp_host` aus dem Panel, gelten `smtp_user`/`smtp_password` nur aus dem Panel (sonst kein Login), nie aus `.env`; Port, Absender, Netze fallen weiter je Feld zurück (security-Fund T2, Abweichung von „je Feld“ der Spec, Spec nachgezogen).
- 2026-11-18 T2: Auflöser ohne Cache — eine Zeile per Primärschlüssel je Aufruf, immer aktuell; kein Invalidieren beim Schreiben nötig (T3).
