### Fixed

- **Agent: Terminal nach Ctrl-C bei der Token-Eingabe:** Bricht man die verdeckte Eingabe von
  `adminhelper-agent provision --token-stdin` mit Ctrl-C ab, zeigt das Terminal danach wieder an, was man tippt
  (Exit 130).

### Changed

- **Agent auf Go 1.27:** `go.mod` verlangt Go 1.27 (Toolchain 1.27.3), dazu aktuelle Fassungen von gopsutil und
  golang.org/x/sys und x/term.
