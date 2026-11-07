### Added

- **Benachrichtigungen: Kanaele ntfy, Telegram und Webhook:** jede Person hinterlegt unter Einstellungen →
  Benachrichtigungen eigene Ziele fuer E-Mail, ntfy, Telegram und Webhook, schaltet Kanaele ab, ohne das Ziel zu
  loeschen, und testet jeden Kanal mit einem Knopf. Telegram braucht `TELEGRAM_BOT_TOKEN`; ntfy- und Webhook-Ziele in
  privaten Netzen sind gesperrt, ausser die CIDR-Liste `NOTIFY_PRIVATE_TARGETS` gibt das Netz frei.
- **Benachrichtigungen: Matrix und Kategorien:** je Schweregrad (Kritisch, Warnung, Info, Erledigt) waehlt eine Person
  die Kanaele, Desktop-Hinweise eingeschlossen; eine ausgeschaltete Kategorie landet nur noch in der Glocke.
- **API:** `POST /api/users/me/notification-prefs/test` schickt eine Testnachricht an das gespeicherte Ziel eines
  Kanals.

### Changed

- **Benachrichtigungen: die Matrix ersetzt die Kanal-Haekchen der Regeln:** die Migration uebernimmt ein E-Mail- oder
  Telegram-Haekchen ab dem Mindest-Schweregrad der Regel und fuer die Entwarnung; die Kanaele gelten jetzt fuer alle
  Server, die eine Regel der Person trifft. `GET`/`PUT /api/users/me/notification-prefs` tragen die neuen Felder,
  `channelEmail`/`channelTelegram` entfallen in der Antwort und werden beim Speichern ignoriert.
