### Added

- **Monitoring: App-Sensor fuer BigBlueButton, OpenLDAP und WordPress:** der Agent liest ueber den neuen Sensor
  `app` das Innere dieser Anwendungen auf dem eigenen Host, nur lesend und ohne ein Programm zu starten; der
  Monitoring-Dienst nennt nur eine feste Ansicht. BigBlueButton zeigt alle 5 min Meetings und Teilnehmer aus
  `getMeetings` (Checksumme aus dem lokalen `securitySalt`, nur an den Port von bbb-web; nie Namen, Passwoerter,
  Teilnehmer oder Metadaten) und warnt alle 15 min bei fehlgeschlagenen Aufzeichnungen (Marker `*.fail`).
  OpenLDAP liest beim Paket alle 5 min die Replikation ueber `ldapi` mit SASL EXTERNAL und warnt bei einem
  syncrepl-Consumer ohne Verbindung; ohne cn=Monitor bleibt der Check `unknown`. WordPress zeigt stuendlich die
  Version aus `wp-includes/version.php` des Containers, auch beim fpm-Image. `bbb-conf --check` startet der Agent
  nie. Die Checks brauchen einen Agent in der Version des Monitoring-Dienstes; auf schon uebernommenen Instanzen
  kommen sie still hinzu. Doku: Monitoring, Abschnitt App-Module; Agent und Monitoring-Architektur (DE+EN).
