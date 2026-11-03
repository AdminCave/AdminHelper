### Changed

- **CI: die Shards der Server-Suite vergleichen ihre Sammlung:** jeder Shard schreibt Zahl und Hash der gesammelten
  Tests, und der Ergebnis-Job der Leg ist rot, wenn sie abweichen oder ein Shard keins schreibt. Eine rote Leg bricht
  die andere nicht mehr ab.
- **CI: Actions auf dem aktuellen Release:** alle Workflows pinnen das aktuelle Release jeder Action per SHA
  (checkout, setup-go, setup-node und setup-python v7, die docker-Actions, action-gh-release, rust-cache), und
  tauri-cli steht in CI und Release auf 2.12.4.
