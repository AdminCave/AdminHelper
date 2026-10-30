### Fixed

- **Desktop: Tunnel-Abgleich mit Lesegrenze:** Die App liest die Tunnel-Liste vom Server hoechstens 16 MiB weit,
  wie die Verbindungsliste; eine groessere Antwort lehnt sie ab, ohne sie zu zitieren.
- **Desktop: Zuruecksetzen der Geraete-Identitaet haelt die App nicht auf:** Die Schritte am Schluesselbund laufen
  auf einem eigenen Thread, ein wartender Schluesselbund blockiert keine anderen Befehle.
- **Desktop: Registrierung, die der Workspace nicht behaelt:** Scheitert danach auch das Zuruecksetzen, sagt die
  Meldung das und dass die Identitaet bleibt (in den Einstellungen zuruecksetzen).
