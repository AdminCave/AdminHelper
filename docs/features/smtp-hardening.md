<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# SMTP: ein Verhalten für Hub- und Monitoring-Mail, Zugangsdaten je Relay, Monitoring bekommt SMTP_*

Stand des Codes: `origin/main@b1432223`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/smtp-hardening.md`. Roadmap R-0634 (T4); T1–T3 gehören zum Paket (Härtung, Kevin 2026-10-22).

## Problem / Motivation

AdminHelper verschickt E-Mails an zwei Stellen: den **Notification-Hub** im Server (Outbox, `send_email` in
`apps/server/app/modules/notifications/sender.py:19-41`, läuft im `scheduler`-Dienst) und den **E-Mail-Kanal der
Alert-Regeln** im Monitoring (`_send_email` in `apps/monitoring/app/alerter.py:638-691`). Beide lesen dieselben
Variablen `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`
(`apps/server/app/core/config.py:163-171`, `apps/monitoring/app/core/config.py:68-80`), verhalten sich aber
verschieden, und die Konfiguration erreicht nur einen von beiden.

1. **Zugangsdaten je Relay (T1).** Eine Alert-Regel darf in `channel_config` einen eigenen Relay setzen
   (`smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`, `from`; `docs/admin/monitoring.html:340`: „pro Regel
   überschreibbar“). `_send_email` ergänzt dabei jedes fehlende Feld aus der Umgebung
   (`alerter.py:651-654`), unabhängig davon, welchen Host die Regel nennt. Gewollt ist: Die Zugangsdaten aus der
   Umgebung gehören zum Relay aus `SMTP_HOST`; eine Regel mit eigenem Relay bringt ihre eigenen mit.

2. **Passwort in Template-Antworten (T2).** Alert-Regeln geben ein gesetztes `smtp_password` als `***` aus
   (`MonitorAlertRule.to_dict`, `apps/monitoring/app/models.py:154-173`, Maske `:159-160`), und `PUT /alerts/{id}`
   behandelt `***` als „unverändert“ (`apps/monitoring/app/routers/alerts.py:108-120`). Templates tragen dieselben
   `channel_config` in ihren Alert-Definitionen, geben sie aber ungekürzt aus (`MonitorTemplate.to_dict`,
   `models.py:232-257`, `alertDefinitions` `:247-249`): in `GET /templates`, `GET /templates/{id}`, den Antworten von
   `POST /templates`, `PUT /templates/{id}`, `POST /templates/{id}/builtin-update`
   (`apps/monitoring/app/routers/templates.py:67-93`, `:133-162`, `:165-181`, `:184-222`, `:309-327`) und im Feld
   `current.alertDefinitions` von `GET /templates/{id}/builtin-update` (`:280-306`). Der Desktop schickt beim
   Speichern eines Templates die `channel_config` zurück, wie er sie gelesen hat
   (`apps/desktop/ui/src/lib/models/monitorTemplate.ts:68-71`, `:84-88`); mit einer Maske ohne „`***` =
   unverändert“ würde das erste Speichern `***` als Passwort in das Template und jede daraus erzeugte Regel schreiben
   (`apps/monitoring/app/template_sync.py:534`). Beide gehören deshalb in eine Task.

3. **TLS des Hub-Versands wie im Monitoring (T3).** Das Monitoring nutzt für beide Wege einen Kontext aus
   `ssl.create_default_context()` (Zertifikat und Hostname werden geprüft) und STARTTLS auf jedem Port außer 465
   (`alerter.py:666-683`, Tests `apps/monitoring/tests/test_alerter_dispatch.py:241-277`, `:320-345`). Der Hub wählt
   TLS anders (`sender.py:30-41`): `SMTP_SSL` und `starttls()` ohne eigenen Kontext, `starttls()` nur bei Port 587.
   Ziel ist dasselbe Verhalten wie im Monitoring. Der Docstring von `apps/server/tests/test_email_sender.py:5-8` nennt
   STARTTLS für jeden anderen Port; getestet sind nur 465 und 587. Die Doku nennt für den Hub „587 (STARTTLS, Default)
   oder 465 (implizites TLS/SMTPS)“
   (`docs/admin/betrieb.html:141`, EN `docs/en/admin/operations.html:100`) und für das Monitoring „beide prüfen das
   Server-Zertifikat“ (`docs/admin/monitoring.html:340`).

4. **Monitoring bekommt kein SMTP_* (R-0634, T4).** Compose reicht `SMTP_*` an `server` (`docker-compose.yml:107-115`)
   und `scheduler` (`:159-164`), nicht an `monitoring` (`environment` `:367-389`). Die Doku sagt für den E-Mail-Kanal:
   „SMTP standardmäßig aus den Umgebungsvariablen `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`,
   `SMTP_FROM`; pro Regel überschreibbar“ (`docs/admin/monitoring.html:340`, EN `:340`). Jede E-Mail-Regel ohne
   eigenen `smtp_host` scheitert daher mit `SMTP not configured (SMTP_HOST missing)` (`alerter.py:656-657`). Beleg
   (Probe an `origin/main@b1432223`, Parser wie `apps/server/tests/test_env_parity.py:61-93`, dreimal identisch):
   `server` und `scheduler` je `SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER`, `monitoring` keine.
   Der Mail-Kreislauf der Multibox (`scripts/tests/box_serverbox.sh:419-460`) setzt `smtp_host` je Regel und sieht es
   deshalb nicht.

## Ziel & Nicht-Ziele

Ziel:
- T1: `_send_email` nimmt `SMTP_USER`/`SMTP_PASSWORD` nur, wenn der Relay der Regel der aus `SMTP_HOST` ist (Regel
  ohne `smtp_host` oder mit demselben Namen, verglichen nach `strip()` und Kleinschreibung). Eine Regel mit anderem
  Host meldet sich nur mit ihren eigenen `smtp_user`/`smtp_password` an, sonst ohne Login. Port und `from` fallen wie
  bisher auf die Umgebung zurück.
- T2: Template-Antworten zeigen ein gesetztes `smtp_password` in Alert-Definitionen als `***`, überall dort, wo sie
  Alert-Definitionen ausgeben. `PUT /templates/{id}` behandelt `***`, `""` und fehlend wie `PUT /alerts/{id}`: das
  gespeicherte Passwort der Definition mit derselben `def_id` bleibt, gibt es keins, entfällt der Schlüssel.
  `POST /templates` speichert `***`/`""` nicht als Passwort.
- T3: Der Hub verschickt wie das Monitoring: ein Kontext aus `ssl.create_default_context()`, Port 465 über
  `SMTP_SSL(..., context=ctx)`, jeder andere Port über `SMTP` und `starttls(context=ctx)` vor `login()`. Scheitert
  STARTTLS, folgt weder `login()` noch der Versand.
- T4: Compose reicht die fünf `SMTP_*` wortgleich wie an `server` auch an `monitoring`. T4 kommt nach T1.
- T5–T7 (Frage 1, Kevin 2026-10-22: Option (b)): optionale CA-Datei `SMTP_CA_FILE` für Relays mit privater CA, in
  Hub und Monitoring.
- T8 (Kevin 2026-10-22): `PUT /alerts/{id}` und `PUT /templates/{id}` behalten ein gespeichertes `smtp_password`
  bei `***`, leerem oder fehlendem Wert nur, solange `smtp_host` und `smtp_port` gleich bleiben. Ändert derselbe PUT
  den Relay, antwortet `***` mit 422 (Passwort neu eingeben); ohne Passwort entfällt das gespeicherte.
- T9: CHANGELOG-Einträge und zwei Stellen in Betrieb & Konfiguration präzisiert (Funde der Task-Reviews). T10/T11:
  Tests halten fest, dass `SMTP_CA_FILE` die System-CAs ergänzt (Fund der Branch-Prüfung).

Nicht-Ziele (YAGNI):
- Kein typisiertes Schema für `channel_config` (Frage 2): T1 löst die Zugangsdaten-Frage ohne Änderung am
  Request-Vertrag von `/alerts` und `/templates`.
- Kein Mailkanal des Monitorings über den Hub (Frage 3); kein Versand ohne TLS, kein Schalter, der die Prüfung
  abschaltet.
- Keine Änderung an `POST /alerts` (`routers/alerts.py`), am Desktop oder am Web; `PUT /alerts/{id}` ändert nur T8.
- Keine Änderung an `scripts/install.sh` oder `scripts/update.sh`: `update.sh` tauscht `docker-compose.yml` aus dem
  Laufzeit-Bundle des Releases (`scripts/update.sh:5-11`, `:513-536`), T4 erreicht Installationen also mit dem
  nächsten Release.

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | monitoring | `apps/monitoring/app/alerter.py`, `apps/monitoring/tests/test_alerter_dispatch.py`, `docs/admin/monitoring.html`, `docs/en/admin/monitoring.html`, `CHANGELOG.md` |
| T2 | monitoring | `apps/monitoring/app/models.py`, `apps/monitoring/app/routers/templates.py`, `apps/monitoring/tests/test_alert_secrets.py`, `CHANGELOG.md` |
| T3 | server | `apps/server/app/modules/notifications/sender.py`, `apps/server/tests/test_email_sender.py`, `docs/admin/betrieb.html`, `docs/en/admin/operations.html`, `CHANGELOG.md` |
| T4 | server | `docker-compose.yml`, `apps/server/tests/test_compose_smtp.py` (neu), `docs/admin/betrieb.html`, `docs/en/admin/operations.html`, `CHANGELOG.md` |
| T5 | server | `apps/server/app/core/config.py`, `apps/server/app/modules/notifications/sender.py`, `apps/server/tests/test_email_sender.py` |
| T6 | monitoring | `apps/monitoring/app/core/config.py`, `apps/monitoring/app/alerter.py`, `apps/monitoring/tests/test_alerter_dispatch.py` |
| T7 | scripts | `docs/admin/betrieb.html`, `docs/en/admin/operations.html`, `docs/admin/monitoring.html`, `docs/en/admin/monitoring.html`, `CHANGELOG.md` |
| T8 | monitoring | `apps/monitoring/app/models.py`, `apps/monitoring/app/routers/alerts.py`, `apps/monitoring/app/routers/templates.py`, `apps/monitoring/tests/test_alert_secrets.py`, `docs/admin/monitoring.html`, `docs/en/admin/monitoring.html`, `CHANGELOG.md` |
| T9 | scripts | `CHANGELOG.md`, `docs/admin/betrieb.html`, `docs/en/admin/operations.html` |
| T10 | server | `apps/server/tests/test_email_sender.py` |
| T11 | monitoring | `apps/monitoring/tests/test_alerter_dispatch.py` |

Auf `scripts/dev/review-risk.txt` stehen `apps/monitoring/app/alerter.py` (T1, T6),
`apps/server/app/modules/notifications/*` (T3, T5) und `docker-compose*.yml` (T4): diese Tasks bekommen zusätzlich
`security`.

`docker-compose.yml` ändert T4 nur im `environment`-Block von `monitoring`: fünf Einträge und eine Kommentarzeile
zwischen `:375` (`- ALERT_LOG_RETENTION_DAYS=…`) und `:376` (Kommentar `# Notification hub: …`). Die Blöcke von
`server` und `scheduler`, die Postgres-Zeilen von `monitoring` (`:384-389`) und sein Healthcheck bleiben unberührt.

## Datenmodell / API / Migrationen

Keine Migration, keine Spalte, keine neue Route, keine Änderung eines Request- oder Response-Schemas in OpenAPI
(die Template-Routen haben kein `response_model`; Docstrings der Routen bleiben, `test_openapi_snapshot.py` steht im
`Verify:` von T2). Geändert wird nur ein Wert: `alertDefinitions[].channel_config.smtp_password` kommt als `***`
statt als gespeicherter Text, und ein `PUT /templates/{id}` mit `***` überschreibt das gespeicherte Passwort nicht
mehr. Seit T8 gilt für `PUT /alerts/{id}` und `PUT /templates/{id}`: ändert derselbe PUT `smtp_host` oder
`smtp_port`, antwortet ein `***` mit 422 (nichts gespeichert), ein leeres oder fehlendes `smtp_password` verwirft
das gespeicherte. Der einzige Leser, der Desktop, zeigt kein SMTP-Feld (er bearbeitet nur `recipients` bzw. `url`,
`apps/desktop/ui/src/components/monitoring/MonitoringTemplateModal.svelte:140-158`) und schickt `***` beim Speichern
unverändert zurück. Kein Vertrags-Drift zu Web oder Agent. Compose: `monitoring` bekommt fünf Umgebungsvariablen,
die sein Code schon liest (`test_env_parity.py` bleibt grün: gelesen, gesetzt, in `.env.example:126-135`
dokumentiert).

## Externe Integrationen

- Python `smtplib` (docs.python.org/3.12/library/smtplib.html, gelesen 2026-10-22): `starttls(*, context=None)`,
  „Optional context parameter is an ssl.SSLContext object“, wirft `SMTPNotSupportedError`, wenn der Server STARTTLS
  nicht anbietet; `SMTP_SSL(…, context=None)` „can contain a SSLContext“. Mit eigenem Kontext übergibt `smtplib`
  `server_hostname=self._host` (`smtplib.py:780`, `:1030` in 3.12), die Hostnamenprüfung des Kontexts greift also.
- Python `ssl` (docs.python.org/3.12/library/ssl.html, „Best defaults“, gelesen 2026-10-22): „For client use … use
  the create_default_context() function … It will load the system's trusted CA certificates, enable certificate
  validation and hostname checking“, mit genau dem Beispiel `smtp.starttls(context=context)`.
  `create_default_context(cafile=…)` lädt nur die genannte Datei statt der System-CAs;
  `SSLContext.load_verify_locations(cafile=…)` fügt eine hinzu (T5/T6 nutzen Letzteres).
- Container: `python:3.12-slim` (`Dockerfile:14`, `apps/monitoring/Dockerfile:1`); Standard-CA-Datei
  `/usr/lib/ssl/cert.pem` → `/etc/ssl/certs/ca-certificates.crt` (Probe in beiden Images).

## Trade-offs & Alternativen

1. **Wann die Umgebung die Zugangsdaten liefert (T1).** (a) Nur für den Host aus `SMTP_HOST`, Vergleich nach `strip()`
   und Kleinschreibung — **Empfehlung**: ohne Vertragsänderung, eine Stelle, gilt auch für Regeln aus Templates. (b) Nie,
   sobald eine Regel `smtp_host` setzt, auch nicht für denselben Namen — bricht Regeln, die den globalen Relay nur mit
   anderem Port oder Absender nutzen. (c) Ein Schema, das `smtp_host` verbietet — bricht den dokumentierten Override.
   Ein anderer Name für denselben Relay (IP statt Name, abschließender Punkt) zählt als anderer Host; die Regel
   braucht dann eigene Zugangsdaten. Das ist die sichere Richtung.
2. **Feldweiser Rückfall auf dem Host aus `SMTP_HOST` (T1).** Bleibt wie heute (`smtp_user` der Regel plus
   `SMTP_PASSWORD` möglich): derselbe Relay, keine Verhaltensänderung für bestehende Regeln.
3. **Wo die Maske sitzt (T2).** Ein kleiner Helfer in `models.py`, den `MonitorAlertRule.to_dict` und
   `MonitorTemplate.to_dict` nutzen, dazu die Maske für `current` in `GET …/builtin-update`. Der Hash in
   `builtin_edited` liest weiter die gespeicherten Werte (`apps/monitoring/app/builtin_templates.py:326`), eine
   Maske ändert also nicht, ob ein Standard-Template als bearbeitet gilt.
4. **Semantik von `***` beim PUT (T2).** Wie `PUT /alerts/{id}` (`***`, `""`, fehlend = unverändert), zugeordnet über
   `def_id`. Eine Definition ohne `def_id` oder mit neuer `def_id` hat kein gespeichertes Passwort; dort entfällt der
   Schlüssel.
5. **STARTTLS auf jedem Port (T3).** Wie das Monitoring seit 3.24; Port 25 und 2525 bekommen STARTTLS. Ein Relay ohne
   STARTTLS nimmt danach keine Hub-Mail mehr an (Risiken, Frage 1).
6. **CA für Relays mit privatem Zertifikat (T5–T7, Frage 1).** (a) Nichts; (b) `SMTP_CA_FILE`, zusätzlich zu den
   System-CAs, nur für SMTP — **Empfehlung**; (c) ein Schalter, der die Prüfung abschaltet — nicht empfohlen.
7. **Test für T4 als eigene Datei.** `test_compose_smtp.py` nutzt `_compose_environment` aus
   `apps/server/tests/test_env_parity.py` (Import zwischen Testmodulen wie `test_compose_frps.py:47`), statt
   `test_env_parity.py` zu erweitern: andere Vorhaben ändern Compose parallel und erweitern vermutlich dieselbe Datei.

## Risiken & Rollback

- **T3 ändert, welche Relays der Hub erreicht.** Ein Relay ohne STARTTLS (etwa ein lokales Postfix auf Port 25), mit
  selbstsigniertem Zertifikat oder privater CA, oder `SMTP_HOST` als IP ohne passenden SAN im Zertifikat nimmt danach
  keine Hub-Mail mehr an: die Outbox wiederholt bis `NOTIFICATION_MAX_ATTEMPTS` und markiert die Mail als
  fehlgeschlagen, der Grund steht im Log des `scheduler`-Dienstes; Glocke und Desktop-Hinweise bleiben. Dokumentiert
  sind ohnehin nur 587 und 465 mit „externem Relay“ (`docs/admin/betrieb.html:136`, `:141`). CHANGELOG und
  Betriebs-Doku nennen es. Für private CAs: Frage 1.
- **T4 schaltet Monitoring-Mail für jede Installation mit `SMTP_HOST` ein.** E-Mail-Regeln ohne eigenen Relay, die
  bisher mit `SMTP not configured` scheiterten, verschicken danach über den globalen Relay, mit derselben TLS-Prüfung
  wie unter T3. T4 hängt an T1.
- **T1:** Regeln mit eigenem `smtp_host` ohne eigene Zugangsdaten melden sich nicht an; verlangt ihr Relay einen
  Login, steht im Alert-Log `SMTP server refused the message`. Abhilfe: eigene Zugangsdaten in der Regel.
- **T2:** API-Nutzer, die das Passwort aus `GET /templates` gelesen haben, sehen `***`.
- Rollback: jede Task ist ein eigener Commit ohne Datenänderung; Revert genügt. T4 wirkt auf Installationen erst mit
  dem nächsten Release über `update.sh`.

## Doku-Impact

T1: `docs/admin/monitoring.html:340` (DE+EN): die Zugangsdaten aus der Umgebung gelten nur für `SMTP_HOST`; CHANGELOG
(Changed). T2: CHANGELOG (Changed). T3: `docs/admin/betrieb.html:141` / `docs/en/admin/operations.html:100`:
STARTTLS auf jedem Port außer 465, Prüfung von Zertifikat und Hostname; CHANGELOG (Changed). T4: Satz im
SMTP-Abschnitt von `betrieb.html` / `operations.html`, dass derselbe Relay die E-Mail-Regeln des Monitorings bedient;
CHANGELOG (Fixed). T7: `SMTP_CA_FILE` mit Override-Beispiel; CHANGELOG (Added). T8: Zeile `email` in
`docs/admin/monitoring.html` (DE+EN): `***` gilt nur bei unverändertem Relay; CHANGELOG (Changed).

## Offene Fragen

1. **Option für Relays mit privater CA (T5–T7)?** Nach T3 (und mit T4 auch fürs Monitoring über den globalen Relay)
   brauchen Relays ein Zertifikat, dem der Container vertraut. Optionen: (a) nichts — strikt wie das Monitoring seit
   3.24; (b) `SMTP_CA_FILE`: Pfad zu einer PEM-Datei im Container, zusätzlich zu den System-CAs geladen, nur für SMTP,
   eingebunden per `docker-compose.override.yml` (Volume + Variable für `server`, `scheduler`, `monitoring`), ohne
   Eintrag in `docker-compose.yml` und `.env.example`; (c) ein Schalter, der die Prüfung abschaltet.
   **Empfehlung (b):** interne Relays mit Firmen-CA sind im Umfeld der Zielgruppe üblich; ohne Option fehlt ihnen
   nach dem Update jeder unterstützte Weg, (b) lässt die Prüfung an und betrifft nur SMTP. Trade-off: ein Schalter
   mehr und eine Override-Datei beim Betreiber. (c) nicht empfohlen. Relays ohne STARTTLS bleiben bei jeder Option
   außen vor (Empfehlung: hinnehmen, die Doku nennt 587/465). Hängt: T5, T6, T7. **Antwort Kevin 2026-10-22: (b)**,
   Prüfung bleibt an, Einbindung per `docker-compose.override.yml`, Doku mit Beispiel.
2. **Typisiertes `channel_config`?** Empfehlung: nicht in diesem Paket — T1 regelt die Zugangsdaten ohne Änderung am
   Request-Vertrag; ein Schema änderte die OpenAPI von `/alerts` und `/templates` und bräuchte einen Weg für
   gespeicherte Regeln mit weiteren Schlüsseln. Bei Ja eine eigene Roadmap-Zeile. Hängt: keine Task.
3. **R-0634 über Compose statt über den Hub?** Empfehlung Compose (T4): die Doku beschreibt genau das, kleinster
   Eingriff, keine neue interne Route. Folge: `SMTP_PASSWORD` steht dann auch in der Umgebung von `monitoring`, wie
   bei `server` und `scheduler`. Hängt: keine Task (T4 folgt der Abhilfe der Zeile).
