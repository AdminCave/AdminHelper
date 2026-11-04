### Fixed

- **ca-issuer: `rotate-root finish` und `status` nach einer Erneuerung in der Startsekunde (R-1094):** ein Geraet, das
  in derselben Sekunde wie der erste Start unter der neuen Root erneuerte, galt als noch nicht erneuert und hielt
  `finish` bis `--force` fest. Innerhalb dieser Sekunde entscheidet jetzt der Zeitpunkt der Aufzeichnung.
- **ca-issuer: `rotate-intermediates --compromised` nach dem Root-Wechsel (R-1095):** der Scope steht jetzt auch in
  `root-switch.json` unter `compromised`, wie bei `rotate-root switch --compromised`; ein weiterer Lauf ergaenzt die
  Liste.
