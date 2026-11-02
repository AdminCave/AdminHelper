### Fixed

- **Agent: Terminal nach Ctrl-C bei der Token-Eingabe:** Bricht man die verdeckte Eingabe von
  `adminhelper-agent provision --token-stdin` mit Ctrl-C ab, zeigt das Terminal danach wieder an, was man tippt
  (Exit 130).
