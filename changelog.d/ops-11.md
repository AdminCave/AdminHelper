### Fixed

- **agent-install.sh: TOFU-Warnung bei alten Agents:** Kennt der installierte Agent `--ca-fp` noch nicht, verweist
  die Warnung nicht mehr auf den Provisionierungs-Tab (der nur den CA-Fingerprint zeigt), sondern nennt den
  `openssl`-Befehl fuer den Fingerprint des Gateway-Zertifikats und das Server-Update als Weg zur verifizierten
  Erstverbindung.
