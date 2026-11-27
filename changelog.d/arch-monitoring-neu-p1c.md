### Added

- **Monitoring: Ausnahmen "Nicht pruefen" und "Pruefen, nicht bewerten":** Eine Ausnahme `skip` haelt einen Check an:
  Er laeuft nicht, misst nichts und alarmiert nicht. Eine Ausnahme `no_rating` nimmt Objekte eines Checks aus seiner
  Bewertung, er laeuft weiter. Beide gelten, bis jemand sie beendet, und halten fest, wer sie angelegt, geaendert und
  beendet hat. Ausschalten (Ein/Aus-Knopf, `enabled: false`) legt jetzt ein `skip` an, Einschalten beendet es; die
  Eintraege von `ignore_mounts`, `ignore_devices`, `ignore_containers`, `exclude_vmids` und `ignore` beim Dienste-Check
  sind jetzt `no_rating`-Ausnahmen, die der Check-Editor weiter als Liste zeigt.
- **Monitoring: Ausnahmen auf Objekten mit Muster:** `/api/monitoring/exceptions` nimmt die Geltung `object` mit Art
  (Mount, Platte, Container, Gast-Backup, Dienst) und einem Muster auf den Namen, etwa `/mnt/*`; Ausnahmen auf Platten
  und Containern tragen `unstable`, weil sich ihre Namen aendern koennen. Die Objekt-API nennt die Ausnahme, die ein
  Objekt ausnimmt, und fuehrt die Objekte eines angehaltenen Checks als nicht erhoben.
- **Monitoring: Trockenlauf vor dem Update:** `python -m app.exception_migration --dry-run` zeigt mit dem Image der
  neuen Version, welche Checks und Listen das Update in Ausnahmen verschiebt, und rollt alles zurueck.

### Changed

- **Monitoring: Ausgeschaltete Checks und Ignorier-Listen werden Ausnahmen:** Das Update verschiebt sie beim ersten
  Start einmal in Ausnahmen mit der Herkunft `migration`; was ein Template oder ein verschwundenes Modul ausgeschaltet
  hat, bleibt aus. Ein Template-Check, dessen Konfiguration nur in der Liste vom Template abwich, ist danach nicht mehr
  angepasst und folgt wieder dem Template, auch seinen Schwellen; mit eigenen Werten in anderen Schluesseln bleibt die
  Anpassung. Ein Eintrag in einer Ignorier-Liste macht einen Template-Check nicht mehr zum angepassten.
  "Auf Template zuruecksetzen" beendet auch die Ausnahmen `skip` und `no_rating` des Checks.

### Fixed

- **Monitoring: ausgenommene Platte im Standby flackert nicht mehr:** Schlaeft eine Platte, die `smart_health` nicht
  bewertet, gilt der Bericht als unvollstaendig; die Platte verschwindet nicht mehr aus den Objekten und kehrt beim
  naechsten Aufwachen zurueck.
- **Desktop: Ignorieren eines Dienstes trifft nur diesen Namen:** Steht `*`, `?` oder `[` im Namen eines Dienstes,
  maskiert der Knopf *Ignorieren* sie, statt ein Muster zu speichern, das weitere Dienste ausnimmt.
