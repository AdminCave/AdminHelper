### Fixed

- **Monitoring: Jicofo-Unit nach Absturz kritisch:** die Katalog-Regel von Jitsi Jicofo meldet die Unit als kritisch,
  wenn sie `exited` ist (der sysv-Unit bleibt nach einem Absturz `active`). Das Modul steht jetzt auf Version 2, die
  Instanzen bekommen das Update als Angebot.
- **Monitoring: Top-Prozesse und OOM-Liste:** unbrauchbare Einträge (ohne pid oder Namen) belegen keinen der
  angezeigten Plätze mehr.
