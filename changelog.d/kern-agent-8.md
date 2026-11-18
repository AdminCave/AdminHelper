### Changed

- **Agent: Waechter fuer Proben am eigenen Host:** bei Programmen, die mehrere Werkzeuge in einer Datei vereinen
  (`busybox`, `toybox`, `dropbearmulti`), gelten die Namensregeln und das Prozess-Ziel fuer das gestartete
  Werkzeug; laesst es sich nicht bestimmen, ist die Probe nicht pruefbar (`not_allowed`).
