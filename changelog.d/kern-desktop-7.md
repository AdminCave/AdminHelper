### Fixed

- **Desktop: SFTP-Upload ueber eine Teildatei:** Ein Upload schreibt zuerst eine versteckte Teildatei neben dem Ziel
  und benennt sie erst nach dem letzten Byte um; ein abgebrochener Upload laesst die alte Datei unversehrt. Beim
  Ueberschreiben uebernimmt sie Modus sowie, wo der Server es erlaubt, Eigentuemer und Gruppe der alten Datei. Ein Link
  unter dem Namen der Teildatei wird nicht verfolgt.
- **Desktop: Glocke nach dem Abmelden:** Eine Antwort des Benachrichtigungs-Feeds, die erst nach dem Abmelden
  ankommt, fuellt die Glocke nicht mehr und meldet keine alten Eintraege der naechsten Anmeldung als neu.
