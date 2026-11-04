### Added

- **CA-Issuer: Root erneuern ohne neues Enrollment:** `python -m app.cli rotate-root stage`, `switch` und `finish`
  legen eine neue Root neben die alte, schalten mit einem Cross-Zertifikat der alten Root auf sie um und nehmen die
  alte am Ende heraus. Agenten und Desktops gehen ueber ihre gewohnte Erneuerung mit; `status` zeigt Phase und
  Abdeckung, und `finish` wartet, bis das Zertifikats-Register kein aktives Geraet mehr an der alten Root zeigt
  (`--force` uebergeht das). Nach einem Leck eines Zwischenschluessels schliesst `switch --compromised <scope>` es
  ganz. Doku: Betrieb → Root erneuern, Troubleshooting, Agent-Deployment, API-Referenz (DE+EN), ADR 0001.

### Changed

- **Zertifikate: eigene Schwellen fuer die Root:** Die Root wird in der Uebersicht und in den Meldungen gelb unter
  365 und rot unter 120 Tagen (alle anderen weiter 30 und 7). Der ca-issuer warnt ab 365 Tagen vor ihrem Ablauf und
  nennt den naechsten Schritt der Erneuerung statt eines neuen Enrollments aller Clients. Doku: Betrieb,
  API-Referenz (DE+EN).
- **Enrollment und Renew: `chain` traegt jede Root, der der Client vertrauen soll:** waehrend einer Root-Erneuerung
  das Zwischenzertifikat und beide Roots, die zu pinnende zuletzt (nach `switch --compromised` nur die neue); sonst
  wie bisher Zwischenzertifikat und Root. Doku: ADR 0001.
- **Gateway: eigenes Buendel fuer `:8444`:** Das Gateway liest fuer die Enrollment-Ebene
  `gateway-enroll-fullchain.pem`, das erst der neue ca-issuer schreibt. Beide kommen mit demselben Update ueber
  `docker compose`. Doku: ADR 0001.
