<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-notify-6 — Benachrichtigungs-Kanäle und Mail-Design im Admin-Panel

Zug: R-1527 (BUG), R-1531 (FEAT), R-1533 (FEAT).

## Problem / Motivation

- **R-1531:** SMTP-Relay (Host, Port, User, Passwort, Absender), Telegram-Bot-Token und `NOTIFY_PRIVATE_TARGETS`
  stehen heute nur in der `.env` (`apps/server/app/core/config.py:326`–`:382`, `apps/monitoring/app/core/config.py:74`);
  jede Änderung heißt `.env` bearbeiten und `docker compose up -d` für server, scheduler und monitoring. Bei einer
  Neuinstallation (Kevin 2026-11-17) ist das die Hürde vor der ersten Meldung.
- **R-1533:** Mails sind reiner Text mit festem Betreff (`[AdminHelper Monitor] …` in
  `apps/monitoring/app/alerter.py:716`, `:728`, `apps/monitoring/app/alert_bundle.py:87`, `:95`, `:395`; der Titel
  der Meldung im Hub, `notifications/outbox.py`, `digest.py`). Gewünscht ist eine anpassbare Vorlage.
- **R-1527:** Der Docstring von `_send_test` (`notifications/router.py:590`) sagt „every error becomes a neutral
  HTTPException“, das gesperrte Ziel wird aber ein `RequestValidationError` (422); die API-Referenz
  (`docs/developer/api-reference.html:265`, EN ebenso) soll das gesperrte Ziel ausdrücklich als Versandversuch nennen,
  der gegen das 10-s-Limit zählt.

## Ziel & Nicht-Ziele

Ziel:
1. Admins pflegen SMTP-Relay, Telegram-Token und private Ziel-Netze im Web-Admin. Passwort und Token sind
   **write-only** (die API meldet nur „gesetzt“), Test-Versand je Kanal. Gilt für server, scheduler und monitoring
   ohne Neustart. **`.env` bleibt Rückfall:** je Feld gilt der Panel-Wert, wenn gesetzt, sonst die Variable; nur User und
   Passwort gehören zum Relay: steht der Host im Panel, gelten sie nur aus dem Panel.
2. Admins gestalten die Mails mit einer **freien Vorlage** (Kevin 2026-11-18): Betreff-Präfix, Absendername,
   HTML-Teil, Text-Alternative, optional ein Logo (inline eingebettet). Platzhalter, Vorschau, Test-Versand.
   Gilt für Hub-Mails (Outbox, Digest, Test) **und** die Mails der Monitoring-Alert-Regeln (Kevin 2026-11-18).
3. Ohne Panel-Eintrag ändert sich nichts: gleiche Relay-Werte, gleiche Betreffe, reiner Text wie heute.

Nicht-Ziele (YAGNI): `SMTP_CA_FILE` bleibt Datei-Mount per `.env` (Pfad im Container, kein Upload); keine Logik in
der Vorlage (keine Schleifen, Bedingungen, Filter); kein eigenes Design je Empfänger oder Kategorie; SMTP je
Monitoring-Regel bleibt, wie er ist, bis die Monitoring-Neuordnung ihn ablöst (`monitoring-next`-Programm); kein
Desktop-UI (das Admin-Panel ist die Web-App).

## Betroffene Komponenten & Dateien

- **Server** (`apps/server`): neu `app/core/secretbox.py` (AES-GCM, Schlüssel per HKDF aus `SECRET_KEY`), neu
  `app/modules/notifications/channel_config.py` (Auflöser Panel vor `.env`, ohne Cache), neu
  `app/modules/notifications/mail_template.py` (Platzhalter-Renderer, Standardvorlage), neu
  `app/modules/notifications/admin_router.py` (Admin-Routen); geändert `models.py`, `schemas.py`, `sender.py`,
  `outbox.py`, `digest.py`, `escalation.py`, `incidents.py`, `router.py` (`_available`, `_send_test`, internes
  Config-Endpoint), `app/main.py` (Router), zwei Alembic-Migrationen.
- **Monitoring** (`apps/monitoring`): neu `app/notify_config.py` (holt die wirksame Konfiguration beim Hub, Cache,
  Rückfall `.env`), neu `app/mail_template.py` (Kopie des Renderers mit Paritäts-Fixtures); geändert `alerter.py`
  (`_send_email`, Betreffe), `alert_bundle.py` (Betreffe).
- **Web** (`apps/web`): neu `src/pages/Notifications.svelte` (Abschnitte Kanäle und Mail-Design), `src/lib/api/notify.ts`,
  Typen in `src/lib/api/types.ts`, Route in `src/routes.ts`, Eintrag in `Sidebar.svelte`, Texte in
  `src/lib/i18n/dictionaries.ts`.
- **Betrieb/Doku:** `.env.example`, `docker-compose.yml` (Kommentare), `docs/admin/betrieb.html` +
  `docs/en/admin/operations.html`, `docs/admin/monitoring.html` + EN, `docs/developer/api-reference.html` + EN,
  `docs/developer/server.html` + EN, `changelog.d/kern-notify-6.md`.

## Datenmodell / API / Migrationen

- Tabelle `notify_channel_config` (eine Zeile, `id = 1`): `smtp_host`, `smtp_port`, `smtp_user`,
  `smtp_password_enc` (bytes, AES-GCM: Nonce ‖ Chiffrat), `smtp_from`, `telegram_token_enc`, `private_targets` (Text,
  CIDR-Liste), `updated_at`, `updated_by`. `NULL` = „nicht gesetzt, `.env` gilt“.
- Tabelle `notify_mail_template` (eine Zeile): `subject_prefix`, `from_name`, `html`, `text`, `logo` (bytes),
  `logo_type` (`image/png` | `image/jpeg`), `updated_at`, `updated_by`. Keine Zeile = Standard wie heute.
- Admin-API (nur Admins, Audit ohne Geheimnisse):
  `GET/PUT /api/admin/notify/channels` (Passwort/Token: Feld fehlt oder `null` = behalten, `""` = löschen; Antwort
  `passwordSet`/`tokenSet` und je Feld die Quelle `panel` | `env` | `none`),
  `POST /api/admin/notify/channels/test` (`{channel: email|telegram, target}`, Limit wie der persönliche Test),
  `GET/PUT/DELETE /api/admin/notify/template`, `POST /api/admin/notify/template/preview` (gerenderter Betreff,
  HTML, Text mit Beispieldaten; ungespeicherte Vorlage), `POST /api/admin/notify/template/test`,
  `PUT/DELETE /api/admin/notify/template/logo` (PNG/JPEG, ≤ 200 KB).
- Intern: `GET /api/internal/notify-config` (X-Internal-Key wie `/api/internal/events`): wirksame SMTP-Werte samt
  Passwort und die Vorlage für das Monitoring. Monitoring cacht 60 s; ist der Hub nicht erreichbar, gilt der letzte
  gute Stand, ohne einen die `.env`.
- Platzhalter: `{{title}}`, `{{body}}`, `{{severity}}`, `{{category}}`, `{{time}}`, `{{source}}`, `{{logo}}`
  (`cid:logo` in der Mail, `data:`-URL in der Vorschau). Im HTML-Teil HTML-escaped (`body` mit `<br>` für
  Zeilenumbrüche), im Text roh. Unbekannter Platzhalter → 422 beim Speichern. Kein Template-Engine-Paket
  (keine neue Abhängigkeit): reine Ersetzung, damit kein Code aus der Vorlage läuft.
- Kein Vertrags-Drift zum Desktop (er nutzt diese Admin-Routen nicht); Web-Typen neu, `sync-from-web.sh --check`
  im PR.

## Externe Integrationen

SMTP (stdlib `smtplib`, `email.mime` multipart/related + alternative für das Inline-Logo: RFC 2387, RFC 2046),
Telegram Bot API `sendMessage` (unverändert, nur die Token-Quelle). Keine neuen Wire-Formate.

## Trade-offs & Alternativen

- Geheimnisse verschlüsselt mit Schlüssel aus `SECRET_KEY` (Kevin 2026-11-18) statt Klartext: ein DB-Dump verrät
  nichts. Wechselt `SECRET_KEY`, ist der Wert unlesbar → Rückfall `.env`, Warnung im Panel („neu eintragen“).
- Monitoring holt die Konfiguration beim Hub (ein internes GET, Cache) statt seine Regel-Mails über den Hub zu
  schicken: die Regel-Mail behält ihr Ergebnis im AlertLog und den eigenen Relay je Regel; das Passwort geht über
  denselben TLS-Weg wie heute der Internal-Key. Alternative „Hub versendet“ hätte Ergebnis-Rückmeldung und SMTP je
  Regel neu gebraucht.
- Renderer als Kopie im Monitoring (Präzedenz: `_SUBJECT_TO_SPACE` in beiden Diensten) mit gemeinsamen
  Paritäts-Fixtures in beiden Testsuiten statt eines geteilten Pakets.
- Freie Vorlage mit reiner Platzhalter-Ersetzung statt Jinja: Kevins Wunsch „frei“ ist erfüllt (beliebiges HTML),
  ohne Sandbox-Risiko und ohne neue Abhängigkeit.

## Risiken & Rollback

- `NOTIFY_PRIVATE_TARGETS` öffnet Netze für ntfy/Webhooks (SSRF-Freigabe); im Panel nur für Admins, Audit, gleiche
  CIDR-Prüfung wie beim Start. Leere Liste im Panel = `.env` gilt (nicht „alles zu“); „alles zu“ trotz `.env` heißt
  Variable entfernen — so bleibt der Rückfall eindeutig.
- HTML der Vorlage stammt vom Admin; die Web-Vorschau rendert im `iframe sandbox` ohne Skripte. Werte aus Meldungen
  werden escaped (Meldungstexte können von Agents stammen).
- Rollback: Migrationen haben `downgrade`; ohne Panel-Zeilen verhält sich alles wie vor dem Zug.
- Risikopfade: Migrationen, `secretbox.py`, internes Endpoint mit Geheimnissen → `security` je Task.

## Doku-Impact

Betrieb (DE+EN): Kanäle im Panel, Vorrang Panel vor `.env`, `SECRET_KEY`-Wechsel; Monitoring (DE+EN): Regel-Mails
nehmen zentralen Relay und Vorlage; API-Referenz (DE+EN): Admin-Routen, R-1527-Satz; Entwickler/Server: internes
Endpoint; `.env.example` und Compose-Kommentare; `changelog.d/kern-notify-6.md`.

## Offene Fragen

Keine; Kevins Antworten 2026-11-18: verschlüsselt, freie Vorlage, gilt für Hub und Monitoring-Regeln.
