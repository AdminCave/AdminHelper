### Added

- **Monitoring: Katalog-Updates als Angebot:** aendert eine neue Version die Definition eines uebernommenen Modul-Checks,
  laeuft er unveraendert weiter; der Fund wird `changed` und nennt die betroffenen Checks (`updatableChecks`). Erst das
  Uebernehmen schreibt die neue Definition samt Regeln (`updatedChecks`); Name, Intervall, Zeitlimit und Schalter
  bleiben. Eigene Aenderungen an einem Check gelten nie als Update. Der Desktop-Client zeigt die Zahl im Funde-Eingang.
- **Monitoring: Container im Compose-Fund:** der Fund eines Compose-Projekts nennt je Dienst den gebundenen Container
  (`containers`); ein neuer Containername allein aendert den Fund nicht. Der Desktop-Client zeigt ihn.
- **Agent: implizites TLS und Redis-ACL:** der Sensor `proto` spricht SMTPS, IMAPS, POP3S, LDAPS, Redis mit TLS-Port
  und Banner hinter TLS (`tls: true`); Redis meldet sich mit einem ACL-Nutzer an (Zugang `redis_acl`,
  `benutzer:passwort`). Ein aelterer Agent meldet solche Checks `unknown`.
- **Monitoring: optionale Zugangsdaten:** ein Katalog-Check kann seinen Zugang als optional fuehren; solange der Host
  ihn nicht als hinterlegt meldet, laeuft der Check ohne ihn statt `no_credential` zu melden.

### Changed

- **Monitoring: geloeschte Modul-Checks bleiben geloescht:** loescht ein Admin einen Check, den ein Modul angelegt hat,
  legen ihn weder erneutes Uebernehmen noch ein Katalog-Update wieder an (Migration `module_check_tombstones`).
- **Monitoring: Katalog-Grenzen wie der Agent:** DNS-Namen duerfen Unterstriche tragen (SRV-Namen), der Pfad eines
  Unix-Sockets hoechstens 107 Zeichen.
