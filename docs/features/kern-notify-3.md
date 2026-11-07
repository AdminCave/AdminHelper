# kern-notify-3: Ruhezeiten, Eskalation, Zusammenfassung per E-Mail, Ton bei Kritisch

Roadmap: R-1081 (Zug `tasks/kern-notify-3.md`). Vorlage: Design-Mockup `AdminCave/DesignSystem@244e890`,
`ui_kits/adminhelper/notifications.jsx` (`NotifySettings`, Abschnitt „Ruhe, Eskalation & Bündeln“). Baut auf
R-1079 (Vorfälle) und R-1080 (Kanäle und Matrix) auf, beide gemergt.

## Problem / Motivation

Seit R-1080 wählt jede Person in einer Matrix, welcher Kanal welchen Schweregrad bekommt. Es fehlt alles, was von der
Uhrzeit abhängt:
- **Nachts:** ntfy, Telegram, Webhook und E-Mail melden jede Warnung sofort. Im Desktop gibt es nur „Nicht stören“
  für ein paar Stunden, von Hand gestartet (`apps/desktop/ui/src/lib/stores/dnd.ts`). Kritisches kommt dort immer
  durch, ein Schalter dafür fehlt (`allows`, `dnd.ts:77`).
- **Unbestätigte Kritische:** Ein kritischer Vorfall, den niemand bestätigt, geht nicht noch einmal an einen
  lauteren Kanal.
- **E-Mail-Flut:** Jede Info und jede Warnung, die die Matrix per E-Mail schickt, ist eine eigene Mail.
- **Ton:** Der Desktop zeigt kritische Meldungen als klebenden Toast, aber ohne Ton.

Kevin hat am 2026-11-07 entschieden (Notiz an R-1080/R-1081):
- **Ruhezeiten** wirken auf alle Kanäle der Person. Der Server hält ntfy, Telegram, Webhook und E-Mail für
  Nicht-Kritisches bis zum Ende der Ruhezeit zurück. Der Desktop zeigt in der Zeit keine Pop-ups und spielt keine
  Töne. „Kritisches trotzdem durchlassen“ ist schaltbar und gilt auch für „Nicht stören“.
- **Eskalation** an einen eigenen Kanal der Person: E-Mail, ntfy mit höchster Priorität, Telegram oder Webhook.
  Sie greift nach 5, 10 oder 30 Minuten, einmal je Vorfall. Eine Bereitschaft gibt es nicht.
- **Zusammenfassung** (täglich oder wöchentlich, 08:00): Sie ersetzt die sofortigen E-Mails für Info und Warnung.
- **Zeitzone je Person**, als IANA-Name aus dem Desktop.

## Ziel & Nicht-Ziele

**Ziele**
- **Ruhezeiten je Person:** an/aus, Beginn und Ende als `HH:MM` in der Zeitzone der Person. Der Zeitraum darf über
  Mitternacht gehen (22:00–07:00). Beginn gleich Ende gilt als leer.
  - In der Ruhezeit bekommt ein Outbox-Eintrag für Info, Warnung und Entwarnung (`ok`) `next_attempt_at` = Ende der
    Ruhezeit. Der Drain stellt ihn dann zu, ohne neue Logik im Drain.
  - Kritisches geht sofort, wenn „Kritisches trotzdem durchlassen“ an ist (Standard), sonst wird es ebenso
    zurückgehalten.
  - Im Desktop gibt es in der Ruhezeit weder Toast, OS-Meldung noch Ton. Für Kritisches gilt derselbe Schalter.
- **„Nicht stören“** im Desktop folgt diesem Schalter. Ist er aus, schweigt auch Kritisches bis zum Ende.
- **Eskalation je Person:** an/aus, Frist 5, 10 oder 30 Minuten, ein Kanal aus E-Mail, ntfy, Telegram und Webhook.
  - Ein Vorfall eskaliert, wenn er offen ist (nicht bestätigt, nicht behoben), die Person ihn kritisch gemeldet bekam
    und die Frist seit seiner ersten kritischen Meldung abgelaufen ist.
  - Dann geht an die Person **einmal** eine Nachricht über den gewählten Kanal, auch wenn ihre Matrix den Kanal für
    Kritisch nicht wählt. Text: „Unbestätigt seit N Min.: <Titel>“.
  - ntfy bekommt Priorität 5, wie heute bei Kritisch.
  - Nicht eskaliert wird ein Vorfall, den die Person stummgeschaltet hat, dessen Kanal sie ausgeschaltet hat oder für
    den sie kein Ziel hat.
  - Wird er bestätigt oder behoben, bevor die Frist abläuft, entfällt die Eskalation.
  - Wird er wieder geöffnet und erneut kritisch, darf er noch einmal eskalieren.
  - Die Zeitleiste des Vorfalls trägt den Eintrag `escalated` mit dem Kanal als Text. `escalated` ist schon eine Art
    des Vertrags; dieselbe Art steht heute beim Wechsel von Warnung zu Kritisch. Für die Person mit einer Ruhezeit
    gilt die Regel für Kritisches.
- **Zusammenfassung per E-Mail je Person:** aus, täglich oder wöchentlich (Montag), jeweils um 08:00 in der Zeitzone
  der Person.
  - Ist sie an, bekommen Einträge der Matrix-Spalte E-Mail für Info, Warnung und Entwarnung den Outbox-Status
    `digest` statt `pending`.
  - Ein Scheduler-Job sammelt sie zur Versandzeit in **eine** Mail (Betreff mit Anzahl, je Eintrag Zeit, Schweregrad
    und Titel) und setzt sie auf `sent`. Ohne Einträge geht keine Mail.
  - Wird die Zusammenfassung ausgeschaltet, gehen wartende `digest`-Einträge beim nächsten Lauf als eine
    Zusammenfassung raus, damit nichts verloren geht.
  - Kritisches per E-Mail bleibt sofort.
- **Ton bei Kritisch je Person:** an/aus. Der Desktop spielt bei einem kritischen Toast einen kurzen Ton
  (WebAudio-Oszillator, keine Audiodatei, also keine Lizenzfrage), außer in der Ruhezeit oder unter „Nicht stören“
  ohne Durchlass.
- **Zeitzone:** Der Desktop schickt beim Speichern `Intl.DateTimeFormat().resolvedOptions().timeZone`. Der Server
  prüft den Namen mit `zoneinfo`. Ohne gespeicherte Zone gilt UTC.
- **Standardwerte für alle bestehenden Personen:** Ruhezeiten aus (22:00–07:00 vorbelegt), Durchlass an, Eskalation
  aus (10 Min., kein Kanal), Zusammenfassung aus, Ton aus. Damit ändert sich nach dem Update nichts, bis die Person
  etwas einschaltet.

**Nicht-Ziele**
- Der Schalter „Gleiche Ereignisse bündeln“ des Mockups. Das Bündeln aus R-1079 ist immer an; ein Schalter je
  Person ist eine eigene Roadmap-Zeile (neu).
- Eine Bereitschaft oder Eskalation an andere Personen (Kevin 2026-11-07).
- Ruhezeiten je Kanal oder je Wochentag.
- Das Web-Frontend: Es hat keine Benachrichtigungs-Einstellungen.
- Eine eigene Tondatei oder Tonauswahl.

## Betroffene Komponenten & Dateien

**Server (`apps/server/`)**
- `app/modules/notifications/models.py` bekommt neue Spalten:
  - an `NotificationSettings`: `timezone`, `quiet_enabled`, `quiet_start`, `quiet_end`, `quiet_critical`,
    `escalation_enabled`, `escalation_minutes`, `escalation_channel`, `digest`, `digest_last_at`, `sound_critical`
  - an `Notification` (die Zeile der Person je Vorfall): `escalated_at`
  - an `NotificationIncident`: `critical_since`
- `alembic/versions/<neu>_notification_quiet_escalation_digest.py`: Die Spalten bekommen `server_default` mit den
  Standardwerten. Der Downgrade entfernt sie; wartende `digest`-Einträge gehen dabei auf `pending`.
- `app/modules/notifications/schemas.py`:
  - `NotificationPrefsUpdate` bekommt optionale Felder; ein fehlendes Feld behält seinen Wert, wie bei R-1080.
  - `NotificationPrefsOut` bekommt die Felder `timezone`, `quiet`, `escalation`, `digest` und `soundCritical`.
- `app/modules/notifications/router.py`: `_prefs_response` und `put_prefs` lesen und schreiben die neuen Felder.
- `app/modules/notifications/incidents.py`:
  - `_queue` (Zeile 489): Ruhezeit (`next_attempt_at`) und Zusammenfassung (Status `digest`).
  - `_ping` (Zeile 415) bzw. `_problem`: setzt `critical_since` beim ersten kritischen Ping und leert es, wenn der
    Vorfall behoben wird.
  - `act` (Zeile 767): Beim Wiederöffnen leert es `escalated_at` der Zeilen.
- `app/modules/notifications/quiet.py` (neu, SPDX): reine Zeitrechnung, also ob `now` in der Ruhezeit liegt, wann sie
  endet und wann die nächste Zusammenfassung fällig ist, alles in der Zone der Person.
- `app/modules/notifications/escalation.py` (neu, SPDX): `escalate_due(db, now)`. `digest.py` (neu, SPDX):
  `send_digests(db, now)`.
- `app/modules/hooks/scheduler.py` (bei `schedule_outbox_drain`, Zeile 445) und `app/scheduler_main.py` (Zeile 94):
  zwei Systemjobs, Eskalation jede Minute und Zusammenfassung alle fünf Minuten.
- `app/modules/notifications/outbox.py`: `drain_outbox` (Zeile 49) liest weiter nur `pending`. `digest` bleibt
  liegen, ohne Änderung am Drain; ein Test hält das fest.

**Desktop-UI (`apps/desktop/ui/`)**
- `src/lib/api/types.ts`, `src/lib/api/notifications.ts`: neue Felder der Prefs.
- `src/components/NotificationPrefs.svelte`: Abschnitt „Ruhe, Eskalation & Zusammenfassung“ nach dem Mockup, mit
  Ruhezeiten (zwei Zeitfelder und Schalter), Durchlass, Eskalation (Frist, Kanal, Schalter), Zusammenfassung
  (Aus/Täglich/Wöchentlich) und Ton.
  - Kanäle ohne Ziel oder ausgeschaltet sind in der Kanalauswahl deaktiviert.
  - Beim Speichern geht die Zeitzone mit.
- `src/lib/stores/notifyPrefs.ts`: hält die neuen Felder und rechnet die Ruhezeit (`inQuiet(now)`) in der
  gespeicherten Zone (`Intl`).
- `src/lib/stores/dnd.ts` (`allows`, Zeile 77): berücksichtigt den Durchlass-Schalter und die Ruhezeit.
- `src/components/AppShell.svelte` (Zeile 231): spielt den Ton für kritische Toasts; die OS-Meldungen (`osNotify.ts`)
  folgen derselben Prüfung.
- `src/lib/sound.ts` (neu, SPDX): kurzer Ton über WebAudio; fehlt `AudioContext`, passiert nichts.
- i18n DE/EN für die neuen Texte.

## Datenmodell / API / Migrationen

- **Neue Spalten**, Werte wie oben. `quiet_start` und `quiet_end` sind `String(5)` im Format `HH:MM`.
  `escalation_minutes` ist ein Integer aus {5, 10, 30}, `escalation_channel` ist nullable (`email|ntfy|telegram|webhook`),
  `digest` ist `off|daily|weekly`.
- **Outbox:** `status` kennt zusätzlich `digest`. Die Spalte ist ein freier String, kein Schemawechsel.
- **API `GET/PUT /api/users/me/notification-prefs`:** nur additiv.
  - Neue Felder im Response:
    - `timezone`: string
    - `quiet {enabled, start, end, critical}`
    - `escalation {enabled, minutes, channel}`
    - `digest`: `off|daily|weekly`
    - `soundCritical`: bool
  - Dieselben Felder optional im Request. Geprüft werden das Zeitformat, `minutes` ∈ {5,10,30}, der Kanal und die
    Zone (`zoneinfo.available_timezones`/`ZoneInfo`); ein Verstoß gibt 422.
  - Eskalation an mit einem Kanal ohne Ziel wird gespeichert. Der Job überspringt die Person, die UI zeigt den
    Hinweis.
  - oasdiff erwartet keine ERR: Es kommen nur Response-Properties und optionale Request-Properties hinzu.
- **Vertrags-Drift:** Betroffen ist nur der Desktop; Web und Agent lesen die Prefs nicht. Der OpenAPI-Snapshot wird
  nachgezogen.

## Externe Integrationen

Kein neues Wire-Format. ntfy-Priorität 5 (`X-Priority`, docs.ntfy.sh/publish, „Message priority“) ist schon in
`sender.py:99`. Die Zeitzonen kommen aus der IANA-Datenbank über `zoneinfo`. Im Server-Image muss `tzdata`
vorhanden sein; ob es da ist, wird in T1 geprüft (sonst kommt das Paket `tzdata` in die Abhängigkeiten, mit einer
Zeile in `THIRD_PARTY_LICENSES.md`).

## Trade-offs & Alternativen

- **Ruhezeit über `next_attempt_at`:** Gewählt, weil der Drain unverändert bleibt und Backoff und Fehlerpfad
  dieselben bleiben. Die Alternative wäre ein eigener Status `held` mit einem Freigabe-Job; der wäre mehr Code ohne
  Gewinn. Nachteil: Ein zurückgehaltener Eintrag trägt den Text vom Zeitpunkt des Pings, also kommen um 07:00
  mehrere Meldungen einzeln. Hingenommen; die Zusammenfassung ist der Weg gegen die Flut.
- **Zusammenfassung über den Outbox-Status `digest`:** Die Einträge tragen schon Text, Schweregrad und Person.
  Die Alternative, beim Versand die Glocke-Zeilen neu abzufragen, verlöre den Text des Pings und die Matrix-Wahl.
- **Eskalation an `Notification.escalated_at`:** Je Person und Vorfall gibt es genau eine Zeile, also passt die
  Spalte genau zu „einmal je Vorfall und Person“. Eine eigene Tabelle wäre nur bei mehreren Eskalationsstufen nötig.
  Das ist YAGNI.
- **`critical_since` am Vorfall statt aus der Zeitleiste rechnen:** Die Zeitleiste wird gekappt
  (`_cap_history`), deshalb ist eine Spalte robuster.
- **Ton per WebAudio statt Audiodatei:** keine Asset-Lizenz, kein Bundle-Zuwachs.

## Risiken & Rollback

- **Zeitrechnung über Mitternacht und Sommerzeit:** Getestet wird mit festen Zeitpunkten in `Europe/Berlin`, auch an
  den Umstellungstagen, sowie in UTC und mit einer Zone ohne DST. Eine Endzeit, die es am Umstellungstag nicht gibt,
  löst `zoneinfo` mit `fold` auf; der Test belegt den Wert.
- **Zurückgehaltene Einträge** liegen bis zu einer Ruhezeit lang in der Outbox. Der Drain liest sie nicht vor
  `next_attempt_at`, es gibt also keine Mehrlast.
- **Eskalationsjob unter Last:** Er braucht eine Abfrage über offene kritische Vorfälle mit `critical_since` vor
  `now − 5 min`, dazu die Zeilen ohne `escalated_at`. Gezählt wird mit einem Test der Abfragen, wie beim Drain.
- **Doppelte Eskalation bei zwei Scheduler-Prozessen:** Der Scheduler läuft als ein Prozess. Die Zeile wird
  trotzdem mit `escalated_at IS NULL` im UPDATE gesetzt, deshalb gewinnt nur ein Lauf.
- **Rollback:** Der Downgrade der Migration entfernt die Spalten und setzt `digest` auf `pending`. Ein Revert des
  Merges stellt das alte Verhalten her.

## Doku-Impact

- `docs/admin/monitoring.html` (Abschnitt `#kanaele`) und `docs/en/admin/monitoring.html` (`#channels`): neuer
  Unterabschnitt Ruhezeiten, Eskalation, Zusammenfassung und Ton.
- `docs/developer/server.html` + EN: Outbox-Status `digest`, die zwei Systemjobs, `critical_since` und
  `escalated_at`.
- `docs/developer/api-reference.html` + EN: die neuen Prefs-Felder.
- `changelog.d/kern-notify-3.md`.

## Offene Fragen

Keine; die vier Entscheidungen aus Kevins Bereich stehen in der Notiz an R-1081 (2026-11-07).
