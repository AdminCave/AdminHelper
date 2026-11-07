### Added

- **Benachrichtigungen: Ruhezeiten:** je Person ein Zeitraum in ihrer Zeitzone, in dem der Desktop schweigt und der
  Server E-Mail, ntfy, Telegram und Webhook bis zum Ende zurueckhaelt; Kritisches geht wahlweise trotzdem durch.
- **Benachrichtigungen: Eskalation:** bleibt ein kritischer Vorfall 5, 10 oder 30 Minuten unbestaetigt offen, geht
  einmal eine Nachricht an einen eigenen Kanal der Person.
- **Benachrichtigungen: Zusammenfassung per E-Mail:** taeglich oder woechentlich um 08:00 eine Mail statt der
  einzelnen Info-, Warnungs- und Erledigt-Mails.
- **Desktop: Ton bei Kritisch:** auf Wunsch ein kurzer Ton zum kritischen Hinweis.
- **API:** `GET`/`PUT /api/users/me/notification-prefs` tragen `timezone`, `quiet`, `escalation`, `digest` und
  `soundCritical` bzw. `sound_critical`.
