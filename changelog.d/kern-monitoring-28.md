### Added

- **Monitoring: Web-Domains und PHP-Anwendungen auf dem Host:** Die Erkennung liest die vHosts von nginx und Apache
  (nur Linux, hoechstens 500). Jede Domain mit TLS wird eine Instanz von `web_domain`: Ablauf und Name des
  ausgelieferten Zertifikats, dazu ein Hinweis, wenn ein erneuertes Zertifikat noch nicht neu geladen wurde. Nextcloud,
  Moodle, WordPress und BookStack ohne Container bekommen die Module `nextcloud_native`, `moodle_native`,
  `wordpress_native` und `bookstack_native`. Die Domainnamen gehen als Instanzen zum Monitoring-Dienst; Pfade,
  Konfigurationstext und Dateiinhalte verlassen den Host nie, den privaten Schluessel eines Zertifikats oeffnet der
  Agent nie.
- **Monitoring: Moodle-Systempruefungen:** `moodle_native` fuehrt alle 15 Minuten `admin/cli/checks.php` als Benutzer
  des Webservers aus, nie als root, und meldet nur Zustand und Zahl der Pruefungen, die nicht OK sind. Gehoeren Code
  oder Datenverzeichnis nicht nur root und diesem Benutzer, bleibt der Check `unknown`.
- **Monitoring: HAProxy-Zertifikate:** Das Modul `haproxy` prueft taeglich die Zertifikatsdateien der `bind`-Zeilen
  und warnt, wenn eines in weniger als 14 Tagen ablaeuft.
