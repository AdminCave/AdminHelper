### Changed

- **CI: die Shards der Server-Suite vergleichen ihre Sammlung:** jeder Shard schreibt Zahl und Hash der gesammelten
  Tests, und der Ergebnis-Job der Leg ist rot, wenn sie abweichen oder ein Shard keins schreibt. Eine rote Leg bricht
  die andere nicht mehr ab.
- **CI: Actions auf dem aktuellen Release:** alle Workflows pinnen das aktuelle Release jeder Action per SHA
  (checkout, setup-go, setup-node und setup-python v7, die docker-Actions, action-gh-release, rust-cache), und
  tauri-cli steht in CI und Release auf 2.12.4.
- **CI: Runner ubuntu-26.04:** alle Linux-Jobs laufen ausdruecklich auf `ubuntu-26.04`. Der Desktop-Build des
  Releases und sein Smoke in CI bleiben auf `ubuntu-24.04`, damit das ausgelieferte Binary weiter auf Ubuntu 24.04
  und Debian 12 startet.
