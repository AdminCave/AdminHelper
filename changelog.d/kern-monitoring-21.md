### Fixed

- **Monitoring: Wiki.js-Funde gehen nach dem Update nicht mehr auf:** eine vor den tag-gebundenen Checks gespeicherte
  Zusammenfassung ohne `tag_checks` machte jede uebernommene Wiki.js-Instanz einmal `changed` und oeffnete verworfene
  Funde wieder. Der fehlende Schluessel zaehlt nicht mehr als Aenderung; ein Wechsel der Hauptversion schon.
