### Changed

- **Event-Hooks: `server.startup` einmal je Start:** Das Event feuert der Scheduler-Dienst, sobald seine Jobs
  eingeplant sind, statt jeder Web-Worker (bisher N-mal bei `WEB_CONCURRENCY=N`). Hooks darauf loggen im Log des
  `scheduler`-Dienstes.
- **Event-Hooks: begrenzte Warteschlange:** Hoechstens 1000 Events warten oder laufen gleichzeitig, jedes weitere wird
  mit einer Warnung verworfen; beim Herunterfahren wartet der Server bis zu 10 s auf laufende Hooks.

### Fixed

- **Event-Hooks und Benachrichtigungen nur nach gespeicherter Aenderung:** Events feuern erst, wenn die Aenderung
  committet ist. Ein gescheitertes Loeschen eines Benutzers meldete bisher `user.deleted`, obwohl der Benutzer
  bestehen blieb.
