### Fixed

- **Monitoring: Dienstnamen unter Windows:** Der Dienste-Check im Modus `list` findet einen Windows-Dienst ohne
  Rücksicht auf Groß-/Kleinschreibung (`w32time` findet `W32Time`), wie Windows selbst; unter Linux und FreeBSD bleibt
  der Vergleich exakt.
