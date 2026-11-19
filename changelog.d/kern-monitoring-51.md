### Fixed

- **Monitoring: Dienstnamen unter Windows:** Der Dienste-Check im Modus `list` findet einen Windows-Dienst ohne
  Ruecksicht auf Gross-/Kleinschreibung (`w32time` findet `W32Time`), wie Windows selbst; unter Linux und FreeBSD bleibt
  der Vergleich exakt.
- **Monitoring: agent_ping nach einem Neustart:** Nach einem Stillstand des Monitoring-Dienstes zaehlt die Stillstandszeit
  nicht mehr als Schweigen des Agents; vom Alter des letzten Reports geht nur die Stillstandszeit ab, ein schon vorher toter Agent bleibt critical.
- **Monitoring: Server loeschen:** Die Entwarnungen fuer die Vorfaelle eines geloeschten Servers gehen erst nach der
  Antwort an den Server hinaus; das Loeschen wartet nicht mehr auf den Hub.
