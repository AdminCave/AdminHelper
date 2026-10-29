### Changed

- **Agent: frpc-Abgleich ohne Antwort von systemd:** Antwortet systemd nicht, laedt der Agent eine geaenderte
  Tunnel-Liste ueber die Admin-API des laufenden frpc, sofern frpc auf seinem Admin-Port lauscht und der gemeinsame
  Teil der Konfiguration unveraendert ist; sonst aendert der Abgleich wie bisher nichts.
- **Agent: `--ca-fp` auf das Server-Zertifikat selbst:** Ist der Fingerabdruck der des vorgelegten Server-Zertifikats
  statt einer CA, prueft der Agent dessen Gueltigkeit und Verwendungszweck wie bei einer Kette zur CA.
- **Agent: Schluessel der Server-Konfiguration fuer frpc:** Der Agent nimmt in der frpc-Konfiguration vom Server
  nur Schluessel mit hoechstens 32 Segmenten an; frp kennt keine tieferen Felder.
- **Agent: `run --once` bei SIGTERM:** Stoppt systemd den Timer-Lauf, beendet der Agent den laufenden Schritt
  ueber seinen Kontext wie im Dauerbetrieb, statt hart abzubrechen.
- **Agent-Paket: Einrichtungs-Hinweis mit `--token-stdin`:** Der Hinweis nach der Installation des deb- und
  rpm-Pakets gibt den Provision-Token ueber stdin statt als Argument, wie die Doku; so steht er weder in der
  Shell-History noch in der Prozessliste.

### Fixed

- **Agent: Abbruch waehrend des frpc-Abgleichs:** Endet der Lauf (Signal, Laufbudget) waehrend frpc neu geladen
  wird, startet der Agent frpc nicht mehr neu und behaelt den Stand; der naechste Lauf laedt, statt alle Tunnel neu
  aufzubauen.
- **Agent: Monitoring-Befehle mit offenem Kindprozess:** Endet ein Werkzeug (etwa docker, zpool, apt-get) mit
  Erfolg, waehrend ein von ihm gestarteter Prozess seine Ausgabe noch offen haelt, wertet der Agent die Ausgabe
  aus, statt "did not start" zu melden; ein abgebrochener Lauf heisst "canceled before it ended".
