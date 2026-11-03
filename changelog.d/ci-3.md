### Changed

- **CI: die Shards der Server-Suite vergleichen ihre Sammlung:** jeder Shard schreibt Zahl und Hash der gesammelten
  Tests, und der Ergebnis-Job der Leg ist rot, wenn sie abweichen oder ein Shard keins schreibt. Eine rote Leg bricht
  die andere nicht mehr ab.
