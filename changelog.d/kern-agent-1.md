### Changed

- **Agent: frpc-Abgleich ohne Antwort von systemd:** Antwortet systemd nicht, laedt der Agent eine geaenderte
  Tunnel-Liste ueber die Admin-API des laufenden frpc, sofern frpc auf seinem Admin-Port lauscht und der gemeinsame
  Teil der Konfiguration unveraendert ist; sonst aendert der Abgleich wie bisher nichts.
- **Agent: `--ca-fp` auf das Server-Zertifikat selbst:** Ist der Fingerabdruck der des vorgelegten Server-Zertifikats
  statt einer CA, prueft der Agent dessen Gueltigkeit und Verwendungszweck wie bei einer Kette zur CA.

### Fixed

- **Agent: Abbruch waehrend des frpc-Abgleichs:** Endet der Lauf (Signal, Laufbudget) waehrend frpc neu geladen
  wird, startet der Agent frpc nicht mehr neu und behaelt den Stand; der naechste Lauf laedt, statt alle Tunnel neu
  aufzubauen.
