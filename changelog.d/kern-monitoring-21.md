### Fixed

- **Monitoring: Wiki.js-Funde gehen nach dem Update nicht mehr auf:** eine vor den tag-gebundenen Checks gespeicherte
  Zusammenfassung ohne `tag_checks` machte jede uebernommene Wiki.js-Instanz einmal `changed` und oeffnete verworfene
  Funde wieder. Der fehlende Schluessel zaehlt nicht mehr als Aenderung; ein Wechsel der Hauptversion schon.
- **Monitoring: der Wiki.js-Check `/healthz` kommt mit Tag 2 zurueck:** passt ein tag-gebundener Check nach einem
  Wechsel der Hauptversion nicht mehr, entfernt das Uebernehmen ihn (samt Intervall, Timeout und Name) statt ihn
  abzuschalten; kehrt das Image auf einen passenden Tag zurueck, legt das naechste Uebernehmen ihn neu an.
