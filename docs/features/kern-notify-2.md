# kern-notify-2: Kanäle ntfy, Telegram und Webhook, Matrix Schweregrad × Kanal, Kategorien

Roadmap: R-1080 (Zug `tasks/kern-notify-2.md`). Vorlage: Design-Mockup `AdminCave/DesignSystem@244e890`,
`ui_kits/adminhelper/notifications.jsx` (`NotifySettings`).

## Problem / Motivation

Heute stellt der Notification-Hub außer der Glocke nur E-Mail zu:
- `drain_outbox` (`apps/server/app/modules/notifications/outbox.py:35`) holt nur Zeilen mit `channel == "email"`
  (Zeile 42).
- Telegram hat ein Abo-Feld (`channel_telegram`) und die Chat-ID am Nutzer, wird aber nie versendet: die Einträge
  bleiben in der Outbox liegen.
- ntfy und Webhook gibt es für Personen gar nicht.

Welcher Kanal was bekommt, steht als zwei Häkchen an jeder Regel (`NotificationSubscription.channel_email` /
`channel_telegram`, `models.py:40`). Das Mockup ordnet stattdessen je Person Schweregrad und Kanal in einer Matrix zu
(„Die Glocke bekommt immer alles“), hat je Kanal einen Test-Knopf und einen Schalter, und Kategorien, die man
ausschalten kann („Ausgeschaltete Kategorien landen nur noch im Center, ohne Pop-up“).

Kevin hat am 2026-11-07 entschieden (Notiz an R-1080):
- Kanal-Ziele gelten **je Person**, wie E-Mail und Chat-ID heute.
- Der Telegram-Bot-Token kommt aus der Env-Variable `TELEGRAM_BOT_TOKEN`.
- ntfy- und Webhook-Ziele sind gesperrt wie der Monitoring-Webhook: privat, Loopback, Link-Local, Metadaten, keine
  Redirects. `NOTIFY_ALLOW_PRIVATE_TARGETS=true` gibt private Ziele frei; Loopback und Metadaten bleiben gesperrt.
- Die Matrix Schweregrad × Kanal je Person ersetzt `channel_email`/`channel_telegram` der Abos. Eine Datenmigration
  übernimmt die Häkchen (Kanal an für Schweregrade ≥ `min_severity`); die API-Felder fallen weg.

## Ziel & Nicht-Ziele

**Ziele**
- Kanäle je Person: Desktop, E-Mail, ntfy, Telegram, Webhook. Je Kanal ein Ziel (E-Mail-Adresse, ntfy-Topic-URL,
  Telegram-Chat-ID, Webhook-URL; Desktop braucht keins) und ein Schalter an/aus, der das Ziel behält.
- Matrix je Person: Zeilen `critical`, `warning`, `info`, `ok` (Entwarnung), Spalten die fünf Kanäle. Die Glocke ist
  keine Spalte: sie bekommt alles, was eine Regel trifft.
- Kategorien je Person ausschalten: ein Eintrag einer ausgeschalteten Kategorie landet nur in der Glocke, ohne
  Desktop-Pop-up und ohne externen Kanal.
- Versand für ntfy, Telegram und Webhook über die vorhandene Outbox, mit Backoff und `NOTIFICATION_MAX_ATTEMPTS`
  wie bei E-Mail.
- Test-Knopf je Kanal: schickt eine Testnachricht an das gespeicherte Ziel und meldet Erfolg oder Fehler.

**Nicht-Ziele**
- Mehr als ein Ziel je Kanal (Knopf „+ Kanal“ im Mockup). Je Typ ein Ziel deckt Kevins Entscheidung „je Person“.
- Ruhezeiten, Eskalation, Bündeln, Ton, Zusammenfassung (Abschnitt „Ruhe, Eskalation & Bündeln“): R-1081
  (`tasks/kern-notify-3.md`).
- Kategorien, die der Server heute nicht erzeugt (`backup`, `ansible`, `session` im Mockup). Angezeigt werden die,
  die er sendet: `monitoring`, `security`, `tunnel`, `agent`.
- Die `categories` der einzelnen Regel bleiben, wie sie sind (sie filtern, ob eine Regel überhaupt trifft).
- Das Web-Frontend: es hat keine Benachrichtigungs-Einstellungen.
- Ein Bot-Token je Person oder Telegram-Gruppen per Bot-Kommando einrichten.

## Betroffene Komponenten & Dateien

**Server (`apps/server/`)**
- `app/modules/notifications/models.py`: neue Tabelle `notification_settings`; `channel_email`/`channel_telegram`
  verlassen `NotificationSubscription`.
- `alembic/versions/<neu>_notification_settings.py`: Tabelle, Datenmigration, Spalten entfernen.
- `app/modules/notifications/service.py`:
  - `resolve_recipients` (Zeile 120) liefert nur noch die Glocke mit ihren Servern.
  - `default_admin_subscription` (Zeile 101) ohne Kanal-Felder.
- `app/modules/notifications/incidents.py`: `_queue` (Zeile 487) wählt die Kanäle aus Matrix, Schaltern,
  ausgeschalteten Kategorien und den gespeicherten Zielen, nach dem Schweregrad des Pings (`ok` für die Entwarnung).
- `app/modules/notifications/outbox.py` und `sender.py`: Versand für `ntfy`, `telegram`, `webhook`.
- `app/core/ssrf.py`: `check_target(url, *, allow_private=False)`; dieselbe Änderung in `apps/monitoring/app/core/ssrf.py`, weil `tests/test_ssrf_parity.py` beide Kopien gleich verlangt (das Monitoring ruft ohne das Argument, sein Verhalten bleibt).
- `app/core/config.py`: `TELEGRAM_BOT_TOKEN`, `NOTIFY_ALLOW_PRIVATE_TARGETS`.
- `app/modules/notifications/schemas.py` und `router.py`:
  - Prefs-API neu (`NotificationPrefsUpdate` Zeile 147, `SubscriptionInput` Zeile 124, `_prefs_response` Zeile 350).
  - `IncidentDetailOut.channels` (Zeile 241) um `ntfy`, `webhook` erweitert.
  - Neue Route `POST /api/users/me/notification-prefs/test`.
- Tests unter `tests/`: unter anderem `test_notifications.py`, `test_notification_category_migration.py`,
  `test_cli.py`, `test_bootstrap.py`, `test_users.py`, `test_certificate_expiry_watch.py` und
  `openapi.snapshot.json`.
- `.env.example`: Abschnitt neben SMTP.

**Desktop-UI (`apps/desktop/ui/src/`)**
- `components/NotificationPrefs.svelte`: Abschnitte Kanäle, Matrix und Kategorien nach dem Mockup. Die Regeln
  (Bereich, Mindest-Schweregrad, Kategorien) bleiben, ohne Kanal-Häkchen.
- `lib/api/types.ts`, `lib/api/notifications.ts`.
- `components/AppShell.svelte` (`onNewNotifications`, Zeile 228): Toast und OS-Hinweis nur, wenn die Matrix den
  Desktop für den Schweregrad hat, der Desktop-Schalter an ist und die Kategorie nicht ausgeschaltet ist.
- `lib/i18n/dictionaries.ts` und die Tests der Settings.

**Desktop-E2E und Test-Skripte**
- `apps/desktop/e2e/test/lib/live.js` (`ensureAllSubscription`, Zeile 204).
- `scripts/tests/sse_push_e2e.sh` und `scripts/tests/desktop_e2e_sse_push.sh`: Sie schicken heute
  `channel_email`/`channel_telegram`.

## Datenmodell / API / Migrationen

**Tabelle `notification_settings`** (eine Zeile je Person, `user_id` Primärschlüssel, FK auf `users` mit
`ON DELETE CASCADE`):
- `ntfy_url`, `webhook_url` (Text, nullable).
- `matrix`: JSON-Text `{"critical": [...], "warning": [...], "info": [...], "ok": [...]}`, Werte aus `desktop`,
  `email`, `ntfy`, `telegram`, `webhook`.
- `disabled_channels`: JSON-Text, Liste von Kanälen, deren Schalter aus ist.
- `muted_categories`: JSON-Text, Liste von Kategorien.

E-Mail-Adresse und Telegram-Chat-ID bleiben, wo sie sind (`users.email`, `users.telegram_chat_id`).

Ohne Zeile gilt die Vorgabe: Desktop in allen vier Zeilen, sonst nichts. Das ist das heutige Verhalten (Toasts für
alles, externe Kanäle opt-in).

**Datenmigration** (je Person mit Regeln):
- Für `email` und `telegram`: Der Kanal steht in Zeile `s` (`info`/`warning`/`critical`), wenn eine aktive Regel mit
  dem Häkchen `min_severity ≤ s` hat. In Zeile `ok` steht er, wenn er in irgendeiner Zeile steht: Heute bekommt die
  Entwarnung den Kanal der Regel, die das Problem gemeldet hat.
- `desktop` in allen vier Zeilen.
- Danach entfallen `channel_email` und `channel_telegram`.
- Downgrade: Spalten zurück; das Häkchen ist gesetzt, wenn der Kanal in einer Zeile der Matrix steht. Die Tabelle
  entfällt. Der Downgrade ist verlustbehaftet (die Matrix ist feiner als die Häkchen), so wie Kevins Entscheidung es
  hinnimmt.

**Wechsel im Routing.** Heute wirkt ein Häkchen nur für die Server seiner Regel. Künftig trifft eine Regel die
Person, und die Matrix der Person wählt die Kanäle für alle getroffenen Server. Ein Bündel nennt in jedem Kanal die
Server der Glocke. Das folgt aus „Matrix ersetzt Häkchen“; die Migration bildet es so nah ab, wie es geht.

**Unbekannter Schweregrad:** wie heute zur Zustellung hin; die Zeile `critical` gilt.

**Prefs-API (`/api/users/me/notification-prefs`, Vertragsbruch auf Kevins Wort):**
- `GET` liefert:
  - `email`, `telegramChatId`, `ntfyUrl`, `webhookUrl`
  - `matrix`, `disabledChannels`, `mutedCategories`
  - `subscriptions` ohne `channelEmail`/`channelTelegram`
  - `available`: welche Kanäle der Server zustellen kann (`email` nur mit `SMTP_HOST`, `telegram` nur mit
    `TELEGRAM_BOT_TOKEN`)
- `PUT` nimmt dieselben Felder in snake_case.
  - Wie heute ist er ein Replace-all: `null` löscht ein Ziel.
  - Fehlt eines der neuen Felder (`ntfy_url`, `webhook_url`, `matrix`, `disabled_channels`, `muted_categories`),
    bleibt sein gespeicherter Wert. So bricht ein Aufrufer, der nur Regeln schickt, die Matrix nicht.
  - `channel_email`/`channel_telegram` in einer Regel lehnt das Schema ab (`RequestModel`), wenn es zusätzliche
    Felder verbietet. Sonst werden sie ignoriert; T3 prüft das und nennt es in der Doku.
- **Prüfung beim Speichern:**
  - ntfy- und Webhook-URL: nur `https://` oder `http://` mit Host, höchstens 2048 Zeichen, keine Zugangsdaten im
    Userinfo-Teil.
  - Matrix und Listen: nur bekannte Kanäle und Schweregrade.
  - `muted_categories`: höchstens 32 Einträge zu je 64 Zeichen.
  - Die SSRF-Sperre prüft nicht beim Speichern, sondern bei jedem Versand: DNS kann sich bis dahin ändern.
- **`POST /api/users/me/notification-prefs/test`** mit `{"channel": "email"|"ntfy"|"telegram"|"webhook"}`:
  - Schickt sofort eine Testnachricht an das gespeicherte Ziel, ohne Outbox, und antwortet `200`.
  - Kein Ziel oder nicht zustellbar (`available`): `409`.
  - Versand gescheitert: `502` mit neutralem Text (Ausnahmetyp beziehungsweise HTTP-Status, nie URL oder Token).
  - Gesperrtes Ziel: `422`.
  - Höchstens ein Test je Person und Kanal in zehn Sekunden über `app/core/rate_limit.py` (Redis, sonst im Speicher),
    sonst `429`.
  - Der Desktop-Kanal testet lokal (Toast und OS-Hinweis).

**Versand** (`outbox.py`, eine Funktion je Kanal in `sender.py`):
- **ntfy:** `POST` an die gespeicherte Topic-URL, Body = Text, Titel und Priorität als Header.
  - Priorität: critical 5, warning 4, info 3, ok 2.
  - Zugang über den Query-Parameter `auth` in der URL (ntfy-Doku). So braucht es kein eigenes Feld.
- **Telegram:** `sendMessage` an `https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/`.
  - `chat_id` = gespeicherte Chat-ID, `text` = Titel, Leerzeile, Text.
  - Kein `parse_mode`, damit nichts escaped werden muss. Der Text wird auf das Limit der API gekürzt.
- **Webhook:** `POST` JSON `{"title", "body", "severity", "category", "sent_at"}` an die gespeicherte URL, ohne
  Signatur.
- **Allgemein für ntfy und Webhook:**
  - Jeder Versand geht durch `check_target(url, allow_private=NOTIFY_ALLOW_PRIVATE_TARGETS)` und `pinned_client`,
    ohne Redirects.
  - Mit Opt-in sind private Adressen und `100.64.0.0/10` (CGNAT, etwa Tailscale) erlaubt. Loopback, Link-Local
    (Metadaten `169.254.169.254`), unspezifiziert, Multicast, reserviert und `0.0.0.0/8` bleiben gesperrt.
- Ein Status außer 2xx und jeder Netzfehler ist ein Fehlversuch mit Backoff wie bei E-Mail.
- Ein gesperrtes Ziel ist sofort `failed`: Ein neuer Versuch ändert daran nichts.
- **Log-Regel:** Logs und `last_error` nennen nie URL, Chat-ID oder Token, nur Kanal, Ausnahmetyp und HTTP-Status.
  httpx-Ausnahmen tragen die URL samt Token im Text.

**Desktop:**
- Toast und OS-Hinweis kommen nur, wenn alle drei gelten:
  - Die Matrix hat `desktop` für den Schweregrad des Eintrags. Ein Eintrag eines erledigten Vorfalls zählt als
    `ok`, sofern der Feed das trägt; T4 prüft es.
  - `desktop` ist nicht abgeschaltet.
  - Die Kategorie ist nicht stumm.
- Die Prefs lädt das Desktop beim Aktivieren der Benachrichtigungen und nach dem Speichern.
- Fehlen sie (Fehler, älterer Server), gilt die Vorgabe: Toasts wie heute.
- Der lokale Schalter für OS-Hinweise (`osNotifications`) und „Nicht stören“ bleiben.

Der Agent ist nicht betroffen, das Monitoring nur durch die gespiegelte `ssrf.py` ohne Verhaltensänderung. Das Monitoring hat eigene Alert-Kanäle (`MonitorAlertRule`).

## Externe Integrationen

- **ntfy, Publish:** https://docs.ntfy.sh/publish/.
  - Belegt: PUT/POST an `<server>/<topic>`; Header `X-Title`, `X-Priority` (1–5), `X-Tags`; Zugang per
    Query-Parameter `auth`.
  - Nicht verifiziert, vor T2 nachlesen: die Kodierung eines Titels mit Nicht-ASCII im Header (sonst JSON-Publish an
    die Root-URL) und die genaue Form von `auth`.
- **Telegram Bot API:** https://core.telegram.org/bots/api.
  - Belegt: `https://api.telegram.org/bot<token>/<method>`, nur HTTPS, Antwort `{ok, description, error_code,
    result}`.
  - Nicht verifiziert, vor T2 nachlesen: das Textlimit von `sendMessage` und die Bedeutung von `parse_mode` ohne
    Angabe.
- **Webhook:** eigenes Format, oben beschrieben.

## Trade-offs & Alternativen

- **Eigene Tabelle `notification_settings` statt Spalten an `users`.** Sie hält das Modul zusammen und lässt
  `users/` (Risikopfad Auth) unberührt. Kosten: ein Join bei jeder Zustellung. Empfohlen und geplant.
- **Kanal-Schalter als eigene Liste statt „Spalte leer“.** Wer ntfy kurz abschaltet, behält seine Matrix. Kosten: ein
  Feld mehr. So zeigt es das Mockup.
- **ntfy-Zugang nur über `?auth=` in der URL statt eigener Felder für Token und Basic-Auth.** Ein Feld und ein
  Geheimnis an einer Stelle. Kosten: Die URL ist ein Geheimnis, deshalb kommt sie nie in Logs und zeigt sich in der
  UI wie ein Passwortfeld. Empfohlen.
- **Webhook ohne HMAC-Signatur.** YAGNI: Der Monitoring-Webhook signiert auch nicht, ein Ziel mit Geheimnis im Pfad
  reicht für den Anfang. Eine Signatur ist eine spätere Roadmap-Zeile, wenn jemand sie braucht.
- **Test synchron statt über die Outbox.** Der Knopf soll das Ergebnis sofort zeigen. Die Sperre je Person und Kanal
  verhindert, dass er als Verstärker taugt.
- **SSRF-Prüfung beim Versand statt beim Speichern.** Nur so gilt sie auch nach einem DNS-Wechsel. Beim Speichern
  prüft das Schema nur die Form.

## Risiken & Rollback

- **Migration entfernt zwei Spalten.** Der Downgrade stellt sie aus der Matrix wieder her (verlustbehaftet, siehe
  oben). Rollback: Revert und `alembic downgrade` um eine Revision.
- **Ausgehende Requests an nutzergesetzte Ziele (SSRF).**
  - Geschützt durch `check_target`/`pinned_client` je Versand, ohne Redirects.
  - Gegen den Test-Knopf: die Sperre je Person und Kanal.
  - Der Opt-in lässt Loopback und Metadaten gesperrt.
  - `security` prüft T1 (Alembic) und T2/T3 (ausgehende Requests, Rate-Limit).
- **Geheimnisse in Zielen** (ntfy-`auth`, Webhook-Pfad, Bot-Token): nie in Logs und nie in `last_error`. Die
  Outbox-Zeile trägt die Ziel-URL wie heute die E-Mail-Adresse; sie liegt in der DB, nicht in Logs.
- **Telegram-Token fehlt:** Telegram ist nicht `available`, `_queue` legt keine Zeile an, und der Test antwortet
  `409`.
- **Ältere Desktop-Clients** schicken beim Speichern Regeln mit `channel_email`. T3 entscheidet je nach `RequestModel`
  zwischen ignorieren und `422`. Ein Client derselben Version ist nie betroffen.

## Doku-Impact

- **Bedienung:** `docs/admin/monitoring.html` und `docs/en/admin/monitoring.html`, Abschnitt Persönliche
  Benachrichtigungen: Kanäle, Matrix, Kategorien, Test.
- **Betrieb:** `docs/admin/betrieb.html` und `docs/en/admin/operations.html`: `TELEGRAM_BOT_TOKEN` und
  `NOTIFY_ALLOW_PRIVATE_TARGETS` neben SMTP.
- **Entwickler:** `docs/developer/server.html` DE+EN (Tabellen `notification_settings`, Outbox-Kanäle) und
  `docs/developer/api-reference.html` DE+EN (Prefs-API und Test-Route).
- **Weiteres:** `.env.example` und `changelog.d/kern-notify-2.md`.

## Offene Fragen

Keine aus Kevins Bereich. Kevin hat am 2026-11-07 entschieden (Notiz an R-1080). Selbst entschieden und oben
begründet:
- eigene Tabelle
- Schalter als Liste
- ntfy-Zugang per `?auth=`
- Webhook ohne Signatur
- CGNAT unter dem Opt-in
- fehlende neue Felder beim `PUT` behalten ihren Wert
