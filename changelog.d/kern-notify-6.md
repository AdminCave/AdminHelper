### Added

- **Benachrichtigungs-Kanaele im Web-Admin:** Admins pflegen SMTP-Relay, Telegram-Bot-Token und die privaten Netze
  fuer ntfy-/Webhook-Ziele unter „Benachrichtigungen“, mit Test-Versand je Kanal. Passwort und Token sind write-only
  und liegen verschluesselt in der Datenbank; die `.env`-Variablen bleiben je Feld der Rueckfall. Server, Scheduler und
  Monitoring uebernehmen Aenderungen ohne Neustart.
- **Mail-Design:** eine freie HTML-Vorlage mit Text-Alternative, Betreff-Praefix, Absendername und eingebettetem Logo,
  mit Platzhaltern, abgeschotteter Vorschau und Test-Versand. Sie gilt fuer die Mails des Notification-Hubs und der
  Monitoring-Alert-Regeln; ohne Design bleiben die Mails reiner Text wie bisher.

### Fixed

- **API-Referenz:** ein persoenlicher Kanal-Test an ein gesperrtes Ziel zaehlt wie jeder Versandversuch gegen das
  Zehn-Sekunden-Limit.
